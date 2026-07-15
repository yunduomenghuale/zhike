import os

from rest_framework import serializers

from .models import Catalog, Course, PPTResource, TeachingVideo


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

    def get_children(self, obj):
        return CatalogSerializer(obj.children.all(), many=True).data


class PPTResourceSerializer(serializers.ModelSerializer):
    parse_status_display = serializers.CharField(source="get_parse_status_display", read_only=True)
    allowed_extensions = {".ppt", ".pptx"}

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
            raise serializers.ValidationError("课件只支持上传 PPT / PPTX 文件")
        return value


class TeachingVideoSerializer(serializers.ModelSerializer):
    gen_status_display = serializers.CharField(source="get_gen_status_display", read_only=True)

    class Meta:
        model = TeachingVideo
        fields = [
            "id", "course", "catalog", "ppt", "scripts",
            "audio_url", "subtitle_url", "video_url",
            "gen_status", "gen_status_display", "is_published", "published_at",
        ]
