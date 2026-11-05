# Stage 2 证据（草稿）：页面上传 + L2 沙箱门控 + 预览 + 静态扫描

> 日期：2026-11-05　分支：feature/ai-queue　前置：Stage 0（eaa021c/fd8589a）、Stage 1（07602ba/1ea5176）已完成
> **状态：本地验收全绿，已按用户授权口径推送。**
> **口径变更（用户 2026-11-05 明确授权）**：原纪律要求「验收门槛逐条全绿才改状态表 / push / 进下一阶段」，其中含「8092 复测」。因本机网络切至 `192.168.0.0/24`、`192.168.3.145` 不可达，用户授权 **「后续任务都先在本地测试；8092 复测延后，等我过几天再进行；本地全绿即逐阶段推送」**。故本阶段以本地全绿收尾并推送。8092 复测 **未跳过、未改期望、未伪装通过**，只是推迟为独立补测批次，清单见 §四。

## 一、改动摘要

| 文件 | 改动 |
| --- | --- |
| `backend/apps/labs/gate.py` | 新增 `FRAME_URL` / `PARENT_TEMPLATE` / `<base>` 剥离与 head 注入工具；`sign_preview()` / `verify_preview()`、`frame_url()`、`_asset_sig_exp()`（预览页资产 base 用正式 `sign_lab` 重签）、`_read_static()`；`inject_bridge(html, mode, base, preview)` 三分流；`render_parent()` / `render_frame()`；`read_page()` 对 custom 从 `LabPage.file` 读取 |
| `backend/apps/labs/views.py` | `lab_gate_page` 三分流（preview / custom 父页面验票据+发布态+排课窗口 / template 原逻辑不验票据）；新增 `lab_gate_frame`；`page` 上传/替换/删除 action 与 `page/preview` action（均 `[IsTeacher]`）；`perform_destroy` 清盘；`_GATE_CSP` 严格 CSP（`form-action 'none'` / `base-uri 'self'` / `object-src 'none'`）+ `Referrer-Policy: no-referrer` 覆盖父页面与 frame 两个响应；frame 显式 `X-Frame-Options: SAMEORIGIN`（C44） |
| `backend/apps/labs/urls.py` | 显式 `path("lab-gate/frame/<token>/<sig>/<exp>/")` **排在 `router.urls` 之前**（C22/C43） |
| `backend/apps/labs/serializers.py` | `LabPage` 元信息字段（`has_custom_page`/`custom_page_name`/`custom_page_size`）；S8 静态扫描 8 条规则（localStorage / sessionStorage / document.cookie / window.opener / eval / 外链 src / sendBeacon / WebSocket），命中→`require_confirm` 二次确认→管理员告警 |
| `backend/apps/labs/tests.py` | 新增 `LabCustomPageTest` 3 用例（上传替换删除 / L2 父页面与 frame / 静态扫描与预览）+ `LabStaticContractTest` 1 用例（C40–C46 静态契约逐条对照，读真实静态文件与源码） |
| `deploy/labs/lab-gate-parent.html` | 平台父页面：`sandbox="allow-scripts allow-forms allow-modals"` iframe（无 `allow-same-origin`）、四占位符 `/*__X__*/` 注释形态、`<script src="lab-bridge-parent.js">` |
| `deploy/labs/lab-bridge-parent.js` | 唯一持 `LabAttemptToken` 的脚本；IIFE 闭包删除引导变量；`loadContext()` 调 `bridge-validate` 只映射四字段；消息监听校验 `event.source === frame.contentWindow`（C41）；S4 一次性闸门（失败自动解除）；代发 `POST /api/lab-gate/grade/` |
| `deploy/labs/lab-bridge-shim.js` | iframe 内兼容 `window.LabBridge`（preview/context/validate/reportGrade），只经 `postMessage` 与父页面通信，**不含票据头与同源 API fetch 字面量**（C42） |
| `frontend/src/views/student/LabList.vue` | `window.open(url, '_blank', 'noopener,noreferrer')`（C37/S6） |
| `backend/apps/courses/views.py` | 存量自定义导图/演示门控页 CSP 补 `form-action` / `base-uri` / `object-src`（C36/C39） |

**偏离说明 1**：设计文档原把 `bridge_validate` 的 context 追加放到 Stage 3，但 L2 父页面 `loadContext()` 现在就需要 `total_score`；故 Stage 2 在 `lab` dict 提前补 `"total_score": float(lab.total_score)`。断言未放宽（浏览器 S3 仍要求 `totalScore` 为 number）。

**偏离说明 2（实现与设计对齐）**：C44 假定 frame 响应 `X-Frame-Options: SAMEORIGIN`，实测由 Django 中间件下发 `DENY`（依赖「CSP `frame-ancestors` 覆盖 XFO」的浏览器行为）。已在 `lab_gate_frame` 显式设为 `SAMEORIGIN` 并加单测断言，避免依赖该隐式行为。

## 二、命令与输出（真实执行，落文件）

1. **本地单测**：`./venv/Scripts/python.exe manage.py test apps.labs --keepdb -v 2` → **Ran 17 tests in 4.119s，OK**（存量 10 + Stage 1 的 3 + Stage 2 的 4）。输出：`stage2-unit.log`。
   - `test_sandbox_parent_and_frame`：父页面 `<iframe sandbox=属性>` 不含 `allow-same-origin`、iframe src 绝对路径且不含 attempt token、`<base>` 与 `lab-bridge-parent.js`、父页面 CSP 三项、frame 返回教师 HTML + shim + `<base>`、无票据/引导变量、教师自带 `<base> https://evil.example/` 被剥离、frame CSP `sandbox` 指令、`X-Frame-Options: SAMEORIGIN`、无票据访问父页面 403。
   - `test_static_scan_and_preview`：含 `eval` / 外链 / WebSocket / sendBeacon / cookie / opener 的脏 HTML 首次 400 + `require_confirm` + ≥6 命中项且不落库、不告警；`confirm=1` 后落库且管理员收到「静态扫描命中」通知；干净文件直接成功；预览草稿可开、`preview=true` 且 `BOOT_TOKEN=null`、预览页 `<base>` 用正式签名使 `lab-bridge-parent.js` / `lab-bridge-shim.js` 均 200；学生上传/预览 401/403。
   - `test_upload_replace_delete_page`：非 .html / 空文件拒绝；上传记录 sha256 + 上传人；替换后旧磁盘文件被清；发布前置校验；删除回退 template；删除实验磁盘无残留。
   - `test_c40_c46_static_contract`：读 `settings.LABS_ROOT` 下三个真实静态文件 + `views.py` 源码，逐条断言 C40/C41/C42/C44/C45/C46。
2. **存量回归**：`manage.py test apps.courses --keepdb` → **Ran 84 tests，OK**；`manage.py test apps.analytics apps.classroom --keepdb` → **Ran 87 tests，OK**。输出：`stage2-regression.log`。
3. **前端构建**：`npx vite build --outDir dist_new` → `✓ built in 11.99s`，随后 `mv dist dist_bak_<ts> && mv dist_new dist`。输出：`stage2-build.log`。
4. **真实浏览器（本地 5273，CDP headless Chrome）**：`CDP_PORT=9223 SHOT_PREFIX=stage2-local node test/e2e/stage2-sandbox-verify.js <正式父页面URL> <预览URL>` → **19/19 ALL_PASS**。输出：`stage2-browser-local.log`；截图 `test/screenshots/stage2-local-parent.png`、`stage2-local-preview.png`、`stage2-local-after-report.png`。
   - 正式模式：P1–P5 父页面渲染 / sandbox 属性 / iframe src 不含票据 / parent.js 200 / `<base>` 签名资产路由。
   - iframe 内三项隔离（**在 OOPIF 独立执行上下文中实测**）：I1 localStorage `SecurityError`、I2 sessionStorage `SecurityError`、I3 `document.cookie` `SecurityError`、I4 `window.parent.document` `SecurityError`、I5 `window.opener` null、I6 `fetch('/api/...')` REJECTED（C42 的 CORS 预检阻断）。
   - 桥接链路：S1 shim 注入且 `LabBridge` 存在、S2 `preview=false`、S3 `validate()` 经 postMessage 拿到四字段 context（无票据）、S4 `reportGrade()` 触发父页面代发并收到响应（Stage 3 端点未实现，返回 500，按 Stage 2 预期只验链路已触发）。
   - 预览模式：V1 `preview=true` 且无票据、V2 iframe 带 `preview=1` 且无票据、V3 iframe 内 `LabBridge.preview=true` 且跳过提交。
5. **CSP 响应头原文（真实 HTTP，5273→8005）**：`bash D:/tmp/stage2-collect-csp.sh` 采集 A 正式父页面 / B 预览父页面 / C 正式 frame / D 预览 frame 四组响应头（每组两处 dump）。输出：`stage2-csp-headers.log`。
   - 4 组全部 200；8 处 `Content-Security-Policy` 均含 `form-action 'none'` / `base-uri 'self'` / `object-src 'none'`；8 处 `X-Frame-Options: SAMEORIGIN`；父页面与 frame 均 `Referrer-Policy: no-referrer`、`Cache-Control: no-store`、`X-Content-Type-Options: nosniff`；frame 额外有 `sandbox allow-scripts allow-forms allow-modals` 指令前缀。
   - 资产路由：`lab-bridge-parent.js` / `lab-bridge-shim.js` / `lab-bridge.js` 均 HTTP 200。
6. **8092 后端与静态文件已部署（本轮之前完成）**：custom lab id=2 已上传页面并发布，容器已重启，`8091 HTTP 401`、`makemigrations --check` 零变更；`deploy/labs/` 三个新文件同步至 `/data/zhike-v2/deploy/labs/`（与生产 8088 只读共享同一目录，只新增文件、未改 `lab-bridge.js`、未重启生产、未碰 8088）。
7. **8092 真实浏览器复测**：⛔ **未执行**（网络阻断，见 §四）。`stage2-browser-8092.log` 与 `stage2-8092-parent.png` / `stage2-8092-preview.png` 尚未生成。

### 调试记录（现象 → 原因 → 修法）

| # | 现象 | 原因 | 修法 |
| --- | --- | --- | --- |
| 1 | 上传/删除两个 `@action` 同 `url_path="page"`，POST 返回 405、发布失败 | DRF 路由冲突，POST 被映射到 DELETE action | 合并为单 action `methods=["post","delete"]`，内部按 `request.method` 分派 |
| 2 | 父页面渲染成 `window."token" = "token";` | 朴素 `.replace("__LAB_BOOT_TOKEN__", ...)` 误伤脚本变量名里的同名字符串 | 占位符改注释形态 `/*__X__*/`，`gate.py` replace 同步 |
| 3 | Chrome DevTools 端口 9225 绑定失败 | Windows 端口排除范围 | 脚本默认 `CDP_PORT=9223`，支持环境变量覆盖 |
| 4 | 浏览器脚本从父页面上下文探测 iframe 导致假失败 | OOPIF 有独立执行上下文，父页面 `Runtime.evaluate` 到不了 | 用 `Target.setAutoAttach` 扁平会话定位 iframe session，在其自己的会话中执行 |
| 5 | P2 断言「父页面 outerHTML 不含 `allow-same-origin`」失败 | 父页面 HTML 注释里写了该禁用词 | 改为精确读 `iframe.getAttribute('sandbox')` 断言；本轮再顺手清掉注释里的字面量 |
| 6 | S3 `validate()` 返回 `totalScore: null` | `bridge_validate` 响应无 `lab.total_score` | 补 `total_score` 字段（偏离说明 1），断言不放宽 |
| 7 | S4 `reportGrade()` 返回 500 | Stage 3 的 `/api/lab-gate/grade/` 尚未实现 | Stage 2 只要求验证 postMessage 链路已触发；成绩入库留 Stage 3（验收期望未改） |
| 8 | V3 `LabBridge is not defined` | 预览 URL 用 preview 签名，但 `<base>` 也沿用该签名；资产路由只认正式 `verify_lab` 签名 → parent.js / shim.js 403 | `gate.py` 新增 `_asset_sig_exp()`：预览模式下 `<base>` 另签一对正式 sig/exp；新增单测断言两个资产 200 |
| 9 | 预览 iframe session 定位失败 | 复用了正式页面旧 session / URL 过滤过严 | 记录 `attachBefore`，导航后只取新增 `Target.attachedToTarget` iframe session |
| 10 | C42 静态扫描会命中 `lab-bridge-shim.js` | 文件头注释写了 `X-Lab-Token` / `fetch('/api...')` 字面量（执行逻辑并无此调用） | 清理注释措辞，新增 `test_c40_c46_static_contract` 对真实静态文件做硬断言 |
| 11 | frame 响应 `X-Frame-Options: DENY`，与 C44 不符 | `lab_gate_frame` 未显式设置，Django 中间件下发默认 DENY | 显式 `response["X-Frame-Options"] = "SAMEORIGIN"` + 单测断言（偏离说明 2） |
| 12 | 改完 `views.py` 后重新采集 CSP 仍是 DENY | 本地 8005 由 `E:\Miniconda\python.exe ... --noreload` 持有（违反纪律），不热加载 | 杀掉两个陈旧 runserver，用 `backend/venv/Scripts/python.exe manage.py runserver 8005 --noreload` 完整重启，8 处 XFO 全部变 SAMEORIGIN |
| 13 | `stage2-csp-headers.log` 初版只有标题无响应头 | 采集时本地 8005/5273 后台进程已被中断杀死 | 重启本地服务后用采集脚本重新采集，四组头完整 |
| 14 | 8092 / SSH 全部不可达 | 本机网络切至 `192.168.0.0/24`（网关 `192.168.0.1`），无 `192.168.3.0/24` 路由 | **外部网络环境问题，非代码缺陷，本轮无法自行修复**，见 §四 |

## 三、逐条验收结论

| 门槛 | 结论 |
| --- | --- |
| 本地单测：父页面 `<iframe sandbox=`、静态断言不含 `allow-same-origin`、`<base>` + parent.js 200 | ✅ 17/17 OK（`stage2-unit.log`） |
| frame 返回教师 HTML + shim、静态断言无票据/引导变量、frame URL 不含 attempt_token | ✅ `test_sandbox_parent_and_frame` + 浏览器 P3 |
| 双路由 CSP 含 `form-action 'none'` / `base-uri 'self'` | ✅ 真实 HTTP 8 处 dump 全含（`stage2-csp-headers.log`） |
| template 门控页不验票据、`LabGateTest` 全绿 | ✅ labs 17/17 含 `LabGateTest` 6 用例全绿；三分流 template 分支原逻辑保留 |
| 上传/替换/删除后磁盘无残留 | ✅ `test_upload_replace_delete_page` 断言旧文件与新文件路径均不存在 |
| 本地真实浏览器：iframe 内存储 / API / 父页面三项隔离 | ✅ 19/19 ALL_PASS，I1–I6 全为 `SecurityError` / REJECTED |
| `<script src="lab-bridge-parent.js">` 不 404 | ✅ 浏览器 P4 + 资产路由 200 校验（parent.js / shim.js / lab-bridge.js 均 200） |
| C40 / C41 / C42 / C44 / C45 逐条对照 | ✅ `test_c40_c46_static_contract` 读真实文件逐条断言 + 浏览器 P2/P3/S3/I6 佐证 |
| C46 新 action `[IsTeacher]` | ✅ 静态契约断言 page / preview 两个 action 均 `[IsTeacher]` 且无 `IsTeacherOrAdmin`；单测学生 401/403 |
| 预置实验零回归 | ✅ 本地 courses 84 + analytics/classroom 87 全绿；`lab-bridge.js` 资产 200（**8092 侧复测待补**） |
| S8 静态扫描标记 + 二次确认 + 管理员告警 | ✅ 本地单测覆盖（**8092 真实账号复测待补**） |
| **iframe 内三项隔离在「本地和 8092」都实测成立** | 🕐 **本地 ✅；8092 侧按用户授权延后**（非跳过，独立补测批次，见 §四） |
| **8092 真实账号 + 真实浏览器复测、截图留证** | 🕐 **延后**（`stage2-browser-8092.log` / `stage2-8092-*.png` 待补） |

**结论**：本地侧 12 项验收门槛全绿（单测 17/17、真实浏览器 19/19、CSP 头 8/8、回归 84+87）。含 8092 的 2 项按 2026-11-05 用户授权延后，**用例与期望一字未改**。按新口径改状态表为「已完成」并推送，进入 Stage 3；8092 回来后按 §四 逐条补测并回填本证据。

## 四、8092 复测延后说明与补测清单

- **现象**：本机 `192.168.0.102`（网关 `192.168.0.1`），无 `192.168.3.0/24` 路由；`192.168.3.145` ping 100% 丢包，`8092`/`8091` HTTP 000，SSH 22 不可达；备用 `192.168.99.170:8092` 同样 HTTP 000。
- **性质**：机房内网 `192.168.3.145` 只在特定网络可达（项目笔记亦记「机房内网，回家连不上」）。属外部网络环境变化，非代码缺陷。
- **用户口径（2026-11-05）**：后续阶段先只做本地测试；8092 复测等用户过几天回来后作为独立批次统一补；本地全绿即可逐阶段改状态表 + commit + push。
- **恢复条件**：本机回到可访问 `192.168.3.145` 的网络（或提供可达的 8092 新地址/端口映射）。
- **补测批次范围**：Stage 2、3、4、5 各自的 8092 复测统一并入本批次；本文件只记 Stage 2 部分，后续阶段证据各自留「8092 待补」小节。
- **补测清单**（严格按原顺序补齐，不得跳过、不得改期望）：
  1. `8092` 前端 dist 通道以 Stage 0 证据为准同步；`deploy/labs/` 三个静态文件与 `views.py` / `tests.py` 等后端改动重新同步（只增改、不动 `lab-bridge.js`、不碰 8088）；显式 `migrate labs`（此前已跑过 0006，需确认零变更）；重启 `zhike_qv_backend` / `zhike_qv_worker`。
  2. 用 `test_admin` 与 `B2204011` 走同一套 `stage2-sandbox-verify.js`（`BASE=http://192.168.3.145:8092`、`SHOT_PREFIX=stage2-8092`），输出 `stage2-browser-8092.log` + 两张截图。
  3. 8092 上补跑「含 eval / 外链 HTML 上传 → 标记 → 二次确认 → 管理员告警」。
  4. 8092 预置实验零回归冒烟（复用 `stage0-8092-smoke.js`）。
  5. 补 `stage2-csp-headers.log` 的 8092 侧响应头原文。
  6. 补齐本证据文档 §二第 7 条与 §三 8092 两项结论（把 🕐 改成 ✅ 并写明日志/截图文件名），单独出一个 `docs(labs)` 证据回填 commit；状态表日期/证据不变，仅在该行备注「8092 补测已完成」。

> 本阶段提交文件：8 个已跟踪改动 + `deploy/labs/` 三个新静态文件 + `test/e2e/stage2-sandbox-verify.js` + 本证据与各 `.log`（`.log` 用 `git add -f`）。**无关未跟踪项** `backend/inflight_cache/`、`docs/Java课程资源/`、`frontend/dist_bak_1793871154/` 一律不 add。截图按 Stage 0/1 先例留在 `test/screenshots/`（该目录被 ignore），只在证据里写文件名。
