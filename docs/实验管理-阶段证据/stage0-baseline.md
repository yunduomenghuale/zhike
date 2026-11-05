# Stage 0 证据：基线冻结 + 设计文档入库 + 环境核验

> 日期：2026-11-05　分支：feature/ai-queue（origin 同步，HEAD `18e775a`）　执行人：WorkBuddy 会话

## 一、改动摘要

- 无业务代码改动。
- 新增本文档与 `stage0-unit.log` / `stage0-migrate.log` / `stage0-8092-smoke.log`（本目录）。
- 新增测试环境冒烟脚本 `test/e2e/stage0-8092-smoke.js`（CDP 真实浏览器，参照 `prod-smoke.js` 范式，BASE 可配）。
- 方案文档 §0.1 状态表：Stage 0 → 已完成。

### 8092 测试环境基线夹具（本阶段创建，供后续阶段复用）

| 项 | 值 |
| --- | --- |
| 预置模板 | `manage.py seed_lab_templates` 已跑，7 个模板在库（labs_labtemplate 1–7） |
| 预置实验 | Lab id=1「实验一：交换机基础配置与VLAN/STP实验」（template 1，course 1，T0001 创建，已发布） |
| 排课 | LabSchedule id=1 → class 1（计算机一班），open/close 留空 = 立即开放不限制 |
| 学生作答 | Submission id=1（B2204011，in_progress，未提交——基线只进入不提交） |
| 账号口令 | T0001 / B2204011 均重置为 `Test123456!`（测试环境夹具口令） |

## 二、命令与输出（真实执行，全部落文件）

1. `git status -sb && git pull --ff-only` → `## feature/ai-queue...origin/feature/ai-queue`，Already up to date。工作区无关未跟踪项（`backend/inflight_cache/`、`docs/Java课程资源/`）保持不动。
2. 本地起服务：`manage.py runserver 8005 --noreload` + `node serve-local.js`；`curl --noproxy '*' ` 探测：`127.0.0.1:8005/api/` → **401**（鉴权端点正常响应）、`127.0.0.1:5273/` → **200**。双端可达。
3. 基线单测：`manage.py test apps.labs --keepdb -v 2` → **Ran 10 tests in 2.628s，OK**（LabFlowTest 3 + LabGateTest 4 + LabReportTest 1，共 10 全绿）。输出：`stage0-unit.log`。
4. 迁移一致性：`makemigrations --check --dry-run` → exit 0，仅标准输出 `No changes detected`（21 字节）。输出：`stage0-migrate.log`。
5. 8092 冒烟 curl：`curl --noproxy '*' -I http://192.168.3.145:8092/` → **HTTP 200**。
6. 真实浏览器（headless Chrome CDP，`test/e2e/stage0-8092-smoke.js`）：
   - 场景 A：test_admin 登录 → `/teacher/courses/1/labs` 渲染含实验内容、无控制台错误 → 截图 `test/screenshots/stage0-8092-admin-labs.png`。
   - 场景 B：B2204011 登录 → 打开预置实验门控页（submission start 返回的签名 URL）→ readyState=complete、`window.LabBridge` 存在、页面含 lab-bridge script、无控制台错误；步骤清单（步骤1–6）渲染正常，**未提交** → 截图 `test/screenshots/stage0-8092-student-gate.png`。
   - 汇总 **7/7 ALL_PASS**。输出：`stage0-8092-smoke.log`。

### 调试记录（现象 → 原因 → 修法）

| # | 现象 | 原因 | 修法 |
| --- | --- | --- | --- |
| 1 | 场景 B 登录脚本崩 `Cannot convert undefined or null to object` | 场景 A 已登录 admin，再访问 /login 被路由重定向到 dashboard，登录表单不在 DOM，取 inputs[0] 为 undefined | `login()` 入口先 `localStorage.clear()` 再导航 /login |
| 2 | 清 storage 崩 `Access is denied` | 首次调用时页面还是 about:blank，localStorage 不可读 | clear 包 try/catch |
| 3 | B4 控制台错误断言失败 | HTTP 非安全源（192.168.3.145 纯 HTTP）下 Chrome 把「Cross-Origin-Opener-Policy header has been ignored」记为 error 级日志；属环境性告警，与应用无关（任意存量页面同现） | `consoleErrors()` 过滤该已知告警；其余 error 仍严格断言 |

## 三、三项部署事实（8092，已核实）

1. **compose 目录 / 项目名 / 重启命令**：目录 `/data/zhike-queue-verify`，文件 `docker-compose.qv.yml`（非默认名，必须 `-f` 指定），项目名 `zhike_qv`；容器 `zhike_qv_backend / zhike_qv_worker / zhike_qv_frontend / zhike_qv_qdrant`。重启 backend/worker 的确切命令：
   `cd /data/zhike-queue-verify && sudo docker compose -f docker-compose.qv.yml restart backend worker`
   （backend 为 bind mount `/data/zhike-queue-verify/backend → /app` rw，改代码重启即生效；**不需要 compose build**。）
2. **deploy/labs 挂载**：backend 与 worker 均挂载 `/data/zhike-v2/deploy/labs:/app/labs:ro` —— **与生产 8088 共用同一目录**（:ro）。含义：Stage 2 新增静态文件（lab-gate-parent.html 等）是增量新增、对生产无影响；但**严禁改动/删除该目录既有文件**（lab-bridge.js 等），否则波及生产。
3. **8092 前端 dist 通道**：frontend 容器（nginx）挂载 `/data/zhike-queue-verify/dist:/usr/share/nginx/html:ro`。部署方式 = 本地 build 后把**整份 dist** 同步到该目录（chunk hash 全量重算，增量不可行）。**不使用** `deploy/deploy-frontend-dist.py`（那是生产 8088 一键脚本，复用即违规）。

### 数据库与备份

- 运行时库（经 `.env.qv`）：`mysql://root:***@192.10.0.3:3306/zk_queue_verify`（共享 test-mysql80，只动 zk_queue_verify，**不 stop 容器**）。
- 回滚垫备份：`/data/zhike-queue-verify/backups/zk_queue_verify-pre-labs-20261105.sql.gz`（14M，mysqldump --single-transaction，已 zcat 验头）。
- 8092 库基线状态：labs=0（本阶段建 1）、templates=0（本阶段 seed 7）、courses=6、class=1、students=3。

## 四、逐条验收结论

| 门槛 | 结论 |
| --- | --- |
| 基线单测全绿 | ✅ 10/10（2.628s） |
| 本地 8005/5273 可达 | ✅ 401 / 200 |
| 8092 预置实验可正常进入 | ✅ 门控页 200、LabBridge 注入、步骤渲染、无提交、7/7 浏览器断言通过 |
| 三项部署事实全部有明确答案 | ✅ 见上（compose/挂载/dist 通道） |
| 备份存在 | ✅ zk_queue_verify-pre-labs-20261105.sql.gz（14M，已验证） |
| makemigrations --check 零变更 | ✅ exit 0 |

**结论：Stage 0 验收全绿，允许进入 Stage 1。**
