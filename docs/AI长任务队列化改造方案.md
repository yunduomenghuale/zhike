# AI 长任务队列化改造方案（讲稿 / 配音优先）

> 状态：**方案定稿（v2.0）** ｜ 2026-11-02 ｜ D1–D6 全部锁定，12 项疑问已逐条决议（§14）
> **配套必读**：`docs/AI长任务队列化-实施冲突评审.md`（17 项冲突，3 项阻断级；本文件已按评审修订）
> v2.0 相对 v1.2 的实质变化：并发从两层改三层（加调用闸门）、用户级限跑、worker 线程模型、
> `force`/取消/唯一索引的完整协议、配额预留生命周期、发布与换版规则分清、E2E 重写口径。
> 目标读者：项目负责人、后端/前端实现者
> 输入依据：`docs/AI任务并发量排查总结.md`（2026-10-26）＋本轮对 `apps/ai`、`apps/courses`、`frontend/src/store/generation.js`、`deploy/` 的重新勘察

---

## 0. 结论摘要

1. 当前讲稿/配音**不是"异步任务"，而是"由浏览器驱动的一串同步 HTTP 请求"**：前端 for 循环 → 每请求同步跑 6 页 → 循环直到 done。浏览器关掉任务就停，服务端没有任何人接着干。
2. 生产 gunicorn **2 workers × 2 threads = 4 个请求处理器**。一次讲稿请求占住 1 个线程几十秒到几分钟，4 个教师同时生成 → **全站 API 排队**（含登录、交作业）。
3. 并发上限是**进程内信号量**（`_TASK_SEMAPHORE = BoundedSemaphore(2)`），2 workers → 实际 4，且**扩容即失真**。这不是"系统级并发限制"，是"每个进程各自限制"。
4. 改造方向：**DB 表当队列 + 独立 worker 容器消费 + 作业级并发预算 + 前端任务中心**。不引入 Redis/Celery，保持项目"零外部中间件"形态。
5. 本方案已过实施冲突评审（`docs/AI长任务队列化-实施冲突评审.md`）：**17 项冲突、3 项阻断级**——
   跨进程丢失 AI 调用上下文、`video.scripts` 整字段覆盖导致丢更新、容器 `ENTRYPOINT` 吞掉 `command`。
   这三项不改就会"功能错/数据丢/worker 根本没跑"，实施前必须先落修正。
6. 本方案把"排队"从**用户体验的退让**变成**系统能力的显性化**：用户看得见排队位置、能关浏览器、完成有通知、失败可重试。

---

## 1. 现状勘察（证据）

### 1.1 执行链路（讲稿）

```
CourseCatalog.vue 点击「生成讲稿」
  └─ store/generation.js runScript()  for(;;)
       └─ POST /catalogs/{id}/generate-script/ {limit:6}     ← 同步，axios timeout 300s
            └─ courses/views.py generate_script()
                 └─ ai/services.py generate_script_pages_batched()
                      · pending 页取 batch_size*2（最多 24 页）
                      · 切 3 页/小块，ThreadPoolExecutor(max_workers=min(4, chunks))
                      · as_completed 逐块落库 video.scripts（增量，刷新不丢）
            ← 返回 {script_pages, pages, remaining, done}
       直到 done=true 才 break
```

配音同理：`limit=3`（≤10），池 3，逐页落库。

### 1.2 并发现状

| 环节 | 上限 | 跨进程有效 | 备注 |
|---|---|---|---|
| 讲稿 | 无全局上限，≈ 教师数 × 4 | — | 受 4 个请求线程自然封顶 |
| 配音 | 无全局上限，≈ 教师数 × 3 | — | 同上 |
| AITask（学情/总结/生题/复用） | `BoundedSemaphore(2)` | ❌ 进程内 | 生产实际 = 4 |
| provider 层 | 无限流 | — | 全靠上游报错兜底 |

### 1.3 由此产生的 4 个具体病症

- **线程饥饿**：4 个请求线程被长任务占满后，第 5 个请求（哪怕只是查列表）排队；nginx 表现为全站卡顿。
- **浏览器即执行器**：关标签页 = 任务停摆。现有 `localStorage` 续跑机制只是"用户下次回来自动接着点"，不是真正的后台执行。
- **并发不可控**：并发度 = 同时点按钮的人数，无法回答"现在系统里在跑几个 LLM 调用"。
- **无法排队/无法公平**：先到先得靠抢线程，没有队列位置、没有优先级、没有限流、没有取消。

### 1.4 现有可复用资产（不要重造）

- `AITask` 模型 + `/api/ai-tasks/<id>/`、`/api/ai-tasks/active/` 轮询端点（前端 `useAiTaskPolling` 已在 4 处使用）。
- 增量落库（讲稿逐块、配音逐页）→ **天然可断点续跑**，这是队列化最关键的既有优势。
- `AICallLog` 已有 scene 维度（`script_gen` / `tts`），队列指标可直接复用。
- MySQL 8.0.22 支持 `SELECT ... FOR UPDATE SKIP LOCKED`；`common/mysql_partial_unique.py` 已有"生成列 + 普通唯一索引"解决 MySQL 丢条件唯一约束的成熟做法。
- `users.Notification` 站内通知可直接用于"任务完成"推送。

---

## 2. 目标与非目标

### 目标
1. 讲稿/配音提交后**秒级返回**，执行与浏览器解耦，关页面照样完成。
2. **全系统唯一**的并发预算：任意时刻在飞的 LLM/TTS 调用数可被一个数字描述、可配置、可观测。
3. 队列**可见可控**：排队位置、预计等待、取消、重试、失败原因。
4. 不占用 gunicorn 请求线程：长任务执行期间 API 容量不变。
5. 现有体验不倒退：按钮上仍能看到页进度，完成后自动刷新。

### 非目标（本期不做）
- 不引入 Celery/RQ/Redis（部署成本、出网 5Mbps、运维复杂度都不划算）。
- 不做多机分布式调度（单机 32 核足够，先做单 worker 副本 + 可扩副本的兜底设计）。
- 不改 RAG 问答（实时交互，另走限流方案）。
- ~~不改 PPT 渲染~~ → **已改为纳入范围**（2026-11-02）：课件解析入队为 `ppt_parse` 任务，
  渲染从"全局串行 1"改为"槽位化并发 2"。详见 `docs/课件解析与渲染链路改造-方案讨论.md`。
  注意它依赖队列内核（B1–B4），且必须与 `embed` 闸门同批——否则课件入库会绕开并发预算。

---

## 3. 总体架构

```
┌─────────────────────────────┐        ┌──────────────────────────────┐
│ 浏览器 (Vue)                 │        │ gunicorn 2w×2t (API only)    │
│  · 点「生成讲稿」            │  POST  │  · 只做校验+入队，秒返 task  │
│  · 任务中心抽屉（轮询 2.5s） │───────▶│  · 不再执行任何长任务        │
└─────────────────────────────┘        └──────────────┬───────────────┘
         ▲                                            │ INSERT pending
         │ GET /ai-tasks/<id>/                        ▼
         │                                  ┌──────────────────────┐
         └──────────────────────────────────│  MySQL: ai_task 表   │
                                            │  pending/running/... │
                                            └──────────┬───────────┘
                                                       │ claim (SKIP LOCKED)
                                            ┌──────────▼───────────┐
                                            │ ai_worker 容器 (×1)  │
                                            │  · 作业级并发槽      │
                                            │  · 心跳/超时回收     │
                                            │  · 分批 + 增量落库   │
                                            └──────────┬───────────┘
                                                       │ chat / tts
                                            ┌──────────▼───────────┐
                                            │ Provider (DashScope) │
                                            └──────────────────────┘
```

**为什么是"独立 worker 容器"而不是"API 进程里的线程池"**（对比见 §12 开放决策 D1）：

| 维度 | 独立 worker | API 进程内线程池 |
|---|---|---|
| 并发预算单一事实源 | ✅ 一个进程一套槽位 | ❌ 2 workers = 双份 |
| 占用请求线程 | ✅ 不占 | ❌ 或需额外线程预算 |
| 重启 API 是否中断任务 | ✅ 不中断 | ❌ 全丢（靠心跳救回） |
| 部署成本 | 多一个 compose 服务（同镜像） | 0 |
| 扩容 | 改副本数（需配合 DB 级槽位） | 自动但失控 |

结论：**独立 worker**。多一个容器换来的正是本需求的核心价值。

---

## 4. 数据模型

### 4.1 扩展 `AITask`（不新建表）

新增 `TaskType`：`SCRIPT_GEN = "script_gen"`（章节讲稿）、`AUDIO_GEN = "audio_gen"`（章节配音）、
`PPT_PARSE = "ppt_parse"`（课件解析：文本 → 渲染 → 入库，priority=50 最高）、
`EMBED_INGEST = "embed_ingest"`（讲稿向量入库，priority=200 最低）。

新增字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `payload` | JSON | 作业参数：`{ppt_id, ppt_version, limit, force, voice, only_pages}` |
| `priority` | int (默认 100) | 越小越先；`ppt_parse`=50，教师生成=100，后台衍生=200 |
| `dedupe_key` | CharField(120, 可空) | 如 `script:catalog:123`，配合唯一索引防重复 |
| `attempts` | int | 已尝试次数 |
| `max_attempts` | int (默认 3) | 超限落 FAILED |
| `next_run_at` | DateTime | 退避重试用；空=立即可跑 |
| `claimed_by` | CharField(64) | worker 实例标识（host:pid） |
| `heartbeat_at` | DateTime | 卡死检测 |
| `cancel_requested` | bool | 优雅取消标志 |
| `trace_id` | CharField(32, 可空) | C1 重建上下文后回写，配额结算按它 count `AICallLog` |

复用已有 `progress` / `result` / `error` / `course` / `catalog` / `triggered_by`。

### 4.2 唯一约束（防重复提交 / 防双跑）

```python
# 语义：同一章节同类型同时只能有一条 pending/running
UniqueConstraint(
    fields=["task_type", "catalog"],
    condition=Q(task_type__in=["script_gen", "audio_gen"],
                status__in=["pending", "running"]),
    name="uniq_active_catalog_gen",
)

# 课件解析按「PPT 资源」去重，不能用 catalog ——
# 一个章节可以有多个 PPT 版本（version 递增），按 catalog 去重会让
# 「上传第二版」被判成重复、新文件永远不解析（课件方案自审 F3）
UniqueConstraint(
    fields=["task_type", "ppt"],
    condition=Q(task_type="ppt_parse", status__in=["pending", "running"]),
    name="uniq_active_ppt_parse",
)
```

⚠️ **必踩的坑**：该条件唯一约束在 MySQL 会被 Django 静默丢弃 → 必须走
`common/mysql_partial_unique.py` 的「生成列 + 普通唯一索引」方案（已有 4 个迁移先例）。
生成列表达式需把 `catalog_id` / `ppt_id` 与 `status` 组合成可空列（NULL 不参与唯一），
并在迁移里用 `atomic = False` 写 DDL。

> `ppt` 是新增的 nullable FK（CASCADE），`ppt_parse` 用；讲稿/配音仍用 `catalog`。两条约束互不干扰。

### 4.3 索引

```python
Index(fields=["status", "priority", "next_run_at", "id"])   # 取任务
Index(fields=["task_type", "status", "-created_at"])        # 已有，看板用
Index(fields=["claimed_by", "heartbeat_at"])                # 卡死回收
```

---

## 5. 调度与并发

### 5.1 三层并发（v2.0 修正）

v1.1 只设计了"作业槽位 × 块并发"，隐含假设是"槽位不会被调大"。这个假设很脆：
有人把 `AI_JOB_SLOTS_SCRIPT` 从 2 调到 4，在飞调用就悄悄翻倍且没人知道。v2.0 拆成三层：

| 层 | 管什么 | 默认值 | 载体 |
|---|---|---|---|
| **作业槽位** job slot | 同时跑几个整章作业 | 讲稿 2 / 配音 2 / 分析 2 | worker 内按类型计数 |
| **用户并发** user cap | 同一教师同时几个作业 | 1（见 §5.3） | claim 时子查询 |
| **调用闸门** call gate | 同时在飞的 provider 调用 | chat 6 / tts 4 | **进程级 `BoundedSemaphore`，包在任务流水线的单次调用外** |

前两层决定"谁在跑"，第三层决定"最多几个请求真的打到上游"。加闸门后：

- 调大槽位不会再突破上游 QPS —— 只是排队位置更靠前、跑得更慢，不会打爆；
- 单个作业也能吃满闸门（3 块并发），不必为了吞吐把槽位调高；
- 总量是一个**显式数字**，可以写进验收（"同秒 chat ≤ 6"）。

**挂点选在哪里**（v2.0 推敲后改口）：**任务流水线里的单次 provider 调用**外层，共 5 处 ——
`_request_script_batch`（讲稿块）、`_synthesize`（配音页）、`analytics_ai` 分批调用、
`question_gen_ai` 分组调用、`ingest` 的 embed。
**不要挂在 `factory.get_provider()` 上**：那样会把学生 RAG 的 SSE 流式问答也罩进去，
一条流能持锁 30s，等于把交互功能拖到后台任务的节奏上。

```python
# apps/ai/gate.py
_GATES = {"chat": BoundedSemaphore(AI_MAX_CONCURRENT_CHAT),   # 6
          "tts":  BoundedSemaphore(AI_MAX_CONCURRENT_TTS)}    # 4

@contextmanager
def gated(capability):
    gate = _GATES.get(capability)
    if gate is None:
        yield; return
    gate.acquire()
    try: yield
    finally: gate.release()
```

> ⚠️ 闸门持锁期间**必须是纯 HTTP 等待**，不得再进 DB 事务，否则会把行锁持到秒级。
> 这也是 §13.1-B11「事务内绝不调 AI」的同一约束，两条互相印证。

> 单 worker 副本时，作业级槽位用进程内 `Semaphore` 就够（唯一消费者）；但**取任务用 DB 条件更新**，
> 这样即便未来起 2 个副本也不会双跑（§5.2）。副本数 >1 时，槽位需改为 DB 计数（`ai_worker_slot` 表或
> `SELECT COUNT(*) FROM ai_task WHERE status='running' AND task_type=...` 事务内判定），本期先锁副本=1 并文档化。

**内存与本地模型的耦合（评审 C11）**：讲稿完成后的 `ingest_video_scripts()` 会调 embed provider。
若 embed 配置为 `local`，worker 需再加载 BGE-M3（≈2.3GB）且与 API 各持一份 → `mem_limit` 必须与
backend 对齐 8g。更优解是把它拆成独立的 `embed_ingest` 任务，让 worker 能控制"什么时候吃这份内存"。

### 5.2 认领（claim）——必须 DB 原子，不能用内存锁

```python
with transaction.atomic():
    rows = (AITask.objects
            .select_for_update(skip_locked=True)          # MySQL 8.0.22：真实生效
            .filter(status=PENDING, task_type__in=slots_have_room,
                    Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))
            .order_by("priority", "id")[:1])
    task = rows.first()
    if task:
        # 防御性不变量：状态迁移只允许成功一次
        # （覆盖 SKIP LOCKED 管不到的场景——心跳回收把它改回 pending 时，
        #   消费者手里可能还攥着一份旧的 running 快照）
        updated = AITask.objects.filter(id=task.id, status=PENDING).update(
            status=RUNNING, claimed_by=worker_id, heartbeat_at=now,
            started_at=now, attempts=F("attempts") + 1)
        if updated != 1:
            return None
```

`rowcount != 1` 即放弃本轮。这一句不是为了兼容 SQLite（本项目已全线 MySQL，
SQLite 只是 `.env` 里的休眠回退分支），而是让"pending→running 只能发生一次"
由一次条件更新直接保证，而不是寄托在隔离级别与消费者纪律上。

### 5.3 排队公平性（v2.0 修正）

v1.1 写"单教师同时排队 ≤ 2"，但没约束"同时在跑"。一个教师连点 10 个章节，2 个槽位会被他一个人占满，
其他教师永远排在后面。改成**按用户限跑 + 放开放宽排队**：

| 规则 | 值 | 行为 |
|---|---|---|
| 单教师同时**运行** | 1 个作业 | claim 时排除「该 `triggered_by` 已有 running」的任务，多章节自动串行 |
| 单教师同时**排队** | 5 个作业 | 超出 429「你已有 5 个章节在排队」 |
| 全队列上限 | 50 | 超出 429「系统任务队列已满，请稍后」 |
| 同章节合并 | 唯一索引 | 重复点击返回**已有任务**的 task_id（不新建、不报错） |
| 依赖检查 | 配音前置讲稿 | 见 §6.2 的三态判定 |
| 优先级 | priority, id | 100=教师显式提交；200=后台衍生（embed 入库） |

**为什么是"运行 1 / 排队 5"**：教师是低频操作者，单人串行的总时长可预期
（10 章 × 90s ≈ 15 分钟，且排队位置透明）；而槽位只在"多教师同时提交"时才需要并行。
代价是单人场景槽位利用率减半（2 个槽只跑 1 个），换来的是**永远不会出现一个人卡住所有人**。
若后续观察发现单用户场景占多数，可加一条动态规则：`pending` 里没有其他用户时允许提升到 2（P3，不做）。

claim 的子查询实现（一次查询搞定，不需要额外锁定）：

```python
mine_running = AITask.objects.filter(
    status=RUNNING, triggered_by=OuterRef("triggered_by")
).exclude(triggered_by=None)
qs = qs.annotate(has_running=Exists(mine_running)).filter(has_running=False)
```

> 注意：`triggered_by` 可空（SET_NULL）。`NULL` 之间不互相排斥，孤儿任务不会因此饿死。

### 5.4 容量估算（给决策用）

实测口径：单页讲稿约 3~5s，3 页小块约 10~15s；单页 TTS 约 6s（`synthesize_audio_for_video` docstring）。

| 场景 | 讲稿耗时 | 配音耗时 |
|---|---|---|
| 30 页课件（典型） | 10 块 / 3 并发 ≈ **50~70s** | 30 页 / 2 并发 ≈ **90s** |
| 60 页课件 | ≈ 100~140s | ≈ 180s |

排队等待 = ⌈前面作业数 / 槽位数⌉ × 单作业耗时。10 个教师同时提交 30 页课件（单个约 60s）
→ 最后一位约等 **4~5 分钟**；若都是 60 页课件（单个约 2 分钟）→ 约 8~10 分钟。
**这个量级对"可等待"的功能是可接受的**，但 UI 必须显式告知（"前面还有 3 个任务，预计 6 分钟"），否则用户会以为卡死。

> **单用户串行的代价**（§5.3 的规则）：10 个章节同属一个教师时，总时长 = 10 × 单作业耗时 ≈ 15 分钟，
> 且同时只占 1 个槽位。这是刻意选的：可预期的等待 > 不可预期的抢占。

### 5.5 worker 线程模型与停机协议（v2.0 新增）

这是所有并发/取消/停机实现的**地基**，v1.1 只写了"独立容器"，没写进程内部长什么样。

```
主线程（调度）
 ├─ 每 2s：reap_stale() → claim 候选 → 有空闲槽位则起任务线程
 ├─ 每 30s：打印队列深度/槽位占用（一行日志，便于 grep）
 ├─ 信号处理：SIGTERM/SIGINT → stop_event.set() + 通知所有任务线程
 └─ join(所有任务线程, timeout=8s) → 退出

任务线程 ×N（N = 各类型槽位之和，默认 6）
 ├─ 进入：set_current_user / ai_scene（C1）
 ├─ 每批开始前：检查 stop_event 与 cancel_requested
 ├─ 每 30s：heartbeat_at = now（一条 UPDATE，不碰业务字段）
 ├─ 每批结束：page_store.merge_pages(...)（短事务）
 └─ 退出：clear_current_user() + close_old_connections()   ← 必须，否则长驻进程连接泄漏
```

**几个必须钉死的细节**

| 细节 | 为什么必须这样 |
|---|---|
| 每线程退出 `close_old_connections()` | Django 每线程一条连接；长驻进程反复起线程不清理 → MySQL `max_connections` 耗尽（项目已有同类教训，`tasks.py` F11 注释） |
| 心跳用 `update()` 单条语句 | 用 `task.save()` 会把整行（含 `progress` JSON）写回，与业务线程的字段级写入互相覆盖 —— 正是 `question_gen_ai.py:59` 注释里"按字段落库避免整行覆盖"的同一个坑 |
| 任务线程不直接 claim | 调度集中在一处，槽位计数才有唯一真相；否则多线程各自 claim 会突破槽位 |
| 停机只等 8s | docker 默认 10s 后 SIGKILL；等太久会被强杀，反而来不及把任务回置 pending |
| 批次边界检查取消 | 一批讲稿最多 12 页（≈30s），取消延迟可接受；不必做到 chunk 级 |

**停机时的状态处理**：被打断的任务不置 failed，而是 `status=pending` + `claimed_by=None` +
`next_run_at=now+30s`，**`attempts` 不增**（不是任务本身出错，不该消耗重试次数）。
重启后从断点续跑，已生成的页不会重做——这正是"增量落库"在架构上的第二次收租。

---

## 6. 状态机与异常处理

```
                    ┌──────── cancel ────────┐
                    ▼                        │
  提交 ──▶ pending ──── claim ────▶ running ──┴──▶ success
              ▲                       │
              │                       ├──▶ failed (attempts ≥ max)
              └── 心跳超时/退避重试 ◀──┘
```

| 场景 | 处理 |
|---|---|
| 单批 LLM 失败 | 该块走本地兜底文本（现状不变），任务继续；整任务统计 `fallback_pages` |
| 整任务异常 | `error` 落库，`attempts<3` → `next_run_at = now + 30s×2^n` 回 pending |
| worker 被 kill | 启动时把 `status=running AND heartbeat_at < now-300s` 回收为 pending（attempts 不增，因为增量落库，重跑只补剩余页） |
| 用户取消 | pending 直接置 cancelled；running 置 `cancel_requested`，作业在**批次边界**检查后退出，已完成页保留，状态 cancelled |
| 优雅停机 | SIGTERM → 停止 claim → 当前小块跑完即退出 → running 任务回置 pending（5s 内退出，避免 docker 10s SIGKILL） |
| 章节/课程被删 | FK CASCADE/SET_NULL 已覆盖；worker 取到 `catalog=None` → 直接取消 |
| PPT 换版本 | `payload.ppt_version` 与当前不一致 → 取消旧任务（避免给过期 PPT 生成讲稿） |
| 重复点击 | 唯一索引 → 返回已有任务 |

**幂等性来源**：讲稿逐块、配音逐页都立即落库，重跑只处理 `script` 为空 / `audio_url` 为空的页。这是本方案不引入事务性消息队列也能"至少一次 + 幂等"的根本原因。

### 6.1 `force` / 取消 / 唯一索引 三者的交互（v2.0 新增）

这是最容易设计出死锁或"永远点不动"的地方。v1.1 只说"命中已有任务返回原 task_id"，
但 `force`（重新生成）与唯一索引天然对立：教师明确要求重做，而索引说他已经在做了。

**协议**（按旧任务状态分三支，必须在同一事务内完成判断与写入）：

| 旧任务状态 | force=0（普通点击） | force=1（重新生成） |
|---|---|---|
| 无任务 | 新建 → 200 | 新建 → 200 |
| **pending**（还没跑） | 返回原 task_id → 200 `dedupe_hit` | **原子替换**：旧置 `cancelled` → 新建 → 200（旧任务放弃） |
| **running**（正在跑） | 返回原 task_id → 200 `dedupe_hit` | **拒绝** → 409 `{code:"task_running", task_id}`，前端把按钮切成「取消并重新生成」 |
| failed / cancelled / success | 新建 → 200 | 新建 → 200 |

**为什么 running + force 选择"拒绝"而不是"取消后接续"**：
自动接续会引入任务链（A 取消 → B 排队 → B 又被取消…），排查时一个章节对应 4 条任务行，
而 running 通常 1 分钟内结束。拒绝的代价是教师多点一次，换来的是**一个章节同时只有一条有效任务**这条不变量。

**实现必须注意**：dedupe 只能靠**捕获 `IntegrityError`**，不能先查后插——两个并发请求会同时通过 `exists()`
检查（这是 `docs/AI任务并发量排查总结.md` §2.1 记录的"学情分析双跑窗口"同款竞态，同一个坑不要再踩一次）。

```python
try:
    with transaction.atomic():
        task = AITask.objects.create(...)
except IntegrityError:
    task = AITask.objects.filter(task_type=..., catalog=..., 
                                 status__in=[PENDING, RUNNING]).first()
    return api_response({... "task_id": task.id, "dedupe_hit": True})
```

### 6.2 配音依赖讲稿的三态判定（v2.0 细化）

v1.1 的"讲稿未完成 → 400"在排队模型下会误伤。改为三态：

| 讲稿状态 | 行为 |
|---|---|
| 有 pending/running 的讲稿任务 | 409 `{code:"wait_script", task_id}`，提示「讲稿正在生成（排队第 N 位），完成后自动可配音」 |
| 讲稿页全部有内容、无空页 | 正常入队配音 |
| 讲稿部分有内容、且无在跑任务 | 允许入队，但 `payload.only_pages` = 已有内容的页；`progress.total` 按**当前 PPT 页数**算，避免提前判 done |

**不建议自动串联**（讲稿完成后自动起配音）：教师往往要先生成讲稿、检查一遍再配音。
自动配音等于把未经检查的文本直接烧成音频（有成本、且返工要重配），省下的一步不值得。

### 6.3 发布状态机与内容切换规则（v2.0 细化）

学生可见性由 `TeachingVideoViewSet.get_queryset()` 的 `catalog__is_published=True, is_published=True`
两个条件共同决定（`courses/views.py:648-649`）。据此把"什么时候清空、什么时候可见"钉死：

| 触发 | 旧内容 | 执行中 | 完成后 |
|---|---|---|---|
| **PPT 换版本**（`ppt_id` 变） | **立即下线**（内容已不匹配）+ 清学生观看进度 | 学生看不到该章节 | 整章替换后重新上线 |
| **同版本 force 重生成** | 保持可见 | 学生仍看旧内容（无感） | 原位替换 + `published_at` 更新 |
| 普通增量补齐（有空页） | 保持现状 | 学生看到部分内容 | 补齐后置 `SCRIPT_READY` |
| 配音补齐 | 保持 `SCRIPT_READY` | — | 全章有音频 → `AUDIO_READY` |

这修正了评审 C4：**"要不要清空"取决于 PPT 是否换版，而不是取决于是否提交了任务**。
v1.1 一律把重置推迟到 worker 是过度修正——换 PPT 时旧讲稿必须立刻下线，否则学生看到的是
"新课件 + 旧讲稿"的错配内容。

⚠️ **`done` 判定的一个既有隐患**：`generate_script_pages_batched` 用 `script_pages == total`，
而 `total = len(scripts)`（`services.py:201-203`）——若 `scripts` 只覆盖了 5/6 页（PPT 解析页数变化），
会误判"全部完成"并发布。队列化后必须把分母改成 `len(ppt.parsed_pages)` 并先补齐空页占位。

---

## 7. 接口契约

### 7.1 提交（语义变更，路径不变）

```
POST /api/catalogs/{id}/generate-script/   {force?: bool}
→ 200 {code:0, data:{task_id, status:"pending", queue_position:3, eta_seconds:360,
                     script_pages:6, pages:30, remaining:24, done:false, queued:true}}
```

- `limit` 参数**废弃**（不再由前端控制批次）：worker 自己按 `AI_SCRIPT_CHUNK_PAGES` 切，
  老前端多传一个 `limit` 也不会报错，忽略即可。
- 命中已有任务：200 + 同一 `task_id` + `dedupe_hit:true`（不报错、不新建），协议见 §6.1。
- running + `force=1`：409 `{code:"task_running", task_id}`。
- **旧前端（v2.0 改口）**：不再返回 `done:true` 伪造完成，而是 **410** + 中文提示。
  理由见评审 C8 的修正——旧循环没有重试上限，若不返回 `done:true` 它会每秒发一次请求死循环；
  若返回 `done:true` 它又会弹「已生成 30 页讲解稿」的假成功。两者都不可接受，干脆让它失败一次。
  新前端通过全局 axios 头 `X-AI-Task-Mode: queue` 标识自己；无此头 → 410。
  该开关是**一次性迁移垫片**，上线一个版本后删除（代码里留 `# TODO(2026-12) remove`）。
- 旧端点 `POST /videos/<id>/generate-scripts/`（一次性生成全部页、同步、无分批）**下线为 410**：
  它绕过队列且会长时间占住请求线程，是这条链路上最危险的历史入口。

### 7.2 查询（复用）

```
GET  /api/ai-tasks/{id}/        → {status, progress:{stage,done,total,queue_position,eta}, result, error}
GET  /api/ai-tasks/active/?task_type=all   → 任务中心列表（已有，需补 queue_position/课程名）
POST /api/ai-tasks/{id}/cancel/ → 新增
POST /api/ai-tasks/{id}/retry/  → 新增（仅 FAILED/CANCELLED，复用同一行，attempts 归零）
```

### 7.3 progress 结构

```json
{"stage": "generating", "done": 18, "total": 30, "message": "第 18/30 页", "fallback_pages": 2}
```

> **`progress` 归业务流水线独占，队列层永不写入**：`questions` 链路已把生成配置
> （groups/objective）存在 `progress` 里（`questions/views.py:233`、`question_gen_ai.py:284`），
> 队列写入会污染配置。见冲突 C5。

`queue_position` / `eta_seconds` 由 `GET /ai-tasks/<id>/` **读时现算**：

```json
{"id": 42, "status": "pending", "progress": {...},
 "queue_position": 3, "eta_seconds": 360}
```

`queue_position` = 同类型 pending 中 `(priority, id)` 排在前面的条数；
`eta_seconds` = `queue_position / 槽位数 × 同类型近 20 条平均耗时`，允许粗糙。

---

## 8. 前端改造

1. **新增全局任务中心**（`components/AiTaskCenter.vue`，顶栏铃铛 + 抽屉）：
   列表项 = 类型 / 课程·章节 / 状态 / 页进度条 / 排队位置 / 取消·重试。
   挂载在 `App.vue`（与 `restoreTasks()` 同位置），轮询 `/ai-tasks/active/?task_type=all`，2.5s。
2. **`store/generation.js` 瘦身**：删除 localStorage 分批循环与 `runnerId` 认领逻辑（那是"用浏览器当执行器"的补丁），
   改为 `submitScript(catalogId)` → 记 task_id → 交给任务中心。**保留 `scriptTasks/audioTasks` 的对外接口**，
   但 `CourseCatalog.vue` **仍需小改**（v1.1 此处有误，见冲突 C5 与评审 §5）：
   `:343-357` 用 `!!scriptTasks[id]` 当 loading、`:840-844` 用 `done/total` 渲染进度条，
   队列态必须能显示「排队中（第 3 位）」，因此记录对象要扩成 `{done, total, queued, queuePosition}`，
   按钮模板加一个 `queued` 分支。
3. **按钮态**：`排队中（第 3 位）` / `生成中 18/30` / `已完成`，全部来自任务中心状态，刷新不丢。
4. **完成反馈**：toast + 任务中心未读徽标；课程目录页自动刷新（复用 `completedTick`）。
5. **权限/多标签页**：不再需要标签页认领——服务端只跑一次。
6. **轮询节流（v2.0 新增，对应 C10）**：任务中心 2.5s 轮询看似无害，但 20 个教师同时在线 = 8 rps 常驻，
   而后端总共只有 4 个请求线程。三层节流缺一不可：
   - **无在跑任务时**：30s 一次（或直接停），有任务才回到 2.5s；
   - **`document.hidden` 时暂停**（`visibilitychange`），切回前台立刻拉一次补进度；
   - **服务端 3s 缓存** `active` 结果（key = user_id + task_type，用 `CACHES["oversight"]` 同款文件缓存，
     跨 gunicorn worker 一致）。3s 缓存不会让进度显得卡顿——后端本来就是逐块/逐页落库，秒级粒度足够。
7. **旧记录清理（v2.0 新增）**：新前端启动时 `localStorage.removeItem('zhike:generation-tasks')` 一次，
   彻底废掉旧续跑记录；配合 §7.1 的 410，旧标签页最多失败一次点击。
8. **提交按钮防抖**：提交中禁用直到响应返回（服务端虽能 dedupe，但前端不该制造 5 个并发请求）。

---

## 9. 迁移与发布

| 阶段 | 内容 | 风险 |
|---|---|---|
| M1 | AITask 加字段 + 两个 task_type + 唯一索引（生成列方案）+ `ai_worker` 命令 + 改两个提交端点 | 中：迁移需在本地 `zk` 与测试库 `test_zk` 各验一轮（SQLite 已是休眠回退路径，不作为验收目标） |
| M2 | 前端任务中心 + generation.js 瘦身 + **重写 `test/e2e/script-progress-realtime-verify.py`**（排队模型下旧断言必失败） | 低 |
| M3 | 把现有 3 类 AITask（学情/总结/生题）+ 课程复用从"进程内线程 + 信号量"切到同一队列 | 中：去掉 `_TASK_SEMAPHORE`，行为等价性需回归（tests_ai_task.py 604 行） |
| M4 | embedding 入库、授课计划目录入队；管理端队列看板 | 低 |
| M5 | **课件解析入队 + 渲染槽位化并发 2 + md5 复用**（`ppt_parse`，见 `docs/课件解析与渲染链路改造-方案讨论.md` W0/W2/W4/W5） | 中高：必须排在队列内核之后；渲染并发是唯一需要灰度观察的改动 |

**部署变更**：
- `deploy/docker-compose.yml` 增 `worker` 服务。⚠️ **必须显式 `entrypoint: ["python","manage.py","ai_worker"]`**：
  Dockerfile 的 `ENTRYPOINT ["sh","/app/deploy-entrypoint.sh"]` 不会读 `command` 参数，
  只写 `command:` 会让 worker 静默变成第二个 gunicorn（评审 C3）。
- 该服务**不跑 migrate**（`depends_on: backend: service_started`），启动自检 `SELECT 1 FROM ai_task` 失败重试 60 次。
- 共享 `../data`（含 PPT 渲染锁库、本地模型缓存）、`../media`、`bnet-test`/`zhike_v2_net` 网络；
  `mem_limit: 8g`（与 backend 对齐，理由见 §5.1 内存耦合）；`stop_grace_period: 15s`。
- `deploy/Dockerfile.fast` 同步（`COPY . /app` 已覆盖新命令，无需改）。
- **发布清单**：`docker compose up -d backend worker` —— 只重启 backend 会造成新旧代码并存读新 schema（评审 C16）。

**本地开发**：`AI_QUEUE_MODE=inline` —— 在 `AppConfig.ready()` 起一个消费线程（仅 `DEBUG` 且 `RUN_MAIN` 才起，避免 autoreload 双进程双消费）。
默认 `worker` 模式，开发者另开终端跑 `manage.py ai_worker`。

---

## 10. 可观测与运维

- **管理端「任务队列」页**（P4）：pending/running/failed 数量、按类型分布、平均排队时长、平均单页耗时、
  失败原因 Top5、手动取消/重试、当前 worker 心跳。
- **复用 `AICallLog`**：`scene=script_gen/tts` 的调用次数、耗时、失败率已在统计口径内，队列看板直接聚合。
- **告警条件**（写日志 + 管理端红点，不做外部告警）：队列深度 > 20、失败率 > 30%、worker 心跳 > 120s 未更新。
- **健康检查**：`GET /api/ai-tasks/worker-health/`（超管）返回 worker 心跳、槽位占用、队列深度，供 `curl` 探活。

---

## 11. 风险清单

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | MySQL 条件唯一约束被静默丢弃（项目已知坑） | 重复任务双跑，双倍 LLM 成本 | 生成列方案 + 单测断言索引真实存在（`mysql_upgrade_check.py` 加一项） |
| R2 | worker 单副本挂掉 | 队列停摆，但 API 正常 | 心跳 + `restart: unless-stopped`；pending 任务不丢；管理端红点 |
| R3 | 队列积压无人察觉 | 教师等 30 分钟 | 队列位置/ETA 上 UI + 深度告警 |
| R4 | AI 日配额与长任务不匹配（一个 30 页作业 = 10 次 chat） | 教师中途被 429 | 提交时按预估页数**预留**配额；或任务类只校验不累计（见 D4） |
| R5 | 旧前端缓存仍跑循环 | 重复提交 | 唯一索引兜底 + `done:true` 立即 break |
| R6 | 心跳/时钟漂移误判 | 任务被重复执行 | 回收条件收紧到 300s + 回收时 attempts 不增；任务本身幂等 |
| R7 | worker 与 API 内存竞争 | OOM | `mem_limit` 分开设；本地模型不放 worker（或评估后单独进程） |

---

## 12. 决策记录（2026-11-02 已拍板）

| # | 决策 | 结论 | 影响 |
|---|---|---|---|
| D1 | 载体 | **DB 表 + 独立 `ai_worker` 容器**（不引 Redis/Celery） | 多一个 compose 服务；并发预算全系统唯一 |
| D2 | 范围 | **讲稿 + 配音 + 现有 4 类 AITask 全部统一**（学情分析/章节总结/AI 生题/课程复用） | 必须移除 `_TASK_SEMAPHORE`，否则两套并发体系并存 |
| D3 | 并发预算 | **讲稿 2 / 配音 2**（块内并发 3 / 2 不变） | 在飞 LLM ≈ 6~8，TTS ≈ 4 |
| D5 | 发布语义 | **保持自动发布**（讲稿全部完成即 `is_published=true`，配音完成同理） | 行为不变；但完成后必须发通知，避免教师不知道内容已上线 |
| D4 | 配额口径 | **提交时按预估页数预留，结束按 `AICallLog` 实际结算补扣**（新增 `AIQuotaReservation`） | 校验口径改为 `已用 + 预留中`；管理端配额页需展示三段；见冲突 C7 |
| D6 | 旧接口 | **路径不变、语义改为入队；旧客户端返回 409 提示刷新，新前端启动时清除 legacy localStorage 记录** | 比 v1.1 更硬：不让旧循环"假报成功"；见冲突 C8 |

**D2 连带影响（重要）**：现有 `apps/ai/tests_ai_task.py`（604 行）通过
`patch("apps.ai.tasks.threading", _FakeThreading)` 把 daemon 线程改成同步执行来断言。
切 worker 后这条路径消失，测试需改为「调 `_dispatch()` 直跑 + 断言 DB 状态机」，
是本次改造里**工作量被低估的部分**。

---

## 13. 实施分解

### 13.1 后端

| # | 任务 | 落点 | 要点 |
|---|---|---|---|
| B1 | 模型扩展 | `apps/ai/models.py` | 8 个新字段 + 2 个 task_type；`Meta.indexes` 补取任务/心跳索引 |
| B2 | 迁移（唯一约束） | `apps/ai/migrations/00xx` | 走上限 2 个 pending/running 的 `uniq_active_catalog_gen`；MySQL 走生成列；`atomic=False` |
| B3 | 队列内核 | 新建 `apps/ai/queue.py` | `enqueue()`（校验配额/防重/队列上限）、`claim()`（SKIP LOCKED + 条件更新）、`heartbeat()`、`reap_stale()`、`cancel()` |
| B4 | worker 命令 | 新建 `apps/ai/management/commands/ai_worker.py` | 主循环：reap → 按类型取空闲槽 → claim → dispatch → 心跳线程；SIGTERM 优雅退出 |
| B5 | 执行体迁移 | 改 `apps/ai/tasks.py` | `submit_ai_task` 只建行入队；`_dispatch` 变为 worker 侧分发；删除 `_TASK_SEMAPHORE`、daemon 线程**与 `copy_call_context()`（跨进程无意义）**；worker 侧改用 `set_current_user(task.triggered_by)` + `ai_scene(...)` 重建上下文（评审 C1） |
| B6 | 讲稿流水线 | 新 `apps/courses/gen_script.py` | 把 `generate_script_pages_batched` 的循环从"一次一批"改为"整章跑到完"，逐块更新 `progress`、每批检查 `cancel_requested` |
| B7 | 配音流水线 | 新 `apps/courses/gen_audio.py` | 同上；页级失败记 `audio_error` 但不终止整任务（与现状一致：根因持续则退避重试到上限） |
| B8 | 提交端点 | 改 `apps/courses/views.py:333/382` | 改为 `enqueue()`；保留 `force/limit` 语义；命中已有任务返回原 task_id |
| B9 | 任务端点 | 改 `apps/ai/views.py` | 详情补 `queue_position/eta_seconds`；新增 `cancel/`、`retry/`、`worker-health/` |
| B10 | 测试 | `apps/ai/tests_ai_task.py`、新增 `tests_queue.py` | 状态机、防重、心跳回收、取消、重试退避；`_FakeThreading` 改直调 `_dispatch` |
| B11 | 落库正确性 | 新增 `courses/page_store.py`；改 6 处写点：`ai/services.py:144-198`（分批讲稿）、`ai/services.py:571-598`（分批配音）、`courses/views.py` 的 `regenerate_script_page` / `regenerate_audio_page` / `update_script` / `generate_scripts`(下线) | **短事务 `select_for_update` + 页级合并，DB 已有非空值的页永不覆盖**；手改与重生成走"强制覆盖"分支（评审 C2） |
| B12 | 配额预留 | 新增 `AIQuotaReservation` + 改 `ai/quota.py` | 提交预留、终结结算；校验口径 `已用 + 预留中`；管理端配额页三段展示（评审 C7） |
| B13 | ingest 独立任务 | 拆 `ingest_video_scripts` 为 `embed_ingest` 任务 | 讲稿任务完成后入队，不阻塞主任务、可控内存（评审 C11） |
| B14 | 渲染锁槽位化 | 改 `courses/ppt_parser.py:87-118` | 锁库从 `tempdir` 挪到 `/app/data/render-guard/slot-{i}.sqlite`；**删除进程内 `_RENDER_THREAD_LOCK`**（否则并发恒为 1）；PDF 改走独立信号量 3；Windows 强制 1 槽 |
| B15 | 渲染并发 | 改 `ppt_parser.py:269-300` | `-env:UserInstallation=/app/data/lo-profiles/{i}` + 预建 profile 池；`AI_RENDER_CONCURRENCY=2`；逐槽 `timeout=0.2` 轮询 |
| B16 | 课件解析入队 | 改 `courses/views.py:531-545`（**override `create()`**）、`:595-625` | 上传只存文件+建 PARSING+入队（`AI_JOB_SLOTS_PPT=2`，去重键 `ppt`）；worker 执行 parse→render→embed，沿用 `_make_parse_progress_writer` 节流 |
| B17 | 课件 md5 复用 | 加 `PPTResource.file_md5`；复用页图目录与 `parsed_pages` | **embed 仍重跑**（`KnowledgeChunk` 按课程归属） |

### 13.2 前端

| # | 任务 | 落点 |
|---|---|---|
| F1 | 任务中心组件 | 新建 `components/AiTaskCenter.vue`（顶栏铃铛 + 抽屉），挂 `App.vue` |
| F2 | store 瘦身 | 改 `store/generation.js`：删 localStorage 循环/`runnerId` 认领；`runScript/runAudio` 改为提交 + 订阅任务进度，对外接口不变 |
| F3 | 按钮态文案 | `views/teacher/CourseCatalog.vue`：`排队中（第 3 位）` / `生成中 18/30` / `已完成` |
| F4 | 完成反馈 | toast + 未读徽标 + `completedTick` 触发目录刷新（沿用现有机制） |

### 13.3 部署

| # | 任务 | 落点 |
|---|---|---|
| O1 | compose 增 worker 服务 | `deploy/docker-compose.yml`：同镜像、**`entrypoint: ["python","manage.py","ai_worker"]`（不可只用 `command`）**、`depends_on backend`、`stop_grace_period: 15s`、`mem_limit: 8g`、挂 `data/media` 与两个网络 |
| O2 | 环境变量 | `.env.production` 增 `AI_JOB_SLOTS_SCRIPT/AUDIO/ANALYTICS`、`AI_MAX_CONCURRENT_CHAT/TTS`、`AI_USER_RUNNING_CAP`、`AI_QUEUE_MAX`；开发 `.env` 增 `AI_QUEUE_MODE=inline` |
| O3 | 校验脚本 | `scripts/mysql_upgrade_check.py` 增断言：唯一索引与生成列确实存在 |

### 13.4 验收口径

1. 4 个教师同时提交 30 页讲稿：API 响应 < 1s，其余业务接口 P95 无劣化（对比基线）。
2. 提交后立刻关闭浏览器，10 分钟后重新登录：任务已完成、内容可见、通知存在。
3. 并发观测：`worker-health` 显示槽位占用 ≤ 2，`AICallLog` 同秒 chat 调用数 ≤ 8。
4. 杀掉 worker 容器（`docker kill`）后重启：running 任务在 5 分钟内被回收并跑完，无重复页、无数据丢失。
5. 同章节连点 5 次「生成讲稿」：只产生 1 条任务，5 次返回同一 `task_id`。
6. **生成期间在界面上点「重新生成第 5 页」，任务跑完后第 5 页仍是教师的新版本**（评审 C2）。
7. **旧构建的前端提交**：返回 409 提示刷新，不出现「已生成 30 页讲解稿」的假成功（评审 C8）。
8. **讲稿任务在跑时点配音**：明确提示等待并给出讲稿 task_id，不产生前半章配音（评审 C6）。
9. **管理端配额页**：显示 `已用 / 预留中 / 上限`，教师在被拦截前能看到真实剩余（评审 C7）。

---

### 13.5 配额预留落地设计（D4）

**问题**：现有配额只数 `AICallLog`（`quota.py:45-49`），而一条 30 页的讲稿作业在跑完前**一条日志都没有**。
不预留 → 教师能连提 5 个作业，跑到第三个时额度耗尽，任务中途 429；预留 → 又要处理结算与泄漏。

**表**（新增，与 `AITask` 一对一）：

```python
class AIQuotaReservation(BaseModel):
    task    = OneToOneField(AITask, CASCADE, related_name="quota_reservation")
    user    = FK(User, SET_NULL)              # 用户删除后仍可结算
    amount  = IntegerField()                   # 预留
    settled = IntegerField(default=0)          # 实际
    status  = CharField(choices=[pending, settled, released])
    expires_at = DateTimeField()               # 泄漏兜底
```

**生命周期五步**：

| 步骤 | 时机 | 动作 |
|---|---|---|
| ① 预留 | 提交任务时（与建任务同事务） | `amount = ceil(空页数 / chunk) * 1.2`（20% 重试余量，向上取整） |
| ② 校验 | 提交时 | `chat_calls_today(user) + active_reserved(user) >= limit` → 429 |
| ③ 记账 | 任务执行中 | **不额外写**，`AICallLog` 照常记录（C1 保证带 `trace_id`） |
| ④ 结算 | 任务终结（success/failed/cancelled） | `settled = AICallLog.objects.filter(trace_id=task.trace_id).count()`；`status=settled` |
| ⑤ 回收 | worker 启动 / 每小时 | `task` 已终态或不存在 → 按 ④ 结算；`expires_at < now` 且任务仍 pending → 释放 |

**为什么能用 `trace_id` 结算**：C1 的重建方案让"一个任务 = 一个 trace_id"
（`ai_scene` 只在同 scene 嵌套时复用，`calllog.py:99-103`）。因此新增 `AITask.trace_id` 字段，
dispatch 时把 `ai_scene` 生成的 trace_id 回写，结算就是一条 count——不需要额外埋点。

**三个边界**：

- **超额**：重试导致 `settled > amount`。不拦截、不冻结，因为此时调用已经发生；表现为"当日剩余变少"。
  若要加强，可在任务每批结束时做一次软检查（超过 `amount` 的 1.5 倍 → 置 `cancel_requested`），列为 P2。
- **泄漏**：worker 崩溃没结算 → `expires_at`（提交 + 6h）兜底释放，避免永久占用额度。
- **用户删除**：`user` 为 SET_NULL，结算照常；`active_reserved` 统计时按 `user_id` 过滤自然跳过。

**管理端 UI 必须显示三段**：`已用 / 预留中 / 上限`。现在 `/api/admin-panel/ai-quota/` 的 GET
只返回策略配置、**不返回用量**（`views_ai_quota.py:28-42`），直接加了个 `usage` 块：
`{used_today, reserved_now, limit}`；否则教师看到的"剩余"和实际拦截阈值永远对不上。

### 13.6 测试策略（C13 的具体化）

| 层 | 文件 | 关键点 |
|---|---|---|
| 队列内核单测 | 新建 `apps/ai/tests_queue.py` | 必须用 `TransactionTestCase`（`select_for_update` 在 `TestCase` 的外层事务里**不会真正阻塞**，测了等于没测）。项目已有先例：`tests_ai_task.py:136` 就是 `TransactionTestCase` |
| 状态机 | 同上 | claim 唯一性（并发两线程只成功一个）、心跳回收、退避、取消、force 三支 |
| 配额 | 同上 | 预留/结算/泄漏回收/超额 |
| 现有任务测试 | 改 `tests_ai_task.py` | `_FakeThreading`（:37/:187/:408）改为直调 `_dispatch(task)`；断言从"线程被拉起"改为"DB 状态迁移" |
| **E2E（必须重写）** | `test/e2e/script-progress-realtime-verify.py` | 现脚本断言"请求进行中进度推进"（:98-110），排队模型下该断言永远失败。改为：提交 → 轮询 `/ai-tasks/<id>/` → 断言 `progress.done` 递增；并新增"提交后不轮询、等 90s 再查，任务已完成"的用例 |
| **E2E（PPT，共 4 个文件）** | `parse-progress-realtime-verify.py`、`parse-progress-freeze-repro.py`、`script-progress-realtime-verify.py`、`parse-progress-fix-verify.js` | 上传改为秒返后，这些脚本"上传响应里带 `parsed_pages`/上传期间进度推进"的断言全部失效；同时 `backend/apps/courses/tests.py:76/695` 的 upload 助手要改成"入队 → 直调 `_dispatch` → 断言终态" |

> E2E 脚本还要补 `X-AI-Task-Mode: queue` 头，否则会被 410 挡住（§7.1）。这是重写时最容易漏的一行。

---

## 14. 疑问点决议（v2.0）

本轮把方案里所有"待定/想当然"逐条钉死。**结论列即最终口径**，理由列是防止后来者改回去。

| # | 疑问 | 结论 | 关键理由 |
|---|---|---|---|
| Q1 | 并发到底有几层？槽位调大会不会打爆上游 | **三层**：作业槽位 / 用户并发 / 调用闸门（§5.1） | 只有前两层时，调大槽位=悄悄突破 QPS；闸门让总量成为显式数字 |
| Q2 | 一个教师能不能占满两个槽 | **不能**，同用户同时 running ≤ 1（§5.3） | 单人串行总时长可预期；永不出现"一个人卡住所有人" |
| Q3 | worker 进程内部长什么样 | 主线程调度 + 每任务一线程 + 心跳单条 UPDATE（§5.5） | 调度集中才有唯一槽位真相；心跳必须单条写，否则与业务字段互覆盖 |
| Q4 | 停机/杀容器时任务会怎样 | 回置 pending、attempts 不增、30s 后可重跑（§5.5） | 不是任务出错，不该消耗重试次数；增量落库保证不重做 |
| Q5 | `force` 与唯一索引冲突怎么解 | 分三支：pending 原子替换 / running 拒绝 409 / 其余新建（§6.1） | 自动接续会产生任务链，排查成本 > 多点一次的代价 |
| Q6 | 配音能不能自动跟着讲稿跑 | **不自动**，三态判定 + 让教师检查后手动（§6.2） | 未检查的文本直接烧成音频＝真金白银的返工 |
| Q7 | 换 PPT 和 force 重生成要不要清空旧内容 | **分清**：换版本立即下线；force 保持可见、原位替换（§6.3） | v1.1 一律推迟到 worker 是过度修正，会造成"新课件+旧讲稿"错配 |
| Q8 | 配额怎么算才不中途 429 | 预留 + trace_id 结算 + 6h 过期回收（§13.5） | 一次任务 = 一个 trace_id，结算只需一条 count |
| Q9 | 旧前端怎么办 | 无 `X-AI-Task-Mode` 头 → 410 报错一次，逼刷新（§7.1） | 假报完成与死循环都不能接受；旧同步端点一并 410 |
| Q10 | 测试怎么保证不是"测了个寂寞" | 队列测试一律 `TransactionTestCase` + E2E 重写（§13.6） | `TestCase` 的外层事务让 `select_for_update` 不阻塞，并发断言会假绿 |
| Q11 | 向量入库放哪 | 拆独立 `embed_ingest` 任务、priority=200（§5.1 内存耦合 + 评审 C11） | 讲稿不该因入库失败而失败；内存峰值可控 |
| Q12 | 任务表会无限涨吗 | `prune_ai_tasks`：success 30 天、每章节每类型留 3 条；failed 90 天（评审 C12） | 队列化后每次生成都落一行，不清理半年就是几十万行 |

**仍未决、留到实施期拍板的两条**（不影响架构）：
- `AI_MAX_CONCURRENT_CHAT` 到底给 6 还是 8 —— 取决于生产 DashScope 的实际配额，实施时用压测定；
- 是否允许"队列里无他人时单用户提到 2 并发" —— 观察一周真实排队数据再决定。

---

## 15. 附：本次勘察的关键文件索引

| 主题 | 位置 |
|---|---|
| 讲稿分批 + 小块并发 | `backend/apps/ai/services.py:101-218`（chunk 3、池 4） |
| 配音并发 | `backend/apps/ai/services.py:544-609`（池 3、单页 6s） |
| 讲稿/配音端点 | `backend/apps/courses/views.py:333-420` |
| AITask 框架 + 进程内信号量 | `backend/apps/ai/tasks.py:32, 35, 62` |
| AITask 模型与既有约束 | `backend/apps/ai/models.py:264-375` |
| 任务轮询端点 | `backend/apps/ai/views.py:94-161`、`config/urls.py:16-17` |
| 前端分批循环 + localStorage 续跑 | `frontend/src/store/generation.js`（全文 295 行） |
| 前端任务轮询 composable | `frontend/src/composables/useAiTaskPolling.js` |
| gunicorn 2w×2t×180s | `backend/deploy-entrypoint.sh` 末尾 |
| MySQL 条件唯一约束方案 | `backend/apps/common/mysql_partial_unique.py` |
