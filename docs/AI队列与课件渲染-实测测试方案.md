# AI 队列与课件渲染 · 实测测试方案

> 对象：`docs/AI长任务队列化改造方案.md`（v2.0）＋`docs/课件解析与渲染链路改造-方案讨论.md`（v1.2）
> 时间：2026-11-02 ｜ 状态：待实施
> 原则：**每一层都要有可自动判定的断言**。"看起来跑通了"不算通过——这次改的正是"看不见的地方"
> （并发、队列、锁、上下文），肉眼最难判断对错。

---

## 0. 测试分层与顺序

| 层 | 验证什么 | 手段 | 不通过就不能进下一层 |
|---|---|---|---|
| L1 单元/集成 | 状态机、唯一索引、配额、merge 语义 | Django `TransactionTestCase` + 真实 MySQL | ✅ |
| L2 故障注入 | 崩了会怎样（最容易漏，价值最高） | kill 容器 / 打桩超时 / 断库 | ✅ |
| L3 并发与容量 | 并发预算是否真的生效 | 并发脚本 + DB 观测 | ✅ |
| L4 浏览器 E2E | 用户真实路径与交互 | CDP 驱动 Chrome（localhost） | ✅ |
| L5 真 provider 抽样 | 真实质量（mock 骗不了人） | 1 章真链路，限成本 | ✅ |
| L6 生产灰度 | 线上行为 | 分步开关 + 指标观察 | — |

---

## 1. 环境前置（三个必须先解决的坑）

1. **数据库**：本地 `zk`（8.0.36）+ 测试库 `test_zk`。
   ⚠️ 队列的唯一索引是**生成列 + 普通唯一索引**，SQLite 下不成立 → **必须用 MySQL 跑**，
   且 `manage.py test --keepdb`（不带会重建库，20 分钟起，中途不要 kill）。
2. **worker 进程**：`manage.py ai_worker` 与 `runserver` 并列起两个终端。
   ⚠️ `runserver` 有 autoreload，`AI_QUEUE_MODE=inline` 会起两个消费者 → 本地测试统一用
   `worker` 模式（显式进程），不要用 inline。改 `.env` 后必须杀进程完整重启（autoreloader 继承旧 env）。
3. **前端**：`node serve-local.js`（dist + 代理 8005，端口 5273）。
   改源码后要重新 build；`npm run build` 会被 safe-delete 钩子拦，用
   `npx vite build --outDir dist_new` 再替换目录。
4. **账号**：`t101` 的 `pass1234` 在当前库已失效（脚本里的 `['pass1234','A0987654']` 兜底能过）；
   管理员 `admin / A0987654`；教师 `20249999`。**跑 E2E 前先手工验一次登录**，别让测试死在鉴权上。

---

## 2. L1 单元 / 集成

新建 `apps/ai/tests_queue.py`，**基类必须是 `TransactionTestCase`**：
`TestCase` 会把用例包在事务里，`select_for_update` 根本不阻塞，并发断言会"假绿"（测了等于没测）。
项目已有先例：`tests_ai_task.py:136` 就是 `TransactionTestCase`。

| # | 用例 | 断言 |
|---|---|---|
| Q1 | 双线程同时 claim 同一任务 | 只有一个 `rowcount==1`，另一个拿到 `None`，任务只执行一次 |
| Q2 | 同章节重复入队（并发 5 次） | 只产生 1 条任务，5 次返回同一 `task_id` + `dedupe_hit` |
| Q3 | 上传第二版 PPT 再入队 | 生成两条任务（**不被 catalog 去重挡住**，验证 F3 的修正） |
| Q4 | 心跳超时回收 | 把 `heartbeat_at` 改到 10 分钟前 → `reap` 后回 pending、`attempts` **不增** |
| Q5 | 退避重试 | attempts=1/2/3 时 `next_run_at` 间隔递增；到 3 次落 failed |
| Q6 | 取消 | pending 立即 cancelled；running 置 `cancel_requested` 后在下个批次边界退出，已完成页保留 |
| Q7 | SIGTERM 语义 | 直接调停机钩子 → 任务回 pending、`claimed_by=None`、attempts 不变 |
| Q8 | 配额预留/结算 | 提交后 `reserved` 增加；任务终结后 `settled` = `AICallLog` 同 trace_id 条数；过期 6h 释放 |
| Q9 | merge 语义 | ① worker 不覆盖已有非空 `script`；② `overwrite_pages` 才覆盖；③ `audio_url` 独立判定 |
| Q10 | 上下文重建 | 任务跑完后 `AICallLog` 的 `triggered_by`/`scene`/`course_id` 非空，且同任务 `trace_id` 一致 |
| Q11 | 连续两个任务的身份隔离 | 教师 A 的任务跑完后，教师 B 的任务日志 `triggered_by` **不能是 A** |

> Q10/Q11 是评审 C1 的直接回归——这两条最容易在上线后才发现（报表归零不报错）。

**既有回归**：`tests_ai_task.py`（604 行）改造后必须全绿。它现在靠
`patch("apps.ai.tasks.threading", _FakeThreading)` 同步执行，切 worker 后这条路径消失，
要改成直调 `_dispatch(task)` + 断言 DB 状态。

---

## 3. L2 故障注入（最容易被跳过，也最容易暴露真问题）

| # | 场景 | 注入方式 | 通过标准 |
|---|---|---|---|
| F1 | worker 被杀 | 任务跑到 50% 时 `docker kill zhike_v2_worker` | 5 分钟内任务被回收、从断点续跑；页数只增不减、无重复页 |
| F2 | provider 超时 | mock provider 打桩 `raise Timeout` | 单块走本地兜底、任务继续；整任务失败时 `error` 可读 |
| F3 | provider 慢 | 打桩 `sleep(5)` | 全局在飞调用数不超过闸门（`AICallLog` 按秒 group by ≤ 6） |
| F4 | 数据库断连 | `KILL` 掉 worker 的 MySQL 连接 | 自动重连、任务不丢、不产生错误行 |
| F5 | 渲染失败 | 打桩 soffice 返回码 1 | 课件 `parse_status=FAILED` + `parse_progress.error` 可见；**任务也置 failed**（不能一个失败一个还在跑） |
| F6 | 优雅停机 | `docker stop`（SIGTERM，10s 后 SIGKILL） | 8s 内退出，日志显示"回置 pending"，无 SIGKILL 痕迹 |
| F7 | 磁盘写满 | `fallocate` 占满 tmp | 渲染失败但不影响其他任务；错误信息可诊断 |

**F1 的判定细节**：不能只看任务状态，要**数页**。重跑后 `scripts` 里每页最多一条，
且已完成页的 `script` 内容与中断前一致（用 md5 对比前 N 页）。

---

## 4. L3 并发与容量（要出数字，不是"感觉快了"）

### 4.1 讲稿/配音

脚本 `test/e2e/queue-load-verify.py`：
- 5 个教师账号并发提交 30 页讲稿（各 1 章）；
- 同时每 2s 打一次 `/api/courses/` 作为"普通接口探针"；
- 记录：提交响应耗时、每任务排队时长、总完成时长、`AICallLog` 按秒峰值、探针 P95。

**通过标准**：
- 提交响应 < 1s（P95）；
- 普通接口 P95 劣化 < 20%（对比改造前基线，基线用同一脚本在旧版本跑一遍留存）；
- chat 同秒 ≤ 6、TTS 同秒 ≤ 4；
- 单教师提交 10 章时 `running ≤ 1`（查 `AITask` 状态分布）。

### 4.2 课件渲染

- 4 个教师并发上传 60 页 PPT；
- 渲染期间采样 `ps -ef | grep soffice`，**应看到 2 个**（并发 2 生效）；
- 若只看到 1 个 → 说明 F2（`_RENDER_THREAD_LOCK` 未删）或槽位=1 没改，直接判失败；
- 同时传 4 个 PDF：`soffice` 应为 0 个（PDF 不走 soffice），pypdfium2 并发 ≤ 3。

> **⚠️ 本组用例在 Windows 本地测不了**（本地走 PowerPoint COM 路径、并发强制 1，永远看不到
> 2 个 soffice）。闭环途径三选一（详见交接书 §2.5.6）：过渡机 124 起容器 / 本地 Docker Desktop /
> 生产灰度期验证。无论走哪条，**实现时必须在获取渲染槽位打日志**
> `[render] slot=1/2 acquired, file=xxx`，并让 `worker-health` 输出槽位占用——
> 这样灰度验证不必依赖 `ps`。

> 这组是本次改造唯一的"性能效果验证"。**看不到 2 个 soffice 就等于没做**。

---

## 5. L4 浏览器 E2E

沿用 `test/e2e/*.js` 的 CDP 驱动（`cdp-drive.js` 模式，端口 9222，`--no-proxy-server`）。
**必须用 localhost**（agent-browser/Chrome 在沙箱下只有 localhost 可达）。
弹窗/抽屉内按钮用 DOM click（动画期坐标点击会 miss）；断言 drawer 关闭看 `offsetParent === null`。

| # | 用例 | 断言 |
|---|---|---|
| T1 | 点「生成讲稿」 | 按钮文案进「排队中（第 N 位）」或「讲稿 x/y」；无 console.error |
| T2 | 生成中刷新页面 | 任务中心自动恢复，进度不倒退（只增不减） |
| T3 | 生成中关闭标签页，5 分钟后重开 | 任务已完成、内容可见、有完成通知 |
| T4 | 连点 5 次 | 只有 1 条任务，按钮不重复触发 |
| T5 | **生成中手改第 5 页** | 跑完后第 5 页仍是手改版本（评审 C2 的核心回归，**这条最重要**） |
| T6 | 上传 PPT | 响应 < 2s；进度条阶段推进（text→render→embed）；学生端可见 |
| T7 | 上传后立刻刷新 | 轮询接管，不重头开始 |
| T8 | 任务中心取消/重试 | 状态正确、按钮恢复可点 |
| T9 | 旧前端兼容 | 不带 `X-AI-Task-Mode` 头 → 410 提示刷新，不出现假成功 |

**留证**：每个用例截 1 张关键态图到 `test/screenshots/`，`console.error` 与未捕获异常必须为 0。

---

## 6. L5 真 provider 抽样（mock 骗不了人）

mock 只能证明"流程通"，证明不了"生成的讲稿像人话、配音能播"。
而且 `MockProvider.tts()` 恒返回同一个 `/media/mock/tts_placeholder.mp3`（`providers/mock.py:128-133`），
**所有页拿到同一个 URL** —— 所以"每页都有 audio_url"在 mock 下是平凡成立的，不能当作功能完成的证据。

- 选 1 个 12 页章节，关掉 mock，走真 chat + 真 TTS；
- 检查：讲稿条数 = 页数、无模板话、音频 URL 可访问且时长合理（≈字数/4 字每秒）；
- 记录成本：约 4 次 chat + 12 次 TTS，写进测试记录；
- 只在 L1–L4 全绿后跑一次，避免反复烧钱。

---

## 7. L6 生产灰度

1. **先只上 worker 容器**（队列空转一周）：确认内存、心跳、日志格式、不会被 gunicorn 误占；
2. 切讲稿/配音：`.env` 打开 `AI_QUEUE_MODE=worker`，**保留旧端点开关一天**；
3. 观察 4 个指标：队列深度、失败率、平均等待（`created_at→started_at`）、`AICallLog` 按秒峰值；
4. **回滚**：切回旧模式 + 前端 dist 回滚（`deploy/deploy-frontend-dist.py` 有备份机制）。

⚠️ 本地数据与生产不同（20 用户 vs 13），**禁止本地覆盖生产**；灰度期不要批量重生成，会挤占真实队列。

---

## 8. 已知会红的测试（先列清单，免得误判为"改造引入的 bug"）

| 文件 | 为什么会红 | 改成什么 |
|---|---|---|
| `test/e2e/script-progress-realtime-verify.py` | 断言"请求进行中进度推进"（:98-110） | 提交 → 轮询 `/ai-tasks/<id>/` → 断言 `progress.done` 递增 |
| `test/e2e/generation-persist-verify.js` | GP.1–GP.6 全部围绕 `localStorage['zhike:generation-tasks']` 续跑 | 改为"任务中心恢复"用例；旧键已被新前端清除 |
| `test/e2e/parse-progress-realtime-verify.py` | 上传同步、响应带 `parsed_pages` | 上传后轮询 `parse_progress` 到 `done` |
| `test/e2e/parse-progress-freeze-repro.py` | 同上 | 同上 |
| `test/e2e/parse-progress-fix-verify.js` | 同上 | 同上 |
| `backend/apps/courses/tests.py:76/695` | upload 助手断言响应含 `parsed_pages` | 入队 → 直调 `_dispatch` → 断言终态 |
| `backend/apps/ai/tests_ai_task.py` | `_FakeThreading` 路径消失 | 直调 `_dispatch` + 断言状态机 |

**共 7 个文件**，这是本次改造的测试预算，不能当"顺手改改"。

---

## 9. 验收清单（Definition of Done）

> ⚠️ 阶段级 DoD 是「**实测通过 + 已推送**」（见交接书 §2.5）。下面的清单是**实测**这一半的内容；
> 推送是另一半，缺任一都不算完成。

- [ ] L1 全绿，且 `tests_ai_task.py` 604 行改造后仍全绿
- [ ] Q10/Q11（上下文与身份隔离）通过
- [ ] F1 杀容器后 5 分钟内自动续跑，页数不重不漏
- [ ] 单教师提交 10 章：`running ≤ 1`，排队 ≤ 5，第 11 个返回 429
- [ ] 5 教师并发：提交 < 1s、普通接口 P95 劣化 < 20%
- [ ] 4 教师上传 PPT：`ps` 能看到 **2 个 soffice**
- [ ] T5（生成中手改第 5 页不被覆盖）通过
- [ ] T9（旧前端 410）通过
- [ ] 1 章真 provider 抽样，音频可播放
- [ ] 7 个既有测试文件全部改写并通过
- [ ] `p1_permission_matrix.py`(64) / `p4_graduation_check.py`(41) / `p5_security_check.py`(39) 全绿
      （p5 输出**必须落文件**，走 PIPE 会因 64K 写满冻结服务）

---

## 10. 时间盒（建议）

| 阶段 | 内容 | 占比 |
|---|---|---|
| L1 | 队列内核 + merge + 配额单测 | 30% |
| L2 | 故障注入（要搭打桩与容器操作） | 20% |
| L3 | 并发脚本 + 基线对比 | 20% |
| L4 | 浏览器 E2E（9 个用例） | 20% |
| L5/L6 | 真 provider + 灰度 | 10% |

> L1 与 L2 不要合并：故障注入会暴露"单测里不可能出现"的时序问题（第 4 次心跳、第 2 次回收、
> 半页落库），这些恰恰是队列类改造最容易翻车的地方。
