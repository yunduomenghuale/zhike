from rest_framework import serializers

from apps.courses.models import Catalog

from .models import AnswerRecord, Question


class QuestionSerializer(serializers.ModelSerializer):
    catalog = serializers.PrimaryKeyRelatedField(queryset=Catalog.objects.all())
    catalog_title = serializers.CharField(source="catalog.title", read_only=True)
    qtype_display = serializers.CharField(source="get_qtype_display", read_only=True)
    difficulty_display = serializers.CharField(source="get_difficulty_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Question
        fields = [
            "id", "course", "catalog", "catalog_title", "qtype", "qtype_display", "stem", "options",
            "answer", "analysis", "score", "difficulty", "difficulty_display",
            "knowledge_tags", "source", "status", "status_display", "creator", "created_at",
        ]
        read_only_fields = ["creator"]

    def validate(self, attrs):
        course = attrs.get("course", getattr(self.instance, "course", None))
        catalog = attrs.get("catalog", getattr(self.instance, "catalog", None))
        if not catalog:
            raise serializers.ValidationError({"catalog": "题目必须归属到具体章节"})
        if course and catalog.course_id != course.id:
            raise serializers.ValidationError({"catalog": "所选章节不属于当前课程"})
        return attrs


class StudentQuestionSerializer(serializers.ModelSerializer):
    """给学生答题用：隐藏答案与解析。"""

    qtype_display = serializers.CharField(source="get_qtype_display", read_only=True)

    class Meta:
        model = Question
        fields = ["id", "qtype", "qtype_display", "stem", "options", "score"]


class AnswerRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnswerRecord
        fields = [
            "id", "student", "question", "scene", "scene_ref_id",
            "student_answer", "is_correct", "score", "submitted_at",
        ]
        read_only_fields = ["student", "is_correct", "score", "submitted_at"]
