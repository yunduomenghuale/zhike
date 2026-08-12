import os

from rest_framework import serializers

from .models import Catalog, Course, PPTResource, TeachingVideo, VideoWatchProgress


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
    allowed_extensions = {".ppt", ".pptx", ".pdf"}

    class Meta:
        model = PPTResource
        fields = [
            "id", "course", "catalog", "file_name", "file",
            "parse_status", "parse_status_display", "version",
            "is_active", "parsed_pages", "created_at",
        ]
        read_only_fields = ["parse_status", "parsed_pages", "version"]

    def validate_file(self, value):
        ext = os.path.splitext(value.name)[1].lower()
        if ext not in self.allowed_extensions:
            raise serializers.ValidationError("课件支持 PPT / PPTX / PDF 文件；PDF 可保证页面版式零偏移，推荐优先使用")
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
