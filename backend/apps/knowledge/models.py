from django.conf import settings
from django.db import models

from apps.common.models import BaseModel
from apps.courses.models import Course


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
    file_name = models.CharField("文件名称", max_length=255)
    file_type = models.CharField("文件类型", max_length=20, blank=True)  # pdf/word/ppt/txt
    file = models.FileField("文件", upload_to="materials/", null=True, blank=True)
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

    向量以 JSON 存储，起步用暴力余弦检索；后续可迁移 pgvector / Milvus。
    """

    material = models.ForeignKey(
        Material, on_delete=models.CASCADE, related_name="chunks", verbose_name="来源资料"
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="chunks", verbose_name="课程")
    content = models.TextField("片段内容")
    page = models.IntegerField("页码", null=True, blank=True)
    embedding = models.JSONField("向量", default=list, blank=True)

    class Meta:
        verbose_name = "知识库片段"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.content[:30]


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
    # 会话分组标识（前端生成的 uuid）；同一次连续对话共享一个标识
    session = models.CharField("会话标识", max_length=64, default="", db_index=True)
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="qa_records", verbose_name="学生"
    )
    question = models.TextField("问题")
    answer = models.TextField("回答", blank=True)
    # 引用片段：[{chunk_id, material_name, page, snippet}, ...]
    cited_chunks = models.JSONField("引用片段", default=list, blank=True)

    class Meta:
        verbose_name = "知识库问答记录"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.question[:30]
