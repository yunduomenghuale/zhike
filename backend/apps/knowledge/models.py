from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.models import BaseModel
from apps.courses.models import Course


def _material_file_path(instance, filename):
    """上传文件名 uuid 化：保留原文件名可被猜测/枚举下载，原文件名仅存 file_name 字段展示。"""
    return f"materials/{uuid4().hex}{Path(filename).suffix.lower()}"


class Material(BaseModel):
    """教辅资料（需求 5.6 / 第 9 节·教辅资料）。上传后解析入库构建知识库。"""

    class ParseStatus(models.TextChoices):
        PENDING = "pending", "待解析"
        PARSING = "parsing", "解析中"
        DONE = "done", "已入库"
        FAILED = "failed", "解析失败"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="materials", verbose_name="课程")
    classroom = models.ForeignKey(
        "classroom.ClassRoom",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="materials",
        verbose_name="班级",
    )
    # 归属章节（可选）：设置后 AI 助教参考来源展示「章节标题资料」而非原文件名
    catalog = models.ForeignKey(
        "courses.Catalog",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="materials",
        verbose_name="归属章节",
    )
    file_name = models.CharField("文件名称", max_length=255)
    file_type = models.CharField("文件类型", max_length=20, blank=True)  # pdf/word/ppt/txt
    file = models.FileField("文件", upload_to=_material_file_path, null=True, blank=True)
    parse_status = models.CharField(
        "解析状态", max_length=16, choices=ParseStatus.choices, default=ParseStatus.PENDING
    )
    # 是否向学生开放自由提问（需求 T-K-04）
    qa_open = models.BooleanField("对学生开放提问", default=True)

    class Meta:
        verbose_name = "教辅资料"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.file_name


class KnowledgeChunk(BaseModel):
    """知识库片段（需求第 9 节·知识库片段 / 第 7.2 节 RAG）。

    来源三选一：教辅资料（material）、课件 PPT（ppt，每页一片段）、
    逐页讲解稿（video，每页一片段）。catalog 为冗余章节字段——检索的章节
    候选池过滤直接走本字段，无需 join 来源表；未挂章节的资料片段为 null，
    视为「全课程通用资料」，章节提问时同样入选。
    向量以 JSON 存储，起步用暴力余弦检索；后续可迁移 pgvector / Milvus。
    """

    class Source(models.TextChoices):
        MATERIAL = "material", "教辅资料"
        PPT = "ppt", "课件页面"
        SCRIPT = "script", "讲解稿"

    source = models.CharField(
        "来源类型", max_length=12, choices=Source.choices, default=Source.MATERIAL, db_index=True
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.CASCADE,
        related_name="chunks",
        verbose_name="来源资料",
        null=True,
        blank=True,
    )
    ppt = models.ForeignKey(
        "courses.PPTResource",
        on_delete=models.CASCADE,
        related_name="chunks",
        verbose_name="来源课件",
        null=True,
        blank=True,
    )
    video = models.ForeignKey(
        "courses.TeachingVideo",
        on_delete=models.CASCADE,
        related_name="chunks",
        verbose_name="来源讲稿",
        null=True,
        blank=True,
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="chunks", verbose_name="课程")
    # 冗余章节：与 material.catalog 的 SET_NULL 行为对齐（章节删除后资料片段
    # 转为通用资料保留）；ppt/video 片段随主对象 CASCADE 删除，本字段无所谓
    catalog = models.ForeignKey(
        "courses.Catalog",
        on_delete=models.SET_NULL,
        related_name="chunks",
        verbose_name="所属章节",
        null=True,
        blank=True,
    )
    content = models.TextField("片段内容")
    page = models.IntegerField("页码", null=True, blank=True)
    embedding = models.JSONField("向量", default=list, blank=True)

    class Meta:
        verbose_name = "知识库片段"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["course", "source"]),
            models.Index(fields=["course", "catalog"]),
        ]

    def __str__(self):
        return self.content[:30]


class QASession(BaseModel):
    """问答会话（多轮对话的持久化分组，2026-10-21 会话侧改造引入）。

    设计要点：
    - 绑定 (course, catalog, student)：catalog 为 null 表示课程级会话（AI 助教页），
      非空为章节会话（章节讲解 Dock）——会话与提问范围绑定，跨章节串话从机制上消除；
    - legacy_key 兼容旧前端/移动端：仍传 session 字符串时按
      (course, student, legacy_key) get_or_create，历史自动接续，移动端不发版
      也能无感迁移到会话模型；
    - summary / summary_upto_turn：滚动摘要——长会话早期轮次压缩为摘要注入，
      原文只保留最近几轮（见 apps/ai/services.py build_conversation_context）。
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "进行中"
        ARCHIVED = "archived", "已归档"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="qa_sessions", verbose_name="课程")
    catalog = models.ForeignKey(
        "courses.Catalog",
        on_delete=models.CASCADE,
        related_name="qa_sessions",
        null=True,
        blank=True,
        verbose_name="章节",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="qa_sessions", verbose_name="学生"
    )
    title = models.CharField("标题", max_length=60, default="")
    status = models.CharField("状态", max_length=12, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    summary = models.TextField("滚动摘要", blank=True)
    summary_upto_turn = models.IntegerField("已摘要至轮次", default=0)
    # 旧 session 字符串（前端 genUid / 移动端随机串）；唯一约束见 Meta
    legacy_key = models.CharField("旧会话标识", max_length=64, default="", db_index=True)

    class Meta:
        verbose_name = "问答会话"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=["course", "student", "legacy_key"],
                condition=~Q(legacy_key=""),
                name="uniq_qasession_legacy",
            )
        ]
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or f"会话{self.pk}"


class QARecord(BaseModel):
    """知识库问答记录（需求 5.6 T-K-05 / 6.3 / 第 9 节·知识库问答记录）。"""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="qa_records", verbose_name="课程")
    classroom = models.ForeignKey(
        "classroom.ClassRoom", null=True, blank=True, on_delete=models.SET_NULL, verbose_name="班级"
    )
    # 提问时的章节上下文（章节面板内提问）；为空表示课程级问答页提出的
    catalog = models.ForeignKey(
        "courses.Catalog", null=True, blank=True, on_delete=models.SET_NULL, verbose_name="章节"
    )
    # 会话分组标识（前端生成的 uuid）；同一次连续对话共享一个标识。
    # 2026-10-21 起由 session_ref（QASession）取代，本字段仅保留历史数据只读
    session = models.CharField("会话标识", max_length=64, default="", db_index=True)
    # 所属持久化会话；会话删除时保留记录（删除会话的接口会显式连记录一起删）
    session_ref = models.ForeignKey(
        QASession,
        on_delete=models.SET_NULL,
        related_name="records",
        null=True,
        blank=True,
        verbose_name="所属会话",
    )
    turn_index = models.IntegerField("会话内轮次", default=0, db_index=True)
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="qa_records", verbose_name="学生"
    )
    question = models.TextField("问题")
    answer = models.TextField("回答", blank=True)
    # 引用片段：[{n, chunk_id, source, material_name, page, snippet}, ...]
    cited_chunks = models.JSONField("引用片段", default=list, blank=True)
    # 改写后的检索问题（查询改写，未改写为空串；仅审计，学生看到的仍是原问题）
    rewritten_question = models.CharField("改写后检索问题", max_length=500, blank=True)
    # 上下文快照（审计/追问兜底）：{budgets, degraded_level,
    # chunks: [{n, chunk_id, source, catalog_id, page, score}]}
    context_snapshot = models.JSONField("上下文快照", default=dict, blank=True)
    # 学生反馈：1 有用 / -1 无用 / 0 未评（质量闭环指标来源）
    feedback = models.SmallIntegerField("学生反馈", default=0)

    class Meta:
        verbose_name = "知识库问答记录"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return self.question[:30]
