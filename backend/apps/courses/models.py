from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class Course(BaseModel):
    """课程（需求 5.1 / 第 9 节·课程）。"""

    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"
        ARCHIVED = "archived", "归档"

    name = models.CharField("课程名称", max_length=200)
    intro = models.TextField("课程简介", blank=True)
    cover = models.CharField("课程封面", max_length=500, blank=True)
    term = models.CharField("学期", max_length=50, blank=True)
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="courses",
        verbose_name="授课教师",
    )
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        verbose_name = "课程"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.name


class Catalog(BaseModel):
    """课程目录（章 / 节，需求 5.2 / 第 9 节·课程目录）。

    通过 parent 自引用支持“章-节”层级，可合并 / 拆分 / 排序。
    """

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="catalogs", verbose_name="课程")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
        verbose_name="父级目录",
    )
    title = models.CharField("章节标题", max_length=200)
    order = models.IntegerField("排序号", default=0)
    intro = models.TextField("简介", blank=True)
    is_published = models.BooleanField("是否发布", default=False)

    class Meta:
        verbose_name = "课程目录"
        verbose_name_plural = verbose_name
        ordering = ["order", "id"]

    def __str__(self):
        return self.title


class PPTResource(BaseModel):
    """章节 PPT 资源（需求 5.3 / 第 9 节·PPT 资源）。"""

    class ParseStatus(models.TextChoices):
        PENDING = "pending", "待解析"
        PARSING = "parsing", "解析中"
        DONE = "done", "已解析"
        FAILED = "failed", "解析失败"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="ppts", verbose_name="课程")
    catalog = models.ForeignKey(
        Catalog, on_delete=models.CASCADE, related_name="ppts", verbose_name="章节"
    )
    file_name = models.CharField("文件名称", max_length=255)
    file = models.FileField("文件", upload_to="ppt/", null=True, blank=True)
    parse_status = models.CharField(
        "解析状态", max_length=16, choices=ParseStatus.choices, default=ParseStatus.PENDING
    )
    version = models.IntegerField("版本号", default=1)
    is_active = models.BooleanField("当前启用版本", default=True)
    # PPT 解析后的逐页结构化数据：[{page, title, body, image}, ...]
    parsed_pages = models.JSONField("解析页数据", default=list, blank=True)

    class Meta:
        verbose_name = "PPT 资源"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.file_name


class TeachingVideo(BaseModel):
    """教学视频：PPT 页面 + AI 配音 + 字幕（需求 5.4 / 第 9 节·教学视频）。"""

    class GenStatus(models.TextChoices):
        DRAFT = "draft", "草稿"
        SCRIPT_READY = "script_ready", "讲解稿就绪"
        AUDIO_READY = "audio_ready", "配音就绪"
        COMPOSING = "composing", "合成中"
        DONE = "done", "已合成"
        FAILED = "failed", "生成失败"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="videos", verbose_name="课程")
    catalog = models.OneToOneField(
        Catalog, on_delete=models.CASCADE, related_name="video", verbose_name="章节"
    )
    ppt = models.ForeignKey(
        PPTResource, on_delete=models.SET_NULL, null=True, blank=True, related_name="videos", verbose_name="来源 PPT"
    )
    # 逐页讲解稿：[{page, script}, ...]
    scripts = models.JSONField("逐页讲解稿", default=list, blank=True)
    audio_url = models.CharField("AI 配音地址", max_length=500, blank=True)
    subtitle_url = models.CharField("字幕地址", max_length=500, blank=True)
    video_url = models.CharField("视频地址", max_length=500, blank=True)
    gen_status = models.CharField(
        "生成状态", max_length=16, choices=GenStatus.choices, default=GenStatus.DRAFT
    )
    is_published = models.BooleanField("是否发布", default=False)
    published_at = models.DateTimeField("发布时间", null=True, blank=True)

    class Meta:
        verbose_name = "教学视频"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.catalog.title} 视频"
