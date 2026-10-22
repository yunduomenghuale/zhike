# AI 学情分析深化 与 章节学习 AI 总结 — 设计方案

> 版本：v1.2（已评审定稿 + 第二轮细节排查修正） · 2026-10-22
> 范围：教师端「课程-学习统计-AI 学情分析」改造；新增学生端「章节学习完成 AI 总结」
> 评审结论：D1~D8 已全部按建议决策定稿（D6 默认仅分析有数据学生，无数据学生标记不纳入分析），详见 §9.1
> 排查结论：v1.2 已完成第二轮方案细节排查（14 项，含 4 项必须修：学生端成绩门控/幂等约束矛盾/线程上下文丢失/分析超时口径），修正已全部落进正文，详见 §10
> 关联代码：`apps/analytics/`（views/services）、`apps/ai/`（services/models/calllog/providers）、`apps/courses/views.py`（report_progress）、`frontend/src/views/teacher/Analytics.vue`、`frontend/src/views/student/Learning.vue`

---

## 一、现状诊断：为什么"处理时间长，结果却浅"

### 1.1 现有链路

```
教师点击「生成分析报告」
  → POST /api/analytics/class/<id>/ai-report/   （analytics/views.py: ClassAIReportView）
    → build_class_stats()                        （同步 SQL 聚合，秒级）
    → analyze_class_stats(stats)                 （ai/services.py:1920）
      → provider.chat(messages)                  【单次同步 LLM 调用，整个 HTTP 请求挂起等待】
    → 返回 {report, comments}
  → 前端 el-skeleton 干等，无进度、无取消、刷新即丢
```

### 1.2 三个根因（按贡献排序）

| # | 根因 | 位置 | 后果 |
|---|------|------|------|
| 1 | **Prompt 自我限制输出长度**：明确要求 overview「200~350 字」、逐学生简评「不超过 50 字」 | `ai/services.py:1978-1979` | 单次响应 token 预算被压死，报告必然简短——这是"深度不够"的**直接原因**。当初是为控制单次同步调用的等待时间而做的妥协 |
| 2 | **单次同步调用 + 单次 LLM 请求**：请求线程内阻塞等待一次完整响应 | `analytics/views.py:79`、`ai/services.py:1997` | 网关/浏览器超时风险；用户体感"处理时间长"却只等到一篇短文，投入产出比差；失败无重试、刷新即丢失 |
| 3 | **输入只有聚合指标，没有任何明细数据**：喂给 LLM 的仅 accuracy、提交数、缺交名单、未学习天数 | `ai/services.py:1954-1991` | 没有错题、没有知识点维度、没有提问内容、没有时间趋势——LLM 再强也只能"复读统计数字"，无法做知识点归因和个性化归因，分析强度上不去 |

补充观察：

- `build_class_stats()` 已算出 `homework_missing / exam_missing / lab_missing` 等名单，但**没有任何一处查询学生的错题明细**（`AnswerRecord.is_correct=False` 的题干/答案/解析）、`QARecord` 提问、`WrongNote/WrongMastery`。
- 学生维度已有 `ClassStudentDetailView` 的章节覆盖/正确率矩阵思路（`analytics/views.py:187-251`），但学情分析报告完全没用上。
- 无持久化：报告不落库，换班级/刷新即丢，无历史、无计量归属（AICallLog 有 ANALYTICS 场景，但业务侧无产物留存）。
- Mock 模式下同样同步返回，演示时也要干等。

### 1.3 改造目标

1. **时长问题**：分析全过程异步化，请求秒级返回，进度可见、可离开页面、断线重连后恢复。
2. **深度问题**：输入侧补明细数据（错题/知识点/提问/趋势），输出侧放开字数并改用**分段生成 + 分批并发**，班级整体报告 800~1500 字结构化 markdown，逐学生简评 120~200 字。
3. **覆盖口径**：默认仅分析有数据学生；无数据学生单独标记、不纳入分析与分层（D6 定稿）。
4. **新功能**：学生完成章节学习时，自动生成章节 AI 总结（薄弱知识点 + 提升建议），融合提问、练习、作业、考试、实验、错题全维度数据。

---

## 二、总体架构：共享异步 AI 任务框架

两个功能共性是「**数据聚合（纯 SQL）→ 多轮 LLM 调用 → 产物持久化 + 进度轮询**」，先建一个通用任务层，避免两套轮子。

### 2.1 新增模型 `AITask`（apps/ai/models.py）

```python
class AITask(BaseModel):
    class TaskType(models.TextChoices):
        CLASS_ANALYTICS = "class_analytics", "班级学情分析"
        CHAPTER_SUMMARY = "chapter_summary", "章节学习总结"

    class Status(models.TextChoices):
        PENDING  = "pending",  "排队中"
        RUNNING  = "running",  "进行中"
        SUCCESS  = "success",  "已完成"
        FAILED   = "failed",   "失败"

    task_type     = models.CharField(max_length=24, choices=TaskType.choices, db_index=True)
    status        = models.CharField(max_length=16, choices=Status.choices, default=PENDING, db_index=True)
    version       = models.IntegerField("版本", default=1)   # 章节总结 force 重试递增进；班级分析恒为 1
    progress      = models.JSONField(default=dict)   # {"stage":"...","done":n,"total":n,"message":"..."}
    result        = models.JSONField(default=dict)   # 最终产物（报告/总结）
    error         = models.CharField(max_length=300, blank=True)
    # 业务关联（按 task_type 使用其中一两个，均允许为空）
    course        = FK(Course, null=True)
    classroom     = FK(ClassRoom, null=True)
    catalog       = FK(Catalog, null=True)
    student       = FK(User, null=True)              # 章节总结：总结对象学生
    triggered_by  = FK(User, null=True)              # 触发人（教师/学生本人）
    started_at / finished_at = models.DateTimeField(null=True)
```

要点：
- **进度持久化在行上**，与 `PPTResource.parse_progress` 现成模式一致（前端轮询资源即可），服务重启不丢。
- 每阶段更新 `progress` 用 `queryset.update()` 或 `save(update_fields=[...])`，**避免整行并发写覆盖**（分段生成由单线程顺序执行，问题不大；学生简评批的结果由主线程统一合并，同样顺序写）。
- **幂等设计（F2 排查修正）**：不建 (task_type, student, catalog) 全局唯一约束——与「force 重新生成新建一版」冲突。改为：① 代码级幂等，自动触发时已有 PENDING/RUNNING/SUCCESS 记录则跳过；② 增加 `version` 整数字段（同 student+catalog 递增进，查询取最大版本）；③ 可选加部分唯一索引 `UniqueConstraint(fields=["task_type","student","catalog"], condition=Q(status__in=["pending","running"]))` 防并发双跑（SQLite 支持部分索引）。班级分析同理：不建唯一约束，用 DB 判定频率限制（见 §7）。

### 2.2 任务执行器 `apps/ai/tasks.py`

```python
def submit_ai_task(task_type, *, user=None, **biz_fields) -> AITask:
    """建任务记录（PENDING）并拉起 daemon 线程执行。"""
    task = AITask.objects.create(task_type=task_type, status=PENDING, triggered_by=user, **biz_fields)
    ctx = copy_call_context()          # F3：提交时复制请求上下文（触发人/请求引用）
    threading.Thread(target=_run_task, args=(task.id, ctx), daemon=True).start()
    return task

def _run_task(task_id, ctx):
    from django.db import close_old_connections
    close_old_connections()            # F11：daemon 线程入口清理残留连接
    task = AITask.objects.get(id=task_id)
    ...  # 切 RUNNING，整个 pipeline 经 run_in_context(ctx, pipeline) 执行，except 落 error + FAILED
```

执行体按 `task_type` 分发到 `run_class_analytics(task)` / `run_chapter_summary(task)`（放 `apps/ai/analytics_ai.py`，避免 services.py 已 91KB 继续膨胀；分发 import 放在 `_run_task` 内部懒加载，防环）。

**必须复用的现成机制**（照抄讲稿分批的写法，`ai/services.py:161-181`）：
- **外层线程上下文（F3 排查修正）**：`threading.Thread` 不继承 contextvars，若直接跑 pipeline，`_current_user`/`_request_ref` 全丢，AICallLog 的 triggered_by 为空。修法：提交时 `copy_call_context()` 带进线程，`_run_task` 内 `run_in_context(ctx, pipeline)`；pipeline 在线程内进入 `ai_scene(Scene.XXX, course_id=...)` 生成 trace_id。
- `run_in_context(copy_call_context(), fn, ...)`：S2 线程池同样不继承上下文，提交时再复制一次（此时已含 trace_id/触发人）带进 worker，否则并发批次的 AICallLog 丢场景归属。
- `@scene_decorator(AICallLog.Scene.XXX)`：新增场景值 `CHAPTER_SUMMARY = "chapter_summary", "章节学习总结"`（ai/models.py:182 的 Scene 枚举加一项 + migration）；班级分析沿用 `ANALYTICS`。
- 超时口径（F4 排查修正）：分析类调用输入长（约 6k tokens）、输出长，复用 `AI_SCRIPT_TIMEOUT`（默认 45s）在本地模型上易整段超时。新增 `AI_ANALYTICS_TIMEOUT`（settings.py:355 旁，默认 120s，env 可调），分析链路超时 = 管理端该能力 timeout → `AI_ANALYTICS_TIMEOUT` → 120。
- Mock 兜底：两个任务在 mock provider 下走确定性假数据（见 §7），保证无 Key 环境可演示全流程。

**并发保护**：全局 `threading.BoundedSemaphore(2)` 限制同时运行的分析任务数（LLM 端 QPS 有限），超限任务保持 PENDING，由前端轮询自然排队；worker 结束时 release。**不上 Celery**——当前无任务队列基础设施（requirements 无 celery），单机 daemon 线程 + 进度轮询与项目现有形态一致；规模化（多 worker/多机）后再议，届时把 `_run_task` 换成队列 consumer 即可，接口不变。

### 2.3 轮询端点（通用）

```
POST /api/ai-tasks/                  # 通用提交（body: task_type + 业务参数）——可选，优先用业务端点提交
GET  /api/ai-tasks/<id>/             # {status, progress, result, error} —— 前端 2.5s 轮询（与讲稿生成同款）
```

教师端/学生端业务端点内部调用 `submit_ai_task`，返回 `{task_id}`；前端拿 task_id 轮询通用端点。

**任务可见性规则（F7 排查补充，可执行判定）**：满足任一即放行，否则 404（不暴露存在性）：
1. `task.triggered_by == request.user`（发起人本人）；
2. `task.classroom and task.classroom.teacher == request.user`（班级归属教师）；
3. `task.catalog` 场景：`task.course.teacher == request.user` 或 `task.student == request.user`（总结对象学生本人）；
4. 平台管理员（`is_platform_admin`）。

---

## 三、方案 A：教师端学情分析改造（异步 + 多阶段深度分析）

### 3.1 流水线总览

```
POST /api/analytics/class/<id>/ai-report/     【改造后：秒级返回 {task_id}】
  └─ AITask(class_analytics) → 后台线程：
       S0 数据聚合 build_class_stats_v2()            ~2s    纯 SQL
       S1 班级整体深度报告（3 段顺序生成）            3×20-40s
       S2 逐学生深度简评（分批 4-6 人/批，3-4 并发） 50人≈75s
       S3 汇总落库 → status=SUCCESS
前端 2.5s 轮询 /api/ai-tasks/<id>/，展示阶段进度；完成后渲染报告 + 学生卡片简评
```

50 人班级全程约 **2~4 分钟**（取决于模型），但用户**无感等待**：进度条按阶段推进，可随时离开。

### 3.2 S0：数据聚合增强 `build_class_stats_v2()`（analytics/services.py 扩展）

保留现有全部字段（前端学生卡片在用），**新增**以下喂给 LLD 的维度：

| 新增数据 | 来源 | 用途 |
|----------|------|------|
| 章节正确率矩阵 | `AnswerRecord(scene=PRACTICE)` 按 `question__catalog` 聚合（复用 `ClassStudentDetailView:187-251` 的 root 归属逻辑） | 知识点薄弱定位到具体章节 |
| 学生错题 TOP N | `AnswerRecord(is_correct=False)` → 题干(截80字)/学生答案/正确答案/解析(截120字)/`knowledge_tags` | 薄弱知识点证据链；每生最多 8 条 |
| 知识点聚合 | 代码侧按 `knowledge_tags` 预聚合（班级级：tag→错题数/总题数） | **纯计算先归因，AI 只解读**——省 token、控时长、口径稳 |
| 作业得分明细 | `HomeworkAnswer.score` vs `HomeworkQuestion.snapshot`（stem/tags 展示）；**章节归属过滤走 `homework_question__question__catalog_id` 实时 join，不用 snapshot JSON key 查**（F9：老数据可能缺 snapshot，SQLite JSON key 查询不稳） | 作业维度薄弱点 |
| 考试得分明细 | `ExamSubmission.answers`/`subjective_scores` 对比 `Paper.question_items`（注意：考试未快照读实时 Question，发布后改题会影响口径——已知债，分析时以提交时 answers 为准） | 考试维度薄弱点 |
| 实验得分 | `LabSubmission.total_score / score_breakdown / reviewed` | 实验维度 |
| 提问热度 | `QARecord` 按 catalog 聚合条数 + 高频问题原文（截断）+ `feedback=-1` 点名 | 理解障碍信号（学生问什么，往往就是不会什么） |
| 学习行为 | `VideoWatchProgress.watch_seconds/status` 按 catalog | 投入度维度 |
| 时间趋势 | 近 7/30 天 `AnswerRecord.submitted_at` 分布 | 持续性/下滑预警 |

**无数据学生口径（D6 定稿）**：默认仅分析有数据学生。「有数据」判定 = 该生在本课程存在任一行为记录：章节练习（AnswerRecord）、作业提交、考试提交、实验提交、问答记录（QARecord）、视频学习进度（VideoWatchProgress）——六者全无即无数据。实现上每条 `students` 行增加 `has_data` 布尔标记（同步 SQL 聚合即可判定，零额外成本）：

- 无数据学生：`has_data=false`，前端卡片展示「暂无学习数据」徽标，**不生成 AI 简评、不进分层、不进 S2 分批队列**；其 id+姓名单独汇入 `no_data_students` 名单交给 LLM，仅在报告中一句话说明数量（如「另有 3 名学生暂无学习数据，未纳入本次分析」）。
- 有数据学生：全量进入 S1/S2。注意「有数据但长期不活跃」（如 30 天前做过练习）仍属有数据，正常分析并由预警规则覆盖。

聚合全部走现有索引可覆盖的查询（`question__course_id`、`student`、`catalog_id`），50 人班级预计 < 3s。**输入裁剪硬规则**：错题条数上限、题干/解析截断、提问条数上限——按 token 预算倒推（班级报告 prompt 控制在 6k tokens 内）。

### 3.3 S1：班级整体深度报告（分段顺序生成）

**为什么分段**：单次要求 1500 字结构化 markdown，容易触到模型输出上限被截断（JSON 破损→整体失败）；分 3 段、每段带前文摘要续写，质量与成功率都更稳。三段：

| 段 | 内容 | 字数 |
|---|------|------|
| R1 整体学情 + 知识点掌握分析 | 数据引用准确的概况；薄弱/扎实知识点清单（吃 S0 的 tag 聚合结果）；班级共性误区 | 400~600 |
| R2 学生分层画像 + 风险预警 | 领先/稳定/风险三层名单与特征；逐条预警（谁、什么问题、证据） | 400~600 |
| R3 教学干预建议 + 下阶段重点 | 可执行建议（落到章节/作业/考试名称）；下阶段教学重点 | 300~500 |

prompt 输入：R1 只传 `no_data_students` 的**数量**（不传名单），要求概况里一句话说明「N 名学生暂无学习数据，未纳入分析」；R2/R3 的分层与建议仅基于有数据学生。每段独立 `provider.chat()` 调用、独立 JSON schema 校验（`_safe_json` 兜底），**单段失败重试一次，再失败该段降级为统计数字拼装**（保证报告永远完整可用）。三段顺序执行（后段要前文摘要），全程写入 `task.progress`（如 `{"stage":"report","done":1,"total":3,"message":"正在生成整体学情与知识点分析"}`）。

### 3.4 S2：逐学生深度简评（分批并发）

- **仅对有数据学生生成简评**（`has_data=true`）：无数据学生不进分批队列、不消耗调用；每生输入 = 个人明细 + 个人错题 top8（含知识点）+ 个人高频提问 top5 + 章节覆盖矩阵 + 缺交/缺考名单。
- **批大小 4~6 人/批**（prompt 总量可控），`ThreadPoolExecutor(max_workers=min(4, 批数))`，批间顺序、批内并发——与讲稿 `AI_SCRIPT_CHUNK_PAGES=3` 小块并发同款思路。
- 每生输出 120~200 字：表现概括 → 薄弱点（具体知识点/任务名称）→ 教师可采取的行动（沿用现有第三人称、禁空话的 prompt 约束，`ai/services.py:1980-1984`，把 50 字上限放开到 120~200）。
- 单批失败：该批学生简评留空并在报告尾部注明「N 名学生简评生成失败，可重试」，不拖垮整体。
- 进度：`{"stage":"students","done":x,"total":有数据学生数,"message":"正在生成学生简评 x/N"}`（N = analyzed_count，F10 排查修正），主线程 `as_completed` 增量合并写 `task.result`——**刷新页面后轮询能看到简评一条条长出**（与讲稿分批落库体验一致）。

### 3.5 输出 schema 与存储

```python
task.result = {
  "report": "## 整体学情\n...## 知识点掌握分析\n...## 学生分层\n...## 风险预警\n...## 教学建议\n...",  # 三段合并的 markdown
  "report_sections": {"overview": "...", "knowledge": "...", "layers": "...", "warnings": "...", "advice": "..."},
  "comments": {student_id: "120-200字简评"},          # 仅覆盖有数据学生
  "no_data_students": [{"student_id": 1, "name": "张三"}],  # 无数据学生名单（报告一句话说明，不分析）
  "stats_snapshot": {...build_class_stats_v2 的汇总部分（含 analyzed_count / no_data_count）...},
  "generated_at": "...",
}
```

- 前端渲染沿用 `renderAiMarkdown`（`utils/markdown.js`），学生卡片简评区样式不动（`Analytics.vue:115-119`）。
- **旧同步接口直接切换删除**（D5 定稿）：`ClassAIReportView.post` 只返回 `{task_id}`，老同步逻辑与前端干等分支一并移除，不保留双轨。

### 3.6 边界情况（F5 排查补充）

- **全班无数据**（analyzed_count == 0）：pipeline 检测后**跳过全部 LLM 调用**，`result.report` 固定文案「本班学生暂无学习数据（无练习/作业/考试/实验/问答/学习记录），暂无法生成学情分析」，status 直接 SUCCESS，进度瞬间到完成——前端流程不变，不白发调用。
- **有数据学生为 0 但缺交名单非空**：不适用（缺交以有提交记录为前提的补漏场景由预警规则覆盖）。
- **单段/单批全部失败**：报告仍产出（降级拼装 + 尾部注明），`status=SUCCESS` 但 `result.degraded=true`，前端在报告角标「部分内容生成失败，可重新生成」。

---

## 四、方案 B：学生端章节学习 AI 总结

### 4.1 触发时机

| 触发 | 入口 | 说明 |
|------|------|------|
| **自动（主）** | `report_progress` 接口内（`courses/views.py:601-664`）检测 `completed=true` | 视频连播结束/手动标记完成时，后端 `submit_ai_task(CHAPTER_SUMMARY, student=request.user, catalog=video.catalog, course=video.course)`，**异步不阻塞**进度上报响应；幂等：已有 PENDING/RUNNING/SUCCESS 记录则跳过（含重看重复触发）；上一次 FAILED 时允许再次提交 |
| 手动（辅） | 学生端章节行「AI 总结」按钮 → `POST /api/analytics/chapter-summaries/` | 已有成功记录时返回旧的；带 `force=1` 时**新建一版**（version+1，查询取最大版本，保留历史对比——F2 排查修正，不再依赖唯一约束） |

**"章节完成"的定义**（D2 定稿）：以 `VideoWatchProgress.status=COMPLETED` 为准（现有唯一完成态信号）。总结中如实呈现各维度完成度——视频看完了但练习没做，总结会明确说"本章练习尚未完成"，反而更有导读价值。

**响应兼容（F13 排查补充）**：`report_progress` 响应（`api_response(serializer.data, ...)`）中加性字段 `summary_task_id`（自动提交了任务时非空）。移动端 `app/src/api/course.js` 也调该端点，加性字段旧版忽略即可，无兼容风险；移动端「总结生成中」提示列 P3 跟进。

### 4.2 数据采集 `build_chapter_profile(student, catalog, *, for_student)`（新增，analytics/services.py）

```python
# 签名带可见性口径：教师端调用 for_student=False（看全量）；学生端总结 for_student=True
def build_chapter_profile(student, catalog, *, for_student: bool) -> dict:
    return {
  "chapter": {"title": "...", "course": "..."},
  "learning": {"watch_seconds": 1234, "pages_watched": "8/10", "completed_at": "..."},
  "practice": {  # 章节练习（AnswerRecord scene=PRACTICE, question__catalog=本章）
     "total": 10, "correct": 6, "accuracy": 60,
     "wrong": [{"stem": "...", "my_answer": "...", "correct_answer": "...",
                "analysis": "...", "knowledge_tags": [...], "difficulty": "..."}]  # 最多8条，截断
  },
  "homework": [{"title": "...", "score": 18, "total_score": 20, "rate": 90,
                "wrong_points": [{"stem":"...", "knowledge_tags":[...]}]}],
     # 章节归属：homework_question__question__catalog_id 实时 join（F9）；snapshot 仅作展示
  "exams":    [{"name": "...", "score": 82, "wrong_points": [...]}],
     # 逐题对错复用 apps/exams/resolver.py 的 build_for_review(paper, submission, exam)
     # （已处理乱序选项映射 unmap_student_answer 与 layout）+ score_for_item（F8）——禁止自行比对 answers
  "labs":     [{"title": "...", "total_score": 88, "comment": "教师评语"}],
  "qa":       {"count": 5, "questions": ["..."], "disliked": ["反馈'无用'的问题"]},
  "wrong_book": {"mastered": 2, "pending": 3},   # WrongMastery / WrongNote（见数据缺口 D3）
  "knowledge_agg": [{"tag": "递归", "wrong": 3, "total": 5, "rate": 40}],  # 代码侧预聚合
  "visibility": {"homework_pending_release": 1, "exam_pending_release": 1},
     # for_student=True 时未发布成绩的计数（总结中表述为"成绩尚未发布"，不透露分值）
    }
```

**成绩可见性门控（F1 排查修正，必须实现）**：章节总结是**学生-facing 产物**，而成绩发布有门控——作业 `correct_status=returned`、考试 `score_released` 之后学生才可见分数（`homework/serializers.py:254-270/308-322`、`exams/views.py:528`）。规则：
- `for_student=True`：作业只纳入 `correct_status=RETURNED` 的提交的分数/评语；考试只纳入 `score_released=True` 的分数；未发布的在 `visibility` 计数、总结表述为「成绩尚未发布」，**不得把分值/批改写进 prompt 或产物**；实验分数提交即出分无门控（labs 模型注释），可直接用。
- 客观题的答案/解析学生提交后即可见（serializers.py:247-248 注释），练习错题证据不受门控。
- `for_student=False`（教师端班级分析/教师看学生总结）：看全量，不受门控。

**数据缺口 D3（已定稿）**：`WrongNote`（学生手动错题）**没有 catalog 字段**（只有 course），无法按章节归属。**决策：给 `WrongNote` 加 `catalog` 可空 FK + 录入时选章节（P2 顺带做，约半小时工作量）；历史数据留空，总结中按课程级纳入**（不做题干模糊匹配，不可靠）。

### 4.3 生成逻辑（单轮，1 次 LLM 调用）

章节总结输入量小（单人单章），**不需要分段**：一次调用 + 严格 JSON schema。系统 prompt 角色：「学生的学习督导」，强调：
- **重点 = 知识点薄弱环节 + 学习提升**（用户明确要求）；
- 所有结论必须引用具体证据（"练习中'递归终止条件'3 题错 2"）；
- 提问内容用于推断理解障碍（"询问了 X，反映对 Y 的机制不清晰"），**不得暴露或嘲讽学生的提问**，口吻鼓励、具体；
- 输出结构化 JSON：

```json
{
  "overview": "本章学习总体情况（150-250字，引用学习行为+各维度数据）",
  "knowledge_points": [
    {"name": "递归终止条件", "status": "weak", "evidence": "练习 2/5 错，作业第3题错"}
  ],
  "weak_points": ["薄弱点（按严重度排序，最多3条）"],
  "highlights": ["掌握较好的知识点/行为亮点"],
  "qa_insight": "从提问反映的理解障碍（无提问则略过）",
  "suggestions": ["具体提升动作：重看第X页讲解、重练Y知识点、完成Z作业/实验"],
  "next_step": "一句话下一步行动指引"
}
```

- `knowledge_agg`（代码预聚合）直接嵌进 prompt，让 LLM **只做归因解读与建议生成**，不承担统计——token 省、时长稳（单次 20-40s）、口径与看板一致。
- Mock 模式：按 `knowledge_agg` 拼一段确定性假总结（含 weak_points/suggestions 骨架），演示可用。
- 失败重试一次 → 仍失败落 `error`，学生端提示"总结生成失败，可稍后重试"，不阻塞学习流程。

### 4.4 模型与 API

数据存 `AITask(task_type=chapter_summary, student=..., catalog=..., version=N, result=上述JSON)`——**不新建业务表**，章节总结即任务产物，天然带进度/时间/触发人/版本。查询即按 (student, catalog) 过滤 task 表、取 version 最大的 SUCCESS 记录。

```
# 统一挂 apps/analytics/urls.py（F12：不新建 app 路由，与 ai-tasks 分离，权限风格一致）
# 学生端（IsStudent）
POST /api/analytics/chapter-summaries/                  body: {course_id, catalog_id, force?}  → {task_id} 或 {task_id, cached:true}
GET  /api/analytics/chapter-summaries/?course_id=&catalog_id=   → 本人最新成功版本（含 result）

# 教师端（P3，IsTeacher）：查看班级学生的章节总结，作为学情分析的细粒度输入
GET  /api/analytics/class/<id>/chapter-summaries/?catalog_id=   → 班级学生本章总结列表（for_student=False 全量口径）

# 通用轮询
GET  /api/ai-tasks/<id>/                → 轮询进度（2.5s）
```

权限：学生只能看自己的；教师可看自己班级学生的（`courses_for_user` 口径校验）。

---

## 五、前端交互设计

### 5.1 教师端 Analytics.vue（改造）

```
[生成分析报告] 点击
  → POST 拿 {task_id}，按钮转 loading，AI 卡片展示阶段进度（轮询 2.5s）：
      正在聚合班级学习数据…            （S0）
      正在生成整体学情与知识点分析（1/3）… （S1）
      正在生成学生简评（12/48）…        （S2，数字实时涨）
      分析完成 ✓
  → 渲染 report（renderAiMarkdown，现有样式）；学生卡片逐条填充简评；`has_data=false` 的卡片展示「暂无学习数据」徽标、不显示简评区
  → 失败：卡片内显示错误 + 「重试」按钮（重新提交任务）
```

- 轮询组件可抽 `useAiTaskPolling(taskId)` composable，后续配音/讲稿等长任务也能复用。
- 进度文案由 `task.progress.message` 直接下发，前端不硬编码阶段表。

### 5.2 学生端 Learning.vue（新增）

- **完成即触发**：`report_progress(completed=true)` 响应里带回 `{summary_task_id}`（若自动提交了任务），前端 toast「本章学习完成！AI 总结生成中」；章节行徽章变「总结生成中…」。
- **章节行入口**：每章行新增「AI 总结」按钮（有成功记录显示「查看总结」，无记录显示「生成总结」）；点击开抽屉/弹窗展示 `overview + knowledge_points + weak_points + suggestions`（学生向排版：薄弱点红色标签、建议清单、next_step 高亮）。
- 学生端总结页同时挂「问过的问题」回顾（qa_insight 数据来源透明化，增强信任）。

---

## 六、Prompt 工程规范（两功能共用）

1. **输出永远结构化 JSON**，`_safe_json` 兜底 + 段级校验；单段失败重试一次。
2. **统计先于 AI**：能SQL算的（正确率、tag聚合、缺交名单）全部代码算好嵌入，LLM 只做解读、归因、建议——这是同时解决"时长"与"深度"的关键：token 预算花在洞察上，不花在复读数字上。
3. **证据强制**：每条结论必须带数据引用（prompt 明示 + 后置校验：报告中的数字与 stats_snapshot 抽样比对，偏差 >5% 该段重生成——可选 P4）。
4. **口吻约束**：沿用现有第三人称/禁空话规则并扩展到章节总结（学生向：鼓励+具体，禁说教）。
5. **token 预算表**（按 8k 上下文模型设计，本地小模型需下调条数）：

| 任务 | 输入预算 | 输出预算 | 调用次数 |
|------|---------|---------|---------|
| 班级报告 R1/R2/R3 | ≤6k/段 | ≤1.2k/段 | 3 |
| 学生简评批（5人） | ≤5k/批 | ≤1.5k/批 | ceil(N/5) |
| 章节总结 | ≤4k | ≤1.5k | 1 |

---

## 七、性能、成本与可靠性

| 维度 | 措施 |
|------|------|
| 时长体感 | 异步 + 阶段进度；班级分析 2-4 分钟但用户可离开；章节总结单次 20-40s 同样异步 |
| 并发 | `BoundedSemaphore(2)` 限全局并发任务；学生简评批内 4 并发；DashScope/QPS 类限流由信号量+批次大小吸收 |
| 失败域 | 段/批级失败隔离 + 重试一次 + 降级拼装；单学生/单段失败不影响整体产物 |
| 断线恢复 | 进度与结果全程落 `AITask` 行，刷新/重登后轮询同一 task_id 继续 |
| 计量 | 全部走 `scene_decorator` + `trace_id`，AICallLog 可查每次分析的成本（QA 看板已有成本口径，直接复用） |
| 成本 | D6 默认仅分析有数据学生：无数据学生零调用；50 人班级（按 40 人有数据估）≈ 3 段报告 + 8 批简评 ≈ 11 次 chat 调用，实际成本经 QA 看板 AICallLog 计量观察后再调批次大小 |
| 限流 | **DB 判定**（F6 排查修正，不放内存 dict——重启失效且多进程不共享）：班级分析提交时查同 classroom 最近一条 `class_analytics` 任务，10 分钟内直接拒绝（提示"请稍后再试"）；章节总结每生每章一条有效任务 + force 限 5 分钟 1 次（同为 DB 判定）；后续可挂 DRF throttle |
| 清理 | **章节总结任务是学生可见产物，不做 90 天删除**（F14 排查修正）；仅清理 FAILED 任务与 90 天前的 `class_analytics` 历史；AITask.result 只存产物不存原始 prompt，隐私口径不变 |
| Mock | 两任务均有确定性假数据路径，无 Key 环境全流程可演示 |
| 数据安全 | 提问/错题原文进 prompt，AICallLog 仍只存指纹与截断摘要（现状口径）；需向学生公示「学习数据将用于 AI 分析」 |

---

## 八、分期实施计划

| 阶段 | 内容 | 预估 | 交付物 |
|------|------|------|------|
| **P1 框架+教师端** | `AITask` 模型+migration（含 version）；`apps/ai/tasks.py` 执行器（ctx 恢复/close_old_connections/信号量）；`AI_ANALYTICS_TIMEOUT`；`build_class_stats_v2`（has_data 判定）；`run_class_analytics`（S0-S3 + 空数据边界）；`ClassAIReportView` 改造（DB 频率判定）；`GET /api/ai-tasks/<id>/`；前端轮询与阶段进度；删除旧同步逻辑 | 2-3 天 | 教师端深度报告上线 |
| **P2 章节总结** | `build_chapter_profile`（for_student 成绩门控 + resolver 复用）；`run_chapter_summary`；`WrongNote.catalog` 字段+migration；`report_progress` 自动触发（幂等 + summary_task_id）；学生端 API；Learning.vue 入口与展示抽屉 | 2-3 天 | 章节总结上线 |
| **P3 历史与连通** | 教师端查看学生章节总结；班级报告历史列表（按 AITask 查）；重新生成入口 | 1 天 | 闭环 |
| **P4 质量与治理** | 报告数字抽样校验；反馈（有用/无用）；任务清理策略（仅 FAILED 与 90 天前 class_analytics，F14）；限流 throttle | 1 天 | 治理完善 |

回归重点：`analytics/tests.py` 现有用例（旧同步端点用例需改写）；新增：任务状态机、分段失败降级、并发批次合并、幂等提交（连点/重复完成/force 新建版本）、**无数据学生标记与排除（has_data/no_data_students）**、**成绩门控（for_student=True 不透传未发布分值，for_student=False 全量）**、**线程上下文（AICallLog.triggered_by/trace_id 非空）**、空数据班级跳过调用、Mock 全流程。

---

## 九、评审决策记录（2026-10-22 定稿，全部按建议执行）

### 9.1 决策记录

| # | 问题 | 决策（按建议） |
|---|------|------|
| D1 | 异步线程模型是否够？多教师同时触发放任线程增长？ | **线程模型定稿**。当前规模够（`BoundedSemaphore(2)` 限并发 + 排队）；上 Celery 的触发条件写成注释留档，接口按任务抽象，将来可平移 |
| D2 | "章节完成"仅以视频完成为准是否合理？ | **定稿**：以 `VideoWatchProgress.status=COMPLETED` 触发（唯一现成完成态）；总结中如实呈现未完成维度（练习/作业未做会明确提示）；「练习也完成」作为增强触发放 P4 |
| D3 | `WrongNote` 无 catalog 字段，手动错题无法按章节归属 | **定稿**：给 `WrongNote` 加 `catalog` 可空 FK + 录入时选章节（P2 顺带做）；历史数据留空，按课程级纳入总结 |
| D4 | 考试未快照（Paper 只存 question_id 读实时 Question），发布后改题会影响考试维度分析口径 | **定稿**：分析以 `ExamSubmission.answers` 提交时答案为事实，文档注明；是否快照化属存量技术债，不在本方案范围 |
| D5 | 旧同步 ai-report 接口直接删除还是兼容一版？ | **定稿**：直接切换（唯一调用方是 `Analytics.vue`），双轨维护成本高于收益 |
| D6 | 班级分析每次 10+ 次 LLM 调用的成本；无数据学生是否分析 | **定稿**：默认**仅分析有数据学生**——六类行为记录（章节练习/作业/考试/实验/问答/视频进度）全无即无数据，打 `has_data=false` 标记、前端展示「暂无学习数据」、不生成简评不进分层，仅在报告里一句话说明数量；有数据但长期不活跃的学生仍正常分析。另加同班级 10 分钟 1 次提交限流；后续按 QA 看板 AICallLog 成本计量观察调整批次大小 |
| D7 | 学生提问原文进 prompt 的隐私边界 | **定稿**：产品侧补一行用户协议/提示（学习数据将用于 AI 分析）；技术侧 AICallLog 不落原文的现状不变 |
| D8 | 章节总结由学生手动 force 重试是否允许无限次？ | **定稿**：force 限频 5 分钟 1 次，防刷量 |

---

## 十、方案细节排查记录（2026-10-22 第二轮，已全部修正进正文）

对 v1.1 定稿方案逐条核对真实代码后共发现 14 处细节问题，修正情况如下：

| # | 级别 | 问题 | 排查依据 | 修正 |
|---|------|------|----------|------|
| F1 | **必须** | 学生端章节总结**缺成绩可见性门控**：作业 `correct_status=returned`、考试 `score_released` 后学生才可见分数，未发布成绩/批改若进 prompt 会提前泄露 | `homework/serializers.py:254-270,308-322`；`exams/views.py:528` | §4.2 增加 `for_student` 参数与门控规则，未发布只计数不透露分值；客观题答案提交即可见不受限 |
| F2 | **必须** | 章节总结幂等设计自相矛盾：既建 (task_type,student,catalog) 唯一约束，又要求 force 新建一版，DB 约束下无法新建 | 方案 §2.1/§4.1 交叉审读 | §2.1 改为代码级幂等 + `version` 递进 + 可选部分唯一索引（仅 pending/running） |
| F3 | **必须** | 外层 daemon 线程**丢 contextvars**：`threading.Thread` 不复制上下文，AICallLog 的 triggered_by/trace_id 全空 | `calllog.py:179-191`（copy/run_in_context 仅用于线程池） | §2.2 提交时 `copy_call_context()` 带进线程，`run_in_context(ctx, pipeline)` 包裹整条流水 |
| F4 | **必须** | 分析类调用复用 `AI_SCRIPT_TIMEOUT`（默认 45s）偏短：6k 输入 + 长输出在本地模型上必超时 | `settings.py:355`；模型 help_text「讲稿120+/语音180+」 | §2.2 新增 `AI_ANALYTICS_TIMEOUT`（默认 120s），分析链路优先管理端 timeout |
| F5 | 应修 | 全班无数据时仍会白发 N 次 LLM 调用 | 边界推演 | §3.6 analyzed_count==0 跳过全部调用，固定文案直接 SUCCESS |
| F6 | 应修 | 10 分钟频率限制放内存 dict：重启失效、多进程不共享 | 部署形态（gunicorn 多 worker） | §7 改 DB 判定（查最近一条同 classroom 任务） |
| F7 | 应修 | 任务轮询端点权限只有一句描述，无可执行规则 | §2.3 审读 | §2.3 明确 4 条可见性规则（发起人/班级教师/课程教师或学生本人/平台管理员），否则 404 |
| F8 | 应修 | 考试逐题对错若自行比对 `answers` 会**误判乱序考试**（选项做过映射） | `exams/resolver.py:160-186`（unmap_student_answer/layout） | §4.2 强制复用 `build_for_review` + `score_for_item` |
| F9 | 应修 | 作业章节归属用 `snapshot__catalog_id` JSON key 查：老数据可能缺 snapshot，SQLite JSON 查询不稳 | `homework/models.py:112-113`（snapshot 条件写入） | §3.2/§4.2 过滤改 `homework_question__question__catalog_id` 实时 join，snapshot 仅展示 |
| F10 | 小 | S2 进度 `total` 写"学生数"，实际应为有数据学生数 | §3.4 审读 | 改为 analyzed_count |
| F11 | 小 | daemon 线程的 DB 连接残留风险 | Django 连接模型 | §2.2 `_run_task` 入口 `close_old_connections()`；SQLite 写并发已有讲稿 4 并发先例，可接受 |
| F12 | 小 | 章节总结 API 计划新建路由，与现有风格不一致 | `config/urls.py`、各 app urls 形态 | §4.4 统一挂 `apps/analytics/urls.py`，不新建 app |
| F13 | 小 | 移动端 `app/src/api/course.js` 也调 report-progress，未评估兼容 | 代码排查 | §4.1 响应加性字段 `summary_task_id` 旧版忽略；移动端提示列 P3 |
| F14 | 小 | 「成功任务 90 天归档」会删掉学生端总结产物 | §8 P4 审读 | §7 仅清理 FAILED 与过期 class_analytics；章节总结不删 |

另核实无误的断言：`AICallLog.Scene` max_length=24 容得下 `chapter_summary`（16 字符）；`ai` 最新迁移为 0012（新迁移从 0013 起）；`VideoWatchProgress` 的 (student, video) 唯一约束 + video↔catalog 1:1 天然支撑 (student, catalog) 幂等；`analytics_ai.py` 懒加载分发无环依赖；移动端/教师端 URL 前缀 `/api/analytics/`、`/api/ai/` 已确认。

---

## 十一、附：关键文件改动清单（预排）

| 文件 | 改动 |
|------|------|
| `backend/apps/ai/models.py` | +`AITask`（含 `version` 字段）；`AICallLog.Scene` +`CHAPTER_SUMMARY` |
| `backend/apps/ai/migrations/0013_*.py` | 上述模型迁移（最新现为 0012） |
| `backend/apps/ai/tasks.py`（新） | `submit_ai_task` / `_run_task`（ctx 恢复 + `close_old_connections`）/ 信号量 |
| `backend/apps/ai/analytics_ai.py`（新） | `run_class_analytics`（S0-S3 编排 + 分段 prompt + 批并发）、`run_chapter_summary`、Mock 假数据 |
| `backend/apps/ai/urls.py` + `views.py` | `GET /api/ai-tasks/<id>/`（4 条可见性规则） |
| `backend/config/settings.py` | +`AI_ANALYTICS_TIMEOUT`（默认 120s，settings.py:355 旁） |
| `backend/apps/analytics/services.py` | +`build_class_stats_v2`（has_data 判定）、`build_chapter_profile`（for_student 门控） |
| `backend/apps/analytics/views.py` | `ClassAIReportView` 改异步提交（DB 频率判定）；+章节总结提交/查询/班级列表视图 |
| `backend/apps/analytics/urls.py` | 班级分析提交端点调整 + `chapter-summaries/` 路由 |
| `backend/apps/questions/models.py` + `migrations/0007_*.py`（D3 已定稿，P2 实施） | `WrongNote` +`catalog` 可空 FK |
| `backend/apps/courses/views.py` | `report_progress` 完成时提交章节总结任务（幂等跳过），响应加性字段 `summary_task_id` |
| `frontend/src/api/analytics.js` / 新 `ai-task.js` | task 提交与轮询封装 |
| `frontend/src/views/teacher/Analytics.vue` | 轮询进度 UI、失败重试、无数据学生徽标 |
| `frontend/src/views/student/Learning.vue` | 完成提示、章节行「AI 总结」入口与结果抽屉 |
