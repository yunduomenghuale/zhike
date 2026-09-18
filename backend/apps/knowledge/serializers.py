from pathlib import Path

from rest_framework import serializers

from .models import KnowledgeChunk, Material, QARecord


class MaterialSerializer(serializers.ModelSerializer):
    parse_status_display = serializers.CharField(source="get_parse_status_display", read_only=True)
    chunk_count = serializers.IntegerField(source="chunks.count", read_only=True)
    # 与 knowledge/extractor.py 支持的解析类型对齐；白名单防 HTML/SVG 等在 media 同域下造成存储型 XSS
    allowed_extensions = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".txt", ".md"}

    class Meta:
        model = Material
        fields = [
            "id", "course", "classroom", "file_name", "file_type", "file",
            "parse_status", "parse_status_display", "qa_open", "chunk_count", "created_at",
        ]
        read_only_fields = ["parse_status"]

    def validate_file(self, value):
        if Path(value.name).suffix.lower() not in self.allowed_extensions:
            raise serializers.ValidationError("资料仅支持 PDF、Word、PPT、TXT、Markdown 文件")
        if value.size > 50 * 1024 * 1024:
            raise serializers.ValidationError("资料大小不能超过 50MB")
        return value

    def validate(self, attrs):
        course = attrs.get("course", getattr(self.instance, "course", None))
        classroom = attrs.get("classroom", getattr(self.instance, "classroom", None))
        if classroom and course and not classroom.courses.filter(id=course.id).exists():
            raise serializers.ValidationError({"classroom": "所选班级未关联当前课程"})
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.is_teacher:
            if not course or course.teacher_id != user.id:
                raise serializers.ValidationError("只能维护自己负责课程的资料")
            if classroom and classroom.teacher_id != user.id:
                raise serializers.ValidationError("只能选择自己负责的班级")
        return attrs


class KnowledgeChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeChunk
        fields = ["id", "material", "course", "content", "page"]


class QARecordSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.real_name", read_only=True)

    class Meta:
        model = QARecord
        fields = [
            "id", "course", "classroom", "catalog", "session", "student", "student_name",
            "question", "answer", "cited_chunks", "created_at",
        ]
        read_only_fields = ["student", "answer", "cited_chunks"]
