"""自定义实验「成绩接口」Tab 的动态接入说明渲染（Stage 4）。

纯字符串渲染：不新增表、不写库、不读配置、无副作用。
`GET /api/labs/{id}/integration-spec/` 把当前实验的名称 / 满分 / 上报地址
预填进一段可整段复制给 AI 编程 agent 的 Markdown。

占位符刻意用 `@@NAME@@` 而非 `str.format` / f-string：正文含大量 HTML/JS
花括号（`reportGrade({ total_score })`），`.format()` 会误当格式字段；
`string.Template` 的 `$` 又与 JS 模板字符串 `${}` 冲突。
"""
from decimal import Decimal

# 与 views.GradeReportView / urls.py 的显式 path 保持一致（C22/C43）
GRADE_ENDPOINT = "/api/lab-gate/grade/"


def _fmt_score(value) -> str:
    """Decimal('100.00') -> '100'，Decimal('86.5') -> '86.5'。"""
    d = Decimal(str(value))
    return format(d.normalize(), "f")


# 最小可运行单 HTML：与对接说明 §六同构，且不含任何静态扫描命中写法
# （无 localStorage / cookie / eval / 外链 src / opener / sendBeacon / WebSocket）。
_MIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>我的自定义实验</title>
  <style>
    body { font-family: system-ui, sans-serif; padding: 24px; }
    .task { padding: 10px; margin: 8px 0; border: 1px solid #ddd; border-radius: 8px; }
    button { padding: 8px 20px; font-size: 14px; }
    pre { background: #f6f8fa; padding: 12px; white-space: pre-wrap; }
  </style>
</head>
<body>
  <h1>实验操作区</h1>
  <div id="tasks"></div>
  <button id="finish">完成并提交</button>
  <pre id="log"></pre>

  <script>
  (async function () {
    const log = (m) => { document.getElementById('log').textContent += m + String.fromCharCode(10) }
    const startedAt = Date.now()

    // 预览模式（教师备课）不提交
    if (window.LabBridge && LabBridge.preview) { log('预览模式：不提交成绩'); return }

    // 1. 取实验满分：票据只在平台父页面，iframe 内完全没有
    const ctx = await LabBridge.validate()
    const maxScore = ctx.totalScore

    // 2. 步骤与判分规则全部写在页面内；平台不提供也不接收步骤清单
    const tasks = [
      { title: '任务一', score: 40 },
      { title: '任务二', score: 40 },
      { title: '任务三', score: 20 }
    ]
    const box = document.getElementById('tasks')
    tasks.forEach((t, i) => {
      const div = document.createElement('div')
      div.className = 'task'
      const label = document.createElement('label')
      const cb = document.createElement('input')
      cb.type = 'checkbox'
      cb.dataset.i = String(i)
      label.appendChild(cb)
      label.appendChild(document.createTextNode(' ' + t.title + '（' + t.score + ' 分）'))
      div.appendChild(label)
      box.appendChild(div)
    })

    // 3. 完成即出分：只算一个总分，上限用 ctx.totalScore
    document.getElementById('finish').onclick = async () => {
      let total = 0
      tasks.forEach((t, i) => {
        if (box.querySelector('input[data-i="' + i + '"]').checked) total += t.score
      })
      total = Math.min(Math.round(total * 10) / 10, maxScore)

      // 4. 只调一次 reportGrade；提交时间与正式用时由服务端生成/计算
      const res = await LabBridge.reportGrade({
        total_score: total,
        elapsed_seconds: Math.round((Date.now() - startedAt) / 1000)
      })
      log(JSON.stringify(res, null, 2))
    }
  })()
  </script>
</body>
</html>"""


_AI_PROMPT = """请为我生成一个「单文件 HTML 交互实验页面」，用于上传到智课系统 V2 的自定义实验模块。
硬性要求（必须全部满足，否则平台会拒绝成绩上报）：

1. 单个 .html 文件，所有 CSS/JS 内联，图片用 data URI；不引用任何外部 CDN，
   不写 <base> 标签，不写任何桥接 <script src>（尤其 lab-bridge.js，那是平台预置实验用的）；
   平台会在沙箱 iframe 内注入 lab-bridge-shim.js、在父页面注入 lab-bridge-parent.js。
2. 平台会在沙箱 iframe 内提供 window.LabBridge（由平台注入的 lab-bridge-shim.js 提供，
   票据与真正的上报请求都在平台父页面，iframe 内没有票据）。
   页面启动后先调用 await LabBridge.validate()，从 LabBridge.context 读取 totalScore（实验满分）。
   票据只由平台父页面 lab-bridge-parent.js 的 IIFE 闭包私有持有、代发上报时自动附带，
   window.LabBridge 上没有任何票据属性，页面不需要也不应该接触票据：
   不要读取 location.search、不要存储票据、不要自行拼接 X-Lab-Token。
   若 LabBridge.preview 为 true，只做预览展示，不提交任何成绩。
3. 实验的步骤、每步名称、判分规则全部写在页面内，平台不提供也不接收步骤清单。
   请按下面我描述的实验需求组织交互并逐步判分，最终只算出一个总分。
4. 总分必须在 0 到 @@TOTAL_SCORE@@ 之间，最多保留 1 位小数。
5. 学生点「完成并提交」时，只调用一次：
   await LabBridge.reportGrade({
     total_score: <页面算出的总分>,
     elapsed_seconds: <页面如实统计的实验耗时秒数>
   })
   平台只接收这两个值；提交时间由平台服务端生成，正式用时也由服务端按
   submitted_at - started_at 计算，页面不要传提交时间，也不要为了好看改写用时。
   上报成功后实验即完成，页面显示总分即可；失败时把平台返回的 message 显示出来，
   允许学生重试（失败不会作废票据，也不会锁死 reportGrade 闸门）。
6. 不要上报步骤明细、步骤 key、每步得分等任何额外字段；平台不需要。
7. 页面运行在 sandbox iframe（opaque origin）内：不要读取浏览器存储
   （访问会抛 SecurityError），不要 fetch 平台 /api，不要访问 window.parent /
   window.opener，不要自己发 postMessage；所有平台交互只用 window.LabBridge，
   页面内状态一律用 JS 变量保存。
8. 不引用外部 CDN、不粘贴来源不明的外部代码片段、不要用 eval 动态执行；
   平台会对上传文件做静态扫描（命中浏览器存储访问、外链、动态执行等会标记并
   要求二次确认），留存文件 sha256 与上传者，教师可随时查看已上传源码。

本实验名称与满分：
《@@LAB_TITLE@@》，满分 @@TOTAL_SCORE@@ 分

本实验的交互与判分需求：
[在这里描述你的实验：学生要做什么、每步怎样算对、各步如何给分、总分怎么算]

请直接输出完整可保存为 .html 的代码，不要省略任何部分。"""


_SPEC_TEMPLATE = """# 《@@LAB_TITLE@@》· 自定义实验成绩接入说明

> 本说明由系统按当前实验参数**动态生成**，可整段复制给 AI 编程 agent。
> 实验 ID `@@LAB_ID@@`；页面来源 `custom`（教师上传单 HTML）。

## 1. 实验参数与端点

| 项 | 值 |
| --- | --- |
| 实验名称 | @@LAB_TITLE@@ |
| 实验满分 | **@@TOTAL_SCORE@@ 分**（总分上限，页面判分不得超出） |
| 成绩上报地址 | `POST @@GRADE_ENDPOINT@@` |
| 同源绝对地址 | `@@GRADE_URL@@`（由**平台父页面**代发，教师 HTML 不直接请求） |
| 在线调试端点 | `POST @@DEBUG_ENDPOINT@@`（dry-run，不入库、不消费票据） |
| 接入说明端点 | `GET /api/labs/@@LAB_ID@@/integration-spec/` |

**没有固定密钥、没有 API Key、没有步骤清单要填。** 一次性票据
`X-Lab-Token` 只在平台父页面 `lab-bridge-parent.js` 的 IIFE 闭包里，
由父页面代发上报时自动附带；你的 HTML 编写时和运行时都拿不到，也不需要配置。

## 2. 运行架构（务必先读懂）

学生进入实验时，平台下发**父页面**（HMAC 门控），父页面用
`sandbox="allow-scripts allow-forms allow-modals"` 的 iframe 加载你上传的 HTML，
并在 iframe 内注入 `lab-bridge-shim.js`。iframe 是 **opaque origin**（无 `allow-same-origin`）：

- 读不到 `localStorage` / `sessionStorage` / `document.cookie`（访问抛 `SecurityError`）；
- 不能 `fetch` 平台 `/api/...`（跨域且平台未开放 CORS）；
- 碰不到父页面 DOM / 变量，默认不能导航顶层或开弹窗；
- **允许**内联 `<script>` / `<style>`、表单、`alert` / `confirm` / `prompt`、data URI 图片。

因此分数只能经 `postMessage` 交给父页面代发。**不要自己写 `postMessage`，一律用 `LabBridge`。**

## 3. 页面侧桥接 API（`window.LabBridge`）

| 方法 / 属性 | 说明 |
| --- | --- |
| `LabBridge.preview` | 预览模式为 `true`：跳过 `validate()` 与提交，便于教师备课 |
| `LabBridge.validate()` | 经 `postMessage` 向父页面取回 `context`；必须在取配置前调用 |
| `LabBridge.context` | `{labId, submissionId, totalScore, gradeEndpoint}`，**不含票据** |
| `LabBridge.reportGrade({total_score, elapsed_seconds})` | 经 `postMessage` 交父页面代发 POST；返回平台统一响应；**一次作答只允许成功上报一次**，失败自动解除闸门以便重试 |

## 4. 请求与响应 schema

下面是**平台父页面替你发出**的 HTTP 请求；你的 HTML 只需调 `LabBridge.reportGrade(...)`：

```http
POST @@GRADE_ENDPOINT@@ HTTP/1.1
Host: <平台域名>
Content-Type: application/json
X-Lab-Token: <由平台父页面自动附带，iframe 内页面不接触>
```

请求体**只有两个字段**：

```json
{ "total_score": 86.5, "elapsed_seconds": 742 }
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `total_score` | number | 是 | `0 ~ @@TOTAL_SCORE@@`，最多 1 位小数 |
| `elapsed_seconds` | number | 是 | ≥ 0，页面自报用时秒数；**平台不采信**，仅留痕 |

- **`submitted_at` 由服务端生成，页面不传、传了也忽略**；正式入库用时由服务端按
  `submitted_at - started_at` 计算（S1），页面值只写进 `grade_raw` 供教师对账。
- 不上报步骤明细 / 步骤 key / 每步得分；报文序列化后 ≤ 64KB。
- 越界分数会被拒绝，但**不会作废票据**，学生可修正后重试。

成功响应：

```json
{
  "code": 0,
  "message": "成绩已提交",
  "data": {
    "submission_id": 1234,
    "total_score": 86.5,
    "status": "submitted",
    "submitted_at": "2026-11-05T10:30:00+08:00",
    "graded_at": "2026-11-05T10:30:00+08:00"
  }
}
```

`status: "submitted"` 即代表实验已完成，立即进入学情统计、报告生成与成绩列表。

错误码表（统一 `{code, message, data}`，`code != 0`）：

| 场景 | HTTP | message |
| --- | --- | --- |
| 票据缺失 / 无效 / 已过期 / 已消费 | 401 | 实验票据无效 / 实验票据已过期 / 实验票据已使用 |
| 学籍被暂停或不在班 | 403 | 中文拦截原因 |
| 已提交过 | 400 | 本次实验已提交 |
| 非 custom 实验 | 400 | 该实验不支持页面成绩上报 |
| 实验下线 / 排课窗口已关闭 | 400 | 实验已下线，请联系教师重新上线 / 实验已截止，无法提交 |
| 总分越界 / 小数位过多 / 格式错 | 400 | 成绩超出实验总分范围（0 ~ @@TOTAL_SCORE@@）/ 总成绩最多保留 1 位小数 / 总成绩格式不正确 |
| 缺总成绩 / 报文格式或大小非法 | 400 | 缺少总成绩 / 上报内容格式不正确 / 上报内容过大（超过 64KB） |
| 用时非法 | 400 | 用时格式不正确 / 用时不能为负 |
| 票据与作答不匹配 | 400 | 票据与作答不匹配 |
| 触发限流 | 429 | 提交过于频繁，请稍后重试 |

**重试语义**：任一失败都不写成绩、不作废票据，可直接重试；上报成功才消费票据，
之后不可再提交（自定义实验默认不允许重做）。

## 5. 最小可运行示例（单 HTML，可直接改名上传）

```html
@@MIN_HTML@@
```

要点只有三个：**只算一个总分**、**以 `ctx.totalScore` 为上限**、**只调一次 `reportGrade`**。

## 6. 上传 HTML 的硬性要求

| 要求 | 原因 |
| --- | --- |
| 单文件，内联 `<style>` / `<script>`，图片用 data URI | 平台注入的 `<base>` 指向签名资产路由，你自己的相对路径资源取不到 |
| 不引用外部 CDN、不写 `<base>`、不写任何桥接 `<script src>` | CSP 会拦外链脚本；已有 `<base>` 会被剥离；桥接由平台注入，已存在则跳过 |
| 不读浏览器存储、不 `fetch` 平台 `/api`、不碰 `window.parent` / `window.opener`、不用 `eval` | opaque origin 下运行时必失败；上传时静态扫描会命中并标记，要求二次确认且通知管理员 |
| 预览模式不提交 | `LabBridge.preview === true` 时跳过 `validate()` 与上报 |

**不需要**：步骤清单配置、CORS、https 证书、公网 IP/域名、独立源/DNS、API Key、任何后端服务。

## 7. 可直接复制给 AI 编程 agent 的指令

```text
@@AI_PROMPT@@
```
"""


def build_integration_spec(lab, absolute_grade_url=None) -> dict:
    """按实验参数渲染接入说明。纯渲染，不写库。

    :param lab: `Lab` 实例
    :param absolute_grade_url: 可选，由视图用 `request.build_absolute_uri()` 生成的同源绝对地址
    """
    score = _fmt_score(lab.total_score)
    replacements = {
        "@@LAB_TITLE@@": str(lab.title or ""),
        "@@LAB_ID@@": str(lab.id),
        "@@TOTAL_SCORE@@": score,
        "@@GRADE_ENDPOINT@@": GRADE_ENDPOINT,
        "@@GRADE_URL@@": absolute_grade_url or ("<平台域名>" + GRADE_ENDPOINT),
        "@@DEBUG_ENDPOINT@@": f"/api/labs/{lab.id}/grade-debug/",
        "@@MIN_HTML@@": _MIN_HTML,
        "@@AI_PROMPT@@": _AI_PROMPT,
    }
    markdown = _SPEC_TEMPLATE
    # 多轮展开：`@@MIN_HTML@@` / `@@AI_PROMPT@@` 的替换值里本身还带
    # `@@TOTAL_SCORE@@` / `@@LAB_TITLE@@` 等占位符，单轮按序 replace 会留下
    # 未展开的 `@@...@@`。循环到无残留为止（最多 3 轮防死循环）。
    for _ in range(3):
        for key, value in replacements.items():
            markdown = markdown.replace(key, value)
        if "@@" not in markdown:
            break
    return {
        "lab_id": lab.id,
        "lab_title": str(lab.title or ""),
        "total_score": score,
        "grade_endpoint": GRADE_ENDPOINT,
        "grade_debug_endpoint": f"/api/labs/{lab.id}/grade-debug/",
        "markdown": markdown,
    }
