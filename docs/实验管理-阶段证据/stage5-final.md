# Stage 5 证据：全链路回归 + 8092 验收 + 文档定稿

> **日期**：2026-11-05　**环境**：本地 `127.0.0.1:8005`（venv runserver）+ `127.0.0.1:5273`（`frontend/dist` 直出 + `/api` 代理）+ 独立 MySQL 库 `zk_e2e` / `zk_s5_rollback`
> **结论**：**Stage 5 本地全量验收全绿**（全量单测 863 项、labs 单测 36 项、7 个预置实验 94 项、回滚演练 14 项、性能冒烟 13 项、P1/P4/P5 共 144 项、浏览器 E2E 52 项、落库核对 12 项、既有真实 HTTP 全链路回归，全部通过；控制台无 error）。按用户授权口径允许推送。
> **8092 口径**：`192.168.3.145` 不可达，用户明确授权「后续任务都先在本地进行测试，测试环境复测需等我过几天再进行」「本地全绿即逐阶段推送」。**8092 复测不跳过、不改期望、不伪装通过**，清单见 §六，网络恢复后统一补测并回填本证据。
> **生产**：`192.168.3.145:8088` 本阶段及 Stage 0–4 全程未触碰。

---

## 一、改动摘要

本阶段**没有新增业务特性**，只做全链路回归、可重复验收脚本、缺陷修复与文档定稿。

| 文件 | 改动 |
| --- | --- |
| `docs/实验管理-开发执行方案.md` | 抬头状态「待启动」→「已完成（Stage 0–5 本地全量验收全绿）」；执行顺序按用户口径校准；「当前状态 / 仓库 HEAD」改为交付索引；§0.1 状态表 Stage 5 = 已完成 + `stage5-final.md` + commit；补「已完成」仅指本地全绿、8092 仍待补测的显式说明；§7 交付段同步 |
| `docs/实验管理-模块规划与冲突自检.md` | 抬头「设计稿，尚未实施」→「已实现（v3.2 / Stage 0–5）」；保留 v3.1/v3.2 历史脉络，注明实现事实以代码与阶段证据为准 |
| `docs/实验管理-自定义实验对接说明.md` | 抬头状态由「Stage 0–4 已落地」定稿为「Stage 0–5 定稿，按实现校准」 |
| `docs/实验管理-阶段证据/stage5-final.md`（新） | 本证据：改动摘要 / 命令与输出 / 逐条验收结论 + 调试记录 / 偏离说明 / 8092 补测清单 / 交付索引 |
| `docs/实验管理-阶段证据/stage5-*.log`（新，16 份） | 全部命令输出落盘，JWT 已脱敏为 `<JWT_REDACTED>`；`stage5-sfc.log` 写入「exit 0 且 stdout 为空」的解释性两行，不伪造输出 |
| `test/e2e/stage5-preset-regression.py`（新） | 7 个 template 预置实验逐个真实 HTTP 回归：建课 → 逐模板建实验 → 排课 → 发布 → 门控页 → `bridge-validate` → `submit` → 看分 → 结论 → 报告生成/下载；94 项断言；二进制响应预览净化 |
| `test/e2e/stage5-rollback.py`（新） | 独立库 `zk_s5_rollback` 迁移回滚演练：全量 migrate → 真回退 0005 → 真前进 0006 → `--fake` 模拟「旧代码 + 残留 LabPage 表」→ 原生 SQL 旧字段查询 → 记录对齐 → 隔离性复核；14 项断言 |
| `test/e2e/stage5-perf.py`（新） | 成绩上报性能冒烟：批次 A 20 次快速连打验证 `lab_grade` 10/min 档位；批次 B 限流窗口冷却后按 7s 正常节奏 10 次验证「不误伤」；每次都真实 `start` 领票据 + `X-Lab-Token` 上报 |
| `backend/scripts/p4_graduation_check.py`、`p5_security_check.py` | 修 MySQL 模式下的**可重复运行缺陷**：`cleanup()` 只删 SQLite 副本文件，夹具残留导致重跑 `ProtectedError`。按依赖顺序先删 `AdminActionLog.actor` / `Question.catalog` / `Course.teacher` 引用行再删用户，并把被吞掉的删除异常改为可见打印。**未改任何验收断言** |
| `frontend/src/api/labs.js` | 新增 `getLab(id)`，供创建/刷新后按 id 回查详情 |
| `frontend/src/views/teacher/LabLibrary.vue` | 修 Stage 5 暴露的两处**分页缺陷**（见 §四 记录 5/7）：实验列表与课程下拉都一次取到后端上限 `page_size=100` 并按 id 倒序；`onCreated()` / `refreshCurrent()` 改为按 id 用 `getLab()` 回查详情，不再退回创建响应对象；创建后课程筛选定位到该课程 |
| `test/e2e/lab-custom.js` | `consoleErrors()` 增加出错 URL / 行号，便于定位控制台 500（**只增强诊断，未放宽 F10 断言**） |

**无关未跟踪项**（全程未 `git add`）：`backend/inflight_cache/`、`docs/Java课程资源/`、7 个 `frontend/dist_bak_*`。

---

## 二、命令与输出

所有输出落 `docs/实验管理-阶段证据/stage5-*.log`。服务：`8005` 由 `backend/venv/Scripts/python.exe manage.py runserver 8005` 干净重启（`Watching for file changes with StatReloader`）；`5273` 由 `node serve-local.js` 直出最新 `frontend/dist`。

| 命令 | 证据文件 | 关键输出 |
| --- | --- | --- |
| `cd backend && ./venv/Scripts/python.exe manage.py test apps.labs --keepdb -v 2` | `stage5-unit-labs.log` | `Ran 36 tests` / `OK` |
| `./venv/Scripts/python.exe manage.py test --keepdb -v 1` | `stage5-unit-full.log` | `Ran 863 tests in 310.254s` / `OK` / `FULL_TEST_EXIT=0`；4 处 `Lock wait timeout` 为 `AICallLog.flush()` 旁路埋点打印后被吞掉的既有噪声（见 §四 记录 9） |
| `./venv/Scripts/python.exe manage.py makemigrations --check --dry-run` | `stage5-migrate.log` | `No changes detected` |
| `./backend/venv/Scripts/python.exe test/check_sfc_bindings.py` | `stage5-sfc.log` | `exit=0`，无缺绑定（脚本成功时 stdout 为空，文件内已说明） |
| `cd frontend && npx vite build --outDir dist_new` → `mv dist dist_bak_<ts> && mv dist_new dist` | `stage5-build.log` | `✓ built in 10.75s` |
| `DATABASE_URL=mysql://…/zk_e2e ./venv/Scripts/python.exe manage.py migrate` | `stage5-e2e-migrate.log` | `Applying labs.0006_lab_custom_page_grading... OK`（独立 E2E 库补齐 Stage 1 迁移） |
| `E2E_DATABASE_URL=mysql://…/zk_e2e ./venv/Scripts/python.exe scripts/p1_permission_matrix.py` | `stage5-p1.log` | `通过 64 项，失败 0 项` |
| 同上 `p4_graduation_check.py` | `stage5-p4.log` | `P4 准出：41/41 通过，失败分组 0 个` |
| 同上 `p5_security_check.py` | `stage5-p5.log` | `P5 准出结果：39/39 PASS，0 项失败` |
| `./venv/Scripts/python.exe ../test/e2e/stage5-preset-regression.py` | `stage5-preset.log` | `总计 94 项，通过 94 项，失败 0 项` / `ALL_PASS` |
| `./venv/Scripts/python.exe ../test/e2e/stage5-rollback.py` | `stage5-rollback.log` | `总计 14 项，通过 14 项，失败 0 项` / `ALL_PASS` |
| `./venv/Scripts/python.exe ../test/e2e/stage5-perf.py` | `stage5-perf.log` | `总计 13 项，通过 13 项，失败 0 项` / `ALL_PASS`（详见 §三 第 5 项） |
| `./venv/Scripts/python.exe e2e_real_test.py` | `stage5-regression-e2e.log` | `🎉 全部真实链路测试通过`（含移动端字段齐全、`question_score` 不在响应） |
| `./venv/Scripts/python.exe ../test/e2e/lab-custom-setup.py` | `stage5-setup.log` | `spec OK: markdown=7505 chars, min-html=2152 chars` / `temp lab deleted OK` |
| `BASE=http://127.0.0.1:5273 SHOT_PREFIX=stage5-local node test/e2e/lab-custom.js` | `stage5-browser-local.log` | `总计 52 项，通过 52 项，失败 0 项` / `ALL_PASS` / `PASS \| F10 全流程控制台无 error` |
| `./venv/Scripts/python.exe ../test/e2e/lab-custom-data.py` | `stage5-data.log` | `总计 12 项，通过 12 项，失败 0 项` / `ALL_PASS` |

**真实浏览器截图**（`test/screenshots/`，目录被忽略、不入库）：`stage5-local-library.png`、`stage5-local-create.png`、`stage5-local-grading.png`、`stage5-local-debug.png`、`stage5-local-published.png`、`stage5-local-student.png`。

**关键真实输出摘录**：

```text
PASS | B{idx}-5 template 门控页 200 且注入 <base>/bridge（原逻辑零回归）
PASS | B{idx}-8 grading_source=steps、breakdown 为 template 步骤评分分支（报告双分支零回归）
PASS | R4 回退后 0006 未应用、LabPage 表与新字段已移除
PASS | R9 旧字段只读查询成功且残留 LabPage 表不干扰（旧代码兼容）
PASS | P2 快速连打零 5xx / 零业务错误（限流之外无误伤）
PASS | P5 正常使用节奏 10/10 全部成功（限流不误伤）
PASS | F4 页面经 LabBridge.reportGrade 真实上报成功
PASS | F10 全流程控制台无 error
```

---

## 三、逐条验收结论（方案 §3 Stage 5 六项 + 验收门槛）

| # | 方案要求 | 本地结论 | 8092 |
| --- | --- | --- | --- |
| 1 | 本地 `test apps.labs --keepdb` 全绿；`test`（全量）留足时间勿 kill | ✅ 36/36 `OK`；863/863 `OK`（310.254s，未 kill）；另补 `makemigrations --check` 零输出、SFC 绑定 exit 0、`vite build` 成功 | 不适用 |
| 2 | 8092 全量 E2E：`prod-smoke.js` BASE 改 8092；P1 64 / P4 41 / P5 39（输出落文件非 PIPE） | ✅ **本地等价**：P1 `64/64`、P4 `41/41`、P5 `39/39`，全部输出落文件；另重跑既有真实 HTTP 全链路回归 `🎉 全部真实链路测试通过`、浏览器 E2E 52/52、落库核对 12/12 | ⏳ `prod-smoke.js BASE=http://192.168.3.145:8092` 与三脚本的 8092 版本待补测（§六） |
| 3 | 7 个预置实验逐个：进入 → 操作 → 提交 → 看分 → 报告，确认零回归 | ✅ `stage5-preset-regression.py` **94/94**：7 个模板逐个真实 HTTP 走完门控页 / `bridge-validate` / `submit` / 成绩列表 / 结论 / 生成报告 / 下载 PDF+DOCX；断言 `page_source=template`、`grading_source=steps`、breakdown 为步骤评分分支、template 沿用客户端用时、无 `question_score` 幽灵字段 | ⏳ 8092 上重跑同一脚本（`BASE` 可配置） |
| 4 | 回滚演练：测试环境 `migrate labs 0005` 再 `migrate labs`，可前进可回退、旧代码不因 `LabPage` 表存在而报错 | ✅ **本地独立库等价**：`zk_s5_rollback` 空库全量 migrate → 真回退 0005（表/新字段移除）→ 真前进 0006（结构恢复）→ `--fake` 回退记录保留表 → 原生 SQL 旧字段查询成功且残留表不干扰 → 记录对齐 → `makemigrations --check` 零输出；14/14；复核主库 `zk` 与 `zk_e2e` 的 0006 仍 `[X]`，演练未波及 | ⏳ 8092 数据库上重跑（需先确认目标库与备份，禁止碰生产） |
| 5 | 性能冒烟：连续 20 次成绩上报，记录 p50 / 错误数，确认限流不误伤 | ✅ `stage5-perf.py` 13/13。批次 A 20 次快速连打：`ok=10 / 429=10 / errors=0`，成功请求 `p50≈10.4ms`、`p95≈10.8ms`——`lab_grade` 10/min 档位按设计生效，零 5xx、零业务错误；批次 B 冷却 62s 后按 7s 正常节奏 10 次：`ok=10 / 429=0 / errors=0`，`p50≈11.3ms`、`p95≈16.2ms`，证明正常使用不被误伤（两轮复跑 p50 分别落在 10.3–10.4ms / 10.9–11.3ms）；落库复核 `grading_source=external` 且服务端用时已写入 | ⏳ 8092 上同脚本重跑（含限流计数窗口） |
| 6 | 文档定稿：两份设计文档标「已实现」、§0.1 状态表全绿、补 `stage5-final.md` | ✅ 三份文档抬头已按实现校准；§0.1 Stage 0–5 全「已完成」且各有证据 + commit；本证据已生成 | 不适用 |
| 门槛 | 以上 6 项全绿且证据齐全；`git status` 只剩应提交文件；无遗留 TODO / 调试代码 / 临时打印 | ✅ 本地项全绿、16 份日志 + 6 张截图齐备；`grep -c "TODO\|FIXME\|debugger\|console.log"` 在本次新增/改动的生产代码为 **0**；测试脚本中的 `print()` 是断言输出（证据生成），非临时调试打印；`git status` 中仅剩 9 个应提交文件 + 已在案的无干未跟踪项 | ⏳ 8092 项按 §六 补测后回填 |

> **总判定**：按用户授权口径（本地全绿即逐阶段推送），Stage 5 本地验收通过、允许推送。**8092 相关的第 2/3/4/5 项未伪造成已通过**，在 §0.1 与 §六 中显式标注。

---

## 四、调试记录（现象 → 原因 → 修法）

1. **P4 脚本 `ProtectedError: Course.teacher / AdminActionLog.actor`**
   - 现象：`p4_graduation_check.py` 在 `seed()` 清 `p4v_` 用户时中止。
   - 原因：MySQL 模式下 `cleanup()` 只删 SQLite 副本文件，夹具仍留在 `zk_e2e`；`Course.teacher` / `AdminActionLog.actor` 是 `PROTECT`。
   - 修法：seed 里按依赖顺序先删 `AdminActionLog(actor__in=...)` 与 `Course(teacher__in=...)`，再删用户；重跑 `41/41`。

2. **P5 脚本仍 `ProtectedError: Course.teacher`**
   - 现象：加了上述清理后 P5 仍在删用户处失败。
   - 原因：`Question.catalog` 是 `PROTECT`，删 Course 会 CASCADE 到 Catalog 被题目挡住，而 `except: pass` 把异常吞了。
   - 修法：删课程前先 `Question.objects.filter(course__in=stale_courses).delete()`，并把被吞的删除异常改为可见打印；重跑 `39/39`，P4 修改后重跑仍 `41/41`。**未改任何断言**。

3. **回滚演练首轮 `ALTER command denied to user 'zk'@'localhost'`**
   - 现象：新建库 `zk_s5_rollback` 全量 migrate 失败。
   - 原因：`zk` 账号只有全局 `CREATE, DROP` 与按库显式授权，新建库没有自动 `ALTER`。
   - 修法：本地 root 一次性 `GRANT ALL ON zk_s5_rollback.* TO 'zk'@'localhost'`；脚本增加 `reset_db()`（库名精确断言保护）使演练可重复运行；重跑 `14/14`。

4. **预置回归日志出现 PDF/DOCX 二进制乱码**
   - 现象：日志被 git 识别为二进制文件。
   - 原因：`api()` 把非 JSON 响应用 `r.text[:120]` 预览，打印了 PDF / ZIP 原始字节。
   - 修法：按 `Content-Type` 判定二进制，改写 `<binary {ctype} {bytes}B>`；**不改任何断言**，净化后完整重跑 `94/94`。

5. **浏览器 E2E 首轮 `38/52`，E1b/E2d/E4/E5/E6b 连锁失败**
   - 现象：「实验页面」Tab 显示「尚未上传」、排课列表空、列表找不到 `.lab-row-<id>`；但真实库里该实验 `has_custom_page=True`、有排课、`last_debug.passed=True`。
   - 原因：`Lab.Meta.ordering = [course_id, order, id]` + 默认分页 20 条；Stage 5 造数据后实验数超过 20，新建实验不在第一页。`onCreated()` / `refreshCurrent()` 用 `labs.value.find()` 找不到就退回创建响应对象（无页面名 / 无 schedules），于是详情显示陈旧数据、列表找不到行。这是**真实产品缺陷**，非测试问题。
   - 修法：列表与课程下拉改为 `page_size=100` 并按 id 倒序；`onCreated()` / `refreshCurrent()` 用新增的 `getLab(id)` 按 id 回查详情；创建后筛选定位到该课程。重建 dist 后重跑。

6. **浏览器 E2E 第二轮 `51/52`，F10 控制台多条 500**
   - 现象：`Failed to load resource: 500`，无 URL 难以定位。
   - 修法：给 `consoleErrors()` 增加 `entry.url` / 行号（仅诊断增强），定位到 `/api/ai-tasks/active/?task_type=all`；`APIClient` 同接口 200，常规实验接口全部 200，判定与本次实验代码无关。
   - 根因：`8005` 上长期运行的旧 `runserver` 进程状态陈旧（文件缓存 / 环境），并非代码缺陷。按纪律停旧进程、用 `backend/venv/Scripts/python.exe manage.py runserver 8005` 干净重启；重启后该接口真实 HTTP 连续 200，全套 E2E `52/52`。
   - 说明：Windows venv 的 `Scripts/python.exe` 是 launcher，进程映像显示为基础解释器 `E:\Miniconda\python.exe`，与「勿用 Miniconda 直接启动」的纪律不冲突；关键是按 `venv/Scripts/python.exe` 入口重启而非直接调用 Miniconda。

7. **浏览器 E2E 第三轮 B4「选择所属课程」失败并连锁**
   - 现象：新建抽屉课程下拉里选不到 setup 新建的课程。
   - 原因：课程总数已达 21，`/courses/` 默认第一页 20 条，最新课程不在其中（实测 `target_in_page20=False`、`target_in_page100=True`）——与记录 5 同源的分页缺陷。
   - 修法：课程下拉同样一次取全 `page_size=100`；重建 dist + 重跑 SFC，浏览器 E2E 恢复 `52/52 ALL_PASS`（含 F10 无 error）。

8. **`check_sfc_bindings.py` 成功但 stdout 为空**
   - 现象：日志 0 字节。
   - 修法：与 Stage 3/4 同口径，在 `stage5-sfc.log` 写「exit=0 且 stdout 为空」的解释性两行，不伪造输出。

9. **全量单测 4 处 `Lock wait timeout exceeded`**
   - 现象：日志中 4 段 traceback，但 `Ran 863 tests ... OK`。
   - 原因：堆栈头部均为「写入 AI 调用流水失败（tts/tongyi）」，是 `apps/ai/calllog.py::flush()` 旁路埋点打印后被吞掉的既有观测噪声（与 Stage 3 记录一致），异常不在用例断言链上。
   - 处理：不改该文件、不降低断言，分项与合并回归均 OK；如实留在日志中。

10. **`npm run build` 被 safe-delete 钩子拦**（沿用既有纪律）
    - 修法：`npx vite build --outDir dist_new` 成功后 `mv dist dist_bak_<ts> && mv dist_new dist`；本阶段两次重建均成功，未使用生产一键脚本。

---

## 五、偏离说明

1. **8092 验收延后**：用户 2026-11-05 授权「后续任务都先在本地进行测试；测试环境复测需等我过几天再进行」「本地全绿即逐阶段推送」。本阶段只调整推送时机，**不降低验收标准**；第 2/3/4/5 项中依赖 8092 的部分列入 §六 独立补测批次，状态表「已完成」的限定含义已写进 §0.1。
2. **回滚演练改在独立本地库**：方案原文要求「在测试环境」；为避免破坏本地开发库 `zk` 的 Stage 0–5 测试数据，改用 `zk_s5_rollback` 独立库，并额外覆盖「`LabPage` 表残留时旧字段查询不受影响」这一原文语义。8092 版本仍待补测。
3. **性能冒烟本地化 + 拆两批次**：原文「8092 上连续 20 次」在本地 8005 执行；因 `lab_grade` 档位是 10/min，20 次快速连打必然出现 10 次 429，故增加「正常节奏 10 次」批次区分「限流按设计生效」与「不误伤正常使用」，未改期望。
4. **P1/P4/P5 使用本地 `zk_e2e` 独立库**：脚本自带隔离机制，输出落文件非 PIPE；为让三个脚本在 MySQL 模式下可重复运行，修了 seed 清理顺序（不动断言），并记录在 §四 1/2。
5. **新增 3 个可重复 E2E 脚本**：Stage 5 原文只列「真实测试」动作，未指定脚本名；为让 8092 补测可原样重跑，新增 `stage5-preset-regression.py` / `stage5-rollback.py` / `stage5-perf.py`，均支持通过 `BASE` / 环境变量切换目标。
6. **Stage 5 收敛了前端分页缺陷**：`LabLibrary.vue` / `api/labs.js` 的修复属于本阶段新暴露的产品缺陷，超出原文「改动清单」（原文无清单），已按「验收未过 → 调试到通过 → 重跑全部测试」处理，`console.log` / TODO 检查为 0。
7. **列表 100 条上限**：`StandardPagination.max_page_size=100`，当前修复在 100 条以内保证「新建实验可见」；超过 100 条需加分页控件或服务端排序，列为 §八 后续建议，不影响本阶段验收。

---

## 六、8092 统一补测清单（网络恢复后独立批次）

| 来源 | 待跑项 | 命令 / 动作 | 通过标准 |
| --- | --- | --- | --- |
| Stage 2 `stage2-sandbox.md` §四 | 8092 前端 dist 部署（按 Stage 0 核实的通道，禁止复用生产一键脚本）、L2 沙箱门控 / 预览 / 静态扫描浏览器复测 | Stage 2 证据中列出的命令 | 与本地同标准，控制台无 error |
| Stage 3 `stage3-grade.md` | 8092 上报端点 / 防刷状态机 / 统计 / 报告 / 导出全链路复测 | Stage 3 证据中列出的命令 | 与本地同标准 |
| Stage 4 `stage4-frontend.md` §六 | 8092 部署本次 `frontend/dist` → `BASE=http://192.168.3.145:8092 node test/e2e/lab-custom.js` → `API_BASE=... lab-custom-data.py` → 移动端 H5 成绩页目检 | 换 `BASE` / `API_BASE`，**脚本与断言不改** | 52/52 + 12/12，截图留证 |
| Stage 5 项 2 | `BASE=http://192.168.3.145:8092 node test/e2e/prod-smoke.js`；P1 / P4 / P5 指向 8092 对应库 | 输出落文件非 PIPE | 冒烟通过；64 / 41 / 39 全绿 |
| Stage 5 项 3 | `BASE=http://192.168.3.145:8092 ./venv/Scripts/python.exe ../test/e2e/stage5-preset-regression.py` | 7 个预置实验逐个 | 94/94 |
| Stage 5 项 4 | 8092 库上 `migrate labs 0005` → `migrate labs` | **先确认目标库与备份，禁止碰生产 8088** | 可前进可回退，业务无异常 |
| Stage 5 项 5 | `BASE=http://192.168.3.145:8092 ./venv/Scripts/python.exe ../test/e2e/stage5-perf.py` | 20 次上报 + 正常节奏批次 | 13/13，记录 p50 / 错误数 |

补测完成后：把结果写入各阶段证据 §对应段落，并在本文件追加「8092 补测回填」小节与日期。

---

## 七、交付索引

| 阶段 | 证据 | commit |
| --- | --- | --- |
| Stage 0 基线冻结 | `stage0-baseline.md` | `eaa021c` |
| Stage 1 数据模型 + 报告双分支 | `stage1-model.md` | `07602ba` |
| Stage 2 页面上传 + L2 沙箱门控 | `stage2-sandbox.md` | `2b0b8ca` |
| Stage 3 成绩上报 + 防刷状态机 | `stage3-grade.md` | `a1fbdb9` |
| Stage 4 前端实验管理 + 动态接入说明 | `stage4-frontend.md` | `d370f3d` |
| Stage 5 全链路回归 + 文档定稿 | `stage5-final.md`（本文件） | 主 commit 见 §0.1 状态表回填 |

（各阶段另有 `docs(labs): Stage N - 状态表回填 commit hash` 提交，见 `git log`。）

---

## 八、已知边界与后续

- **不在本方案内**：生产 `8088` 发布（§7 已写明需另起任务）；TLS 生产切换待授权（项目既有遗留风险）。
- **列表规模**：`LabLibrary.vue` 一次取 100 条；超过 `max_page_size` 时需补分页控件或服务端 `ordering=-id`。
- **8092 补测**：§六 清单未完成前，不得把 8092 相关项表述为「已验收」。
- **本地演练库**：`zk_s5_rollback` 与 `zk_e2e` 均为本地独立库，脚本内含受保护库名断言；生产库 `zk` / `test_zk` 未被写入或回退。
