# AI 队列化与课件渲染 · 开发执行交接书

> 用途：**新会话（开发执行）的唯一起点**。方案讨论已在上一会话完成并两轮评审，本文件不重复设计，
> 只回答"从哪开始、按什么顺序、哪些坑不能踩、什么时候必须停下来"。
> 时间：2026-11-02 ｜ 状态：待执行

---

## 1. 开工前（15 分钟）

### 1.1 必读文档（按顺序，读完再动手）

| # | 文档 | 读什么 | 不读会怎样 |
|---|---|---|---|
| 1 | `docs/AI长任务队列化改造方案.md`（v2.0） | §4 数据模型、§5 调度、§6 状态机、§7 接口、§13 实施分解 | 会按"常规异步任务"想当然设计，踩已记录的 17 个坑 |
| 2 | `docs/AI长任务队列化-实施冲突评审.md` | §8 三个阻断项处理方案（C1/C2/C3） | 上线后发现成本报表全空、教师手改被覆盖、worker 没跑 |
| 3 | `docs/课件解析与渲染链路改造-方案讨论.md`（v1.2） | §2 W0–W6、§7 自审 16 项 | 并发改完看不到效果（F1/F2）、上传第二版课件永远不解析（F3） |
| 4 | `docs/AI队列与课件渲染-实测测试方案.md` | §2–§5 与 §8 | 拿 7 个"注定会红"的旧测试当 bug 查 |

### 1.2 环境

```bash
# 后端（不要用 Miniconda 的解释器）
cd backend && ./venv/Scripts/python.exe manage.py runserver 8005

# worker（独立终端；不要用 AI_QUEUE_MODE=inline，autoreload 会起两个消费者）
cd backend && ./venv/Scripts/python.exe manage.py ai_worker

# 前端（dist + 代理 8005）
node serve-local.js          # 5273；改源码要重新 build
```

- 库：本地 `zk`（`mysql://zk:zk123456@127.0.0.1:3306/zk`），测试库 `test_zk`（`--keepdb`）
- 账号：管理员 `admin / A0987654`，教师 `20249999`；`t101` 的 `pass1234` 已失效
- 改 `.env` 或后端代码必须**杀进程完整重启**（autoreloader 继承旧 env）
- `curl` 加 `--noproxy '*'`，API 路径带尾斜杠

---

## 2. 已锁定、不得再讨论的决策

| # | 决策 | 结论 |
|---|---|---|
| D1 | 队列载体 | MySQL 表 + 独立 `ai_worker` 容器（不引 Redis/Celery） |
| D2 | 范围 | 讲稿 + 配音 + 现有 4 类 AITask + 课件解析，统一一套队列 |
| D3 | 并发 | 三层：作业槽位（讲稿2/配音2/分析2/课件2）× 用户 running≤1 × 调用闸门（chat6/tts4） |
| D4 | 配额 | 提交时按预估页数预留，按 `trace_id` 结算，6h 过期回收 |
| D5 | 发布语义 | 讲稿/配音全完成仍自动 `is_published=True`；换 PPT 版本立即下线，同版本 force 保持可见 |
| D6 | 旧接口 | 无 `X-AI-Task-Mode` 头 → 410；路径不变 |
| E1 | 课件改造 | 三件事一次做完（异步化 + 渲染并发 2 + md5 复用） |
| E2 | 渲染并发 | `AI_RENDER_CONCURRENCY=2`、PDF 独立信号量 3、删进程内 `threading.Lock` |
| E3 | 任务归属 | `ppt_parse` 与讲稿同一个 worker，`AI_JOB_SLOTS_PPT=2` |

其余 12 项疑问的结论见方案 §14，**不要逐条重新论证**。

---

## 2.5 开发规则（强制，每个阶段都适用）

### 2.5.1 阶段完成的定义 = **实测通过 + 已推送**，缺一不可

一个阶段只有同时满足下面三条才算完成，否则不进下一阶段：

1. **功能实测通过**：在真实运行栈上跑通该阶段指定的验证命令，输出留在会话里；
2. **回归通过**：受影响的既有测试全绿（含交接书 §5 里"已知会红"的文件改写后的版本）；
3. **已推送到远端**：对应 commit 在 `origin/feature/ai-queue` 上，且汇报里给出 hash。

> 单测通过**不等于**实测通过。单元测试证明的是"逻辑对"，实测证明的是"在真栈上跑得通"——
> 这次改的全是并发、队列、锁、跨进程上下文，单测里最不可能暴露问题。两者都要过。

### 2.5.2 "实测"的判定标准

- 必须起真实进程：后端 `runserver 8005` + `manage.py ai_worker` + 前端 `serve-local 5273`
  （纯 API 阶段可不起前端，但**必须起 worker**——没有 worker 的"实测"只测了入队）；
- 必须用文档里给的验证方式，不许自创简化版：阶段判据在交接书 §3，分层用例在
  `docs/AI队列与课件渲染-实测测试方案.md` §2–§5；
- 必须留**可复核的证据**：命令原文 + 关键输出。优先要数字（队列深度、并发数、耗时、断言条数、
  `ps` 看到的 soffice 进程数），其次日志片段，交互类补截图；
- **mock 结果不能冒充实测**：`MockProvider.tts()` 恒返回同一个占位 mp3，所有页 URL 相同——
  "每页都有 audio_url"在 mock 下是平凡成立的。

### 2.5.3 不通过怎么办

```
失败 → 定位根因（读代码/加日志，不猜） → 修复
     → 重跑该阶段**全部**验证项（不是只重跑失败那一项）
     → 通过则推送；仍失败则继续
     → 同一原因连续两次修不好 → 停下来汇报，不要硬凑
```

三条禁止：

- **禁止**通过注释断言、放宽阈值、跳过用例来"让它过"；
- **禁止**只重跑失败项就宣布阶段通过（修复可能破坏同阶段其它用例）；
- **禁止**把未验证的改动先推上去"占位"。

### 2.5.4 推送规范

- **分支**：已建好 `feature/ai-queue`（基于 `3ed91d9`，从 `feature/org-refactor` 切出），新会话直接
  `git checkout feature/ai-queue` 工作，每个阶段一个 commit；不要切回 `feature/org-refactor`。
- **只提交本阶段相关的明确路径**：`git add backend/apps/ai/queue.py backend/apps/ai/models.py ...`。
  工作区已于 2026-11-02 清理（历史杂项分 4 个 commit 入库），但仍**禁止 `git add -A` / `git add -u`**
  ——规则不变，防止今后混入无关改动。
- **commit message**：`feat(队列): 阶段N <做了什么>` / `fix(队列): <修了什么>`，中文，模块在前。
- **同一 commit 必须包含**：代码改动 + 迁移文件（若有）+ 该阶段的验证脚本/用例。
- **不得入库**：`.env`、`media/`、`*.sqlite3`、`data/`、临时日志。
- **禁止** `--no-verify`、禁止 force push、禁止 amend 已推送的 commit。
- push 遇到 502 属沙箱已知问题，重试即可；连续 3 次失败再上报。

### 2.5.6 本地覆盖边界（必须知道哪些测不了）

以下三项**在 Windows 本地环境无法验证**，不是测试偷懒，是平台限制：

| 缺口 | 为什么本地测不了 | 闭环途径（三选一） |
|---|---|---|
| **soffice 并发 2**（阶段 6 关键判据） | 本地开发走 PowerPoint COM 路径（`_render_with_powerpoint` 优先，COM 单实例），`AI_RENDER_CONCURRENCY` 强制 1——**Windows 上永远看不到 2 个 soffice** | ① 过渡机 124.70.107.64（CentOS+Docker，公网可连）起容器验证；② 本地 Docker Desktop 用 `Dockerfile.fast` 起 backend+worker（首次构建要下 torch，慢）；③ 放到生产灰度第一步验证，**前提是 worker 日志自报槽位**（见下） |
| **容器编排语义**（ENTRYPOINT 覆盖 / stop_grace_period / depends_on / 双容器共享 `/app/data` 锁库） | compose 的这些行为只在 Linux 容器成立；本地 `bnet-test` 是生产专属网络，compose 起不来 | 同上①②；阶段 0 的 compose 语法检查（`docker compose config`）本地可做，但语义验证必须容器环境 |
| **L6 生产灰度** | 定义上就在生产 | 观察指标 + 分步开关（测试方案 §7） |

**配套要求（让缺口可兜底）**：渲染获取槽位时必须打日志 `[render] slot=1/2 acquired, file=xxx`；
`worker-health` 端点必须输出 `AI_RENDER_CONCURRENCY` 与当前占用的槽位号。
这样途径③不靠 `ps` 也能验证并发生效。

### 2.5.5 每阶段汇报必须包含推送结果

```
阶段 N 完成
改动：path/to/file.py:120-180（做了什么）
实测：命令 + 关键输出（数字优先）
回归：受影响的测试文件 + 结果
推送：分支 feature/ai-queue / commit <hash> / 已 push
遗留：…
回滚点：<hash>
```

---

## 3. 执行顺序（阶段 0 → 7）

> 每个阶段都必须「**实测通过 + 已推送**」后才进下一阶段（详见 §2.5）。每阶段结束记录一个
> 可回滚点（该阶段 commit hash）。

### 阶段 0 · 部署骨架（半天，零业务改动）

**改**：`deploy/docker-compose.yml` 增 `worker` 服务；`apps/ai/management/commands/ai_worker.py` 空壳（含 `--selftest`）。

```yaml
worker:
  image: zhike-v2-backend
  entrypoint: ["python", "manage.py", "ai_worker"]   # 关键：不写 entrypoint 会变成第二个 gunicorn
  command: []
  depends_on: { backend: { condition: service_started } }   # 迁移由 backend 独占
  stop_grace_period: 15s
  mem_limit: 8g
```

**验证**：`docker compose config | grep entrypoint` 有输出；容器内 `ps -ef` 无 gunicorn；
日志首行 `[ai_worker] pid=… slots(...)`；`--selftest` 能连库打印队列深度。

### 阶段 1 · 模型与迁移

**改**：`apps/ai/models.py`（9 个新字段 + 4 个 task_type + `ppt` FK）、新迁移、`scripts/mysql_upgrade_check.py` 加断言。

**关键**：两条条件唯一约束必须走生成列方案（`common/mysql_partial_unique.py`），
`RunPython` 里 `atomic = False`；`ppt_parse` 用 `(task_type, ppt)`，**不能用 catalog**。

**验证**：迁移在 `zk` 与 `test_zk` 各跑一次；查 `information_schema.statistics` 确认索引真实存在；
连续跑两次迁移不报 "Duplicate column"。

### 阶段 2 · 队列内核与上下文

**改**：新建 `apps/ai/queue.py`（enqueue/claim/heartbeat/reap/cancel）、`apps/ai/gate.py`（调用闸门）、
`apps/ai/tasks.py`（`submit_ai_task` 只入队；`_dispatch` 加 `SCENE_OF` + `set_current_user` + `ai_scene`；删 `_TASK_SEMAPHORE` 与 `copy_call_context`）。

**验证**：`tests_queue.py` 的 Q1–Q7、Q10、Q11（`TransactionTestCase`）；
手工塞一条假任务，跑通"入队→认领→心跳→成功"。

### 阶段 3 · 讲稿链路（最危险的一阶段）

**改**：新建 `apps/courses/page_store.py`（`merge_pages`）；收敛 **6 处** `video.scripts` 写点；
新建讲稿执行体（整章循环）；`generate_script` 改为入队 + force 协议 + 旧客户端 410。

**验证**：Q9 merge 用例；本地点一次生成，"生成中手改第 5 页"后该页不被覆盖。

### 阶段 4 · 配音链路

**改**：配音执行体、三态依赖判定（讲稿在跑 → 409 `wait_script`）。

**验证**：讲稿与配音先后跑通；讲稿排队时点配音返回明确提示。

### 阶段 5 · 前端

**改**：`store/generation.js` 瘦身、新增 `AiTaskCenter.vue`、`CourseCatalog.vue` 两处（queued 分支 + 不立即 done）、
轮询节流、启动清 `zhike:generation-tasks`。

**验证**：浏览器 E2E T1–T5、T9；刷新/关页/连点/旧客户端四个场景。

### 阶段 6 · 课件解析与渲染

**改**：`ppt_parser.py`（锁槽位化 + 删线程锁 + profile 池 + PDF 信号量 + 逐槽 0.2s 轮询）、
`courses/views.py`（**override `create()`** + 入队）、`ingest` 改"先建后删"、md5 字段。

**验证**：4 人上传时 `ps` 看到 **2 个 soffice**；PDF 上传不产生 soffice；T6/T7；F5 片段空窗验证。

### 阶段 7 · 存量任务迁移与收尾

**改**：4 类既有 AITask 切队列（删 `_TASK_SEMAPHORE` 的残留）、`AIQuotaReservation`、`prune_ai_tasks` 命令、管理端队列看板。

**验证**：`tests_ai_task.py`（604 行）改造后全绿；配额三段展示；P1/P4/P5 脚本全绿。

---

## 4. 坑清单（每条都踩过或推演过，不要重新发现）

### 4.1 部署与容器

1. Dockerfile 的 `ENTRYPOINT ["sh","/app/deploy-entrypoint.sh"]` **不读 `command`**，worker 必须显式 `entrypoint:`，否则静默变成第二个 gunicorn（还抢着跑 migrate）。
2. worker 不跑 migrate；启动先 `SELECT 1 FROM ai_task` 自检，失败重试 60 次。
3. 发布必须 `docker compose up -d backend worker`——只重启 backend 会新旧代码并存读新 schema。
4. 渲染锁库必须放 `/app/data`，**不能放 `/tmp`**（backend 与 worker 不共享 tempdir）。

### 4.2 数据库

5. MySQL 会**静默丢弃**条件唯一约束 → 生成列 + 普通唯一索引；`atomic=False`；生成列表达式必须含 `task_type`（否则配音被讲稿挡住）与 `ppt_id`。
6. `ppt_parse` 去重键是 `ppt` 不是 `catalog`（一个章节有多个 PPT 版本）。
7. 队列测试必须 `TransactionTestCase`（`TestCase` 外层事务让 `select_for_update` 不阻塞，断言会假绿）。
8. `manage.py test --keepdb`，不带会重建库（20 分钟，中途别 kill）。

### 4.3 并发与任务

9. claim = `SKIP LOCKED` + 条件更新 `rowcount==1`；不要用内存锁。
10. 心跳必须单条 `update()`，**不能 `task.save()`**（整行覆盖 `progress`，与 `question_gen_ai.py:59` 同一个坑）。
11. dedupe 只能捕获 `IntegrityError`，**不能先查后插**（同学情分析双跑竞态）。
12. 长驻循环每任务必须重设用户，否则 A 教师身份串到 B 教师日志。
13. 任务线程退出 `close_old_connections()`，否则长驻进程连接泄漏。
14. 事务内**绝不调 AI**；闸门持锁期间不碰 DB。
15. 闸门挂任务流水线的单次调用（5 处），**不要挂 `factory.get_provider()`**（会把学生 SSE 问答也罩进去）。

### 4.4 内容写入（最容易丢数据）

16. `video.scripts` 有 **6 处**整数组读改写：分批讲稿、分批配音、`regenerate_script_page`、`update_script`、`regenerate_audio_page`、`generate_scripts`(旧端点)。全部收敛到 `page_store.merge_pages`。
17. 覆盖策略按来源区分：worker 只填空页，教师显式重生成才覆盖。
18. 不要跨批次持有 `video` 实例；每批 `select_for_update` 重取。
19. `done` 的分母用 `len(ppt.parsed_pages)`，**不是 `len(scripts)`**（会误判完成并发布）。
20. 课件入库改"先建后删"，否则 ingest 静默失败会留下永久无向量的课程。

### 4.5 前端

21. 旧客户端必须 410：给 `done:true` 是谎报完成，什么都不给会触发 `for(;;)` 死循环。
22. 新前端启动清 `localStorage['zhike:generation-tasks']`。
23. 上传响应秒回后，轮询首拍可能查不到记录 → 按 `ppt_id` 兜底并宽限 2 拍。
24. `PPT_PARSE_ACTIVE_STAGES` 不需要新增 `queued`（`parse_status=parsing` 已覆盖），但排队超 10 分钟会被 stale 误判。
25. `CourseCatalog.vue` 用 `!!scriptTasks[id]` 当 loading，队列态必须加 `queued` 分支。

### 4.6 渲染

26. 必须删除 `ppt_parser.py:87` 的 `_RENDER_THREAD_LOCK`，否则进程内并发恒为 1。
27. `AI_JOB_SLOTS_PPT` 必须等于 `AI_RENDER_CONCURRENCY`，否则并发 2 用不上。
28. 槽位等待逐槽 `timeout=0.2` 轮询，不要对每个槽用长 timeout（会卡死在 0 号槽）。
29. 现有"抢锁异常退化为直接渲染"在多槽模式等于取消保护，只允许 Windows 单槽退化。

### 4.7 验证脚本

30. `p5_security_check.py` 输出**必须落文件**，走管道会因 64K 写满冻结服务。
31. 生产 `192.168.3.145` 是机房内网，**本任务不动生产**；本地数据与生产不同，禁止本地覆盖。

---

## 5. 已知会红的 7 个测试文件（改造预算，不是 bug）

| 文件 | 原因 |
|---|---|
| `test/e2e/script-progress-realtime-verify.py` | 断言"请求进行中进度推进" |
| `test/e2e/generation-persist-verify.js` | GP.1–GP.6 全围绕 localStorage 续跑 |
| `test/e2e/parse-progress-realtime-verify.py` | 上传同步 + 响应带 `parsed_pages` |
| `test/e2e/parse-progress-freeze-repro.py` | 同上 |
| `test/e2e/parse-progress-fix-verify.js` | 同上 |
| `backend/apps/courses/tests.py:76/695` | upload 助手断言响应含 `parsed_pages` |
| `backend/apps/ai/tests_ai_task.py` | `_FakeThreading` 路径消失 |

---

## 6. 停止条件（遇到必须停下来问，不要自行决定）

1. 文档与代码不一致（行号漂移不算，逻辑不一致才算）。
2. 需要修改对外 API 契约的**非本任务部分**（如鉴权、分页格式）。
3. 需要动生产服务器、生产库，或需要跑数据迁移。
4. 测试会碰真实课程/真实学生数据（E2E 必须自建自清，只删本链自建 id）。
5. 某一阶段的验证连续两次不过，且原因不属于坑清单里的任何一条。

---

## 7. 每阶段汇报格式

见 §2.5.5。核心是三样：**改了什么（路径:行）／实测命令与关键数字／推送的 commit hash**。
缺推送 hash 的汇报视为阶段未完成。

---

## 8. 附：新会话提示词（可直接复制）

```
你是智课系统V2（Django 5 + DRF + Vue3，MySQL 8）的开发执行者。
任务：落地「AI 长任务队列化 + 课件解析渲染改造」。方案已在上一会话完成并通过两轮评审，
不要重新设计，也不要重新论证已有决策。

开工前先按顺序读这五份文档，读完再动手：
1. docs/AI队列化-开发执行交接书.md      ← 唯一入口：开发规则、顺序、坑清单、停止条件
2. docs/AI长任务队列化改造方案.md        ← v2.0 架构与数据模型
3. docs/AI长任务队列化-实施冲突评审.md    ← 3 个阻断项的处理方案
4. docs/课件解析与渲染链路改造-方案讨论.md ← v1.2 + §7 自审
5. docs/AI队列与课件渲染-实测测试方案.md   ← 六层测试与 DoD

硬约束（不可协商）：
- 只跑 MySQL（本地 zk / 测试 test_zk）。禁止以 SQLite 兼容为由做设计取舍；
  manage.py test 必须带 --keepdb。
- 不引入 Redis / Celery / 任何新中间件；worker 单副本。
- 严格按交接书阶段 0→7 推进，每个阶段自测通过再进下一阶段，禁止一次性大改。
- 不改与本任务无关的模块；不动生产服务器 192.168.3.145；不跑生产数据迁移。
- E2E 测试数据必须自建自清，只删本链自建的 id，不碰真实课程与学生数据。

开发规则（强制）：
- 每个阶段的完成 = 实测通过 + 已推送，缺一不可；未通过就排查调试，不得进入下一阶段。
- "实测"指真实进程栈（backend 8005 + ai_worker + 前端 5273）上跑交接书指定的验证命令，
  并留下命令与关键数字；单测通过不等于实测通过；mock 结果不能冒充实测。
- 失败时先定位根因再改，禁止注释断言/放宽阈值/跳过用例；修复后要重跑该阶段全部验证项，
  不能只重跑失败项。同一原因连续两次修不好，停下来问我。
- 分支 feature/ai-queue 已建好（基于 3ed91d9），直接 git checkout feature/ai-queue 工作；
  只 git add 本阶段相关路径，禁止 git add -A / -u。
- commit 格式 feat(队列): 阶段N …；不得 --no-verify、不得 force push；push 502 重试即可。
- 每阶段汇报：改动路径:行 / 实测命令与关键数字 / 回归结果 / commit hash / 回滚点。

工作方式：
- 先做阶段 0（部署骨架），它不碰业务逻辑，用来确认 worker 容器跑的是 ai_worker 而不是第二个 gunicorn。
- 阶段 3（video.scripts 六处写点收敛）是最危险的一步，验收就一条：
  生成期间改第 5 页，跑完后第 5 页仍是改后的版本。
- 遇到交接书 §6 的 5 类停止条件，先停下来问我。
```
