# Stage 4 证据 · 前端实验管理 + 动态接入说明 + 在线调试 + 移动端修正

> **状态：本地验收全绿，已按用户授权口径推送。**
> **口径变更（2026-11-05 用户明确授权）**：「后续任务都先在本地进行测试；测试环境 8092 复测等我过几天再进行；本地全绿即逐阶段推送」。本阶段以「本地单测 + 本地真实浏览器 + 本地真实数据核对全绿」为推送门槛；**8092 复测未跳过、未改期望、未伪装通过**，只是延后为独立补测批次，清单见 §六。本阶段未触碰生产 `192.168.3.145:8088`。

---

## 一、改动摘要

### 1.1 后端：动态接入说明端点（纯渲染，零迁移）

| 文件 | 改动 |
| --- | --- |
| `backend/apps/labs/integration_spec.py`（新） | 动态 Markdown 渲染模块：`GRADE_ENDPOINT`、`build_integration_spec(lab, absolute_grade_url)`。占位符用 `@@NAME@@` 多轮展开（正文含大量 HTML/JS 花括号，`.format()` / f-string 会误解析）；含实验参数表、运行架构、`LabBridge` 四 API、请求/响应 schema、字段约束、按实现校准的错误码表、最小可运行单 HTML、可整段复制给 AI 的生成指令、末尾 `report_note`。纯字符串渲染，不新增表、不写库 |
| `backend/apps/labs/views.py` | `LabViewSet.integration_spec`：`GET /api/labs/{id}/integration-spec/`，显式 `[IsTeacher]`（不含 admin，C46），行级归属由 `get_queryset()` 保证；`data` 含 `lab_id/lab_title/total_score/grade_endpoint/grade_debug_endpoint/report_note/markdown` |
| `backend/apps/labs/tests.py` | 新增 `LabIntegrationSpecTest` 7 用例：动态预填、占位符零残留、`report_note` 末尾、权限（学生 403 / admin 403 / 跨课程教师 404 / 匿名）、纯渲染无副作用且草稿可用、逐实验参数不串、最小 HTML 静态扫描零命中、票据不下发页面契约 |

### 1.2 前端：顶级「实验管理」与公共组件

| 文件 | 改动 |
| --- | --- |
| `frontend/src/api/labs.js` | 新增 5 个 API：`uploadLabPage`（FormData + `silent:true` 以便组件自管 S8 二次确认）/ `deleteLabPage` / `previewLabPage` / `getIntegrationSpec` / `gradeDebug` |
| `frontend/src/router/index.js` | MainLayout children 加 `teacher/labs` → `lab-library`（role teacher） |
| `frontend/src/layouts/MainLayout.vue` | 教师端菜单加 `{ index:'/teacher/labs', label:'实验管理', icon: Pointer }` |
| `frontend/src/components/lab/LabPageUploader.vue`（新） | 单 HTML 拖传（≤50MB、`.html/.htm`、非空）；两种用法：新建抽屉暂存 File / 已有实验直接上传·替换·删除·预览；S8 命中展示 `hits` 并带 `confirm=1` 二次确认 |
| `frontend/src/components/lab/LabGradingPanel.vue`（新） | 「成绩接口」Tab：接口地址 + 复制、动态 Markdown + 一键「复制给 AI」（clipboard 失败降级 `execCommand`）、`report_note` 编辑保存、在线调试（满分/零分/部分分示例 + `blocking` 提示项灰显 + 写入预览 + `last_debug` 徽标刷新） |
| `frontend/src/components/lab/LabCreateDrawer.vue`（新） | 新建抽屉双 Tab（平台预置 / 自定义上传）；基本信息 + 可选章节 + 自定义 HTML 上传 + 补充说明；`allow_resubmit` 默认 `False`（C12）；创建后上传，S8 命中走二次确认重传；`created` 事件让父页面直接打开「成绩接口」Tab |
| `frontend/src/views/teacher/LabLibrary.vue`（新） | 顶级页：课程筛选 + 列表（名称/课程/类型/状态/调试徽标/已完成/均分/操作）+ 详情抽屉五 Tab（概览 / 实验页面 / 成绩接口 / 排课 / 成绩）；`fetchLabStats` 按 `grading_source` 排除 external 的步骤指标（C17）；行 class `lab-row-<id>` 便于 E2E 精确定位 |
| `frontend/src/views/teacher/LabManage.vue` | 删掉内联「新建实验」表单，改为公共 `LabCreateDrawer`；详情抽屉对 `page_source=custom` 增加「成绩接口」区复用 `LabGradingPanel`；课程空间 tab 保留 |
| `frontend/src/views/student/LabList.vue` | C5 按 `status` 三分支徽标（未开始 / 进行中 / 已出分）+「自定义」标签；`grading_source=external` 只渲染总分 + 服务端用时 + 提交时间，**不渲染步骤明细表**；C12 修正重做入口（见 §四 调试记录 5） |

### 1.3 移动端 / 文档 / 测试资产

| 文件 | 改动 |
| --- | --- |
| `app/src/pages/lab/grades.vue` | 删除 `question_score` 幽灵字段，改「实验用时」（`elapsed_seconds`）；external 下基础分 / 完成效率显示「不适用」（C6/C17） |
| `backend/e2e_real_test.py` | `need` 去掉 `question_score`、加 `elapsed_seconds` / `grading_source`，并断言幽灵字段确实不在响应；另修复 P0–P5 后失效的建班/入班段（见 §四 调试记录 2） |
| `docs/实验管理-自定义实验对接说明.md` | 状态改「已实现（Stage 4 按实现校准）」；补 `integration-spec` 响应结构说明；错误码表按实现校准（票据类一律 401，非 400）；补 `grade-debug` 的 `blocking` 提示项与草稿态调试语义 |
| `test/e2e/lab-custom-setup.py`（新） | 真实 HTTP + ORM 准备课程/班级/学籍；**从真实 `integration-spec` 返回的 Markdown 中提取最小 HTML** 存为 `fixtures/stage4-from-spec.html`，删除临时实验；产物 `D:/tmp/stage4-setup.json` |
| `test/e2e/lab-custom.js`（新） | CDP 真实浏览器 52 项断言，`BASE` / `SHOT_PREFIX` 可配置（本地 5273 / 8092 通用） |
| `test/e2e/lab-custom-data.py`（新） | 12 项真实 HTTP 落库核对，`API_BASE` 可配置 |
| `test/e2e/fixtures/stage4-from-spec.html`（新） | 从动态说明提取的「AI 生成页面样本」，上传后真实跑通上报 |

---

## 二、命令与输出

所有输出已落 `docs/实验管理-阶段证据/stage4-*.log`（JWT 已脱敏为 `<JWT_REDACTED>`）。

| 命令 | 证据文件 | 关键输出 |
| --- | --- | --- |
| `cd backend && ./venv/Scripts/python.exe manage.py test apps.labs --keepdb -v 1` | `stage4-unit.log` | `Found 36 test(s)` / `Ran 36 tests in 6.969s` / `OK`（Stage 3 为 29，本阶段新增 7） |
| `./venv/Scripts/python.exe manage.py makemigrations --check --dry-run` | `stage4-migrate.log` | `No changes detected`（Stage 4 零模型改动、零迁移） |
| `./backend/venv/Scripts/python.exe test/check_sfc_bindings.py` | `stage4-sfc.log` | `exit 0`，无缺绑定（脚本成功时不打印内容，文件内已说明） |
| `cd frontend && npx vite build --outDir dist_new` → `mv dist dist_bak_<ts> && mv dist_new dist` | `stage4-build.log` | `✓ built in 10.25s`；产出 `LabLibrary-*.js` / `LabGradingPanel-*.js` chunk |
| `cd backend && ./venv/Scripts/python.exe e2e_real_test.py` | `stage4-regression-e2e.log` | `🎉 全部真实链路测试通过`（含 `✅ 移动端字段齐全`、`question_score` 不在响应） |
| `./venv/Scripts/python.exe ../test/e2e/lab-custom-setup.py` | `stage4-setup.log` | `course OK` / `class/student OK` / `spec OK: markdown=7505 chars, min-html=2152 chars` / `temp lab deleted OK` |
| `BASE=http://127.0.0.1:5273 SHOT_PREFIX=stage4-local node test/e2e/lab-custom.js` | `stage4-browser-local.log` | `总计 52 项，通过 52 项，失败 0 项` / `ALL_PASS` |
| `./venv/Scripts/python.exe ../test/e2e/lab-custom-data.py` | `stage4-data.log` | `总计 12 项，通过 12 项，失败 0 项` / `ALL_PASS` |

**服务状态**：`8005` 由 `backend/venv/Scripts/python.exe manage.py runserver 8005` 干净启动（`StatReloader`）；`5273` 由 `node serve-local.js` 直出 `frontend/dist`（新构建）并代理 `/api` → 8005。

**关键真实输出摘录**：

```text
PASS | C4 动态 Markdown 含实验名/满分/schema/最小HTML/AI指令
PASS | D4 提示项渲染为灰色「提示」而非红色失败（blocking=false） | {"total":7,"info":4,"bad":0,"ok":3}
PASS | D9 dry-run 未产生任何真实提交 | count=0
PASS | E5b 列表状态变为「已发布」
PASS | F3 说明里的最小 HTML 正常运行（3 个任务渲染）
PASS | F4 页面经 LabBridge.reportGrade 真实上报成功 | {"code": 0, "message": "成绩已提交", "submission_id": 16, "total_score": 100, ...}
PASS | F7 external 只显示总分 + 用时、不渲染步骤表
PASS | F9 自定义实验提交后不提供重做入口（C12 allow_resubmit=False） | []
PASS | F10 全流程控制台无 error
```

```text
PASS | D7 S1 落库用时 == submitted_at - started_at | 0 vs 0
PASS | D9 grade_raw 原文与 sha256 摘要留痕 | digest=0c9b6c7b...
PASS | D11 C8 grade_raw 角色裁剪（教师可见 / 学生 None） | teacher=dict student=None
```

**本地浏览器截图**（`test/screenshots/`，目录被 `.gitignore` 忽略，故不入库，文件名在此留证）：

| 文件名 | 内容 |
| --- | --- |
| `stage4-local-library.png` | 顶级「实验管理」列表 + 侧栏入口 |
| `stage4-local-create.png` | 新建抽屉「自定义上传」Tab + 已选 HTML |
| `stage4-local-grading.png` | 「成绩接口」Tab：接口地址 / 动态说明 / 复制给 AI / 在线调试 |
| `stage4-local-debug.png` | 在线调试结果与写入预览 |
| `stage4-local-published.png` | 发布后列表状态 |
| `stage4-local-student.png` | 学生端 external：总分 + 用时、无步骤表 |

---

## 三、逐条验收结论

执行方案 §3 Stage 4「真实测试」与「验收门槛」逐条对照：

| # | 验收项 | 结论 | 依据 |
| --- | --- | --- | --- |
| 1 | `npx vite build --outDir dist_new` → 替换 dist；`node serve-local.js` 起 5273 | ✅ | `stage4-build.log` `✓ built in 10.25s`；`5273/` 与新 chunk 均 200 |
| 2 | 本地浏览器**真实点击**完整 UI 流程：双 Tab 新建 → 上传 → 创建即显示「成绩接口」→ 复制说明 → 在线调试 → 详情页/排课/成绩 Tab 无报错 → 发布 | ✅ | `stage4-browser-local.log` A–E 共 39 项全 PASS；F10 控制台零 error |
| 3 | `check_sfc_bindings.py` 无缺绑定；`test/e2e/lab-custom.js` 跑通 | ✅ | `stage4-sfc.log` exit 0；`stage4-browser-local.log` `52/52 ALL_PASS` |
| 4 | 8092 用测试环境前端通道部署 dist → 浏览器重跑同一套流程（含移动端 H5）→ 截图 | ⏸ **延后** | 用户 2026-11-05 授权；补测清单见 §六，脚本已参数化可直接复跑 |
| 5 | 把接入说明整段贴给 AI（或用现成最简示例 HTML）生成页面，上传后真实跑通上报 | ✅ | setup 从**真实** `integration-spec` 返回的 Markdown 提取最小 HTML → 上传 → sandbox iframe 内 3 任务渲染 → `LabBridge.reportGrade()` 返回 `code:0 成绩已提交`（F3/F4）；样本 `test/e2e/fixtures/stage4-from-spec.html` |
| 门槛 a | 5273 UI 全流程无控制台报错 | ✅ | F10 |
| 门槛 b | 复制出来的说明可直接使用 | ✅ | 门槛 5 + 单测 `test_min_html_is_uploadable_and_scan_clean`（静态扫描零命中）+ C5 占位符零残留 |
| 门槛 c | `check_sfc_bindings.py` 全绿 | ✅ | `stage4-sfc.log` |
| 附加 | 本地单测 36/36、迁移一致性、既有全链路回归 | ✅ | `stage4-unit.log` / `stage4-migrate.log` / `stage4-regression-e2e.log` |
| 附加 | 真实落库核对 12/12（S1 用时、C8 裁剪、C6 幽灵字段、票据消费态） | ✅ | `stage4-data.log` |

**结论：Stage 4 本地验收全绿，按用户授权口径允许推送并进入 Stage 5。8092 补测不跳过、不改期望，作为独立批次统一补测并回填本证据 §六。**

---

## 四、调试记录（现象 → 原因 → 修法）

1. **`integration-spec` 单测首轮 2 项失败（7 项中 5 通过）**
   - 现象：`'@@' unexpectedly found`（AI 指令块里残留 `@@TOTAL_SCORE@@` / `@@LAB_TITLE@@`）；`allow-same-origin` 断言误报。
   - 原因：① `_AI_PROMPT` 作为**替换值**插入，而它在替换顺序中晚于 `@@TOTAL_SCORE@@`，嵌套占位符单轮 `replace` 未展开；② C40 的约束是「iframe 属性不得含 `allow-same-origin`」，说明文档本就应明确写「**无** `allow-same-origin`」，把「文档不得出现该词」当断言语义写错了。
   - 修法：① `build_integration_spec` 改为多轮展开直到无 `@@` 残留（最多 3 轮）；② 断言改为「沙箱属性串 `allow-scripts allow-forms allow-modals` 正确」+「不含被放宽的四项组合」。重跑 7/7 OK。

2. **`e2e_real_test.py` 教师建班返回 403**
   - 现象：`❌(期望201) [403] POST /classes/ 班级由学校统一分配，仅平台管理员可维护`，脚本在建班断言处中止。
   - 原因：P0–P5 权限重构后班级 CRUD 收归 `/admin/classes*`、入班走 `ClassStudent` 单一写入口，教师端 `/classes/` 与 `/classes/{id}/add-student/` 已下线；该既有脚本未同步，与 Stage 4 改动无关。
   - 修法：用真实 ORM（`ClassRoom` / `ClassCourse` / `ClassStudent` + `assign_students`）建立等价数据（复用已有 active 学籍时不破坏存量），后续排课 / 发布 / 学生实验 / 成绩 / 报告 / 下载**仍全部走真实 HTTP**，未改任何业务断言或期望。重跑 `🎉 全部真实链路测试通过`。

3. **本地 8005 被旧解释器与重复进程持有**
   - 现象：`Get-CimInstance` 显示 4 个 `runserver 8005` 进程（2 个 `E:\Miniconda\python.exe`、2 个 venv），其中 Miniconda 进程持有端口，违反「勿用 Miniconda」纪律。
   - 原因：历次会话残留进程。
   - 修法：全部 `Stop-Process` 后确认端口释放，用 `backend/venv/Scripts/python.exe manage.py runserver 8005` 干净重启（`Watching for file changes with StatReloader`），新端点 `/api/labs/1/integration-spec/` 返回 401（路由生效、权限拒绝）而非 404。

4. **浏览器 E2E 首轮 39/44，5 项连锁失败**
   - 现象：`E2c 保存排课` FAIL → `E2d 排课记录`、`E5b 已发布`、`F1 学生 start`（400 无排课权限）连锁失败；`F1` 无 `page_url` 又导致 `Cannot navigate to invalid URL` 异常。
   - 原因：`clickButton('.el-drawer', '保存排课')` 用 `document.querySelector('.el-drawer')` 命中了**已关闭但仍在 DOM 中**的新建抽屉（EP drawer 关闭后 `display` 仍 flex，前端防坑已记录），因此找不到详情抽屉里的按钮。
   - 修法：① `clickButton` 遍历所有 scope 匹配项并按可见性过滤按钮；② F 阶段对 `gateUrl` 加空值保护（缺失时明确记 3 项 FAIL 而不抛异常）；③ 重新跑 setup 生成全新实验名避免复用旧数据。重跑 `52/52 ALL_PASS`。

5. **截图目检发现「重做实验」按钮误导（C12）**
   - 现象：学生端 external 卡片在 `allow_resubmit=False` 的自定义实验已提交后仍显示「重做实验」；进行中的作答也显示「重做」。
   - 原因：按钮条件仅判断 `submissionOf(row)` 存在，未看 `row.allow_resubmit` 与 `status`；点击会被后端拒绝。
   - 修法：条件加 `row.allow_resubmit`，文案按 `status` 区分「继续实验 / 重做实验」；E2E 增加 F9 回归断言（自定义实验提交后按钮列表为空）。重建 dist 后重跑 **全部** Stage 4 测试（SFC / build / 36 单测 / setup / E2E / 数据核对）全绿。

6. **Stage 3 交接项落地**（非失败）：`grade-debug` 的 `checks` 带 `blocking`，Stage 4 面板把 4 个环境提示项渲染为灰色「提示」，草稿态「当前 draft」不标红；E2E D4 实测 `{"total":7,"info":4,"bad":0,"ok":3}`。

---

## 五、偏离说明

1. **新增 `backend/apps/labs/integration_spec.py`**：执行方案 Stage 4 改动清单未显式列该文件，但设计 §5.3 / §6.2 明确要求 `GET /api/labs/{id}/integration-spec/` 动态渲染。实现为独立纯渲染模块（无新表 / 无迁移 / 无新依赖），`views.py` 只挂一个 action，避免把 7.5KB Markdown 模板塞进已 1000 行的 views。
2. **`backend/e2e_real_test.py` 额外改动**：清单只要求修 `question_score` 断言，实际还修了建班/入班段（见调试记录 2）。原因是该脚本在当前权限模型下根本跑不到被修的断言；未放宽任何断言、未改期望。
3. **`frontend/src/views/student/LabList.vue` 额外改动**：清单只列三分支徽标 / 自定义标签 / external 展示，顺带修了 C12 重做入口（清单内文件，真实浏览器目检发现的缺陷，见调试记录 5）。
4. **新增 `test/e2e/` 三件套 + fixture**：执行方案 §3 Stage 4 真实测试第 3、5 条要求 `test/e2e/lab-custom.js`（`BASE` 可配置）与「AI 生成页面样本」，故新增 setup / browser / data 三脚本与从真实说明提取的 HTML 样本。
5. **8092 复测延后**：唯一口径变更，用户 2026-11-05 明确授权，只调整推送时机，不降低验收标准。

---

## 六、8092 补测清单（延后独立批次，未跳过）

网络恢复后按以下顺序补测并回填本文件（沿用 Stage 0 核实的前端通道，**禁止复用生产 8088 一键脚本**）：

1. 确认目标为测试环境 `zhike_qv` / `192.168.3.145:8092`，backend 是 bind mount；`deploy/labs/` 三静态文件与 `views.py` / `integration_spec.py` 已同步，必要时重启 backend/worker；本次零模型改动，无需 `migrate`。
2. 按 Stage 0 核实的**测试环境前端通道**部署本次 `frontend/dist`（chunk hash 全量重算，不可增量）。
3. `BASE=http://192.168.3.145:8092 ./venv/Scripts/python.exe ../test/e2e/lab-custom-setup.py`（`OUT=D:/tmp/stage4-setup-8092.json`）。
4. `SETUP=D:/tmp/stage4-setup-8092.json BASE=http://192.168.3.145:8092 SHOT_PREFIX=stage4-8092 node test/e2e/lab-custom.js` → 期望 `52/52 ALL_PASS`。
5. `SETUP=D:/tmp/stage4-setup-8092.json API_BASE=http://192.168.3.145:8092 ./venv/Scripts/python.exe ../test/e2e/lab-custom-data.py` → 期望 `12/12 ALL_PASS`。
6. 移动端 H5 成绩页 external 展示目检（总分 + 用时、四项基准分「不适用」），截图 `stage4-8092-h5.png`。
7. 截图名回填本文件 §二表格，并把 §三第 4 项与门槛 a 的 8092 结论改为 ✅；若失败，按 D5 记录现象→原因→修法并**重跑本阶段全部测试**。
