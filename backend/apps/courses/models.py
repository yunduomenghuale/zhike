from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


def _ppt_file_path(instance, filename):
    """上传文件名 uuid 化：保留原文件名可被猜测/枚举下载，原文件名仅存 file_name 字段展示。"""
    return f"ppt/{uuid4().hex}{Path(filename).suffix.lower()}"


class Term(BaseModel):
    """学期字典（学年 + 季节）。

    学年以起始年记录：2026 表示 2026-2027 学年。这样"2027 春"不会产生歧义
    （它属于 2026 学年，而不是 2027 学年）。
    """

    class Season(models.TextChoices):
        SPRING = "spring", "春季"
        AUTUMN = "autumn", "秋季"

    year = models.PositiveSmallIntegerField("学年起始年")
    season = models.CharField("季节", max_length=8, choices=Season.choices)
    name = models.CharField("显示名", max_length=50, unique=True)
    start_at = models.DateField("开始日期", null=True, blank=True)
    end_at = models.DateField("结束日期", null=True, blank=True)
    is_current = models.BooleanField("当前学期", default=False)

    class Meta:
        verbose_name = "学期"
        verbose_name_plural = verbose_name
        ordering = ["-year", "season"]
        constraints = [
            models.UniqueConstraint(fields=["year", "season"], name="unique_term_year_season"),
            models.UniqueConstraint(
                fields=["is_current"],
                condition=models.Q(is_current=True),
                name="unique_current_term",
            ),
        ]

    def __str__(self):
        return self.name


class Course(BaseModel):
    """课程（需求 5.1 / 第 9 节·课程）。"""

    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"
        ARCHIVED = "archived", "归档"

    name = models.CharField("课程名称", max_length=200)
    intro = models.TextField("课程简介", blank=True)
    cover = models.CharField("课程封面", max_length=500, blank=True)
    term = models.ForeignKey(
        Term,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="courses",
        verbose_name="学期",
        help_text="允许为空：历史课程可能未归属学期，列表按「学期待归属」提示补齐",
    )
    # 学期字段从 CharField 迁移到 FK 时的原文本备份，确认迁移无误后再删（勿新代码引用）
    term_text = models.CharField("学期（原始文本）", max_length=50, blank=True)
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        # P5-B5（方案 X-25）：教师离职走停用（is_active=False），不物理删；
        # 有课的教师被删会连带级联整门课及课件/讲稿/作业/考试/成绩，故库层
        # PROTECT 兜底（含 queryset 删除通道），必须先转移课程归属。
        on_delete=models.PROTECT,
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
    # 解析进度（上传解析过程的实时可视化）：
    # {"stage": "text|render|embed|done|failed", "done": int, "total": int, "error": str}
    parse_progress = models.JSONField("解析进度", default=dict, blank=True)

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


def _course_video_file_path(instance, filename):
    """【已废弃】数字人视频文件名 uuid 化——CourseVideo 模块已删除（2026-10-28），
    本函数仅为历史迁移 0008_coursevideo 的可导入性保留，不得在新代码中使用。"""
    return f"course_videos/{uuid4().hex}{Path(filename).suffix.lower()}"


def _course_resource_file_path(instance, filename):
    """文档资源文件名 uuid 化（原文件名仅存展示字段），防路径猜测。"""
    return f"course_resources/{uuid4().hex}{Path(filename).suffix.lower()}"


class CourseResource(BaseModel):
    """课程教学资源：思维导图 / 交互演示（平台预置静态页）/ 文档（教师上传）。

    资源直接归属课程，不再挂载章节（2026-10-28 调整：章节聚焦型学习链路
    与课程级资源展示冲突，且部分资源本就跨章节）。
    思维导图/交互演示本体是平台预置静态 HTML（nginx /resources/ 子路径，只读），
    教师侧仅做"引用 + 排序 + 发布"；文档类为教师上传的 pdf/doc/docx（≤100MB）。
    每行独立 access_token，对外链接唯一，经签名门控访问（2h 时效，下架即失效）。
    """

    class Kind(models.TextChoices):
        MINDMAP = "mindmap", "思维导图"
        DEMO = "demo", "交互演示"
        DOCUMENT = "document", "文档"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="resources", verbose_name="课程")
    kind = models.CharField("资源类型", max_length=16, choices=Kind.choices)
    title = models.CharField("资源标题", max_length=200)
    # 预置类：相对 /resources/ 的路径，如 mindmap/chapter1.html、demos/tcp-demo.html；文档类为空
    path = models.CharField("资源路径", max_length=255, blank=True, default="")
    # 文档类：教师上传文件（pdf/doc/docx）；预置类为空
    file = models.FileField("文档文件", upload_to=_course_resource_file_path, null=True, blank=True, max_length=255)
    file_name = models.CharField("原始文件名", max_length=255, blank=True)
    file_size = models.BigIntegerField("文件大小(字节)", default=0)
    # 每条资源独立的访问令牌：对外链接唯一（/api/course-resources/page/{token}/），
    # 配合签名与发布状态门控，未发布/非本人课程无法拿到有效签名 URL
    access_token = models.UUIDField("访问令牌", default=uuid4, unique=True, editable=False)
    intro = models.TextField("资源说明", blank=True)
    is_published = models.BooleanField("是否发布", default=False)
    order = models.PositiveIntegerField("排序号", default=0)

    class Meta:
        verbose_name = "课程资源"
        verbose_name_plural = verbose_name
        ordering = ["course_id", "order", "id"]
        constraints = [
            # 仅预置类按 path 判重（文档类 path 恒为空，不参与）
            models.UniqueConstraint(
                fields=["course", "path"],
                condition=~models.Q(path=""),
                name="unique_course_resource_path",
            ),
        ]

    def __str__(self):
        return f"{self.course} - {self.title}"

    @property
    def url(self) -> str:
        # 规范地址（唯一，按资源令牌）；实际访问需经 /sign/ 签发带时效的签名 URL
        return f"/api/course-resources/page/{self.access_token}/"
