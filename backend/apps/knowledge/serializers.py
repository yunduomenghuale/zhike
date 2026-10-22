from pathlib import Path

from rest_framework import serializers

from .models import KnowledgeChunk, Material, QARecord, QASession


class MaterialSerializer(serializers.ModelSerializer):
    parse_status_display = serializers.CharField(source="get_parse_status_display", read_only=True)
    chunk_count = serializers.IntegerField(source="chunks.count", read_only=True)
    catalog_title = serializers.CharField(source="catalog.title", read_only=True, default="")
    # 与 knowledge/extractor.py 支持的解析类型对齐；白名单防 HTML/SVG 等在 media 同域下造成存储型 XSS
    allowed_extensions = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".txt", ".md"}

    class Meta:
        model = Material
        fields = [
            "id", "course", "classroom", "catalog", "catalog_title", "file_name", "file_type", "file",
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
        catalog = attrs.get("catalog", getattr(self.instance, "catalog", None))
        if catalog and course and catalog.course_id != course.id:
            raise serializers.ValidationError({"catalog": "所选章节不属于当前课程"})
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
        fields = ["id", "material", "ppt", "course", "content", "page"]


class QARecordSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.real_name", read_only=True)

    class Meta:
        model = QARecord
        fields = [
            "id", "course", "classroom", "catalog", "session", "student", "student_name",
            "question", "answer", "cited_chunks", "rewritten_question", "feedback", "created_at",
        ]
        read_only_fields = ["student", "answer", "cited_chunks", "rewritten_question", "feedback"]


class TeacherQAIssueSerializer(serializers.ModelSerializer):
    """教师端问题下钻明细（质量看板 Phase 2）。

    在 QARecordSerializer 基础上补充下钻定位所需的派生字段：
    course_name / catalog_title / student_name 供列表直接展示；
    degraded_level / skip_retrieval 来自 context_snapshot（审计字段，
    不下发学生端），用于解释「这条问题为什么有问题」。
    """

    course_name = serializers.CharField(source="course.name", read_only=True)
    catalog_title = serializers.CharField(source="catalog.title", read_only=True, default="")
    student_name = serializers.CharField(source="student.real_name", read_only=True)
    degraded_level = serializers.IntegerField(
        source="context_snapshot.degraded_level", read_only=True, default=0
    )

    class Meta:
        model = QARecord
        fields = [
            "id", "course", "course_name", "catalog", "catalog_title",
            "student", "student_name", "question", "answer", "cited_chunks",
            "rewritten_question", "feedback", "degraded_level",
            "skip_retrieval", "created_at",
        ]


class QASessionSerializer(serializers.ModelSerializer):
    """问答会话列表项（record_count / last_message_at 由视图 annotate）。"""

    record_count = serializers.IntegerField(read_only=True, default=0)
    last_message_at = serializers.DateTimeField(read_only=True, allow_null=True)
    catalog_title = serializers.CharField(source="catalog.title", read_only=True, default="")

    class Meta:
        model = QASession
        fields = [
            "id", "course", "catalog", "catalog_title", "title", "status",
            "record_count", "last_message_at", "created_at", "updated_at",
        ]
        # title/status 允许经 PATCH 修改（改名/归档）；创建时 title 由后端生成
        read_only_fields = ["record_count", "last_message_at"]
