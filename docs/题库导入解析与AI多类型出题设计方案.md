# 题库导入解析 与 AI 多类型混合出题 设计方案

> 版本：v3（细节排查修订版，开发依据） · 2026-10-23
> 范围：教师端题库（apps/questions）两大增强能力
> 关联需求：T-Q-01（AI 出题）、题目录入（现有手动表单）
> v2→v3：完成一轮与现有代码的细节排查，修订 12 处冲突/缺口（见附录 B）

---

## 〇、已确认决策（v2 落定，v3 维持）

| # | 决策点 | 结论 |
|---|---|---|
| 1 | AI 生成结果落库方式 | **预览编辑后入库**，保留「一键全部入库」快捷按钮；生成任务异步执行，**离开页面不丢失**——结果落库为草稿批次，回页可恢复（§3.5） |
| 2 | 导入解析方式 | **只做规则解析**（解析后可编辑，规则解析足够）；AI 辅助解析不纳入计划，解析器预留扩展位 |
| 3 | 填空题分值语义 | 每组 score = **每题总分**，服务端按空数均分（余数补前空，与 `_split_score` 一致） |
| 4 | 文档多章节分段 | **暂不做**，一篇文档一个目标章节 |
| 5 | 支持格式 | **pdf / doc / docx / txt / md**（不含 ppt；.doc 走 LibreOffice/COM 兜底，生产容器已有 soffice） |
| 6 | 导入原件留存 | **入库即删**：批次草稿全部保存后删除上传文件，`raw_text` 截断保留供排查 |

---

## 一、现状分析

### 1.1 题库现状盘点

**数据模型**（`backend/apps/questions/models.py`）：

| 维度 | 现状 |
|---|---|
| 题型 | 5 种：`single` 单选 / `multi` 多选 / `judge` 判断 / `blank` 填空 / `short` 简答 |
| 答案结构 | JSON 按题型分化：选择 `{key/keys}`、判断 `{key}`、填空 `{blanks:[{text,score}]}`（按空赋分，save() 按 Σ空分重算总分）、简答 `{text}` 参考答案 |
| 来源 | `source`：`ai` / `manual` 两档（需增加 `import`） |
| 状态 | `draft` / `pending` / `published` / `disabled`，草稿机制已存在 |
| 约束 | catalog 必填（PROTECT）；serializer 校验章节归属课程、教师只能维护自己的课、填空逐空校验 |

**现有录入链路**：`frontend/src/views/teacher/QuestionManage.vue` 纯手动单题表单，`POST/PATCH /api/questions/`。

**现有 AI 出题链路**：
- 前端：QuestionManage 内「AI 生成」弹窗 —— 仅 3 个配置项：**章节、单一题型、数量（1-20）**，同步等待。
- 后端：`POST /api/questions/generate/`（`QuestionViewSet.generate`）→ `apps/ai/services.py::generate_questions()`：单次 LLM 调用，上下文 = 章节 PPT 前 25 页 + 知识库前 5 chunk（**课程级、未按章节收敛**），**截断到 3000 字**，直接落库为草稿（source=ai）。

### 1.2 痛点归纳

**功能一（导入）痛点**：无批量录入能力。教师手里的试卷/题库文档（Word/PDF/TXT）只能逐题手敲，50 题的试卷要重复 50 次表单操作。

**功能二（AI 出题）痛点**：
1. **单题型**：一次只能一种题型，出混合试卷要调用 N 次；
2. **配置弱**：不能按题型配分值与难度，无教学目标入口（后端有 objective 参数但前端未暴露），无难度分布；
3. **同步阻塞**：单次 LLM 长输出在 HTTP 请求内完成，无进度、无重试、大数量有超时风险（对比：讲稿/配音/学情分析都已异步化，生题是最后一个同步 LLM 长任务）；
4. **无复核环节**：直接落库，教师要在列表里逐题检查草稿；
5. **上下文窄**：3000 字截断，章节内容稍多就丢信息。

### 1.3 可复用资产（两个功能都大量复用现有基建）

| 资产 | 位置 | 复用点 |
|---|---|---|
| 文档文本抽取 | `apps/knowledge/extractor.py` | 已支持 pdf/docx/txt/md，旧版 .doc 走 LibreOffice/COM 兜底；**但 `_read_docx` 只读段落不读表格，需增强（附录 B-1）** |
| 「上传→解析→预览→确认落库」先例 | `courses/views.py::preview_from_file`（目录识别） | 功能一的交互范式完全同款（临时文件 → 解析 → 删临时文件） |
| AI 异步任务框架 | `AITask` + `apps/ai/tasks.py::submit_ai_task`（daemon 线程 + BoundedSemaphore(2) + progress JSON） | 功能二异步化直接复用 |
| 任务轮询 | `frontend/src/composables/useAiTaskPolling.js`（1.5s 轮询、代数守卫、超时兜底） | 前端直接 import（超时文案需泛化，附录 B-8） |
| 任务详情端点 | `GET /api/ai-tasks/<id>/`（注册于 `config/urls.py`，`_task_visible` 触发人可见） | 无需改造即可用于生题任务 |
| AI 调用日志 | `AICallLog.Scene.QUESTION_GEN` 已存在；`provider.chat` 内经 `record_ai_call` 按上下文场景落库 | 新流水线需 `ai_scene(QUESTION_GEN)` 包裹（现 generate_questions 无包裹，落 OTHER，附录 B-11） |
| Mock Provider | `apps/ai/providers/mock.py` | 未配真实模型时生题有兜底，功能不瘫 |
| 题目表单逻辑 | QuestionManage 的 `buildAnswer/buildOptions/loadBlanks` | 抽成共享组件三处复用（手动/导入/AI 预览） |
| 分值均分算法 | `questions/models.py::_split_score` | 填空题按空均分 |
| 章节化片段 | `KnowledgeChunk.catalog` 冗余字段（course+catalog 有联合索引） | 生成上下文可按章节收敛（附录 B-10） |

**结论：两个功能都不需要新基建，主要是「编排 + 解析器 + 前端向导」工作。**

---

## 二、功能一：题库导入解析预览编辑

### 2.1 目标流程

```
上传文档 → 文本抽取 → 规则解析（同步，秒级） → 草稿批次落库 → 预览编辑（逐题改/删/勾选） → 批量入库
                                                              ↑ 刷新/离开页面后可恢复
```

### 2.2 解析策略：规则解析（唯一方式）

**文本抽取增强（附录 B-1）**：`extractor.py` 新增 `extract_text_with_tables(file_path)`——python-docx 按 `doc.element.body` 文档顺序遍历段落与表格（表格单元格以制表符连接成行）。**不动原 `extract_text`**（知识库向量化链路不受影响）。Word 题库极常见表格排布，这是导入解析的硬前提。

**规则解析器**（`apps/questions/import_parser.py`，纯函数无 IO、可单测）：

| 元素 | 识别规则（示例） |
|---|---|
| 题型分段 | `一、单选题` `二、多选题` `（三）判断题` `四、填空题` `1. 单项选择题` |
| 题号 | 行首 `1.` `2、` `(1)` `1．` |
| 选项 | 行首 `A.` `A．` `A、` `（A）`；**行内粘连**（`A.xxx B.xxx`，PDF 高发）需二次切分；选项缺失 → 选择题降级待修正 |
| 跨页/跨段续接 | PDF 分页符与软换行不作为断题边界，题号/选项/答案标志出现才断 |
| 答案 | `答案：A` `参考答案：ABC` `【答案】A`；题干尾部粘连的 `答案：/解析：` 剥落后并入字段 |
| 解析 | `解析：xxx` `答案与解析：xxx` |
| 填空空位 | 题干中 `____`（2+ 下划线）、全角空括号 `（ ）`；空数 = 空位数；答案按空拆分（`答案：x;y` 或 `答案：x、y`） |
| 判断题答案 | `对/错` `正确/错误` `T/F` `√/×` → 归一 `{key:"A"/"B"}`（A=正确）；无法归一 → 该题告警待修正 |
| 简答题 | 无选项无空位、题型段落在简答区 → `answer={text:"..."}`（取「参考答案」） |
| 选项 key 归一 | 甲乙丙丁/罗马数字等 → A/B/C/D，**题干内引用与答案 key 同步重映射** |

每条解析结果带**告警**（如「第 3 题未识别到答案」「多选题只识别到 1 个选项」），预览态醒目标注，教师点开即可修。**解析后可人工编辑，规则解析的误识别不构成阻塞**——这是决策 2 的落地逻辑。解析器结构上预留 AI 结构化扩展位（二期如需，仅替换 parse 实现，批次/预览/入库链路不变）。

### 2.3 数据模型：新增 `QuestionDraftBatch`（题目草稿批次）

导入与 AI 生成**共用同一张批次表**（决策 1「离开页面不丢失」的载体——AI 生成完成即在服务端建批次，前端编辑也回存批次，刷新/重登不丢任何中间态）：

```python
def _import_file_path(instance, filename):
    # 仿 Material：uuid 命名防枚举，原文件名只存 file_name（附录 B-5）
    return f"question_imports/{uuid4().hex}{Path(filename).suffix.lower()}"

class QuestionDraftBatch(BaseModel):
    """题目草稿批次：文档导入 / AI 生成共用的待入库题目池。"""
    class Origin(TextChoices):
        IMPORT = "import", "文档导入"
        AI_GEN = "ai_gen", "AI 生成"
    class Status(TextChoices):
        PARSED = "parsed", "待入库"
        SAVED  = "saved",  "已入库"

    origin   = CharField(choices=Origin)
    course   = FK(Course, on_delete=CASCADE)
    catalog  = FK(Catalog, null=True, on_delete=SET_NULL)  # 目标章节（预览期可改；删除不牵连批次）
    creator  = FK(User, SET_NULL)
    file     = FileField(upload_to=_import_file_path, null=True)  # 仅 import；入库即删
    file_name = CharField(max_length=255, blank=True)
    raw_text = TextField(blank=True)      # 抽取原文，截断至 10 万字符 + truncated 标记（附录 B-6）
    # 草稿数组：[{qtype, stem, options, answer, analysis, score, difficulty,
    #            _warnings:[...]}]；保存成功的条目即时移除，批次=剩余待入库
    drafts   = JSONField(default=list)
    stats    = JSONField(default=dict)    # {"total":n,"warned":n}
    task     = FK(AITask, null=True)      # 仅 ai_gen：关联生成任务
    status   = CharField(choices=Status, default=PARSED)
```

**为什么不放 AITask.result 而非要建批次行**：① 预览编辑的中间态（逐题修正后的 drafts）需要可回存，AITask.result 是任务执行器的写域，不宜被前端 PATCH；② 两个功能统一恢复入口（一个列表端点）；③ 批次带 catalog/文件/统计，审计清晰。

### 2.4 API 设计

| 方法 | 端点 | 说明 |
|---|---|---|
| POST | `/api/questions/import/` | multipart：file + course（+ catalog?）。**权限 IsTeacher + course.teacher==user**（平台管理员除外——批次含答案解析，学生绝不可见，附录 B-2）。流程：临时文件 → `extract_text_with_tables` → 规则解析 → **建批次**（file 从临时文件入库）→ 删临时文件。白名单 pdf/doc/docx/txt/md + 魔数复检，>10MB 拒绝；解析出 0 题 → 400「未能识别出题目」；无可提取文本（扫描件）→ 明确提示 |
| GET | `/api/question-draft-batches/?course=&status=parsed` | **可恢复批次列表**（creator=user 且 course__teacher=user），导入与 AI 生成共用；页面挂载时调用，有条目即显示恢复入口 |
| GET | `/api/question-draft-batches/<id>/` | 批次详情（drafts 全量） |
| PATCH | `/api/question-draft-batches/<id>/` | 改目标章节；前端逐题编辑后**防抖回传 drafts**（关闭预览时强制回传）——编辑不丢 |
| POST | `/api/question-draft-batches/<id>/save/` | **批量入库**，body `{items:[...]}`。服务端流水线：① 规范化（填空题按空数均分 score、judge 答案归一并补 A/B 选项、judge/single/multi 结构与 grading.py 契约对齐）；② 结构校验（single/multi ≥2 选项且答案 key ∈ 选项 keys；judge 答案 ∈ A/B；否则该条 failed）；③ 逐条 `QuestionSerializer` 校验（章节归属/教师归属/填空赋分全部复用）；④ **精确查重**：同课程同题干已存在 → 跳过并计入 `skipped`（防请求重试/重复导入导致重复入库，附录 B-3）；⑤ 返回 `{saved:[id...], skipped:n, failed:[{index,error}]}`；⑥ 成功条目从 drafts 移除（按规范化 JSON 相等匹配，重复项按序移除首个），drafts 空 → status=saved、**删除上传文件**（入库即删） |
| DELETE | `/api/question-draft-batches/<id>/` | 放弃批次（先删文件再删行） |

**部分失败语义**：几十题里错 1 题是常态——失败项留批次内可修正重试，成功项即时移除，不整批回滚。

### 2.5 前端设计

**入口**：QuestionManage 工具栏新增「导入题目」按钮（与「AI 生成」「新建题目」并列）。

**恢复入口**：页面挂载时请求可恢复批次列表，顶部显示横幅：「N 个题目草稿批次待处理（文档导入 x / AI 生成 y）」→ 点击直接打开对应预览。

**三步向导对话框**（`QuestionImportDialog.vue`，参照目录识别向导形态）：

1. **上传**：el-upload 拖拽区（accept=".pdf,.doc,.docx,.txt,.md" + 白名单提示）+ 目标课程/章节选择（默认带入当前筛选章节）+「开始解析」（同步等待，通常 <2s；超时/失败可重试）。
2. **预览编辑**（核心）：
   - 汇总条：`共识别 23 题 · 待修正 4 题 · 已剔除 1 题` + 全选/反选 +「导入所选 (N)」+「一键全部入库」；
   - 左列题目卡片：题型徽标 + 题干截断 + 分值 + ⚠️ 告警数；勾选纳入/剔除；
   - 右列/弹出单题编辑：**复用共享单题表单组件**（§4.1），与手动录入同款交互；支持改题型、改章节（条目级覆盖批次章节）；
   - 编辑防抖 1s 回传 PATCH + 关闭强制回传。
3. **入库结果**：逐条结果（成功/跳过/失败 + 原因），失败与跳过项留预览态可修正重试；完成后关闭向导、刷新题库列表。

---

## 三、功能二：AI 多类型混合自动出题

### 3.1 配置模型（题型组）

```json
{
  "catalog": 12,
  "objective": "覆盖本章核心概念与计算",
  "difficulty": "medium",
  "groups": [
    {"qtype": "single", "count": 5, "score": 2},
    {"qtype": "multi",  "count": 3, "score": 4,  "difficulty": "hard"},
    {"qtype": "judge",  "count": 4, "score": 2},
    {"qtype": "blank",  "count": 2, "score": 6},
    {"qtype": "short",  "count": 1, "score": 10}
  ]
}
```

**服务端参数校验（附录 B-12，错误信息中文，项目约定）**：groups 非空；qtype ∈ 5 种；count 1-20；score 0.5-100（一位小数）；difficulty ∈ easy/medium/hard（组级缺省继承全局，全局缺省 medium）；总题数 ≤30；objective ≤500 字。

- **填空组 score = 每题总分**（决策 3），入库时按识别空数均分（余数补前空），模型 save() 的 Σ空分重算天然兼容；
- 兼容旧调用：平铺的 `{qtype, count}` 自动归一为单组，url_path 与前端 API 函数签名不变。

### 3.2 执行架构：异步任务 + 按组分批

```
POST /api/questions/generate/  {catalog, objective, difficulty, groups[]}
   → 参数校验（§3.1）→ submit_ai_task(QUESTION_GEN, course, catalog)   # 秒级返回 task_id
   → daemon 线程（信号量排队，页面关闭不影响执行）
      → apps/ai/question_gen_ai.py::run_question_generation(task)
        ├─ 组装章节上下文：PPT 前 40 页 + KnowledgeChunk **按 catalog 收敛**（无挂靠片段退课程级），
        │   预算 8000 字，替代原 3000 字课程级截断（附录 B-10）
        ├─ 逐组 LLM 调用，全程 ai_scene(Scene.QUESTION_GEN) 包裹（附录 B-11）
        │    └─ 组内 count > 10 切块（每块 5-10 题），单块失败只影响该块
        ├─ 每组完成即 flushProgress（{stage:"groups", done, total, items:[{qtype,done,total}]}）
        ├─ 后组 prompt 带入前组已出题干列表 → 组间防重复
        └─ 收尾：创建 QuestionDraftBatch(origin=ai_gen, task=task, drafts)
             ├─ 成功 → task.result = {batch_id, drafts, failed_groups:[...]}
             └─ 建批次异常 → task.result = {drafts, failed_groups}（无 batch_id，
                前端回退模式：按 task_id 直接保存，附录 B-13）
```

**关键设计决策**：

1. **按组拆分调用**而非一次大调用：单组失败不拖垮整体（记 failed_groups，其余组照常）；进度按组细粒度；各题型 prompt 契约独立、输出质量更高（现有 `qtype_hint` 已按题型给约定，天然适合拆）。
2. **结果不直接建 Question，先进草稿批次**：`task.result.batch_id` 指向批次，前端拿到即开预览（与功能一共用 `QuestionDraftPreview.vue`）；同时提供「一键全部入库」快捷按钮（一次确认全量保存）。备选的「直接落草稿」方案被否决：多类型批量生成时 LLM 输出畸变率上升（选项缺失、答案越界），预览复核收益更大，且与导入体验统一。
3. **防重复提交**：DB 部分唯一约束 `uniq_active_question_gen`（task_type=question_gen + triggered_by + course，status ∈ pending/running），仿现有 `uniqi_active_chapter_summary`（历史 typo 不 retro 修改）；冲突时返回友好提示「该课程已有生成任务进行中」。triggered_by/course 均为可空 SET_NULL，SQLite 下 NULL 不冲突、语义可接受（附录 B-9）。
4. **兜底**：未配真实模型时 Mock provider 按组生成示例题（照 `analytics_ai._mock_*` 模式）；`_safe_json` 失败自动重试 1 次；字段补全（缺 score/difficulty 用组配置、judge 补 A/B 选项）。
5. **入库**：走与导入完全相同的批次 save 端点与逐条校验，`source=ai`。

### 3.3 对现有代码的改造点

| 文件 | 改造 |
|---|---|
| `apps/ai/models.py::AITask` | TaskType 新增 `QUESTION_GEN = "question_gen", "题目生成"`；Meta.constraints 新增 `uniq_active_question_gen`（迁移 ai/0014） |
| `apps/ai/tasks.py::_dispatch` | 新增 QUESTION_GEN 分发 |
| `apps/ai/question_gen_ai.py`（新） | 按组生成流水线（与 `analytics_ai.py` 同款：flushProgress / 失败隔离 / mock 兜底 / 收尾建批次） |
| `apps/ai/services.py::generate_questions` | 重构为单组生成原语 `generate_question_group(...)`（prompt 契约不变，上下文预算加大 + catalog 收敛）；旧函数删除（已确认唯一调用方 questions/views.py:109，无测试引用） |
| `apps/questions/models.py` | 新增 `QuestionDraftBatch`（迁移 questions/0008）；`Question.Source` 新增 `IMPORT = "import", "文档导入"` |
| `apps/questions/views.py` | generate 改造（groups → submit_ai_task → `{task_id}`）；新增 import 端点、批次 ViewSet（list/retrieve/patch/destroy/save） |
| `apps/questions/import_parser.py`（新） | 规则解析器：`parse_questions(raw_text) -> list[draft]` |
| `apps/knowledge/extractor.py` | 新增 `extract_text_with_tables`（不动原函数） |
| `apps/ai/views.py` + `config/urls.py` | 新增 `GET /api/ai-tasks/active/?task_type=question_gen&course_id=`（恢复进行中任务用；ai-tasks 路由现注册于 config/urls.py，同址追加） |
| `frontend/src/api/question.js` | generate 改收 task_id；新增 import / 批次 / active-task API |

### 3.4 前端设计（AI 出题弹窗改造）

- **配置区**：章节 + 教学目标（新暴露）+ 难度全局档 + **题型配置表格**：5 行题型，每行「开关 + 数量 stepper + 分值 input + 难度 select」，行尾显示该组合计分；表尾显示总题数/总分（超 30 题实时拦截）。
- **提交后**：弹窗切进度态——进度条 + 「单选题 3/5 · 多选题 1/3 · 已生成 4 题」（`useAiTaskPolling` 1.5s 轮询，排队中/进行中/失败组红字均可见）；**超时/失败时提供「重试」按钮**（附录 B-8：排队超时、10 分钟轮询超时均可能发生）。
- **完成后**：`task.result.batch_id` → 拉批次 → 进入**预览编辑**（与导入共用组件）→ 勾选「入库为草稿」或「一键全部入库」；无 batch_id 时走回退模式（按 task_id 保存 drafts）。

### 3.5 离开页面不丢失（决策 1 专项设计）

| 场景 | 机制 |
|---|---|
| 生成中离开页面 | daemon 线程服务端独立执行（与 HTTP 连接无关，现有框架即如此）；任务行持久化 |
| 回到页面（任务还在跑） | 挂载时 `GET /api/ai-tasks/active/?task_type=question_gen&course_id=` → 有 pending/running 任务 → `useAiTaskPolling.start(taskId)` 恢复轮询与进度展示；前端 sessionStorage 记住最近 task_id 作双保险 |
| 任务完成但未保存 | 完成时服务端已建草稿批次 → 挂载时 `GET /api/question-draft-batches/?status=parsed` → 横幅「N 个草稿批次待处理」→ 点击恢复预览，drafts 原样还在 |
| 预览编辑中途离开 | 编辑防抖 PATCH 回批次 + 关闭强制回传 → 刷新后 drafts 是修正后的版本 |
| 保存中途离开 | save 是同步请求；成功条目即时移出 drafts，重进页面只剩未保存项；即使响应丢失，精确查重（§2.4④）保证重试不产生重复 |
| 服务重启杀死线程 | 任务行停留 running：active 端点按 created_at 超过 10 分钟判 stale 不恢复 + `useAiTaskPolling` 超时兜底（现有能力） |

**导入侧的恢复同理**：批次即持久化载体，列表端点统一恢复入口。

---

## 四、两功能共用组件

### 4.1 前端共享

| 组件 | 来源 | 复用方 |
|---|---|---|
| `QuestionFormFields.vue` | 从 QuestionManage 编辑弹窗抽出的纯表单（题型/章节/题干/选项/答案/解析/分值/难度 + buildAnswer/buildOptions 逻辑） | 手动新建编辑、导入预览编辑、AI 草稿编辑 |
| `QuestionDraftPreview.vue` | 草稿预览（左列表勾选 + 右编辑 + 汇总条 + 一键全部入库 + 防抖回传） | 导入向导第 2/3 步、AI 生成完成态 |
| `useAiTaskPolling`（现有） | composables | AI 生成进度轮询与恢复 |

### 4.2 后端共享

| 模块 | 内容 |
|---|---|
| `QuestionDraftBatch` | 两功能统一草稿池（origin 区分 import/ai_gen） |
| 批次 save 端点 | 规范化（填空均分/judge 归一并补选项）→ 结构校验 → 逐条 `QuestionSerializer` 校验 → 精确查重 → 明细返回 → 移除成功项、空批即删文件置 saved |
| `import_parser.py` | 纯函数规则解析，无 IO、可单测 |
| `generate_question_group` | 单组生成原语（AI 生成用；导入侧无 AI 解析需求） |

---

## 五、分期实施计划

| 阶段 | 内容 | 预估 |
|---|---|---|
| **P1（本期全量）** | 功能一：pdf/doc/docx/txt/md 规则解析导入（含 docx 表格抽取）+ 批次落库 + 预览编辑 + 批量入库（含精确查重）+ 入库即删；功能二：groups 配置 + 异步任务 + 按组生成 + 进度轮询 + 完成建批次 + 预览编辑入库 + 一键全部入库；恢复机制（active 任务 + 待处理批次横幅）；共享组件抽取 | 后端约 4-5 天 + 前端 4-5 天 |
| **P2（增强）** | 相似度查重提示（替换/补充精确查重）、导入模板文件下载（标准格式样例，提升规则命中率）、难度比例分配（替代逐组指定）、AI 生成推荐知识点标签 | 2-3 天 |

**测试要点**：
- 解析器单测：每种题型 ≥3 种真实格式变体（含缺答案/缺选项等残缺输入、选项 key 归一、行内粘连选项、docx 表格排布、跨页续接）；
- 批量入库：部分失败明细、精确查重跳过、重复提交不产生重复、跨课程章节归属拒绝、填空均分后 Σ=总分、空批删文件；
- 生成任务：单组失败不中断、mock 兜底、信号量排队并发、防重复提交约束、active 端点仅触发人可见；
- **恢复专项**：提交后关闭页面 → 重开 → active 端点恢复进度；完成后关闭 → 重开 → 批次横幅恢复预览；编辑后刷新 → drafts 为修正版；
- 权限专项：学生访问批次端点 403/404（含 answers 不泄露）；
- E2E：上传 docx → 预览修正 2 题 → 入库 → 列表可见且「文档导入」标签正确；AI 五题型混合生成 → 进度推进 → 一键全部入库。

---

## 六、附录 A：涉及文件清单

**后端**
- `apps/questions/models.py`（QuestionDraftBatch、Question.Source + IMPORT）→ 迁移 questions/0008
- `apps/questions/views.py` / `urls.py`（import 端点、批次 ViewSet、generate 改造）
- `apps/questions/serializers.py`（批量校验复用，不改动）
- `apps/questions/import_parser.py`（新，规则解析器）
- `apps/ai/models.py`（TaskType + QUESTION_GEN、uniq_active_question_gen 约束）→ 迁移 ai/0014
- `apps/ai/tasks.py`（_dispatch 新增分发）
- `apps/ai/question_gen_ai.py`（新，按组生成流水线）
- `apps/ai/services.py`（generate_questions → generate_question_group）
- `apps/ai/views.py` + `config/urls.py`（ai-tasks/active 端点）
- `apps/knowledge/extractor.py`（新增 extract_text_with_tables）

**前端**
- `src/api/question.js`（generate / import / 批次 / active-task）
- `src/views/teacher/QuestionManage.vue`（工具栏、恢复横幅、source 三态标签、AI 弹窗改造或抽离）
- `src/components/question/QuestionFormFields.vue`（新，从 QuestionManage 抽取）
- `src/components/question/QuestionDraftPreview.vue`（新）
- `src/views/teacher/QuestionImportDialog.vue`（新，三步向导）
- `src/views/teacher/QuestionAiGenerateDialog.vue`（新，从 QuestionManage 抽离出体型）

---

## 附录 B：细节排查记录（v2→v3，对照现有代码逐项核查）

| # | 级别 | 问题/冲突 | 处置 |
|---|---|---|---|
| B-1 | **高** | `extractor._read_docx` 只读 `doc.paragraphs`，**Word 表格内容整体丢失**——题库文档表格排布极常见，直接复用会导致解析出 0 题 | 新增 `extract_text_with_tables`（按 body 顺序遍历段落+表格，单元格制表符连接）；原函数不动，知识库链路零影响 |
| B-2 | **高** | `courses_for_user` **包含学生 enrolled 课程**；批次 drafts 含答案/解析，若列表/详情只用它过滤，学生可越权看到答案 | 批次端点统一 `IsTeacher + course.teacher==user`（平台管理员除外），不用 courses_for_user；补学生访问 403 测试 |
| B-3 | **高** | save 响应丢失后前端重试 → **重复入库**；同一文档重复导入 → 重复题；v2 未定义 drafts 移除匹配算法 | save 管道加**精确查重**（同课程同题干跳过计入 skipped，从 P2 提至 P1）；移除算法定为「规范化 JSON 相等匹配、重复项按序移除首个」；前端先 PATCH 回编辑后 drafts 再提交 items |
| B-4 | **高** | `QuestionSerializer` **不校验单选/多选选项数与答案归属**（现仅靠前端）；judge 答案 key 若为 C 与默认 A/B 选项不匹配，判分全错 | 批次 save 管道内结构校验：single/multi ≥2 选项且答案 key ∈ 选项 keys、judge 归一到 A/B，违者该条 failed（中文原因）；QuestionSerializer 本身不改（避免影响手动编辑流） |
| B-5 | 中 | 上传文件若用原始文件名入库，可被猜测/枚举，非 ASCII 名有兼容风险 | 仿 `Material._material_file_path`：`question_imports/{uuid}{ext}`，原文件名只存 `file_name` |
| B-6 | 中 | 10MB txt 的 raw_text 全量入库撑爆 SQLite 行 | raw_text 截断 10 万字符 + stats.truncated 标记 |
| B-7 | 中 | 同步解析 + nginx `proxy_read_timeout 180s`：大 PDF（pypdf）解析可能逼近上限，超时前端只看到网络错误 | 10MB 上限 + 明确错误文案 + 可重试；不引入异步（决策 2）；解析耗时超阈值时在 stats 记 parse_ms 便于观测 |
| B-8 | 中 | `useAiTaskPolling` 超时文案写死「分析超时」；生题任务经信号量(2) 排队，排在长学情分析后可能超 600s 队列超时或 10min 轮询超时 | 复用方式：泛化 onFailed 文案（参数化）或接受上限并在 UI 注明；**失败/超时态必须提供「重试」按钮**（重新提交同配置） |
| B-9 | 中 | 新唯一约束的迁移与命名 | 迁移 ai/0014；命名 `uniq_active_question_gen`（现有 `uniqi_active_chapter_summary` 的拼写 typo 不 retro 修改）；triggered_by/course 可空 SET_NULL，SQLite NULL 不冲突，语义可接受 |
| B-10 | 中 | 现生成上下文 `KnowledgeChunk.filter(course_id=...)` 课程级、3000 字截断，章节内容稍多即丢 | `KnowledgeChunk.catalog` 冗余字段有 (course,catalog) 联合索引：按 catalog 收敛优先、无挂靠退课程级；预算提至 8000 字 |
| B-11 | 中 | `generate_questions` 无 `ai_scene` 包裹，AI 调用落 Scene.OTHER，QA 看板/成本统计看不到生题消耗 | 新流水线每组调用 `ai_scene(Scene.QUESTION_GEN)` 包裹 |
| B-12 | 中 | groups 参数无校验规格 | §3.1 校验清单（qtype/count/score/difficulty/总量 ≤30/objective ≤500 字），错误中文 |
| B-13 | 中 | 任务成功但建批次异常 → LLM 成本沉没、drafts 丢失 | 收尾建批次包 try：失败则 drafts 落 `task.result`（无 batch_id），前端回退按 task_id 保存 |
| B-14 | 轻 | `QuestionManage.vue:52-53` source 标签二态（ai/manual） | 改三态（+文档导入）；`filterset_fields` 的 source 过滤自动兼容新 choice |
| B-15 | 轻 | PDF 跨页断题、行内选项粘连、题干尾粘「答案：」 | 解析器规格补充（§2.2）：跨页续接、行内选项切分、尾部答案/解析剥离 |
| B-16 | 轻 | 批次 catalog 删除场景 | `batch.catalog` 用 SET_NULL（可空）；保存时无章节的条目 failed 提示；Question.catalog 仍是 PROTECT 不受影响 |
| B-17 | 轻 | course CASCADE 删批次不删磁盘文件（孤儿 media） | 与现有一致（Material 同款）；destroy 手动删文件，CASCADE 场景接受孤儿 |
| B-18 | 轻 | AI 无费用限流（已知中危） | generate 端点加 `ScopedRateThrottle`（新 settings 键 `TEACHER_AI_THROTTLE_RATES = {"question_gen": "5/min"}`，仿 AdminScopedThrottle 独立键模式）；import 无 LLM 成本轻限或不限 |
| B-19 | 轻 | 两标签页同改一批次 | last-write-wins，接受（防抖回传天然降低概率） |

**排查确认无冲突项**：nginx `client_max_body_size 600m`（10MB 上传无碍）；DRF 默认解析器含 MultiPartParser（FormData 直传 OK）；`request.js` 不强制 JSON content-type、timeout 180s 与 nginx 对齐；`generate_questions` 唯一调用方为 questions/views.py:109（可安全重构，无测试引用）；grading.py 答案契约与解析器输出一致；迁移编号 questions 下一号 0008、ai 下一号 0014；`/api/ai-tasks/active/` 与 `<int:task_id>` 路由无冲突（int 转换器不匹配 "active"）；test/ 下 E2E 无 generate 引用（响应结构变更无回归）。
