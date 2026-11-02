# AI 长任务队列化 · 实施冲突评审

> 评审对象：`docs/AI长任务队列化改造方案.md`（v1.1，D1/D2/D3/D5 已拍板，D4/D6 本次按建议值锁定）
> 评审方式：逐条假设回到代码取证（文件:行），只认代码事实，不认"设计上应该可以"
> 时间：2026-11-02 ｜ 结论：**17 项冲突，3 项阻断级，需修订方案后方可实施**

---

## 0. 结论

方案的主干（DB 队列 + 独立 worker + 作业/调用两级并发 + 增量落库幂等）**成立且与现有代码不矛盾**。
但方案里有 3 处"想当然的套用"，落地即错：

| 级别 | 数量 | 性质 |
|---|---|---|
| **P0 阻断** | 3 | 不改就会功能错误或数据丢失，必须回到方案层修正 |
| **P1 高** | 5 | 影响正确性/体验，方案需补规则，不影响架构 |
| **P2 中** | 5 | 需排期与配套改动，先知情 |
| **P3 低** | 4 | 实施注意事项，写进 checklist 即可 |

同时核验了 5 条"看起来会冲突但实际安全"的假设（§6）——这几条经代码确认成立，可以放心依赖。

---

## 1. P0 阻断级

### C1 · 跨进程丢失 AI 调用上下文（成本统计与 QA 看板会失真）

**证据**

- `apps/ai/calllog.py:179` `copy_call_context()` 返回的是 `contextvars.copy_context()`，`run_in_context()` 是**同进程**恢复；
- `apps/ai/tasks.py:49-55` 提交时复制上下文再塞进 daemon 线程；
- `apps/ai/middleware.py` 的 `AiCallUserMiddleware` 是请求级，进程退出即无。

**冲突**：worker 是独立进程，`copy_call_context()` 拿不到任何东西。迁移后 `AICallLog` 的
`triggered_by`、`scene`、`trace_id`、`course` 全部为空。后果不是"功能坏了"，而是
**「QA 质量看板」「AI 成本统计」「按教师看用量」三条线同时静默归零**——比报错更难发现。

**修正**：worker 侧显式重建，不走 contextvars 继承：

```python
from apps.ai.calllog import set_current_user, ai_scene
SCENE_OF = {"script_gen": "script_gen", "audio_gen": "tts", ...}
set_current_user(task.triggered_by)                    # calllog.py:117 已存在
with ai_scene(SCENE_OF[task.task_type], course_id=task.course_id):
    ...
```

方案 §13.1-B5 只写了"删除 daemon 线程"，没写"重建上下文"——**必须补**。同时删掉
`submit_ai_task` 里的 `copy_call_context()` 调用（它在 worker 模型下是死代码，留着会误导）。

---

### C2 · `video.scripts` 整字段覆盖 → 后台任务会吃掉教师的手工修改

**证据**

- `apps/courses/views.py:749-760`：`regenerate_script_page` **无锁**读 `video.scripts` → 改一页 → `save(update_fields=["scripts"])`（整数组回写）；
- `apps/ai/services.py:157-158`、`573-575`：分批函数每次吸收结果同样整数组回写。

**完整写点共有 6 处**（v2.0 复核补全，全部是"整数组读改写"）：

| # | 位置 | 触发者 |
|---|---|---|
| 1 | `services.py:144-198` `_absorb` | worker 讲稿分批 |
| 2 | `services.py:571-598` `_persist` | worker 配音分批 |
| 3 | `views.py:749-760` `regenerate_script_page` | 教师点单页重生成 |
| 4 | `views.py:684-706` `update_script` | 教师手改文本 |
| 5 | `views.py:770-812` `regenerate_audio_page` | 教师点单页重配音 |
| 6 | `views.py:652-668` `generate_scripts`（旧全量同步端点） | 前端已不用，建议 410 下线 |

只改 1、2 两处不够——3~5 仍然是裸读改写，照样能覆盖 worker 的结果。

**冲突**：现在这两条路径几乎不会同时发生（都靠浏览器串行驱动）。队列化后 worker 会
**持续几分钟**反复整数组回写，教师在界面上点"重新生成第 5 页"、或改完一页立即保存，
两边各持一份快照，后写者覆盖前者 —— **教师刚改的那页被 worker 的旧副本覆盖回去，或反之**。
这不是"可能发生"，是"只要教师在生成期间编辑就必发生"。

**修正**（两层，缺一不可）：

1. **落库改短事务 + 页级合并**：`select_for_update` 锁住 `TeachingVideo` 行 → `refresh_from_db` →
   只填充**目标页当前仍为空**的脚本 → save → 提交。DB 里已有非空值的页**永不覆盖**（尊重人工编辑）。
2. **`regenerate_script_page` / `regenerate_audio_page` 同样走这段短事务**，禁止裸读改写。

根治方案是把 `scripts` JSON 拆成 `TeachingScript` 子表（每页一行），但那是一次数据模型重构，
建议列入 P3，本期先用"锁 + 合并"把正确性兜住。

> 附带收益：合并规则天然实现"增量续跑只补空页"，与方案 §6 的幂等假设一致。

---

### C3 · `Dockerfile` 的 ENTRYPOINT 会吞掉 compose 的 `command`，worker 容器变成第二个 API

**证据**

```dockerfile
# deploy/Dockerfile.backend:54
ENTRYPOINT ["sh", "/app/deploy-entrypoint.sh"]
```

**冲突**：`docker-compose.yml` 里给 worker 服务写 `command: python manage.py ai_worker`
**不会覆盖 ENTRYPOINT**，只会作为参数附加，而 `deploy-entrypoint.sh` 从不读 `$@`——
最终 `exec gunicorn ...`。结果：worker 容器启动了一个**多余的 gunicorn**，
队列无人消费，且它还会与 API 容器抢着跑 `migrate`。

**修正**：

```yaml
worker:
  image: zhike-v2-backend
  entrypoint: ["python", "manage.py", "ai_worker"]   # 必须显式覆盖
  command: []
  depends_on:
    backend: { condition: service_started }           # 迁移由 backend 完成
```

并加启动自检：worker 起来先 `SELECT 1 FROM ai_task LIMIT 1`，失败则重试 60 次后退出
（避免它比迁移先就绪）。

---

## 2. P1 高

### C4 · 换 PPT 版本的"重置"从请求内挪到入队时 → 学生看到的内容被清空后干等排队

**证据**：`apps/courses/views.py:363-372`，`_invalidate_teaching_video_for_new_ppt()` 在生成**之前**
同步执行，清空 `scripts` 并把 `gen_status` 打回。

**冲突**：现在清空后几秒就开始重生成，学生几乎无感。队列化后"清空"发生在提交瞬间，
而任务可能排队 8 分钟 —— **这段时间学生看到的是空白章节**（且 `is_published` 已被影响）。

**修正**（v2.0 进一步细化，见方案 §6.3）：**"要不要清空"取决于 PPT 是否换版，不取决于是否提交了任务** ——

- **`ppt_id` 变了** → 旧讲稿与新课件不匹配，**必须立即下线**（并清学生观看进度）。排队期间学生看不到该章节是正确行为；
- **同版本 force 重生成** → **不清空、不下线**，学生继续看旧内容，完成后原位替换 + 更新 `published_at`。

v1.1 曾写"一律推迟到 worker 认领时重置"，那是过度修正：会让"新课件 + 旧讲稿"错配内容多存活几分钟。

---

### C5 · `AITask.progress` 的语义已被 question_gen 占用，队列元信息不能塞进去

**证据**：`apps/questions/views.py:233` 提交时把生成配置写进 `progress`；
`apps/questions/question_gen_ai.py:280-284` 执行时 `config = task.progress or {}` 读回来当配置用。

**冲突**：方案 §7.3 把 `queue_position` / `eta_seconds` 放进 `progress`。
对 question_gen 而言这是**配置载体**，队列写入会污染配置，导致"生成配置丢失/题型组为空"。

**修正**：
- `progress` **只归业务流水线所有**，队列层永不写入；
- `queue_position` / `eta_seconds` 由 `GET /ai-tasks/<id>/` **读时现算**（pending 队列里 id 小于它的条数），不落库；
- 任务参数一律进 `payload`（方案已有该字段，把 question_gen 的 groups/objective 也建议在 P3 迁过去，消除双语义）。

---

### C6 · 配音的前置检查在排队期必然误判

**证据**：`apps/courses/views.py:387-390`：`if not video or not video.scripts: 400 请先生成讲解稿`。

**冲突**：讲稿任务刚入队（`video.scripts` 还是空，因为重置也推迟了），教师顺手点配音 → 400；
或讲稿只生成了一半，配音把前半章先合成了，后半章永远没有音频（任务判据是"本次 todo 为空"，不是"全章齐"）。

**修正**：配音入队前的判定改为三态：
1. 存在 pending/running 的讲稿任务 → 429/400「讲稿正在生成中，完成后可配音」，并给出 task_id 供前端跟踪；
2. 讲稿已全齐 → 正常入队；
3. 讲稿部分齐且无在跑任务 → 允许，但 `payload.only_pages` 与 `progress.total` 按"全章页数"计算，避免提前判 done。

---

### C7 · D4 的"预留配额"与现有计量口径对不上，且重试必然超支

**证据**：`apps/ai/quota.py:45-49` `chat_calls_today()` 只数 `AICallLog`（capability=chat）；
`AICallLog` 是**调用时**才写。管理端 `/admin-panel/ai-quota/` 显示的也是这个数。

**冲突**：入队时没有任何 `AICallLog` 行 → 预留无处可放；而 worker 失败重试 3 次，
实际调用可能是预留量的 3 倍 → **预留形同虚设，超额仍会发生**。

**修正**（D4 按建议值的具体落法）：
- 新增 `AIQuotaReservation(task, user, amount, settled_amount, status)`；
- 提交时 `amount = ceil(pending_pages / chunk_pages) + 重试余量(20%)`，写入预留；
- 校验口径改为 `chat_calls_today(user) + active_reserved(user) >= limit` 则 429；
- 任务终结时按 `AICallLog` 实际条数 `settled_amount` 结算，差额释放；
- 管理端配额页展示 `已用 / 预留中 / 上限` 三段（否则教师看到的数字与实际拦截不一致）。

> 这条会让 `p5_security_check.py` 的 `p5_4_quota`（:303-320，只测 PUT/GET 设置）保持通过，
> 但配额页 UI 的断言可能需同步更新 —— 实施时跑一遍 P5 全量确认。

---

### C8 · 旧前端不会报错，但会**错误地宣布成功**

**证据**：`frontend/src/store/generation.js:158-163`：
`if (res.done) break` → `ElMessage.success('已生成 30 页讲解稿')`。
它读的是 `res.script_pages` / `res.pages`，入队响应里这两个值若填当前快照，就是 **0/30**。

**冲突**：D6 的"`done:true` 让旧循环立刻退出"只解决了"不死循环"，没解决"谎报完成"。

**修正**（v2.0 定稿为 410）：
- 新前端全局注入 axios 头 `X-AI-Task-Mode: queue`；**无此头 → 410 + 中文提示「生成方式已升级，请刷新页面」**；
- 不选 `done:true`：旧循环会弹「已生成 30 页讲解稿」，而实际 0 页——**谎报完成比报错更糟**；
- 也不选"啥都不返回"：`runScript` 的 `for(;;)` **没有重试上限**，`done` 为 undefined 时会每秒发一次请求，直接死循环；
- 新前端启动时 `localStorage.removeItem('zhike:generation-tasks')` 一次性废掉旧续跑记录；
- 该垫片只保留一个版本（代码内 `# TODO(2026-12) remove`），随后删除；
- **连带**：`test/e2e/script-progress-realtime-verify.py` 必须同批重写（它直连该接口且断言"请求进行中进度推进"），否则 CI 红。

---

## 3. P2 中

### C9 · `active` 端点硬截断 + 只查本人，撑不起任务中心和管理端看板

**证据**：`apps/ai/views.py:139-160`：`qs[:10]`，且固定 `triggered_by=request.user`。

**修正**：加 `page/page_size`；管理端看板另开 `GET /api/ai-tasks/queue/`（IsPlatformAdmin）返回
全量统计与列表；教师端只取本人（保持现口径）。

### C10 · 任务中心轮询会放大成持续 DB 压力

**冲突**：2.5s × 在线教师数。20 人在线 ≈ 8 rps 常驻，而全站只有 4 个请求线程。

**修正**：三层节流 ——
1. 无在跑任务时不轮询（或 30s 一次）；
2. `document.hidden` 时暂停；
3. 服务端对 `active` 结果加 3s 文件缓存（`CACHES["oversight"]` 同款，跨 worker 一致）。

### C11 · 本地向量模型会在 worker 里再加载一份

**证据**：`config/settings.py:570` 注释（BGE-M3 ≈ 2.3GB / Reranker ≈ 1.2GB，每 worker 懒加载）；
`apps/ai/local_models.py:31` `_load_lock`/`_infer_lock` 都是**进程内**。

**冲突**：讲稿完成后要 `ingest_video_scripts()`（`services.py:805`），它调 embed provider。
若 embed 配的是 `local`，worker 需要再吃 2.3GB 且与 API 各持一份模型 → 方案写的 `mem_limit: 4g` 会 OOM。

**修正**：`ingest_video_scripts` 不放在讲稿任务尾部同步跑，改为**独立的 `embed_ingest` 任务**；
worker `mem_limit` 与 backend 对齐 8g（或明确要求 embed 走远程 provider，用启动自检拦住 `local`）。

### C12 · `AITask` 表从"少量任务"变成"每次生成一行"，无 TTL

**修正**：`manage.py prune_ai_tasks --days 30 --keep-per-catalog 3`，挂 crontab；
`script_gen/audio_gen` 的 success 行保留最近 3 条即可（失败行保留全量，便于排查）。

### C13 · 测试基础设施是隐藏工时（604 行）

`apps/ai/tests_ai_task.py` 靠 `patch("apps.ai.tasks.threading", _FakeThreading)`（:187、:408）
把后台线程改同步。切 worker 后这条路径不存在，必须改为「直调 `_dispatch(task)` + 断言 DB 状态机」。
这块与业务代码工作量相当，排期不能按"改个测试"估。

---

## 4. P3 低（checklist）

| # | 事项 | 说明 |
|---|---|---|
| C14 | inline 开发模式双消费 | `AppConfig.ready()` 起消费线程必须判 `RUN_MAIN`（autoreload 子进程会再起一份）且 `sys.argv` 不含 `test`，否则本地双跑 + 测试连库 |
| C15 | worker 与 API 抢迁移 | C3 的连带；worker 必须 `entrypoint` 直启，不跑 migrate |
| C16 | 发布脚本漏掉 worker | `docker compose up -d backend` **不会**重建 worker → 新旧代码并存读新 schema。发布清单改为 `up -d backend worker` |
| C17 | 生成列唯一索引必须含 `task_type` | `UniqueConstraint(fields=["task_type","catalog"])` 的生成列表达式若只取 `catalog_id`，会导致**配音任务被讲稿任务挡住**（同章节两类任务互斥）。另外该约束必须 `atomic=False` 且幂等（`common/mysql_partial_unique.py` 已支持重跑） |

---

## 5. 对方案文档的具体修订

| 位置 | 现状 | 改为 |
|---|---|---|
| §8.2 | "保留对外接口，`CourseCatalog.vue` 的按钮无需改" | **错**。`CourseCatalog.vue:343-357` 用 `!!scriptTasks[id]` 当 loading，队列态会显示"讲稿 0/30"。必须加 `queued` 标志与"排队中（第 3 位）"文案 → 与 F3 自相矛盾，以 F3 为准 |
| §7.3 | `queue_position`/`eta_seconds` 放进 `progress` | 改为读时现算（C5），`progress` 归业务独占 |
| §5.1 | 只写了作业级/调用级槽位 | 补：`mem_limit` 与 embed provider 的耦合（C11） |
| §9 部署 | 只写"增 worker 服务" | 补 `entrypoint` 覆盖、`depends_on`、发布清单含 worker（C3/C15/C16） |
| §13.1-B5 | "删除 `_TASK_SEMAPHORE` 与 daemon 线程" | 补"重建 AI 调用上下文"（C1） |
| §13.3-O1 | `mem_limit: 4g` | 改 8g 或强制 embed 远程（C11） |
| §12-D6 | "响应 `done:true` 让旧循环退出" | 改为旧客户端 409 + 新前端清 legacy localStorage（C8） |

---

## 6. 经核验"不冲突"的假设（可以放心依赖）

1. **claim 的原子性成立，但理由与 SQLite 无关**（v1.1 此处措辞有误，2026-11-02 修正）：
   生产/开发/测试全部跑 MySQL（`.env` 的 `DATABASE_URL=mysql://zk:...`，测试库 `test_zk`），
   `SELECT ... FOR UPDATE SKIP LOCKED` 是**真实生效**的。`SETTINGS` 里的 SQLite 分支只是
   `DATABASE_URL=sqlite` 的休眠回退路径，不构成设计约束。
   条件更新 `filter(id=..., status=PENDING).update(...)` 与 `rowcount == 1` 判定**仍然保留**，
   但它的定位从"跨库兼容"改为**防御性不变量**：解决 `SKIP LOCKED` 覆盖不到的那一类竞争 ——
   心跳回收把任务改回 pending 的同时，消费者手里还攥着一份旧的 running 快照。
   "状态迁移只能成功一次"由这一句保证，而不是由隔离级别保证。
2. **`AITask` 外键删除行为可接受**：`catalog`/`classroom` 是 CASCADE、`course` 是 SET_NULL。
   worker 取到已被删除的任务行会 `DoesNotExist`，`_execute` 已有兜底（`tasks.py:78-80`）。
3. **移动端不受影响**：`app/src` 内无 `generate-script`/`generate-audio` 调用，H5 教师端不走这条链路。
4. **教师端有通知入口**：`layouts/MainLayout.vue:37-51` 已有通知铃铛 + 未读角标 + 30s 轮询，
   `users.Notification` 可直接用于"生成完成"推送，不需要新建通道。
5. **`version` 字段不冲突**：章节总结靠 `version` 递增做幂等，讲稿/配音任务 `version` 恒 1，
   且现有两个条件唯一索引的 `condition` 都带 `task_type`，与新索引不互相干扰。

---

## 7. 修订后的实施顺序（建议）

```
第 1 步  C3 + C15 + C16（部署骨架先通：空 ai_worker 容器能起来、能取到一张空表）
第 2 步  C17 + B1/B2（模型 + 迁移 + 索引，用 mysql_upgrade_check 断言）
第 3 步  C1（上下文重建）+ 队列内核 B3/B4
第 4 步  C2 + C4 + C6（落库正确性与时序，讲稿链路先跑通）
第 5 步  C5 + C9 + C10（端点与轮询）
第 6 步  C7（配额预留）+ C11（ingest 独立任务）
第 7 步  C8 + F1~F4（前端切换，前后端同批发布）
第 8 步  现有 4 类 AITask 迁移（C13 的测试重写在此发生）
```

前三步不碰任何业务逻辑，可以独立验证；第 4 步是真正的风险点（会动 `courses/views.py` 与
`services.py` 的落库方式），建议单独一个分支 + 本地 MySQL（`zk`）与测试库（`test_zk`）各跑一轮回归。

---

## 8. 三个阻断项的处理方案

### C1 · 上下文重建（改动面最小，但漏一步就白做）

**做法**：`apps/ai/tasks.py` 增加 task_type → scene 映射，`_dispatch` 入口重建；删掉 `submit_ai_task`
里的 `copy_call_context()`（跨进程是死代码）；**线程池内的 `copy_call_context()` 全部保留**
（那是同进程，仍然必要，如 `services.py:167`）。

```python
SCENE_OF = {
    AITask.TaskType.SCRIPT_GEN:      AICallLog.Scene.SCRIPT_GEN,
    AITask.TaskType.AUDIO_GEN:       AICallLog.Scene.TTS,
    AITask.TaskType.CLASS_ANALYTICS: AICallLog.Scene.ANALYTICS,
    AITask.TaskType.CHAPTER_SUMMARY: AICallLog.Scene.CHAPTER_SUMMARY,
    AITask.TaskType.QUESTION_GEN:    AICallLog.Scene.QUESTION_GEN,
    AITask.TaskType.COURSE_REUSE:    AICallLog.Scene.OTHER,
}

def _dispatch(task):
    set_current_user(task.triggered_by)          # calllog.py:117，无请求也能用
    with ai_scene(SCENE_OF[task.task_type], course_id=task.course_id):
        ...
```

**已核验的两个关键点**（避免想当然）：

1. `_resolve_user()`（`calllog.py:193`）优先读 `_current_user`，无请求时不报错、直接返回该 dict
   → 不需要伪造 request 对象；
2. `ai_scene` 只在**同 scene 嵌套**时复用 trace_id（`calllog.py:99-103`），每个任务进出一次
   → **一个任务 = 一个 trace_id**，正是管理端想要的调用链粒度。

**必须额外做的一步**：worker 是长驻循环，同一线程连续处理多个任务。每个任务结束后
`clear_current_user()`（或在循环顶部无条件重设），否则 A 教师的身份会泄漏给 B 教师的调用记录。
这条不在原方案里，是实施时最容易漏的。

**验证**：跑一次讲稿任务后断言
`AICallLog.objects.filter(scene="script_gen").order_by("-id").first()` 的
`triggered_by == 该教师`、`course_id` 非空、且该任务全部日志 `trace_id` 一致。
写进 `tests_queue.py` 作为一个用例。

---

### C2 · 页级合并（唯一需要动现有业务代码的阻断项）

**做法**：新增 `apps/courses/page_store.py`，把"写 `video.scripts`"收敛成唯一入口，
三个写点（分批讲稿、分批配音、单页重生成）全部改走它。

```python
def merge_pages(video_id, updates: dict[int, dict], *, overwrite_pages=()):
    """只做 DB 合并，绝不调 AI；调用方负责先拿到结果。"""
    with transaction.atomic():
        video = TeachingVideo.objects.select_for_update().get(id=video_id)
        scripts, index = _normalize(video.scripts)          # 按 page 建索引
        for page, patch in updates.items():
            item = index.get(page) or _append(scripts, page)
            for key, val in patch.items():
                if key in ("script", "audio_url") and page not in overwrite_pages:
                    if str(item.get(key) or "").strip():
                        continue                            # 已有非空值 → 不覆盖
                item[key] = val
        video.scripts = scripts
        video.save(update_fields=["scripts", "updated_at"])
```

**覆盖策略必须按来源区分**，否则要么吃掉人工编辑，要么让"重新生成"失效：

| 来源 | 目标页已有值 | 行为 |
|---|---|---|
| worker 自动分批（讲稿） | 有 `script` | **跳过**（尊重教师手改） |
| worker 自动分批（讲稿） | 空 | 写入 |
| 教师点「重新生成本页」 | 有 `script` | **覆盖**（`overwrite_pages={page}`） |
| worker 自动配音 | 有 `audio_url` | 跳过 |
| 教师点「重新配音本页」 | 有 `audio_url` | 覆盖 |

**三条纪律**（比代码更容易出错的地方）：

1. **事务内绝不调 AI**——锁只包 DB 读写，毫秒级。AI 调用在事务外，结果拿到后再进事务合并；
2. **不要跨批次持有 `video` 实例**——worker 一份实例会在几分钟里变陈旧，每批都 `merge_pages()` 重取；
3. `regenerate_script_page` 顺带清空的 `audio_url/subtitle_url/video_url` 必须并入同一事务，
   否则会出现"新讲稿 + 旧配音"的错配。

**验证**：起一个模拟 3 批的讲稿任务（provider 打桩为固定延迟），在第 1、2 批之间调
`regenerate_script_page(page=5)`，断言最终第 5 页是教师版本、其余页是 worker 版本、
无页丢失。

---

### C3 · 部署骨架（必须先做，否则 C1/C2 无从验证）

**做法**：compose 里显式覆盖 entrypoint，并让 worker 不做迁移、自带就绪自检。

```yaml
  worker:
    image: zhike-v2-backend
    container_name: zhike_v2_worker
    restart: unless-stopped
    entrypoint: ["python", "manage.py", "ai_worker"]   # 关键：覆盖 Dockerfile ENTRYPOINT
    command: []
    env_file: .env.production
    depends_on:
      backend: { condition: service_started }          # 迁移由 backend 独占
    stop_grace_period: 15s
    mem_limit: 8g
    volumes: [../data:/app/data, ../media:/app/media]
    networks: [zhike_v2_net, bnet-test]
```

worker 命令内建两道保险：

- **就绪自检**：`SELECT 1 FROM ai_task LIMIT 1`，失败每 2s 重试，60 次后退出（避免比迁移先起时反复重启刷日志）；
- **身份自报**：首行日志固定格式 `[ai_worker] pid=… slots(script=2,audio=2,analytics=2) poll=2s`，
  发布后 `docker logs --tail 5` 一眼可辨——这是防止"又变成 gunicorn"的最后一道人工检查。

**验证四条**：
1. `docker compose config | grep -A2 entrypoint` 有输出；
2. `docker exec zhike_v2_worker ps -ef` **不含 gunicorn**；
3. `docker logs` 首行是 `[ai_worker]`；
4. `manage.py ai_worker --selftest`（取一条假任务、不执行、打印队列深度）可单独跑通。

**残余风险**：后续有人改回 `command:` 会静默退化。兜底靠 `worker-health` 端点——
"队列有 pending 但 running 长期为 0 且无心跳" 直接判红，让错误可见而不是靠人记得。

---

### 执行顺序与依赖

```
C3（部署骨架）
  └─→ B1/B2（模型 + 迁移 + 索引）
        └─→ C1（上下文重建，单点改动，可独立验证）
              └─→ C2（页级合并 + 单页重生成改造，与讲稿流水线同批）
                    └─→ 其余 P1/P2 项
```

C3 是所有验证的载体，必须最先；C1 无依赖可并行；C2 必须与讲稿流水线一起改
（它改的就是落库路径本身，拆开做等于改两次）。
