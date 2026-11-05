# Stage 3 — 成绩上报端点 + 极简防刷 + postMessage 契约 + 统计分支 · 阶段证据

> **状态：本地验收全绿，已按用户授权口径推送。**
> **口径变更（2026-11-05 用户明确授权）**：「后续任务都先在本地进行测试；测试环境 8092 复测等我过几天再进行；本地全绿即逐阶段推送」。本阶段以「本地单测 + 本地真实浏览器 + 本地真实数据核对全绿」为推送门槛；**8092 复测未跳过、未改期望、未伪装通过**，只是延后为独立补测批次，清单见 §五。
> **生产 8088 全程未触碰**；本地只重启了 `8005` 开发后端与替换了 `frontend/dist`。

---

## 一、改动摘要

| 文件 | 改动 |
| --- | --- |
| `backend/apps/labs/services.py`（新） | `finalize_submission()` 公共状态机（S2：同一事务内 `select_for_update()` 双行锁 → 锁后复验 → 事务内 `consume_token()`）；`parse_grade_payload()`（总分 1 位小数 / 范围 / 报文 ≤64KB / 客户端用时非负）；`server_elapsed_seconds()`（S1）；`is_abnormal()`（S5）。现有 `submit` 与新端点共用，状态机唯一。 |
| `backend/apps/labs/views.py` | 新增 `GradeReportView`（`POST /api/lab-gate/grade/`，`LabTokenAuthentication` + `IsStudent` + 学籍门控 + 独立限流）；新增 `grade-debug` dry-run；`bridge_validate` 去掉 C32 自我抵消身份比较、补排课窗口校验、下发四字段 `context`；`submit` 改用公共状态机。dry-run 用 `blocking` 区分「报文校验」与「环境提示」，草稿态也可调试。 |
| `backend/apps/labs/urls.py` | `lab-gate/grade/` 显式 `path()`，排在 `router.urls` 之前（C22/C43）。 |
| `backend/config/settings.py`、`backend/apps/common/throttles.py` | `lab_grade` 限流 scope 双写（`GLOBAL_THROTTLE_RATES` + `DEFAULT_THROTTLE_RATES`）；`LabGradeThrottle.get_cache_key()` 按 `user.pk`。 |
| `deploy/labs/lab-bridge-parent.js` | `loadContext()` 优先取服务端 `context` 四字段（旧后端回退映射），仍不多透任何业务字段；保留 C41 `event.source` 校验、S4 一次性闸门、失败自动解除、票据只进 `X-Lab-Token` 头、引导变量用完即删。 |
| `backend/apps/analytics/services.py` | C17：章节画像对 `grading_source=external` 把 `passed_steps/total_steps` 置 `None`、加 `step_metrics=「不适用」`，保留总分与用时；预置实验零改动。 |
| `backend/apps/analytics/export.py` | C18：Sheet4「实验明细」对 external 把四项基准分与步骤两列写「不适用」，保留总分 + 用时。 |
| `frontend/src/views/teacher/LabManage.vue` | C17：平均步骤通过率排除 external；详情表步骤列显示「不适用」；`mapSub` 透传 `grading_source`。 |
| `backend/apps/labs/tests.py` | 新增 `LabGradeReportTest`（8 用例）、`LabGradeConcurrencyTest`（真实双线程并发）、`LabExternalAnalyticsTest`（2 用例）、`LabStaticContractTest.test_stage3_grade_contract`；合计 17 → 29。 |
| `test/e2e/fixtures/stage3-page.html`（新） | 单 HTML 教师实验页，调用 `LabBridge.validate()` / `reportGrade()`，含「越界提交」按钮用于失败重试。 |
| `test/e2e/stage3-grade-setup.py`（新） | 真实账号登录 → 建实验（**唯一名称**）→ 上传 → dry-run 四报文 → 排课发布 → 学生 start，产物写 `D:/tmp/stage3-setup.json`。 |
| `test/e2e/stage3-grade-verify.js`（新） | CDP 真实浏览器 32 项：父页面/iframe 隔离、伪造 postMessage 丢弃、失败重试、S4 闸门、预览不提交、学生 UI 看分、教师 UI 统计「不适用」。 |
| `test/e2e/stage3-grade-verify.py`（新） | 28 项真实库/HTTP 核对：入库字段、S1/S5、C8、C17 章节学情、C18 导出 xlsx、报告 docx/pdf 双分支。 |
| 报告步骤清单 `report_generator.py` | **本阶段未改**：Stage 1 已实现 external 双分支（「总分 + 用时」+「不适用」），本阶段用真实数据复验（见 §二 `stage3-data.log`）。 |
| `deploy/labs/lab-bridge.js` / `gate.sign_lab` / `verify_lab` | **一行未改**（D11）；预置实验 7 个零回归。 |

---

## 二、命令与输出（全部落文件）

| # | 命令 | 证据文件 | 关键输出 |
| --- | --- | --- | --- |
| 1 | `manage.py test apps.labs --keepdb -v 2`（Stage 2 基线） | `stage3-baseline-unit.log` | `Ran 17 tests ... OK` |
| 2 | `manage.py test apps.labs --keepdb -v 1`（Stage 3 全量） | `stage3-unit.log` | `Found 29 test(s) ... Ran 29 tests in 6.191s / OK` |
| 3 | `manage.py test apps.courses --keepdb -v 1` | `stage3-regression-courses.log` | `Ran 84 tests in 86.177s / OK` |
| 4 | `manage.py test apps.analytics apps.classroom --keepdb -v 1` | `stage3-regression-analytics.log` | `Ran 87 tests in 71.160s / OK` |
| 5 | `manage.py test apps.courses apps.analytics apps.classroom --keepdb -v 1`（合并复核） | `stage3-regression.log` | `Ran 171 tests in 277.944s / OK` |
| 6 | `manage.py makemigrations --check --dry-run` | `stage3-migrate.log` | `No changes detected`，exit 0（本阶段零模型改动、零迁移） |
| 7 | `python test/check_sfc_bindings.py` | `stage3-sfc.log` | 输出为空（脚本成功不打印），exit 0 |
| 8 | `npx vite build --outDir dist_new` + `mv dist dist_bak_<ts> && mv dist_new dist` | `stage3-build.log` | `✓ built in 10.13s`；备份目录 `frontend/dist_bak_1793877464/`（未入库） |
| 9 | `python test/e2e/stage3-grade-setup.py` | `stage3-setup.log`（已脱敏票据） | `create lab OK: id=19` / `upload page OK: 3144 bytes, scan hits=0` / `grade-debug OK: 100/0/86.5 通过，101 未通过，均为 dry_run` / `sub_id=11` |
| 10 | grade-debug 四报文逐项结果（由 setup 的真实响应导出） | `stage3-grade-debug.log` | 三种有效报文 `passed=True`；101 越界 `passed=False`；四项环境提示标 `blocking=false`；全部 `dry_run=True` |
| 11 | `node test/e2e/stage3-grade-verify.js` | `stage3-browser-local.log` | **`总计 32 项，通过 32 项，失败 0 项 / ALL_PASS`** |
| 12 | `python test/e2e/stage3-grade-verify.py` | `stage3-data.log` | **`总计 28 项，通过 28 项，失败 0 项 / ALL_PASS`**；含真实 `labsubmission` 记录 JSON 摘录与 Sheet4 行原文 |
| 13 | dry-run 双态徽标复核（通过 86.5 / 失败 101） | `stage3-last-debug.log` | `86.5 → last_debug.passed=True`；`101 → last_debug.passed=False`；`no real submission created by dry-run: True` |

**浏览器截图**（`test/screenshots/`，本阶段生成/刷新）：
`stage3-local-after-report.png`、`stage3-local-preview.png`、`stage3-local-student-score.png`、`stage3-local-teacher-detail.png`。

**真实入库记录摘录**（`stage3-data.log`，本地库 `zk`）：`submission_id=11 / lab_id=19 / grading_source=external / total_score=100.0 / started_at=11:36:53.555469 / submitted_at=graded_at=11:37:01.190490 / elapsed_seconds=7（= submitted_at-started_at）/ client_elapsed_seconds=6 / passed_steps=0 / total_steps=0 / abnormal=true / ticket_consumed=true / grade_raw_digest=40a3b20a…f71f`。

**导出文件**：`D:/tmp/stage3-export.xlsx`（真实 HTTP 下载，Sheet4 该实验行：`总分 100 / 折算分 100 / 基础分·操作准确性·完成效率·完成度·通过步骤·总步骤 = 不适用 / 用时(分钟) 0.1`）。

---

## 三、逐条验收结论

### 3.1 方案 §3 Stage 3「真实测试」

| 条目 | 结论 | 依据 |
| --- | --- | --- |
| 1. 本地单测 6 分支：票据无效/过期/已消费、跨实验票据、越界总分、正常入库且票据消费且 `submitted_at` 服务端生成 | ✅ 全绿 | `stage3-unit.log`：`test_invalid_expired_consumed_ticket`、`test_cross_lab_ticket_and_body_fields_ignored`、`test_out_of_range_score_and_failed_retry`、`test_success_uses_server_time_and_raw_digest` |
| 1-① 并发两次上报只有一个成功、票据只消费一次 | ✅ | `LabGradeConcurrencyTest`（`TransactionTestCase` + 双线程 + `threading.Barrier`）：`codes == [200, 400]`，`ticket.consumed=True` |
| 1-② `elapsed_seconds == submitted_at - started_at` 而非请求值 | ✅ | 单测断言 + `stage3-data.log`（7 vs 客户端谎报 6） |
| 1-③ 窗口关闭后持有效票据仍被拒 | ✅ | `test_window_closed_and_unpublished_rejected`；`bridge-validate` 同步 403 |
| 1-④ 满分秒交置 `abnormal=True` | ✅ | `test_perfect_instant_submit_marked_abnormal`（非满分不误标）+ 真实库 `abnormal=true` |
| 1-⑤ 静态断言 `LabBridge.context` 不含票据、shim 内无 `X-Lab-Token` / `fetch('/api` | ✅ | `test_stage3_grade_contract` + `test_c40_c46_static_contract`；浏览器 A9–A11 运行时复核 |
| 1-⑥ 伪造 `postMessage`（`event.source` 不符）被父页面丢弃 | ✅ | 浏览器 A6：顶层 `window.postMessage` 后 `window.__stage3Posts.length === 0` |
| 1-⑦ 现有 `submit` 与 `tests.py` 全绿 | ✅ | `LabFlowTest.test_full_flow` 等 17 个存量用例全绿；`LabGateTest` 4 用例零回归 |
| 2. 8092 端到端（教师建实验 → 上传 → 发布 → 排课 → 学生进入 → 提交 → 立刻看分 → 教师端总分/用时 → 章节学情/导出/报告「不适用」） | 🕐 **本地全链路已全绿；8092 按用户授权延后** | 本地等价链路：`stage3-browser-local.log` A/C/D + `stage3-data.log` 三/四/五；补测清单见 §五 |
| 3. 在线调试：满分/零分/部分分三种模拟报文均通过，`last_debug` 徽标正确、不产生真实提交 | ✅ | `stage3-grade-debug.log`、`stage3-last-debug.log`（通过/失败双态），`stage3-unit.log` 草稿态回归 |
| 4. 失败重试：越界分数 → 中文错误 → 页面显示 message → 修正后重试成功，票据未作废 | ✅ | 浏览器 A12/A13/A14/A16；单测 `test_out_of_range_score_and_failed_retry` |

### 3.2 方案 §3「验收门槛」

| 条目 | 结论 |
| --- | --- |
| 提交即完成、统计/报告/导出同步可见全链路真实跑通 | ✅ **本地**全链路通过（浏览器 32/32 + 数据核对 28/28）；8092 延后 |
| S1 服务端用时 | ✅ 单测 + 真实库 `elapsed_seconds=7`，客户端值只进 `grade_raw` |
| S2 事务内双行锁 + 事务内消费票据 | ✅ `services.py` + 静态契约断言 + 双线程并发实测 |
| S3 窗口/发布/来源/学籍二次校验 | ✅ `test_window_closed_and_unpublished_rejected` + `test_cross_lab_ticket_and_body_fields_ignored` |
| S4 一次性闸门（失败可重试） | ✅ 浏览器 A12→A13 成功、A15 成功后第三次不再发 POST |
| S5 满分极短用时只标记不拒答 | ✅ `abnormal=true` 且 `status=submitted` |
| 7 个预置实验 `submit` 零回归 | ✅ `LabGateTest` 4 用例 + `LabFlowTest.test_full_flow` + `apps.courses` 84 用例全绿 |
| C17/C18 统计分支 | ✅ 章节画像 `passed_steps/total_steps=None`、Sheet4 六列「不适用」、教师页平均步骤「—」、报告「不适用」 |
| D11/D12 纪律 | ✅ `lab-bridge.js` / `sign_lab` / `verify_lab` 未改；iframe 无 `allow-same-origin`；父页面校验 `event.source`；新增 action 均 `[IsTeacher]`；context 四字段；frame URL 绝对路径且不含票据 |

### 3.3 其它硬指标

- 迁移一致性：`No changes detected`（零迁移）。
- 前端构建与 SFC 绑定检查：全绿。
- 控制台错误：学生实验页 / 教师实验页均为 0（浏览器 C4/D6）。
- 预置实验与 `apps.courses` / `apps.analytics` / `apps.classroom` 回归：84 + 87 + 合并 171 全绿。

**结论：Stage 3 本地验收全绿，允许按用户授权口径推送并进入 Stage 4。**

---

## 四、调试记录（现象 → 原因 → 修法）

1. **`SyntaxError: bytes can only contain ASCII literal characters`**：新测试里把含中文的单 HTML 写成 `b"""..."""`。→ 改成 `"""...""".encode("utf-8")`（沿用 Stage 1/2 范式），重跑 29/29。
2. **`assertEqual(sub.total_score, 0)` 失败（实际 None）**：`LabSubmission.total_score` 是 `null=True, blank=True` 无默认值，未提交时为 `None`。→ 修正为 `assertIsNone` 并补断言 `grading_source == "steps"`，语义仍是「未提交不得写分」，未放宽任何约束。
3. **本地 `POST /api/lab-gate/grade/` 返回 404**：`8005` 后端是旧进程以 `--noreload` 启动，URLconf 未热加载。→ 完整重启 `8005`（启用 autoreload），复测得 401「实验票据无效」，端点生效。
4. **回归日志出现 4 条 `Lock wait timeout exceeded`**：来自 `apps/ai/calllog.py::flush()` 旁路埋点写 `AICallLog`，该异常在设计上被 `try/except logger.exception(...)` 吞掉，「不影响主业务流程」；84/87/171 用例仍全部 OK。本阶段未改该文件，判定为测试环境既有观测噪声，**不作代码修改、不降低断言**。
5. **setup 首次跑 `grade-debug` 全判失败**：dry-run 把「发布状态」当阻断项，但 Stage 4 的 UI 顺序是「创建 → 调试 → 发布」，草稿态必须能调试。→ `grade_debug` 的 `check()` 增加 `blocking` 字段，只有「报文格式/范围/大小」参与 `passed`；发布状态/页面文件/页面来源/票据模拟降级为提示项；并新增「草稿态 dry-run 必须通过」回归用例。
6. **教师详情统计全是 0、状态显示「草稿」**：setup 重复执行生成了两个同名实验，浏览器按名称点中了上一次的草稿。→ setup 改为「名称 + 时间戳」唯一化并写入 `lab_title`；浏览器按 `setup.lab_title` 精确匹配；新增 D2b 断言抽屉标题与「已发布」。
7. **学生端 C3 假阳性**：`.lab-score-total` 取到列表第一张卡片（另一预置实验 69.3/100.0）。→ 改为按 `article.lab-card > .lab-title === lab_title` 精确定位卡片，再取该卡片的总分与标签。
8. **Node `SyntaxError: Invalid regular expression`**：正则写在 Node 源码里被双重转义。→ 改用 `parseFloat(scoreCard.total) === 100`，重跑。
9. **浏览器复跑 A1–A3/A7 全 403**：复用了上一次已消费票据的 `stage3-setup.json`，门控按设计拒绝「实验票据已使用」。→ 每次浏览器验证前重新跑 setup 生成新实验 + 新票据；干净重跑 32/32 ALL_PASS。**这是票据一次性生效的正面证据，不是缺陷。**
10. **`grade-debug` 提示项在日志里显示 `[FAIL] 发布状态`**：`ok=False` 但 `blocking=False`、`passed=True`。→ 证据文件显式标注「提示项，不参与判定」；**Stage 4 UI 需按 `blocking` 把提示项渲染为灰色信息而非红色失败**（写入交接）。

---

## 五、8092 复测清单（用户授权延后，独立批次补测）

> 网络：`192.168.3.145` 当前不可达（本机在 `192.168.0.0/24`，无 `192.168.3.0/24` 路由）。恢复后按 Stage 0 核实的事实操作，**禁止复用生产 8088 一键脚本**。

1. 同步本阶段后端改动（`services.py` / `views.py` / `urls.py` / `settings.py` / `throttles.py` / `analytics/*` / `tests.py`）与 `deploy/labs/lab-bridge-parent.js`；`deploy/labs/` 静态文件按 Stage 0 核实的 `:ro` 通道同步；前端 dist 按 **8092 专用通道**部署，重启 `zhike_qv` backend/worker。零迁移（`makemigrations --check --dry-run` 零输出）。
2. `BASE=http://192.168.3.145:8092 TEACHER=test_admin STUDENT=<真实学生> COURSE_ID=… CATALOG_ID=… CLASSROOM_ID=… python test/e2e/stage3-grade-setup.py`（账号与 ID 以 8092 实际数据为准）。
3. `SHOT_PREFIX=stage3-8092 node test/e2e/stage3-grade-verify.js <setupJson>` → 截图 `stage3-8092-*.png`、日志 `stage3-browser-8092.log`，要求 32/32。
4. `python test/e2e/stage3-grade-verify.py <setupJson>` → `stage3-data-8092.log`，要求 28/28。
5. 复核 C17/C18 与报告在 8092 独立库同样表现；用 `test_admin` 目检教师端「不适用」与导出 xlsx。
6. 把 8092 结果回填本文件 §三 中标记 🕐 的条目，并同步更新方案 §0.1；Stage 2 的延后清单见 `stage2-sandbox.md` §四，一并补测。

---

## 六、偏离说明

1. **报告步骤清单**：方案 Stage 3 改动清单列了「报告步骤清单按 `grading_source` 排除 external 或标注不适用」，该分支在 **Stage 1 已实现并验收**（`stage1-model.md`）。本阶段未重复改 `report_generator.py`，只用真实数据复验（docx/pdf 均「总分 + 用时」+「不适用」、无四项基准分）。
2. **`integration-spec/`**：设计 §5.3 有该端点，但方案把「动态接入说明」划归 **Stage 4**，本阶段未实现，未越界。
3. **`grade-debug` 的 `blocking` 字段**：设计只说「返回逐项结果、不入库」，未规定哪些项参与通过判定。实现按 Stage 4 的真实 UI 顺序（草稿即可调试）把环境项降级为提示；此项属于实现细化，不改接口契约的 `passed/checks/preview/dry_run` 四字段结构，仅每项多一个布尔 `blocking`。
4. **8092 复测延后**：仅调整推送时机，不降低任何验收标准；见 §五。
5. **未新增依赖、未执行 `compose build`、未触碰生产 8088**：符合 D10 与「绝对禁止」清单。
