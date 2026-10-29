import os

from rest_framework import serializers

from .models import (
    Catalog,
    Course,
    CourseResource,
    PPTResource,
    TeachingVideo,
    VideoWatchProgress,
)


class CourseSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source="teacher.real_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Course
        fields = [
            "id", "name", "intro", "cover", "term",
            "teacher", "teacher_name", "status", "status_display",
            "created_at", "updated_at",
        ]
        read_only_fields = ["teacher"]


class CatalogSerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = Catalog
        fields = [
            "id", "course", "parent", "title", "order",
            "intro", "is_published", "children",
        ]

    def get_children(self, obj) -> list[dict]:
        children = obj.children.all()
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.is_student:
            children = children.filter(is_published=True)
        return CatalogSerializer(children, many=True, context=self.context).data

    def validate(self, attrs):
        course = attrs.get("course", getattr(self.instance, "course", None))
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        if parent and course and parent.course_id != course.id:
            raise serializers.ValidationError({"parent": "父级章节必须属于同一课程"})
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.is_teacher:
            if not course or course.teacher_id != user.id:
                raise serializers.ValidationError("只能维护自己负责课程的章节")
        return attrs


class PPTResourceSerializer(serializers.ModelSerializer):
    parse_status_display = serializers.CharField(source="get_parse_status_display", read_only=True)
    # 向量片段数：0 表示未入库（向量模型不可用或从未重建），QA 时走原文拼接兜底
    chunk_count = serializers.IntegerField(source="chunks.count", read_only=True)
    allowed_extensions = {".ppt", ".pptx", ".pdf"}

    class Meta:
        model = PPTResource
        fields = [
            "id", "course", "catalog", "file_name", "file",
            "parse_status", "parse_status_display", "version",
            "is_active", "parsed_pages", "parse_progress", "chunk_count",
            "created_at", "updated_at",
        ]
        read_only_fields = ["parse_status", "parsed_pages", "parse_progress", "version"]

    def validate_file(self, value):
        ext = os.path.splitext(value.name)[1].lower()
        if ext not in self.allowed_extensions:
            raise serializers.ValidationError("课件支持 PPT / PPTX / PDF 文件；PDF 可保证页面版式零偏移，推荐优先使用")
        if value.size > 100 * 1024 * 1024:
            raise serializers.ValidationError("课件大小不能超过 100MB")
        return value

    def validate(self, attrs):
        course = attrs.get("course", getattr(self.instance, "course", None))
        catalog = attrs.get("catalog", getattr(self.instance, "catalog", None))
        if catalog and course and catalog.course_id != course.id:
            raise serializers.ValidationError({"catalog": "所选章节不属于当前课程"})
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.is_teacher:
            if not course or course.teacher_id != user.id:
                raise serializers.ValidationError("只能上传自己负责课程的课件")
        return attrs


class TeachingVideoSerializer(serializers.ModelSerializer):
    gen_status_display = serializers.CharField(source="get_gen_status_display", read_only=True)

    class Meta:
        model = TeachingVideo
        fields = [
            "id", "course", "catalog", "ppt", "scripts",
            "audio_url", "subtitle_url", "video_url",
            "gen_status", "gen_status_display", "is_published", "published_at",
        ]

    def validate(self, attrs):
        course = attrs.get("course", getattr(self.instance, "course", None))
        catalog = attrs.get("catalog", getattr(self.instance, "catalog", None))
        ppt = attrs.get("ppt", getattr(self.instance, "ppt", None))
        if catalog and course and catalog.course_id != course.id:
            raise serializers.ValidationError({"catalog": "所选章节不属于当前课程"})
        if ppt and course and (
            not catalog or ppt.course_id != course.id or ppt.catalog_id != catalog.id
        ):
            raise serializers.ValidationError({"ppt": "所选课件与课程章节不匹配"})
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.is_teacher:
            if not course or course.teacher_id != user.id:
                raise serializers.ValidationError("只能维护自己负责课程的视频")
        return attrs
class VideoWatchProgressSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.real_name", read_only=True)
    catalog = serializers.IntegerField(source="video.catalog_id", read_only=True)
    catalog_title = serializers.CharField(source="video.catalog.title", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = VideoWatchProgress
        fields = [
            "id", "student", "student_name", "video", "catalog", "catalog_title",
            "last_page", "last_position", "watch_seconds", "total_seconds",
            "page_durations", "page_watched", "page_count",
            "status", "status_display", "updated_at",
        ]
        read_only_fields = ["student", "watch_seconds", "status"]


class CourseResourceSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    url = serializers.CharField(read_only=True)
    # 文档类上传后展示用（文件名/大小服务端落库，前端不直传）
    file_url = serializers.FileField(source="file", read_only=True)

    # 文档类与自定义 HTML（导图/演示）支持的格式白名单
    # （2026-10-28 定稿：文档仅 pdf/doc/docx，txt/md/epub 暂不开放；
    #   自定义导图/演示先只收单文件 .html，多文件 ZIP 包后续再加）
    DOCUMENT_EXTS = {".pdf", ".doc", ".docx"}
    CUSTOM_HTML_EXTS = {".html"}
    MAX_DOCUMENT_SIZE = 100 * 1024 * 1024  # 100MB
    MAX_CUSTOM_HTML_SIZE = 100 * 1024 * 1024  # 100MB

    class Meta:
        model = CourseResource
        fields = [
            "id", "course", "kind", "kind_display", "title", "path",
            "file", "file_url", "file_name", "file_size",
            "url", "intro", "is_published", "order",
        ]
        # 显式声明 validators 即关闭自动生成的唯一校验（报错不友好），
        # 改由下方 validate() 提前拦截并给出可读提示；DB 层唯一约束仍作兜底。
        validators = []

    def validate_path(self, value):
        # 预置类：只允许平台预置静态页的相对路径，防目录穿越与任意外链；
        # 自定义 HTML 类 path 为空（校验在 validate() 按 kind 分流）
        value = (value or "").strip().strip("/")
        if not value:
            return value
        import re

        if not re.fullmatch(r"(mindmap|demos)/[A-Za-z0-9_\-]+\.html", value):
            raise serializers.ValidationError("资源路径须为 mindmap/*.html 或 demos/*.html 平台预置页")
        return value

    def _validate_upload(self, upload, allowed_exts, max_size, label):
        import os

        ext = os.path.splitext(upload.name)[1].lower()
        if ext not in allowed_exts:
            raise serializers.ValidationError({"file": f"仅支持 {label} 格式，当前为 {ext or '未知'}"})
        if upload.size > max_size:
            raise serializers.ValidationError({"file": "文件不能超过 100MB"})
        if upload.size == 0:
            raise serializers.ValidationError({"file": "文件为空"})

    def validate(self, attrs):
        course = attrs.get("course", getattr(self.instance, "course", None))
        kind = attrs.get("kind", getattr(self.instance, "kind", None))
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.is_teacher:
            if not course or course.teacher_id != user.id:
                raise serializers.ValidationError("只能维护自己课程的资源")

        upload = (request and request.FILES.get("file")) or attrs.get("file")

        if kind == CourseResource.Kind.DOCUMENT:
            # 文档类：必须有上传文件（multipart），path 不允许
            attrs["path"] = ""
            if self.instance is None and not upload:
                raise serializers.ValidationError({"file": "请上传文档文件（pdf / doc / docx，不超过 100MB）"})
            if upload:
                self._validate_upload(upload, self.DOCUMENT_EXTS, self.MAX_DOCUMENT_SIZE, "pdf / doc / docx")
        else:
            # 思维导图/交互演示：平台预置页引用 或 自定义单文件 HTML 二选一
            path_given = attrs.get("path") is not None
            path = attrs.get("path") if path_given else getattr(self.instance, "path", "")
            existing_file = getattr(self.instance, "file", None) if self.instance else None
            if upload:
                # 自定义 HTML：清空 path，按 .html 白名单校验
                self._validate_upload(upload, self.CUSTOM_HTML_EXTS, self.MAX_CUSTOM_HTML_SIZE, ".html")
                attrs["path"] = ""
            elif path:
                # 预置页引用：path 的格式校验在 validate_path（字段级）；
                # 同一课程下同一预置页只能挂一次：提前拦截并给友好提示
                if course:
                    duplicated = CourseResource.objects.filter(course=course, path=path)
                    if self.instance:
                        duplicated = duplicated.exclude(pk=self.instance.pk)
                    dup = duplicated.first()
                    if dup:
                        name = dup.title or dup.path
                        raise serializers.ValidationError(
                            f"该课程下已添加过「{name}」，不能重复添加"
                        )
            elif self.instance is None or not existing_file:
                # 既无 path 也无上传，且不是已有自定义 HTML 的更新（如发布切换）
                raise serializers.ValidationError({"path": "请选择平台预置页面或上传自定义 HTML 文件"})
        return attrs
