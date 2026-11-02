from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.models import BaseModel


class AICapabilityConfig(BaseModel):
    """按能力（对话 / 向量 / 重排序 / 语音）的平台级大模型配置。

    每项能力独立选择服务商、接口与凭证，可混搭（如对话用 DeepSeek、
    向量与语音用通义千问）。密钥使用项目 SECRET_KEY 派生密钥加密保存。
    """

    class Capability(models.TextChoices):
        CHAT = "chat", "对话生成"
        EMBED = "embed", "向量化"
        RERANK = "rerank", "重排序"
        TTS = "tts", "语音合成"

    class Provider(models.TextChoices):
        DEEPSEEK = "deepseek", "DeepSeek"
        TONGYI = "tongyi", "通义千问"
        OPENAI = "openai", "本地模型服务"
        LOCAL = "local", "系统内置模型"
        MOCK = "mock", "模拟模式"

    # 各能力可选的服务商白名单：
    # - DeepSeek 无 embedding / TTS 接口；
    # - 模拟模式（Mock）不产生真实向量/音频，且 64 维假向量会污染真实向量空间，
    #   向量化与语音合成仅开放通义千问与本地模型服务（OpenAI 兼容）；
    # - 系统内置模型（local）：向量化内置 BGE-M3、重排序内置 Qwen3-Reranker-0.6B，
    #   权重系统内推理（apps/ai/local_models.py），无需 Key/接口地址；
    #   对话与语音暂无内置实现，不开放；
    # - 重排序开放通义千问（DashScope 原生 rerank 端点）与系统内置模型
    #   （OpenAI 兼容生态无统一 /rerank 规范，compatible-mode 实测 404；
    #   Mock 无法对真实向量候选打分，开放无意义）；
    # - 对话（chat）保留模拟模式，便于无 Key 环境下演示流程。
    # 序列化层与管理端测试接口均按此校验，防止 API 层绕过前端下拉限制。
    CAPABILITY_PROVIDERS = {
        "chat": ("deepseek", "tongyi", "openai", "mock"),
        "embed": ("tongyi", "openai", "local"),
        "rerank": ("tongyi", "local"),
        "tts": ("tongyi", "openai"),
    }

    class TestStatus(models.TextChoices):
        UNTESTED = "untested", "未测试"
        SUCCESS = "success", "连接成功"
        FAILED = "failed", "连接失败"

    capability = models.CharField(
        "能力", max_length=16, choices=Capability.choices, unique=True
    )
    provider = models.CharField(
        "服务商", max_length=20, choices=Provider.choices, default=Provider.MOCK
    )
    enabled = models.BooleanField("启用配置", default=False)
    base_url = models.URLField("接口地址", max_length=500, blank=True)
    model_name = models.CharField("模型名称", max_length=120, blank=True)
    timeout = models.PositiveIntegerField(
        "超时(秒)", null=True, blank=True,
        help_text="单次请求超时；留空按环境变量/默认值。本地模型推理慢建议调大(讲稿120+/语音180+)",
    )
    voice = models.CharField(
        "发音人", max_length=64, blank=True, default="",
        help_text="TTS 发音人/说话人ID；留空按 AI_TTS_VOICE 或 Cherry。仅语音合成有效",
    )
    supports_vision = models.BooleanField(
        "支持图片(多模态)", default=False,
        help_text=(
            "仅对话能力有效：开启后学生/教师端问答显示图片上传入口；"
            "所用模型无视觉能力时请保持关闭，否则发送图片会被接口拒绝"
        ),
    )
    api_key_ciphertext = models.TextField("加密 API Key", blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_capability_config_updates",
        verbose_name="最后修改人",
    )

    class Meta:
        verbose_name = "大模型能力配置"
        verbose_name_plural = verbose_name

    def set_api_key(self, value: str):
        from .secrets import encrypt_secret

        self.api_key_ciphertext = encrypt_secret(value) if value else ""

    def get_api_key(self) -> str:
        from .secrets import decrypt_secret

        return decrypt_secret(self.api_key_ciphertext) if self.api_key_ciphertext else ""

    @property
    def api_key_configured(self):
        return bool(self.api_key_ciphertext)

    # 配置变更留痕跟踪的字段（API Key 只记存在性，绝不落密钥内容）
    _TRACKED_FIELDS = (
        ("provider", "服务商"),
        ("enabled", "启用"),
        ("base_url", "接口地址"),
        ("model_name", "模型名称"),
        ("timeout", "超时(秒)"),
        ("voice", "发音人"),
        ("supports_vision", "支持图片"),
    )

    def tracked_snapshot(self) -> dict:
        """受跟踪字段快照（api_key 只存存在性，不取密钥内容），供保存前后对比。

        审计双轨已合并：字段级 diff 由管理端视图在保存前后各取一次本快照得出，
        随 AdminActionLog.ai_config_save 一并落库（单一审计轨）。
        """
        snapshot = {field: getattr(self, field, None) for field, _ in self._TRACKED_FIELDS}
        snapshot["api_key"] = bool(self.api_key_ciphertext)
        return snapshot

    @classmethod
    def diff_snapshots(cls, before: dict, after: dict) -> list:
        """对比两份 tracked_snapshot，返回字段级变更 [{field,label,old,new}]。

        API Key 只记「已配置/未配置」；布尔 False 等假值按既有约定记空串
        （str(value or "")）。无差异返回空列表。
        """
        labels = dict(cls._TRACKED_FIELDS)
        labels["api_key"] = "API Key"
        changes = []
        for field, label in labels.items():
            old_value = before.get(field)
            new_value = after.get(field)
            if old_value == new_value:
                continue
            if field == "api_key":
                changes.append({
                    "field": field,
                    "label": label,
                    "old": "已配置" if old_value else "未配置",
                    "new": "已配置" if new_value else "未配置",
                })
            else:
                changes.append({
                    "field": field,
                    "label": label,
                    "old": str(old_value or ""),
                    "new": str(new_value or ""),
                })
        return changes

    def save(self, *args, **kwargs):
        """保存配置。

        变更留痕已合并到管理端操作审计（AdminActionLog.ai_config_save，
        字段级 diff 存 new_value.changes）：模型层不再双写
        AICapabilityChangeLog（该表与端点保留作历史记录，已废弃）。
        """
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_capability_display()} · {self.get_provider_display()} ({'启用' if self.enabled else '停用'})"


class AICallLog(BaseModel):
    """AI 调用流水（Provider 层统一埋点，见 apps/ai/calllog.py）。

    覆盖全部调用路径：外部服务（DeepSeek/通义/OpenAI）、本地 OpenAI 兼容
    服务（vLLM/Ollama/LocalAI）、系统内置本地模型（BGE-M3/Qwen3-Reranker）
    与模拟模式（is_mock=True）。

    计量口径分两类，统计时不能混：
    - HTTP 类服务：响应 usage 解析出 prompt/completion/total token；
    - 进程内本地模型：无 token 概念，以 item_count（条数）与字符数计量。

    内容留痕只存输入指纹（sha256）与截断摘要，不落 prompt/响应全文。
    """

    class Scene(models.TextChoices):
        CATALOG_GEN = "catalog_gen", "目录识别"
        SCRIPT_GEN = "script_gen", "讲解稿生成"
        TTS = "tts", "语音合成"
        MATERIAL_EMBED = "material_embed", "教辅资料向量化"
        PPT_EMBED = "ppt_embed", "课件向量化"
        QA = "qa", "知识库问答"
        QA_REWRITE = "qa_rewrite", "问答查询改写"
        QA_SUMMARY = "qa_summary", "问答会话摘要"
        QUESTION_GEN = "question_gen", "题目生成"
        GRADING = "grading", "作业批改"
        ANALYTICS = "analytics", "学情分析"
        CHAPTER_SUMMARY = "chapter_summary", "章节学习总结"
        TTS_PREVIEW = "tts_preview", "配音试听"
        CONNECTION_TEST = "connection_test", "连接测试"
        VECTOR_REBUILD = "vector_rebuild", "向量重建"
        RAG_EVAL = "rag_eval", "检索评测"
        OTHER = "other", "其他"

    capability = models.CharField(
        "能力", max_length=16, choices=AICapabilityConfig.Capability.choices, db_index=True
    )
    provider = models.CharField("服务商", max_length=20, blank=True, db_index=True)
    model_name = models.CharField("模型", max_length=120, blank=True)
    scene = models.CharField(
        "业务场景", max_length=24, choices=Scene.choices, default=Scene.OTHER, db_index=True
    )
    success = models.BooleanField("调用成功", default=False, db_index=True)
    is_mock = models.BooleanField(
        "Mock 返回", default=False, help_text="真实调用失败回退模拟、或未配置 Key 直接走 Mock"
    )
    error = models.CharField("错误摘要", max_length=300, blank=True)
    latency_ms = models.PositiveIntegerField("耗时(毫秒)", default=0)
    attempts = models.PositiveIntegerField("尝试次数", default=1)
    prompt_tokens = models.PositiveIntegerField("输入token", null=True, blank=True)
    completion_tokens = models.PositiveIntegerField("输出token", null=True, blank=True)
    total_tokens = models.PositiveIntegerField("token合计", null=True, blank=True)
    item_count = models.PositiveIntegerField(
        "条数", null=True, blank=True, help_text="embed/TTS 的文本条数；本地内置模型的主计量口径"
    )
    input_chars = models.PositiveIntegerField("输入字符数", null=True, blank=True)
    output_chars = models.PositiveIntegerField("输出字符数", null=True, blank=True)
    input_digest = models.CharField(
        "输入指纹", max_length=64, blank=True, help_text="输入内容 sha256，用于判重与追溯，不落原文"
    )
    input_preview = models.CharField(
        "输入摘要", max_length=200, blank=True, help_text="输入内容截断展示；敏感内容不落全文"
    )
    trace_id = models.CharField(
        "追溯ID", max_length=32, blank=True, db_index=True, help_text="同一次业务请求的多次调用共享"
    )
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_call_logs",
        verbose_name="触发人",
    )
    course = models.ForeignKey(
        "courses.Course",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_call_logs",
        verbose_name="关联课程",
    )

    class Meta:
        verbose_name = "AI 调用流水"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at", "scene"]),
            models.Index(fields=["-created_at", "capability"]),
        ]

    def __str__(self):
        return f"{self.get_capability_display()} · {self.get_scene_display()} · {'成功' if self.success else '失败'}"


class AITask(BaseModel):
    """AI 异步任务（班级学情分析 / 章节学习总结 / AI 多类型生题）。

    三个长时 AI 功能共用：教师端班级学情分析、学生端章节学习总结、
    教师端 AI 生题（question_gen_ai.run_question_gen）。提交即返回
    task_id，后台 daemon 线程执行（执行器见 apps/ai/tasks.py，
    业务流水见 apps/ai/analytics_ai.py 与 apps/questions/question_gen_ai.py），
    进度与结果持久化在本行，前端轮询 GET /api/ai-tasks/<id>/ 展示，
    刷新/重登不丢。

    幂等口径（无全局唯一约束，与「force 重新生成新建一版」兼容）：
    - 章节总结：同 (student, catalog) 递增 version，查询取最大版本；
      进行中/排队中的任务由部分唯一索引 uniqi_active_chapter_summary 防并发双跑；
    - 班级分析：version 恒为 1，提交频率由业务层 DB 判定（同班级 10 分钟 1 次）；
    - AI 生题：同 (triggered_by, course) 只允许一条 pending/running
      （uniq_active_question_gen），生成配置（groups/objective）存 progress，
      完成后 result.batch_id 指向 QuestionDraftBatch 待入库池。
    """

    class TaskType(models.TextChoices):
        CLASS_ANALYTICS = "class_analytics", "班级学情分析"
        CHAPTER_SUMMARY = "chapter_summary", "章节学习总结"
        QUESTION_GEN = "question_gen", "题目生成"
        COURSE_REUSE = "course_reuse", "课程复用"
        SCRIPT_GEN = "script_gen", "章节讲稿"
        AUDIO_GEN = "audio_gen", "章节配音"
        PPT_PARSE = "ppt_parse", "课件解析"
        EMBED_INGEST = "embed_ingest", "向量入库"

    class Status(models.TextChoices):
        PENDING = "pending", "排队中"
        RUNNING = "running", "进行中"
        SUCCESS = "success", "已完成"
        FAILED = "failed", "失败"
        CANCELLED = "cancelled", "已取消"

    task_type = models.CharField(
        "任务类型", max_length=24, choices=TaskType.choices, db_index=True
    )
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    version = models.IntegerField(
        "版本", default=1, help_text="章节总结 force 重试递增进；班级分析恒为 1"
    )
    # {"stage": "...", "done": n, "total": n, "message": "..."}，随流水推进更新
    progress = models.JSONField("进度", default=dict, blank=True)
    result = models.JSONField("结果", default=dict, blank=True)
    error = models.CharField("错误摘要", max_length=300, blank=True)
    # 业务关联（按 task_type 使用其中一两个，均允许为空）
    course = models.ForeignKey(
        "courses.Course",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_tasks",
        verbose_name="关联课程",
    )
    classroom = models.ForeignKey(
        "classroom.ClassRoom",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="ai_tasks",
        verbose_name="关联班级",
    )
    catalog = models.ForeignKey(
        "courses.Catalog",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="ai_tasks",
        verbose_name="关联章节",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="ai_tasks",
        verbose_name="总结对象学生",
    )
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="triggered_ai_tasks",
        verbose_name="触发人",
    )
    started_at = models.DateTimeField("开始时间", null=True, blank=True)
    finished_at = models.DateTimeField("完成时间", null=True, blank=True)

    # ===== 队列化扩展字段（AI 长任务队列，见 docs/AI长任务队列化改造方案.md §4）=====
    # 作业参数：{ppt_id, ppt_version, limit, force, voice, only_pages, ...}；
    # 队列层只写 status/心跳等元信息，progress 归业务流水线独占（评审 C5）。
    payload = models.JSONField("作业参数", default=dict, blank=True)
    # 越小越先：ppt_parse=50（教师正等着上传），教师生成=100，后台衍生=200
    priority = models.IntegerField("优先级", default=100)
    dedupe_key = models.CharField("去重键", max_length=120, null=True, blank=True, db_index=True)
    attempts = models.IntegerField("已尝试次数", default=0)
    max_attempts = models.IntegerField("最大尝试次数", default=3)
    # 退避重试用；空 = 立即可跑
    next_run_at = models.DateTimeField("下次可执行时间", null=True, blank=True)
    claimed_by = models.CharField("认领者", max_length=64, blank=True)
    heartbeat_at = models.DateTimeField("心跳时间", null=True, blank=True)
    cancel_requested = models.BooleanField("请求取消", default=False)
    # C1：worker 重建上下文后回写；配额结算按它 count AICallLog（评审 C7）
    trace_id = models.CharField("调用链 ID", max_length=32, null=True, blank=True)
    # ppt_parse 的归属键：一个章节可有多个 PPT 版本，去重按 ppt 不按 catalog（自审 F3）
    ppt = models.ForeignKey(
        "courses.PPTResource",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="ai_tasks",
        verbose_name="关联课件",
    )

    class Meta:
        verbose_name = "AI 异步任务"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["task_type", "status", "-created_at"]),
            models.Index(fields=["student", "catalog", "-version"]),
            models.Index(fields=["status", "priority", "next_run_at", "id"]),
            models.Index(fields=["claimed_by", "heartbeat_at"]),
        ]
        constraints = [
            # 章节总结防并发双跑：同一学生同一章节只允许一条进行中/排队中任务
            models.UniqueConstraint(
                fields=["task_type", "student", "catalog"],
                condition=Q(task_type="chapter_summary", status__in=["pending", "running"]),
                name="uniqi_active_chapter_summary",
            ),
            # AI 生题防重复提交：同一教师同一课程只允许一条进行中/排队中任务
            # （triggered_by/course 均为可空 SET_NULL，SQLite 下 NULL 互不冲突，语义可接受）
            models.UniqueConstraint(
                fields=["task_type", "triggered_by", "course"],
                condition=Q(task_type="question_gen", status__in=["pending", "running"]),
                name="uniq_active_question_gen",
            ),
            # 讲稿/配音防双跑：同一章节同类型同时只能有一条 pending/running。
            # MySQL 侧由迁移以"生成列 + 普通唯一索引"落地（本条件约束被静默跳过）。
            models.UniqueConstraint(
                fields=["task_type", "catalog"],
                condition=Q(task_type__in=["script_gen", "audio_gen"], status__in=["pending", "running"]),
                name="uniq_active_catalog_gen",
            ),
            # 课件解析防重复：按 PPT 资源去重而非 catalog（自审 F3，第二版课件
            # 不会被判成重复）。MySQL 侧同走生成列方案。
            models.UniqueConstraint(
                fields=["task_type", "ppt"],
                condition=Q(task_type="ppt_parse", status__in=["pending", "running"]),
                name="uniq_active_ppt_parse",
            ),
        ]

    def __str__(self):
        return f"{self.get_task_type_display()} #{self.id} {self.get_status_display()}"


class AICapabilityChangeLog(BaseModel):
    """大模型能力配置变更记录（字段级 diff）——已废弃，仅存历史。

    审计双轨合并（2026-10-19）：管理端保存 AI 配置改为只写管理端操作审计
    （AdminActionLog.ai_config_save，new_value.changes 存按能力分组的字段级
    diff），模型层 AICapabilityConfig.save() 不再写本表。存量数据已由迁移
    ai/0010 导入审计表；本表与端点 /admin-panel/ai-config-changes/ 暂时保留，
    仅供查询合并前的历史记录，新代码请勿再写入。
    """

    capability = models.CharField(
        "能力", max_length=16, choices=AICapabilityConfig.Capability.choices, db_index=True
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_capability_change_logs",
        verbose_name="操作人",
    )
    changes = models.JSONField(
        "变更明细",
        default=list,
        help_text='[{"field":"model_name","label":"模型名称","old":"a","new":"b"}]',
    )

    class Meta:
        verbose_name = "能力配置变更记录"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        who = self.changed_by.username if self.changed_by else "系统"
        return f"{self.get_capability_display()} · {who} · {len(self.changes)} 项变更"


class AITestRecord(BaseModel):
    """能力连接测试记录（每项能力保留最新一次）。

    仅作测试历史展示，不参与 runtime 解析——环境变量模式下也能记录测试结果，
    且不会因为写入记录而改变实际生效的配置。
    """

    capability = models.CharField(
        "能力", max_length=16, choices=AICapabilityConfig.Capability.choices, unique=True
    )
    provider = models.CharField("测试时服务商", max_length=20, blank=True)
    status = models.CharField(
        "测试状态",
        max_length=16,
        choices=AICapabilityConfig.TestStatus.choices,
        default=AICapabilityConfig.TestStatus.UNTESTED,
    )
    message = models.CharField("测试结果", max_length=500, blank=True)
    tested_at = models.DateTimeField("测试时间", null=True, blank=True)
    tested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_test_records",
        verbose_name="测试人",
    )

    class Meta:
        verbose_name = "连接测试记录"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.capability} · {self.get_status_display()}"


class AIQuotaPolicy(BaseModel):
    """AI 调用日配额（P5-B6）：用户级覆盖 + 全局默认。

    计量数据源 = AICallLog（capability=chat、triggered_by=用户、当天），
    事前校验在业务入口（问答/生题/讲稿等）调 apps/ai/quota.check_ai_quota。
    - user=None 的行是全局默认（最多一行）；
    - daily_limit=None 表示不限。
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="ai_quota_policy",
        verbose_name="用户",
        help_text="为空表示全局默认策略",
    )
    daily_limit = models.IntegerField("每日调用上限", null=True, blank=True, help_text="null 表示不限")

    class Meta:
        verbose_name = "AI 日配额"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(user__isnull=True),
                name="uniq_ai_quota_global_default",
            ),
        ]

    def __str__(self):
        who = self.user.username if self.user else "全局默认"
        return f"{who}: {self.daily_limit if self.daily_limit is not None else '不限'}/日"


class AIQuotaReservation(BaseModel):
    """长任务配额预留（D4/评审 C7）：提交时按预估页数预留，终结按实际结算。

    一条 30 页讲稿作业在跑完前没有任何 AICallLog，不预留 → 教师能连提 5 个作业，
    跑到第三个额度耗尽、任务中途 429。预留后校验口径变为「已用 + 预留中 >= 上限」。

    生命周期（§13.5）：提交时预留（amount=ceil(空页/chunk)×1.2，6h 过期）→
    任务终结（success/failed/cancelled）按 trace_id 数 AICallLog 结算 →
    过期/孤儿由 prune_ai_tasks 与 worker 启动回收释放。
    超额（重试导致 settled > amount）不拦截——调用已发生，表现为当日剩余变少。
    """

    class Status(models.TextChoices):
        PENDING = "pending", "预留中"
        SETTLED = "settled", "已结算"
        RELEASED = "released", "已释放"

    task = models.OneToOneField(
        AITask, on_delete=models.CASCADE, related_name="quota_reservation", verbose_name="任务"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_quota_reservations",
        verbose_name="用户",
    )
    amount = models.IntegerField("预留量")
    settled_amount = models.IntegerField("实际结算", default=0)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField("过期时间")

    class Meta:
        verbose_name = "AI 配额预留"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"task={self.task_id} {self.amount}（结算 {self.settled_amount}）{self.get_status_display()}"
