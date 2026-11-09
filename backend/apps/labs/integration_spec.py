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
_AI_PROMPT = """请为我开发一个智课平台的自定义实验页面，交付物是单个 HTML 文件
（所有 CSS/JS/图片内联，不引用外部资源、不使用 eval）。

实验主题与判分需求：
[在这里描述你的实验：学生要做什么、分几步、每步怎样算对、总分怎么算。
推荐写成场景化操作 + 明确计分，例如：
『十进制与二进制转换练习：学生拨动 8 位二进制开关构造指定十进制值，
共 5 关每关 20 分，构造正确并确认本关得分，全部通关得满分。』]

实验呈现要求（重要——这是虚拟实验，不是答题问卷）：
1. 页面必须有一个「实验场景区」：用 SVG 或 Canvas 绘制与主题相关的可视化场景
   （如网络拓扑图、实验装置、流程示意），标注设备/元件名称与当前状态。
2. 学生的每一步操作都要与场景联动：点击设备/元件进行配置或操作，场景状态实时变化，
   关键过程用动画呈现（如数据包沿链路流动、信号传播、逐步装配，用 CSS/SVG 动画实现）。
3. 判分基于学生在场景中的操作结果（如配置是否正确、目标是否达成），
   可以辅以少量输入题，但纯选择/填空题不应超过总分的一半。

硬性要求：
1. 平台会在沙箱 iframe 内注入 window.LabBridge。页面启动后先 `await LabBridge.validate()`
   读取满分（ctx.totalScore，不要写死）；若 LabBridge.preview === true 表示教师预览，只展示不提交。
2. 学生完成操作后，页面自行判分并只调用一次：
   await LabBridge.reportGrade({ total_score: <总分>, elapsed_seconds: <用时秒> })
   total_score 在 0 ~ @@TOTAL_SCORE@@ 之间、最多 1 位小数；平台只接收这两个字段；
   失败时把返回的 message 展示给学生并允许重试；同一学生多次提交平台只保留最高分。
   上报成功后：停止计时、锁定所有作答交互，页面只展示最终结果与成绩，
   不要再改变计时器读数或允许继续作答。
3. 禁止访问 localStorage/sessionStorage/cookie、fetch 平台 /api、触碰 window.parent/opener；
   票据由平台父页面自动附带，页面不要读取 location.search 或拼接任何 token。

实验名称：《@@LAB_TITLE@@》，满分 @@TOTAL_SCORE@@ 分。
请直接输出完整 HTML 文件内容。"""
_SPEC_TEMPLATE = """# 「@@LAB_TITLE@@」实验页面接入说明

## 1. 你的任务
开发一个**单文件 HTML** 实验页面（所有 JS / CSS / 图片内联，不引用外部资源），
嵌入本平台沙箱内运行：学生在页面里完成实验操作，页面自行判分并上报**一个总分**，
平台负责记录成绩、统计与报告。

- 实验名称：@@LAB_TITLE@@
- 实验满分：**@@TOTAL_SCORE@@** 分（页面内从 LabBridge 读取，不要写死）
- 成绩上报：`POST @@GRADE_URL@@`（同源，由平台父页面代发，页面不直接调用）
- 在线调试：`@@DEBUG_ENDPOINT@@`（dry-run，不入库）

## 2. 与平台交互（window.LabBridge）
页面运行在沙箱 iframe（`sandbox="allow-scripts allow-forms allow-modals"`，无 allow-same-origin）内，
读不到票据与平台数据——票据由平台父页面在正式上报时自动附带，iframe 内页面不接触票据，
无需配置任何密钥。平台会在页面内注入 `window.LabBridge`，只有三个用法：

```js
if (LabBridge.preview) { /* 教师预览模式：只展示，不提交 */ }
const ctx = await LabBridge.validate();
// ctx = { labId, submissionId, totalScore, gradeEndpoint } → 满分用 ctx.totalScore
const res = await LabBridge.reportGrade({
  total_score: 88.5,      // 0 ~ 满分，最多 1 位小数；同一学生多次提交只保留最高分
  elapsed_seconds: 123,   // 只留痕，正式用时由服务端计算
});
// res = { code, message, submission_id, total_score }，把结果展示给学生即可
```

常见失败响应（把 message 展示给学生即可，失败可重试）：
`本次实验已提交` · `成绩超出实验总分范围` · `实验票据已使用` · `提交过于频繁`

## 3. 硬性约束
- **只上报总分与用时**两个字段，不要步骤明细等其他字段；提交时间与正式用时由服务端生成。
- 禁止访问 localStorage / sessionStorage / cookie，禁止 fetch 平台 /api，
  禁止触碰 window.parent / window.opener，禁止 eval（沙箱内必失败，静态扫描会拦截）。

## 4. 可直接复制给 AI 编程 agent 的指令

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
        "@@AI_PROMPT@@": _AI_PROMPT,
    }
    markdown = _SPEC_TEMPLATE
    # 多轮展开：`@@AI_PROMPT@@` 的替换值里本身还带
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
