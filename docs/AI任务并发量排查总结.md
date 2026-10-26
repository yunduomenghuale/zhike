# 智课系统 V2 · AI 任务并发量排查总结

> 排查时间：2026-10-26 ｜ 排查范围：backend/apps 全部 AI 链路（chat/embed/tts/rerank）
> 用途：并发治理专题的输入文档。本文自包含，无需翻阅历史会话。
> 代码基线：commit `189bed0`（deploy/production 分支）

---

## 0. 运行环境进程模型（一切并发结论的前提）

| 环境 | 进程模型 | 请求并发容量 | 备注 |
|---|---|---|---|
| 本地开发 | `manage.py runserver`（单进程， threaded） | 多线程，无硬上限 | 后端 `8005`，前端 `serve-local.js` 5273 |
| 生产（华为云 124.70.107.64:8088） | gunicorn `--workers 2 --threads 2 --timeout 180`（backend/deploy-entrypoint.sh） | **4 个请求处理器**（2×2） | nginx 反向代理；同步长请求占满 4 线程后全站排队 |

**核心结论先行**：进程内信号量/锁在多进程下会按 worker 数稀释——凡标注「进程内」的机制，生产实际值 = 标注值 × 2。

---

## 1. 总览表

| # | AI 功能 | 触发方式 | 执行模式 | 并发上限（本地/生产） | 防重复机制 | 风险等级 |
|---|---|---|---|---|---|---|
| 1 | AI 生题（question_gen） | 教师提交 | AITask 后台线程 | 信号量 2 / **4** | DB 唯一索引（教师+课程） | 低 |
| 2 | 班级学情分析（class_analytics） | 教师提交 | AITask 后台线程 | 信号量 2 / **4** | ⚠️ 仅应用层 10 分钟频率检查 | **中** |
| 3 | 章节学习总结（chapter_summary） | 学生完成章节后自动/手动 | AITask 后台线程 | 信号量 2 / **4** | DB 唯一索引（学生+章节）+ force 5 分钟限频 | 低 |
| 4 | 学生 RAG 问答（ask / ask-stream） | 学生提问 | **请求内同步 / SSE 流式** | **无上限**（≤4 请求线程） | 无 | **高** |
| 5 | 讲稿生成（分批轮询驱动） | 教师按批触发 | 请求内同步 + 批内线程池 4 | 无全局上限（≈教师数×4 LLM 并发） | 无 | 中 |
| 6 | AI 配音（分批轮询驱动） | 教师按批触发 | 请求内同步 + 批内线程池 3 | 无全局上限（≈教师数×3 TTS 并发） | 无 | 中 |
| 7 | 授课计划 AI 目录 | 教师上传计划 | 请求内同步单次调用 | 无（占 1 请求线程至返回） | 无 | 低 |
| 8 | 资料/课件 embedding 入库 | 上传即触发 | 请求内同步 | 无（占 1 请求线程至完成） | 无 | 中 |
| 9 | PPT 页面渲染（LibreOffice） | 课件上传后 | 后台串行 | **全局 1**（进程内 Lock + 跨进程 SQLite 锁库） | — | 低 |
| 10 | 本地模型推理（BGE-M3 / Qwen3-Reranker） | embed/rerank 调用点 | 进程内串行 | 1 / **2**（每 worker 1） | — | 低 |

---

## 2. AITask 异步框架（功能 1-3 共用）

**代码**：`backend/apps/ai/tasks.py`

- `submit_ai_task()`：建行（PENDING）→ 拉起 daemon 线程执行，秒级返回 task_id；前端 2.5s 轮询 `/api/ai-tasks/<id>/`。
- **全局信号量** `_TASK_SEMAPHORE = threading.BoundedSemaphore(2)`（tasks.py:32）：三类任务共享；`acquire(timeout=600)`，排队超 10 分钟标 FAILED「排队超时，请重试」（tasks.py:62-67）。
- **多进程稀释**：信号量是进程内对象，生产 2 workers → 实际全系统最多 **4** 个 AI 任务同时执行，并非全局 2。
- 单任务失败仅落自身 `error`，不影响其它任务；线程入口 `close_old_connections()` 防连接残留。

### 2.1 各任务类型的防重复机制

| 任务类型 | 机制 | 位置 | 跨进程有效？ |
|---|---|---|---|
| question_gen | 部分唯一索引 `uniq_active_question_gen`（task_type+triggered_by+course，status∈pending/running），冲突转 400「已有进行中的生题任务」 | `apps/ai/models.py:365-371`；`apps/questions/views.py:163-165` | ✅ DB 层 |
| chapter_summary | 部分唯一索引 `uniqi_active_chapter_summary`（task_type+student+catalog）；进行中/Success 幂等复用；force 重建 5 分钟限 1 次（D8）；FAILED 不限 | `apps/ai/models.py:358-364`；`apps/analytics/views.py:111-145` | ✅ DB 层 |
| class_analytics | **仅应用层检查**：同班级 10 分钟内有进行中/已完成任务则 429，FAILED 允许立即重试 | `apps/analytics/views.py:75-100`（`RATE_LIMIT_MINUTES=10`） | ❌ 先查后插可竞态双跑 |

**学情分析双跑窗口**：两个并发请求同时通过 `recent.exists()` 检查 → 各自建行双跑（单次分析 2-4 分钟 LLM 成本）。建议补 `(task_type, classroom)` 进行中唯一索引，与生题同款（注意 classroom 可空 SET_NULL 的 NULL 语义，SQLite 下 NULL 互不冲突，需评估或改用非空约束方案）。

---

## 3. 请求内同步链路（功能 4-8，无全局并发管控）

这些链路**不经 AITask 框架**，没有信号量/队列/限流；并发 = 同时到达的请求数，硬顶 = gunicorn 4 个请求线程。LLM provider 层（`apps/ai/providers/`）**无客户端 QPS 限流**，靠 provider 报错 + 调用方重试兜底。

### 3.1 学生 RAG 问答（当前最脆弱链路）

- 代码：`apps/knowledge/views.py` `ask()`（:380）/ `ask_stream()`（:431，SSE 流式）。
- 每请求成本：1 次向量检索（+可能 1 次本地 rerank）+ 1 次 LLM chat（流式期间**一直占用**请求线程）。
- **无队列、无单用户限频、无全局限流**：N 个学生同时提问 = N 个并发 LLM 调用；4 个请求线程占满后，第 5 个请求（含普通页面 API）开始排队，表现为全站卡顿。
- 生产 180s gunicorn 超时是仅有兜底；超时后 worker 线程被强杀，LLM 调用残留由 provider 超时控制。

### 3.2 讲稿生成（T-V-02）

- 入口：`apps/courses/views.py:159` `generate_script_pages_batched`（`apps/ai/services.py:101`）。
- 形态：前端分批轮询驱动——每 HTTP 请求同步处理一批（`batch_size` 默认 6、上限 12，实际每批最多 `batch_size*2` 页）；批内再切 3 页/小块（`AI_SCRIPT_CHUNK_PAGES`，services.py:117），`ThreadPoolExecutor(max_workers=min(4, chunks))` 并发调 LLM（services.py:162），as_completed 逐块落库。
- 并发量级：**无全局上限**——M 个教师同时生成 = 最多 M×4 并发 LLM 调用（受 4 请求线程自然封顶，M≤4）。

### 3.3 AI 配音（T-V-03）

- 入口：`apps/courses/views.py:188` `synthesize_audio_for_video`（`apps/ai/services.py:587`）。
- 形态：同讲稿——前端分批（默认 3 页/批、上限 10），批内 `ThreadPoolExecutor(max_workers=min(3, todo))` 并发 TTS，每页合成即落库。
- 并发量级：无全局上限（M 教师 × 3）。

### 3.4 授课计划 AI 目录（T-D-02）

- 入口：`apps/courses/views.py:216-228` `generate-from-plan` → `generate_catalog_from_plan`。
- 单次同步 LLM 调用，占 1 请求线程至返回；无防重（重复点击 = 重复调用，仅前端按钮 loading 防连点）。

### 3.5 资料/课件 embedding 入库

- 资料：`apps/knowledge/views.py:204/210` `ingest_material`（上传请求内同步切块 + embedding）。
- 课件：`ingest_ppt_pages` 上传即入库（课件解析进度 courses/0009，ingest 在 status 翻 done 后才跑）。
- embedding 提供方：DashScope 远程（批量上限 10/次，openai_compat 自动分批）或本地 BGE-M3（见 §4.2 串行锁）。
- 大文件上传会占住 1 请求线程直至 embedding 完成。

---

## 4. 全局/进程内串行点

### 4.1 PPT 页面渲染（真·全局 1）

- `apps/courses/ppt_parser.py:89` `_RENDER_THREAD_LOCK`：进程内排队；
- 跨进程：**独立 SQLite 锁库**（非业务库）实现文件锁，多进程下也只允许 1 个 LibreOffice 渲染进程——全系统渲染严格串行（防 LibreOffice 并发崩溃，设计如此，勿放宽）。

### 4.2 本地模型推理（每进程 1）

- `apps/ai/local_models.py:31-32` `_load_lock`（加载）+ `_infer_lock`（推理）：BGE-M3 / Qwen3-Reranker 推理进程内串行；
- 生产 2 workers → 全局推理并发 = 2。embed/rerank 全部走本地时，高并发问答会在 `_infer_lock` 上排队（天然限流，但表现为请求变慢）。

---

## 5. 其它相关现状

- **全站无 DRF throttle**：仅平台管理端有 `AdminScopedThrottle`（督管端点按 action_scopes 限流）；业务端（含全部 AI 端点）无频率限制。
- **qa_quality_scan（QA 质量 A 档自动化）尚未实现**，无并发内容可排查。
- **AI 费用/配额**：无按用户/课程的 LLM 调用配额与费用限流（AICallLog 只记录不限制）。
- **TTS 双分支**：DashScope / OpenAI 兼容，超时与发音人管理端可配；provider 层无并发限制。

---

## 6. 风险清单（按建议处理优先级）

| 优先级 | 问题 | 影响 | 建议方向 |
|---|---|---|---|
| P0 | 学生 RAG 问答零防护 | 4 个学生流式提问即占满全部请求容量，全站排队 | 单用户限频（如 1 并发/学生 + 每分钟 N 次）；全站 AI 端点 DRF throttle；必要时 SSE 移出请求线程（队列化） |
| P0 | 学情分析 10 分钟限流可竞态双跑 | 双击/并发请求双倍 LLM 成本 | 补 `(task_type, classroom)` 进行中部分唯一索引（对齐 question_gen 模式），端点捕获 IntegrityError 转中文 |
| P1 | 同步链路（讲稿/配音/embedding/目录）无全局上限 | 多教师同时操作时 LLM QPS 失控、请求线程被长任务占满 | 迁移到 AITask 框架（复用信号量+轮询），或进程级计数器 + Redis/DB 分布式信号量 |
| P1 | AITask 信号量多进程失真（标 2 实 4） | workers 扩容后进一步稀释，LLM QPS 超供 | 换 DB 行计数/Redis 信号量，或在 .env 显式声明「每进程并发」语义并文档化 |
| P2 | 无 AI 费用/配额限制 | 滥用无闸门 | 基于 AICallLog 做按用户/课程日配额（QA 看板 Phase 4 B 档可承载） |
| P2 | gunicorn 180s 超时与长 LLM 调用不匹配 | 流式/批量场景请求被强杀 | 长链路异步化（AITask）后超时压力自然解除；provider timeout 需 < 180s |

---

## 7. 关键文件索引

| 主题 | 文件 | 关键位置 |
|---|---|---|
| AITask 框架/信号量 | `backend/apps/ai/tasks.py` | :32 信号量、:62 排队超时、:35 submit |
| AITask 模型/唯一索引 | `backend/apps/ai/models.py` | :358-371 两个部分唯一索引 |
| AI 生题提交端点 | `backend/apps/questions/views.py` | :119-169 generate、:163 冲突文案 |
| AI 生题流水线（分块进度） | `backend/apps/questions/question_gen_ai.py` | GEN_CHUNK=3、run_question_gen |
| 学情分析提交/限流 | `backend/apps/analytics/views.py` | :75 RATE_LIMIT_MINUTES、:90-100 竞态窗口、:111-145 章节总结幂等 |
| 章节总结/学情分析流水线 | `backend/apps/ai/analytics_ai.py` | :33-34 BATCH_SIZE=5/BATCH_WORKERS=4、:480 批内线程池 |
| RAG 问答端点 | `backend/apps/knowledge/views.py` | :380 ask、:431 ask-stream |
| 讲稿分批+小块并发 | `backend/apps/ai/services.py` | :101-181（batch_size=6、chunk 3 页、池 4） |
| 配音分批并发 | `backend/apps/ai/services.py` | :587（池 3） |
| 讲稿/配音入口端点 | `backend/apps/courses/views.py` | :143-168 讲稿、:170-214 配音、:216-228 目录 |
| embedding 入库 | `backend/apps/ai/services.py:682`、`apps/knowledge/views.py:204/210` | ingest_material 同步 |
| PPT 渲染全局锁 | `backend/apps/courses/ppt_parser.py` | :89 起（进程 Lock + SQLite 锁库） |
| 本地模型推理锁 | `backend/apps/ai/local_models.py` | :31-32、:98、:171 |
| 生产进程模型 | `backend/deploy-entrypoint.sh` | gunicorn 2w×2t×180s |
