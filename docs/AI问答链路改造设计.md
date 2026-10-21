# AI 问答链路改造设计（AI 助教 / 章节讲解问答）

- 日期：2026-10-21
- 状态：P0、P1、P2 全部已实施并验证（2026-10-21）
- 范围：课程 AI 助教（student/KnowledgeQA.vue）、章节讲解 Dock AI 问答（student/Learning.vue）、教师端 AI 问答（teacher/CourseQA.vue）、移动端问答（app/pages/qa）共用的后端 RAG 链路（`apps/ai/services.py` + `apps/knowledge/views.py`）

---

## 1. 背景、目标与设计原则

### 1.1 现状

四个前端入口共用一条后端链路：

```
ask / ask-stream
  → _resolve_qa_scope（课程/班级/章节校验）
  → build_qa_history（按 session 字符串拉最近 10 轮，24000 字符预算）
  → knowledge_qa(_stream)
      → _gather_course_context
          ① _search_relevant_chunks：向量召回15 → 重排 → 按模型阈值 → 相对截断 → top5
          ② PPT 原文兜底（仅未入向量库时，前 40 页全文）
          ③ 逐页讲解稿：无检索、无排序、全量拼接（课程级=全课程讲稿）
      → context = "\n---\n".join(parts)[:6000]   # 硬截断
      → messages = [system, *history, user(课程资料+问题)]
      → provider.chat_stream → SSE → 落 QARecord
```

### 1.2 问题清单（8 项，均有代码依据）

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| P1 | 检索不看历史：追问（"第五个详细讲讲"）拿原句去 embed，检索必退化 | services.py:1200 | 多轮问答脱离课程资料，退化为模型通识 |
| P2 | 讲稿无检索全量拼接，vid_qs 无 order_by；与已入向量库的 PPT 页内容重复；不进 cited | services.py:1003-1014 | 上下文预算被稀释，课程级提问覆盖随机 |
| P3 | 班级定向资料死局：前端不传 classroom，学生检索要求 material.classroom 为空 | vectorstore.py:71 + 三端前端 | 教师按班级上传的资料对学生问答永久隐形 |
| P4 | 未挂章节的通用资料（教材、考纲）在章节问答中不可见 | vectorstore.py:55-59 | 章节提问漏检通用资料 |
| P5 | 资料 500 字符硬切分，无段落边界、无 overlap | services.py:635 | 语义割裂，跨片段答案两边残缺 |
| P6 | 注入无来源标头：纯文本 `\n---\n` 拼接 + 6000 硬截断；模型不知出处；cited 与模型上下文无对应，引用不可交互；system prompt 无来源优先级 | services.py:1092-1104, QA_SYSTEM_PROMPT | 回答无法标注出处，来源冲突无仲裁 |
| P7 | 上下文管理薄弱：① 章节 Dock session 页面级一次性、跨章节共享、刷新即丢、历史不按 catalog 隔离；② 历史按字符预算、超限一次性丢全部；③ 无长会话压缩；④ 无检索快照，追问检索失败无兜底 | Learning.vue:666, services.py:1123-1170 | 跨章节串话、长会话失忆、追问无根 |
| P8 | eval_rag 用裸 search_chunks，未走重排编排，与线上不一致 | eval_rag.py:120 | 评估系统性偏低，不能作质量门禁 |

### 1.3 目标

1. 检索范围"该进的进、该出的出"：讲稿入检索体系、班级资料可见、通用资料入章节候选池、追问检索可命中。
2. 注入"分来源、有编号、可回链"：结构化标头 + 引用编号 + 按预算与片段边界组装。
3. 上下文"持久、隔离、可压缩、可审计"：会话模型化、章节隔离、滚动摘要、分级降级、检索快照。
4. 质量可度量：评估与线上同链路，关键指标可统计。

### 1.4 设计原则

- **兼容优先**：`session` 字符串参数与非流式 `ask` 端点保持可用；移动端不发版也能继续用。
- **失败静默降级**：改写、重排、摘要均为增强项，失败回退原行为，不拖垮主链路。
- **先算后删**：所有入库/回填操作沿用 rebuild_vectors 的四道防线模式。
- **分批落地**：P0 无迁移 → P1 检索侧迁移 → P2 会话侧迁移，每批独立可回滚。

---

## 2. 目标架构

```
ask / ask-stream（+session_id）
  → _resolve_qa_scope（学生自动解析在读班级列表）
  → 会话解析：session_id 或 legacy session 字符串 → QASession（P2）
  → ① 查询改写 rewrite_query(question, history)      # 新增，P0
  → ② build_conversation_context(session, budgets)   # 重写，P0/P2
       [滚动摘要] + [最近 N 轮原文（token 预算内）]
  → ③ _gather_course_context 重构                     # P0/P1
       _search_relevant_chunks（候选池：章节+通用资料+班级资料；
                               来源同池：课件/资料/讲稿；同页融合）
       + PPT 原文兜底（保留）
       + 上一轮检索快照（追问兜底，P2）
  → ④ context_builder：编号标头 + 预算分配 + 片段边界截断  # P0
  → messages = [system(新 prompt), *history, user]
      降级链：L1 丢旧 50% → L2 仅最近 2 轮 → L3 仅摘要 → L4 无历史  # P0
  → provider.chat_stream → SSE（meta 扩展：session_id/编号 cited/改写问题）
  → 落 QARecord（+context_snapshot 审计）→ 触发滚动摘要（阈值时）   # P1/P2
```

---

## 3. 数据模型变更与迁移

### 3.1 KnowledgeChunk（P1，迁移 knowledge/0010）

```python
class KnowledgeChunk(BaseModel):
    class Source(models.TextChoices):
        MATERIAL = "material", "教辅资料"
        PPT = "ppt", "课件页面"
        SCRIPT = "script", "讲解稿"

    source = models.CharField("来源类型", max_length=12, choices=Source.choices, db_index=True)
    # 既有 material / ppt FK 保持；新增：
    video = models.ForeignKey("courses.TeachingVideo", on_delete=models.CASCADE,
                              related_name="chunks", null=True, blank=True, verbose_name="来源讲稿")
    # 冗余章节：检索过滤不再 join material/ppt 取 catalog，过滤与候选池收敛都走本字段
    catalog = models.ForeignKey("courses.Catalog", on_delete=models.CASCADE,
                                related_name="chunks", null=True, blank=True, verbose_name="所属章节")
    class Meta:
        indexes = [models.Index(fields=["course", "source"]), models.Index(fields=["course", "catalog"])]
```

- material/ppt/video 三个 FK 仍互斥（与 source 对应），catalog 对未挂章节资料为 null（= 通用资料）。
- 约束：在 `clean()` 或迁移后检查中保证 source 与非空 FK 一致；应用层写入点统一收口（ingest_* 三个函数），不开放手工创建。

**回填（RunPython）**：
1. `source`：material 非空→material；ppt 非空→ppt。
2. `catalog`：material.catalog_id / ppt.catalog_id 逐行拷贝（ppt.catalog 非空；material.catalog 可空）。

### 3.2 TeachingVideo 讲稿入库（P1）

新增 `ingest_video_scripts(video) -> int`（services.py，与 ingest_ppt_pages 对称）：

- 片段文本：`f"{page_title}\n{script}"`（带 PPT 页标题，利于检索命中），page 存页码；`source=script, video=video, catalog=video.catalog, course=video.course`。
- 分批 embed（EMBED_BATCH_SIZE=10），`allow_fallback=False`；Mock 或失败静默返回 0、旧片段保留。
- 事务内 `video.chunks.all().delete()` + bulk_create（先算后删）。
- 触发点：
  1. 整章讲稿生成完成（分批任务全部落库、状态翻转时）统一调用——不在小块中途入库，避免不完整状态；
  2. 教师单页编辑讲稿保存后调用（幂等全量替换）；
  3. 回填管理命令 `python manage.py ingest_scripts [--course N]`，遍历 scripts 非空的 video 逐部入库，单项失败记录续跑。
- `rebuild_vectors` 扩展第三分队 videos（script 片段随向量模型更换一并重建）。

**学生可见性**（search_chunks 内）：script 片段要求 `video__is_published=True` 且 `video__catalog__is_published=True`（与现讲稿过滤口径一致）。

### 3.3 章节候选池扩展（P1，无字段变更）

`search_chunks` 在 `catalog_id` 时的过滤由：

```python
Q(material__catalog_id=catalog_id) | Q(ppt__catalog_id=catalog_id)
```

改为（走冗余 catalog 字段）：

```python
Q(catalog_id=catalog_id) | Q(catalog__isnull=True, material__isnull=False)
# 即：挂该章节的片段（课件/讲稿/资料）+ 未挂章节的资料片段（天然通用）
```

权衡说明：现注释刻意排除未挂章节资料以防"遗留测试上传"混入。改为纳入的理由——通用资料（教材/考纲）挂章节本就不自然，教师无此操作习惯；测试上传的资料通常未解析或会被清理；`qa_open` 与行级过滤仍然生效。风险可控且省去 Material.scope 字段与教师额外操作。

### 3.4 QASession 会话模型（P2，迁移 knowledge/0011）

```python
class QASession(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "进行中"
        ARCHIVED = "archived", "已归档"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="qa_sessions")
    catalog = models.ForeignKey("courses.Catalog", on_delete=models.CASCADE,
                                related_name="qa_sessions", null=True, blank=True)  # null=课程级
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="qa_sessions")
    title = models.CharField("标题", max_length=60, default="")        # 首问截 30 字，可改名
    status = models.CharField(max_length=12, choices=Status.choices,
                              default=Status.ACTIVE, db_index=True)
    summary = models.TextField("滚动摘要", blank=True)
    summary_upto_turn = models.IntegerField("已摘要至轮次", default=0)
    # 兼容：旧前端/移动端仍传 session 字符串，按 (course, student, legacy_key) 找到或创建会话
    legacy_key = models.CharField("旧 session 字符串", max_length=64, default="", db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["course", "student", "legacy_key"],
                                    condition=~Q(legacy_key=""), name="uniq_qasession_legacy")
        ]
        ordering = ["-updated_at"]
```

**QARecord 扩展（同迁移）**：

```python
    session_ref = models.ForeignKey(QASession, on_delete=models.SET_NULL,
                                    related_name="records", null=True, blank=True)
    turn_index = models.IntegerField("会话内轮次", default=0, db_index=True)
    rewritten_question = models.CharField("改写后检索问题", max_length=500, blank=True)
    context_snapshot = models.JSONField("上下文快照", default=dict, blank=True)
    # {rewritten, budgets:{rag,history}, degraded_level:0-4,
    #  chunks:[{n, chunk_id, source, catalog_id, page, score}], fallback_used:bool}
    feedback = models.SmallIntegerField("学生反馈", default=0)  # 1 有用 / -1 无用 / 0 未评
```

- `session` 字符串字段保留只读（历史数据），新记录写入 session_ref + turn_index。
- **回填（RunPython）**：按 (course, student, session 字符串, catalog) 归组旧 QARecord 建 QASession（title=首问 30 字，legacy_key=session 串），回填 session_ref 与按 created_at 排序的 turn_index；session 为空的旧记录不建会话（保持 legacy 只读展示）。

### 3.5 配置与枚举

- `settings.AI_CHAT_CONTEXT_WINDOW = _ai_env_int("AI_CHAT_CONTEXT_WINDOW", 32768)`：chat 模型上下文窗口，预算计算的基准（管理端不加字段，env 即可）。
- `settings.AI_QA_RAG_TOKEN_BUDGET = _ai_env_int(..., 3000)`：检索资料注入预算（token）。
- `settings.AI_QA_SUMMARY_TRIGGER = 12` / `AI_QA_SUMMARY_KEEP_RECENT = 6`：摘要触发轮次 / 保留原文轮数。
- `AICallLog.Scene` 新增：`QA_REWRITE = "qa_rewrite", "问答查询改写"`、`QA_SUMMARY = "qa_summary", "会话摘要"`。

---

## 4. 检索层设计

### 4.1 查询改写（P0）

新增 `rewrite_query_for_retrieval(question, history) -> str`（services.py）：

- 触发：history 非空。无历史直接返回原问题（口语化单问不改写，避免误改）。
- 调用：chat provider，`temperature=0, enable_thinking=False`，10s 超时（try 包裹，任何异常回退原问题）。
- Prompt：

```
你是检索查询改写器。根据对话历史，把学生的最新问题改写成可独立检索的完整问题：
补全指代（这个/它/第N个/上面说的）、保留专业术语、不回答问题本身。
只输出改写后的问题，单行，不要解释。

对话历史：
{最近 3 轮，每轮 问:... 答:...(截 200 字)}
最新问题：{question}
```

- 结果截 500 字，为空/与历史无关异常输出时回退原问题。
- 改写结果只用于检索（embed + 重排 query），**不进 messages、不展示**；存 `QARecord.rewritten_question` 与 context_snapshot，前端 meta 事件可提示"已按上下文理解检索"。
- 埋点 scene=QA_REWRITE。

### 4.2 统一候选池与同页融合（P1）

`_search_relevant_chunks` 调整：

1. **query 用改写后问题**（4.1）；召回/重排/阈值/相对截断逻辑不变。
2. **候选池**：course 过滤 + 可见性过滤（学生：material qa_open + 班级集合；ppt is_active + 章节已发布；script video 已发布 + 章节已发布）+ 章节语义过滤（3.3）。
3. **同页融合**（重排截断后）：按 `(catalog_id, page)` 分组，同页同时命中 ppt 与 script 片段时合并为一个注入单元：内容 = PPT 原文 + 讲稿（合并超 800 字时保留高分来源），source 记两者。信息不丢、编号不重复占用。
4. top_k 仍为 5，但按"注入单元"计（融合后可能不足 5，不再补足——质量优先）。

### 4.3 班级资料自动解析（P0，纯后端）

`_resolve_qa_scope` 改造：学生且未显式传 classroom 时——

```python
enrolled_ids = ClassStudent.objects.filter(
    student=user, learn_status=ClassStudent.LearnStatus.ACTIVE,
    classroom__courses=course,
).values_list("classroom_id", flat=True)
```

`knowledge_qa(_stream)` 的 `classroom_id` 形参扩为 `classroom_ids: list | None`；`search_chunks` 学生过滤改为：

```python
material_q &= Q(material__classroom__isnull=True) | Q(material__classroom_id__in=classroom_ids or [])
```

显式传 classroom 的旧行为保留（单班级列表）。教师/管理端不过滤（现状）。

### 4.4 语义切分（P1）

新增 `split_text_semantic(raw: str, size=500, overlap=60) -> list[str]`（knowledge/services.py 或 services.py 内）：

1. 按空行/换行切段落，顺序聚合到 size 内成片段；
2. 单段落超 size：按 `。！？；` 断句再聚合，仍超则硬切；
3. 相邻片段尾部重叠 overlap 字符（在片段边界处向前截取，不跨段落中间截断）。

`ingest_material` 与 `rebuild_vectors._rebuild_one` 同步换用（同一函数，保证入库与重建口径一致）；PPT/讲稿页级粒度不变。

### 4.5 追问检索兜底（P2）

当前问题检索结果为空（阈值过滤后 0 条）且会话存在上一轮 `context_snapshot.chunks` 时：

- 按 snapshot 中 chunk_id 捞出前 3 个片段内容，作为独立注入段「上一轮参考」（固定预算 800 token 内），source 标 `prev`；
- 在 context_snapshot 记 `fallback_used=True`。
- 有改写（4.1）后此路径触发率应显著降低，作为双保险保留。

---

## 5. 注入层设计（P0）

### 5.1 结构化上下文

`_gather_course_context` 返回值由 `(context_str, cited)` 改为 `(context_str, cited, snapshot)`。片段格式：

```
【资料1｜课件｜第4章 网络层｜P5】
{content}

【资料2｜课件+讲稿｜第4章 网络层｜P5】
{content}

【资料3｜课程资料｜《复习提纲.pdf》】
{content}

【资料4｜上一轮参考｜第4章 网络层课件｜P7】   # 仅追问兜底时
{content}
```

- 标头要素：编号｜来源类型｜章节标题（资料无章节时为文件名）｜页码。
- cited 协议扩展：`[{n, chunk_id, source, material_name, page, snippet}]`，`n` 与注入编号一一对应——模型看到的编号 = 前端展示的编号，这是引用可回链的基础。

### 5.2 预算分配与边界截断

- 统一 token 估算器：

```python
def est_tokens(text: str) -> int:
    """中英混合保守估算：CJK 约 1.5 字/token，其余约 4 字符/token。"""
```

- 预算（按 `AI_CHAT_CONTEXT_WINDOW` 计算，默认 32768）：

| 段 | 预算 | 说明 |
|---|---|---|
| system + 模板 | 600 | 固定预留 |
| RAG 注入 | `AI_QA_RAG_TOKEN_BUDGET`=3000 | 片段按相关度序填入，整片段取舍（不再半截切断） |
| 输出预留 | 2048 | max_tokens |
| 安全余量 | 512 | |
| **历史** | 窗口 − 以上各项 | 32768 下约 26600 |

- 单片段自身限长（资料片段 500 字 / 讲稿页通常 <400 字，融合单元 800 字上限），截断一律在片段边界。

### 5.3 system prompt 重写

```
你是一位严谨、耐心的课程助教，负责根据教师提供的课程资料回答学生问题。

【回答依据与优先级】
1. 优先依据「课程资料片段」回答；片段按【资料N】编号，注明了来源与页码。
2. 来源冲突时：课件 > 讲解稿 > 课程资料；资料与常识冲突时以资料为准并说明。
3. 使用了某资料的内容时，在该句末尾标注来源编号，格式如 [1][3]。
4. 资料不足以回答时，明确说明"课程资料中暂未覆盖该内容"，可基于通识简要回答并提示仅供参考。

【回答风格】
- 循序渐进：先给定义/结论，再展开解释，适当分点。
- 学生追问时结合对话上下文，保持连贯。
```

非流式 `knowledge_qa` 同步换用。`course_context` 为空时 user 文本保持"（本课程暂无可引用的课程资料）"。

### 5.4 引用回链（前端，P0 后端协议 + P1 前端交互）

- 后端 cited 带 `n` 后，前端 `renderAiMarkdown` 后处理：回答文本中的 `[N]` 渲染为可点上标，点击高亮/展开对应来源卡片（snippet 全文），课件来源可跳章节学习页对应 P 页。
- `groupCitedSources` 保留编号数组，来源 tag 前加编号徽章。

---

## 6. 上下文管理设计

### 6.1 会话生命周期（P2）

- 创建：ask 时 `session_id` 缺省/为 0 → 新建 QASession（course, catalog=请求 catalog 或 null, student, title=首问 30 字）；meta 事件首帧返回 `session_id`。
- 续用：前端持久化 session_id（AI 助教页现有会话制自然接入；章节 Dock 进入章节时拉该章最近 active 会话续用，见 §7）。
- 兼容：请求只传旧 session 字符串时，按 `(course, student, legacy_key=session)` get_or_create——移动端/旧前端无感迁移，历史自动接续。
- 归档/删除：PATCH status=archived（列表默认只出 active）；DELETE 硬删会话及其 records（学生本人）。
- turn_index：每落一条 QARecord = session 内 max(turn_index)+1。

### 6.2 历史装配（P0 重构 build_qa_history → build_conversation_context）

输入：session（或 P0 阶段的临时 (course, student, session 串)）、history_token_budget。

输出 messages 段（按序）：

1. **摘要段**（P2，有 summary 时）：`{"role": "system", "content": f"本对话此前内容的摘要（供你保持连贯）：\n{summary}"}`；
2. **原文轮**：从最新轮往旧取，逐轮扣除 `est_tokens(问)+est_tokens(答)`，预算耗尽即止；单轮超 4000 字符仍走现首尾裁剪。

P0 阶段无 QASession，先实现"预算按 token 估算 + 从最新往旧装填"（现状是从最旧取 10 轮再裁，超预算时砍的是最新轮的上下文）；P2 接入摘要与 turn_index。

### 6.3 滚动摘要（P2）

- 触发：`session.records.count() > AI_QA_SUMMARY_TRIGGER(12)` 且 `count - summary_upto_turn >= 6`。
- 时机：流式回答全文产出后、done 事件前（不阻塞正文显示）；非流式 ask 在 record 保存后同步执行。失败静默（保留旧摘要）。
- Prompt：

```
你在维护一段师生问答对话的滚动摘要，供后续对话保持连贯。
把"旧摘要 + 新增问答轮"压缩为不超过 400 字的新摘要。保留：学生问过的问题主题、
助手给出的关键结论与定义、学生表现出的薄弱点、尚未解决的疑问。丢弃寒暄与重复。

旧摘要：{summary or "（无）"}
新增问答：
{待压缩轮次，每轮 问:... 答:...(各截 300 字)}
只输出新摘要本身。
```

- 写回 `summary` + `summary_upto_turn = 已压缩的最大 turn_index`；埋点 scene=QA_SUMMARY。
- 装配时摘要段 + `summary_upto_turn` 之后的原文轮（最多保留 AI_QA_SUMMARY_KEEP_RECENT=6 轮原文，超出部分信赖摘要）。

### 6.4 分级降级（P0）

`token_limit_error_hint` 触发时不再一次丢光，按级重试（每级重建 messages 重新调用，最多 3 次降级）：

| 级别 | 历史策略 |
|---|---|
| L1 | 丢弃最旧 50% 原文轮 |
| L2 | 仅保留最近 2 轮原文 |
| L3 | 仅摘要段，无原文轮 |
| L4 | 完全无历史（现状行为） |

SSE 事件 `history_dropped` 扩展为 `{type:"history_dropped", level}`，前端按级别提示"对话过长，已省略部分早期内容"。

### 6.5 检索快照与审计（P1）

每条 QARecord 写 `context_snapshot`（结构见 3.4）。用途：

- 追问兜底（4.5）；
- 教师端/管理端排查"回答依据了什么"；
- 离线分析：检索为空率 = snapshot.chunks 为空的记录占比；改写命中率；降级分布（degraded_level）。

注意 snapshot 只存 id/分数/编号等元数据与 snippet 摘要（沿用现有指纹思路），不存全文，控制行体积。

---

## 7. API 变更

### 7.1 ask-stream（POST /api/qa-records/ask-stream/）

请求体：

```json
{ "course": 1, "catalog": 12, "session_id": 34, "session": "旧字符串兼容",
  "question": "...", "image": "data:image/..." }
```

- `session_id` 优先；只传 `session` 字符串走 legacy get_or_create；都不传新建会话。
- SSE 事件序列：`meta → delta* → (history_dropped) → done`。
- **meta 扩展**：`{type:"meta", session_id, rewritten_question, cited:[{n, chunk_id, source, material_name, page, snippet}]}`。rewritten 与原问题相同时置空。
- `history_dropped` 增加 `level` 字段（1-4）。

### 7.2 ask（非流式，移动端用）

同步支持 session_id / 改写 / 新 system prompt；响应 data 增加 `session_id`、`rewritten_question`。移动端不发版行为不变。

### 7.3 QASession 端点（P2，knowledge 新 ViewSet）

| 端点 | 说明 |
|---|---|
| GET /api/qa-sessions/?course=&catalog= | 我的会话列表（catalog 缺省=课程级；含 record_count、last_message_at、title） |
| POST /api/qa-sessions/ {course, catalog?} | 新建会话 |
| PATCH /api/qa-sessions/{id}/ {title?, status?} | 改名 / 归档 |
| DELETE /api/qa-sessions/{id}/ | 删除会话及记录（仅本人） |
| GET /api/qa-sessions/{id}/records/ | 会话内问答（升序） |

权限：IsAuthenticated + 行级（学生本人；教师可见自己课程下全部会话只读列表——沿用 QARecord 现有教师视角口径，教师端 CourseQA 不受影响）。

### 7.4 反馈端点（P2）

`POST /api/qa-records/{id}/feedback/ {value: 1 | -1 | 0}`：仅本人记录可评，幂等覆盖。

---

## 8. 前端改造

### 8.1 组件化（P2）：`components/qa/QaPanel.vue`

现状三端四页各自实现 SSE 读取/节流渲染/来源展示，逻辑重复且已出现不一致（Learning dock 无历史、无会话管理）。抽统一组件：

- props：`courseId`、`catalogId`（null=课程级模式）、`embedded`（dock 窄版样式开关）
- 内置：会话列表/新建/切换/改名/归档、消息流式渲染、图片提问（vision-capability）、来源展示与引用跳转、反馈按钮、降级提示
- 接入点：student/KnowledgeQA.vue、teacher/CourseQA.vue、student/Learning.vue dock；移动端 app 暂不动（legacy 兼容）。

### 8.2 章节 Dock 行为（P2）

- 打开章节（openChapter）→ 拉 `GET /qa-sessions/?course=&catalog=` 最近 active 会话续聊；无则空态（首次提问时后端建会话）。
- 切章节 → 切换/清空到目标章节会话（session 与 catalog 绑定，串话从机制上消除）；chatMessages 随会话切换。
- dock 顶部加"新会话 + 历史"按钮（复用 QaPanel 的会话面板）。
- 刷新续聊：session_id 存内存即可（进入章节重新拉取），不需 localStorage。

### 8.3 引用交互（P1）

- 回答中 `[N]` → 上标链接，点击展开对应来源卡片（snippet + 章节/页码）；课件来源提供"查看课件页"跳转（Learning 页对应 catalog 的 P 页）。
- 来源 tag 增加来源类型徽章（课件/讲稿/资料），与注入标头口径一致。

### 8.4 细节项

- meta.rewritten_question 非空时，assistant 消息下显示一行小字"已按上下文理解检索：{rewritten}"（可折叠）。
- history_dropped level ≥ 1 时显示"对话较长，已省略部分早期内容"。
- 反馈按钮（有用/无用）在回答完成后显示（P2）。

---

## 9. 评估与质量闭环

1. **eval_rag 对齐线上（P0）**：`_collect_samples` 改用 `_search_relevant_chunks`（重排+阈值编排），新增 `--catalog` 跑章节级用例；报告增加"检索为空率"（cited 为空的样本占比）。
2. **回归用例集**：为每门主课维护 10-20 题（含 3-5 个追问/指代题），改造前后各跑一遍对比 faithfulness / answer_relevancy / context_precision。
3. **线上指标**（P1 起可从 context_snapshot 统计）：检索为空率、改写触发率、降级分布、反馈好评率。纳入后续管理端统计（本设计不含看板 UI）。

---

## 10. 分批实施计划

### P0 —— 无迁移批（预计 1 次提交，纯后端为主）

内容：查询改写（4.1）、班级资料自动解析（4.3）、结构化注入 + 编号 + 新 system prompt（5.1/5.3）、token 估算 + 预算分配 + 片段边界截断（5.2）、历史装填改"从最新往旧"（6.2 前半）、分级降级（6.4）、eval_rag 对齐（§9.1）、meta 事件扩展 rewritten（7.1 部分）、图片默认文案问题跳过检索（小修：带图且 question 为默认文案时不做 RAG）。

风险：低（无表结构变更；prompt 变更影响回答风格，用回归用例对比验收）。
回滚：整批 revert 即可。

### P1 —— 检索侧迁移（knowledge/0010）

内容：KnowledgeChunk.source/video/catalog + 回填、ingest_video_scripts + 讲稿生成/编辑触发 + ingest_scripts 回填命令、search_chunks 候选池扩展（章节+通用+script 可见性）、同页融合（4.2）、语义切分（4.4）、context_snapshot 落库（6.5）、rebuild_vectors 覆盖 script、前端引用编号交互（8.3）。

风险：中（迁移 + 回填；讲稿入库改变检索结果分布）。
验证：迁移后 chunk 计数对账；ingest_scripts 抽样核对；eval_rag 章节级对比。
回滚：迁移可逆（删字段）；功能开关——settings.AI_QA_DISABLE_SCRIPT_SOURCE=1 时讲稿片段不参与检索（QA 侧自动退回原文限量兜底，P1 实施时采用的精确开关名）。

### P2 —— 会话侧迁移（knowledge/0011）

内容：QASession + QARecord 扩展字段 + 旧数据回填、会话 API（7.3）、legacy session 兼容接入、滚动摘要（6.3）、追问快照兜底（4.5）、反馈端点与按钮、QaPanel 组件化与三端接入、章节 Dock 会话重做（8.2）。

风险：中（前端改动面大；会话回填量大——按 10 万条 QARecord 估算回填数分钟，可分批）。
回滚：前端保留旧页面开关（路由级）；后端 session 字符串路径长期保留。

---

## 11. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 查询改写增加首 token 延迟（约 300-500ms） | 仅多轮触发；enable_thinking=False + temperature=0；超 10s 静默回退；SSE meta 在改写后才发，前端等待动画已有 |
| 改写误改（问题被曲解） | 仅检索用途、不进对话；rewritten 落库可审计；回退原问题策略 |
| 讲稿入库后检索结果变化（原 PPT 页排名波动） | 同页融合保证同页信息只增不减；eval_rag 对比门禁 |
| 摘要质量不稳 | 摘要只作 system 提示、原文轮仍保留最近 6 轮；失败保留旧摘要 |
| 候选池扩大引入噪声（通用资料混入章节提问） | 重排阈值与相对截断仍在；eval_rag 章节级用例回归 |
| context_snapshot 行体积膨胀 | 只存元数据与 snippet 摘要（≤1KB/行） |

---

## 12. 验收标准（定量）

1. 追问/指代题（预设 5 题）：cited 非空率 ≥ 80%（现状约 0-20%）。
2. eval_rag 同用例集：context_precision 与 faithfulness 不低于改造前，章节级用例提升 ≥ 0.1。
3. 讲稿治理：课程级提问的注入中不再有"未命中检索的讲稿"（context_snapshot.chunks 全部来自检索/融合/快照）；AICallLog QA 场景 prompt_tokens 中位数下降 ≥ 20%。
4. 长会话：连续 20 轮问答不出现 L4 降级；出现降级时 history_dropped.level ≤ 2 占比 ≥ 90%。
5. 引用回链：含 [N] 标注的回答占比 ≥ 60%，人工抽检 20 条标注与 cited 映射一致率 100%。
6. 兼容：移动端（未发版）ask 提问正常，历史接续；旧 session 字符串提问正常归入会话。

---

## 附：改造点与文件对照

| 文件 | 改动 |
|---|---|
| backend/apps/ai/services.py | 改写函数、_gather_course_context 重构、context_builder、build_conversation_context、分级降级、ingest_video_scripts、语义切分、摘要 |
| backend/apps/ai/vectorstore.py | search_chunks 候选池（catalog 冗余字段、script 可见性、班级集合）、同页融合 |
| backend/apps/knowledge/models.py | KnowledgeChunk.source/video/catalog、QASession、QARecord 扩展 |
| backend/apps/knowledge/views.py | _resolve_qa_scope 班级解析、ask/ask-stream session_id、QASessionViewSet、feedback |
| backend/apps/knowledge/serializers.py | QASessionSerializer、QARecord 扩展字段 |
| backend/apps/knowledge/services.py | rebuild_vectors 覆盖 script |
| backend/apps/knowledge/management/commands/ingest_scripts.py | 新增回填命令 |
| backend/apps/knowledge/management/commands/eval_rag.py | 对齐线上检索编排 + --catalog |
| backend/apps/ai/models.py | Scene 新增 QA_REWRITE/QA_SUMMARY |
| backend/config/settings.py | AI_CHAT_CONTEXT_WINDOW / AI_QA_RAG_TOKEN_BUDGET / 摘要参数 |
| frontend/src/components/qa/QaPanel.vue | 新增统一问答面板 |
| frontend/src/views/student/{KnowledgeQA,Learning}.vue、teacher/CourseQA.vue | 接入 QaPanel、章节会话、引用交互 |
| frontend/src/utils/{markdown,cited-sources}.js | [N] 上标解析、编号徽章 |
