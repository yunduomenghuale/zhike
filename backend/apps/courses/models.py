from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


def _ppt_file_path(instance, filename):
    """上传文件名 uuid 化：保留原文件名可被猜测/枚举下载，原文件名仅存 file_name 字段展示。"""
    return f"ppt/{uuid4().hex}{Path(filename).suffix.lower()}"


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
    file = models.FileField("文件", upload_to=_ppt_file_path, null=True, blank=True)
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


class VideoWatchProgress(BaseModel):
    """学生视频（PPT+配音连播）学习进度（需求 S-V-03）。

    记录当前学习到的页码、页内音频位置、累计学习时长与完成状态，
    前端据此实现断点续播，教师据此查看学习进度。
    """

    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "未开始"
        IN_PROGRESS = "in_progress", "学习中"
        COMPLETED = "completed", "已完成"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="video_progress",
        verbose_name="学生",
    )
    video = models.ForeignKey(
        TeachingVideo,
        on_delete=models.CASCADE,
        related_name="watch_progress",
        verbose_name="教学视频",
    )
    last_page = models.IntegerField("当前页索引", default=0)
    last_position = models.FloatField("页内播放位置(秒)", default=0)
    watch_seconds = models.IntegerField("累计学习时长(秒)", default=0)
    total_seconds = models.FloatField("音视频总时长(秒)", default=0)
    page_durations = models.JSONField("每页音视频时长(秒)", default=dict, blank=True)
    page_watched = models.JSONField("每页已看时长(秒)", default=dict, blank=True)
    page_count = models.IntegerField("章节总页数", default=0)
    status = models.CharField(
        "学习状态", max_length=16, choices=Status.choices, default=Status.IN_PROGRESS
    )

    class Meta:
        verbose_name = "视频学习进度"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(fields=["student", "video"], name="unique_student_video_progress")
        ]

    def __str__(self):
        return f"{self.student} - {self.video} 进度"


class CourseResource(BaseModel):
    """课程扩展资源（二期B）：思维导图 / 交互演示静态页。

    资源本体是平台预置的静态 HTML（nginx /resources/ 子路径，只读），
    教师侧仅做"引用 + 挂章节 + 排序 + 发布"，与 Lab/LabTemplate 的三层思路一致。
    """

    class Kind(models.TextChoices):
        MINDMAP = "mindmap", "思维导图"
        DEMO = "demo", "交互演示"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="resources", verbose_name="课程")
    catalog = models.ForeignKey(
        Catalog, null=True, blank=True, on_delete=models.SET_NULL, related_name="resources", verbose_name="章节"
    )
    kind = models.CharField("资源类型", max_length=16, choices=Kind.choices)
    title = models.CharField("资源标题", max_length=200)
    # 相对 /resources/ 的路径，如 mindmap/chapter1.html、demos/tcp-demo.html
    path = models.CharField("资源路径", max_length=255)
    intro = models.TextField("资源说明", blank=True)
    is_published = models.BooleanField("是否发布", default=False)
    order = models.PositiveIntegerField("排序号", default=0)

    class Meta:
        verbose_name = "课程资源"
        verbose_name_plural = verbose_name
        ordering = ["course_id", "order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["course", "path"], name="unique_course_resource_path"),
        ]

    def __str__(self):
        return f"{self.course} - {self.title}"

    @property
    def url(self) -> str:
        return f"/resources/{self.path.lstrip('/')}"


def _course_video_file_path(instance, filename):
    """数字人视频文件名 uuid 化（原文件名仅存展示字段）。"""
    return f"course_videos/{uuid4().hex}{Path(filename).suffix.lower()}"


class CourseVideo(BaseModel):
    """数字人视频（二期C）：教师上传、挂课程章节，发布后学生观看。

    视频文件走 FileField（≤500MB 校验在序列化器），nginx 需同步调大
    client_max_body_size。播放走 /media/ 静态服务。
    """

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="course_videos", verbose_name="课程")
    catalog = models.ForeignKey(
        Catalog, null=True, blank=True, on_delete=models.SET_NULL, related_name="course_videos", verbose_name="章节"
    )
    title = models.CharField("视频标题", max_length=200)
    file = models.FileField("视频文件", upload_to=_course_video_file_path)
    file_name = models.CharField("原始文件名", max_length=255, blank=True)
    file_size = models.BigIntegerField("文件大小(字节)", default=0)
    duration = models.FloatField("时长(秒)", null=True, blank=True)
    is_published = models.BooleanField("是否发布", default=False)
    order = models.PositiveIntegerField("排序号", default=0)

    class Meta:
        verbose_name = "数字人视频"
        verbose_name_plural = verbose_name
        ordering = ["course_id", "order", "id"]

    def __str__(self):
        return f"{self.course} - {self.title}"
