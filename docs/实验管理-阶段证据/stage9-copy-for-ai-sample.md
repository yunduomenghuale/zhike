# 「提示词实测1794191002」实验页面接入说明

## 1. 你的任务
开发一个**单文件 HTML** 实验页面（所有 JS / CSS / 图片内联，不引用外部资源），
嵌入本平台沙箱内运行：学生在页面里完成实验操作，页面自行判分并上报**一个总分**，
平台负责记录成绩、统计与报告。

- 实验名称：提示词实测1794191002
- 实验满分：**100** 分（页面内从 LabBridge 读取，不要写死）
- 成绩上报：`POST http://127.0.0.1:8005/api/lab-gate/grade/`（同源，由平台父页面代发，页面不直接调用）
- 在线调试：`/api/labs/150/grade-debug/`（dry-run，不入库）

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
请为我开发一个智课平台的自定义实验页面，交付物是单个 HTML 文件
（所有 CSS/JS/图片内联，不引用外部资源、不使用 eval）。

实验主题与判分需求：
[在这里描述你的实验：学生要做什么、分几步、每步怎样算对、总分怎么算]

硬性要求：
1. 平台会在沙箱 iframe 内注入 window.LabBridge。页面启动后先 `await LabBridge.validate()`
   读取满分（ctx.totalScore，不要写死）；若 LabBridge.preview === true 表示教师预览，只展示不提交。
2. 学生完成操作后，页面自行判分并只调用一次：
   await LabBridge.reportGrade({ total_score: <总分>, elapsed_seconds: <用时秒> })
   total_score 在 0 ~ 100 之间、最多 1 位小数；平台只接收这两个字段；
   失败时把返回的 message 展示给学生并允许重试；同一学生多次提交平台只保留最高分。
3. 禁止访问 localStorage/sessionStorage/cookie、fetch 平台 /api、触碰 window.parent/opener；
   票据由平台父页面自动附带，页面不要读取 location.search 或拼接任何 token。

实验名称：《提示词实测1794191002》，满分 100 分。
请直接输出完整 HTML 文件内容。
```
