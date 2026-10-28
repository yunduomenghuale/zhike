from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from rest_framework import serializers

from apps.courses.models import Catalog

from .models import AnswerRecord, Question, QuestionDraftBatch, SceneTag


class SceneTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = SceneTag
        fields = ["id", "code", "name"]


class QuestionSerializer(serializers.ModelSerializer):
    catalog = serializers.PrimaryKeyRelatedField(queryset=Catalog.objects.all())
    catalog_title = serializers.CharField(source="catalog.title", read_only=True)
    qtype_display = serializers.CharField(source="get_qtype_display", read_only=True)
    difficulty_display = serializers.CharField(source="get_difficulty_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    # 题图走「先上传后提交」：image 为媒体库相对路径（question_images/ 前缀），
    # image_url 为只读展示地址（/media/...）
    image = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    image_url = serializers.SerializerMethodField()
    # 用途分类按 code 读写（practice/homework/exam），多选；空数组=服务端默认
    scenes = serializers.SlugRelatedField(
        slug_field="code", queryset=SceneTag.objects.all(), many=True, required=False
    )

    class Meta:
        model = Question
        fields = [
            "id", "course", "catalog", "catalog_title", "qtype", "qtype_display", "stem", "image",
            "image_url", "options", "scenes",
            "answer", "analysis", "score", "difficulty", "difficulty_display",
            "knowledge_tags", "source", "status", "status_display", "creator", "created_at",
        ]
        read_only_fields = ["creator"]

    def validate_scenes(self, value):
        # 显式提交至少选一个分类；缺省字段（导入/旧客户端）走模型 save 兜底
        if self.initial_data.get("scenes") is not None and not value:
            raise serializers.ValidationError("请至少选择一个用途分类")
        return value

    def get_image_url(self, obj) -> str:
        return f"/media/{obj.image.name}" if obj.image else ""

    def validate(self, attrs):
        course = attrs.get("course", getattr(self.instance, "course", None))
        catalog = attrs.get("catalog", getattr(self.instance, "catalog", None))
        if not catalog:
            raise serializers.ValidationError({"catalog": "题目必须归属到具体章节"})
        if course and catalog.course_id != course.id:
            raise serializers.ValidationError({"catalog": "所选章节不属于当前课程"})
        image = attrs.get("image")
        if image is not None:
            image = str(image).strip()
            if not image:
                attrs["image"] = None  # 空串=移除题图
            elif not image.startswith("question_images/"):
                raise serializers.ValidationError({"image": "题图路径不合法"})
            else:
                attrs["image"] = image
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.is_teacher:
            if not course or course.teacher_id != user.id:
                raise serializers.ValidationError("只能维护自己负责课程的题目")
        self._validate_blank_answer(attrs)
        return attrs

    def _validate_blank_answer(self, attrs):
        """填空题按空赋分校验：answer 显式传入时逐空检查 text 非空、分值 > 0。

        仅在 answer 参与本次校验时触发，避免破坏只改 status/难度等字段的旧题 PATCH；
        题目总分由模型 save() 按 Σ空分重算，不接受直填。
        """
        qtype = attrs.get("qtype") or getattr(self.instance, "qtype", None)
        if qtype != Question.QType.BLANK or "answer" not in attrs:
            return
        blanks = (attrs.get("answer") or {}).get("blanks") or []
        if not blanks:
            raise serializers.ValidationError({"answer": "填空题至少需要设置一个空"})
        for i, b in enumerate(blanks, 1):
            if not isinstance(b, dict):
                raise serializers.ValidationError({"answer": f"第{i}空的答案格式不正确"})
            if not str(b.get("text", "")).strip():
                raise serializers.ValidationError({"answer": f"第{i}空的答案不能为空"})
            raw = b.get("score")
            if raw is None or str(raw).strip() == "":
                raise serializers.ValidationError({"answer": f"第{i}空的分值不能为空"})
            try:
                score = Decimal(str(raw))
            except (InvalidOperation, TypeError, ValueError):
                raise serializers.ValidationError({"answer": f"第{i}空的分值必须是数字"})
            if score <= 0:
                raise serializers.ValidationError({"answer": f"第{i}空的分值必须大于 0"})


class QuestionDraftBatchSerializer(serializers.ModelSerializer):
    """题目草稿批次：导入/AI 生成共用的待入库池。

    drafts 可写（PATCH 防抖回传编辑后的草稿）；origin/course/file_name/stats/status
    只读（服务端流转字段，前端不可直改）。
    """

    origin_display = serializers.CharField(source="get_origin_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    course_name = serializers.CharField(source="course.name", read_only=True)
    catalog_title = serializers.CharField(source="catalog.title", read_only=True, default="")

    class Meta:
        model = QuestionDraftBatch
        fields = [
            "id", "origin", "origin_display", "course", "course_name", "catalog", "catalog_title",
            "file_name", "drafts", "stats", "status", "status_display", "created_at",
        ]
        read_only_fields = ["origin", "course", "file_name", "stats", "status"]

    def validate_drafts(self, value):
        if not isinstance(value, list) or not all(isinstance(d, dict) for d in value):
            raise serializers.ValidationError("草稿数据格式不正确")
        return value

    def validate(self, attrs):
        instance = self.instance
        course = attrs.get("course", getattr(instance, "course", None))
        catalog = attrs.get("catalog", getattr(instance, "catalog", None))
        if catalog is not None and course and catalog.course_id != course.id:
            raise serializers.ValidationError({"catalog": "所选章节不属于当前课程"})
        return attrs


class StudentQuestionSerializer(serializers.ModelSerializer):
    """给学生答题用：隐藏答案与解析；填空题只给空数量（多空题按数渲染输入框）。"""

    qtype_display = serializers.CharField(source="get_qtype_display", read_only=True)
    blank_count = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Question
        fields = ["id", "qtype", "qtype_display", "stem", "image_url", "options", "score", "blank_count"]

    def get_image_url(self, obj) -> str:
        return f"/media/{obj.image.name}" if obj.image else ""

    def get_blank_count(self, obj):
        if obj.qtype != Question.QType.BLANK:
            return None
        blanks = (obj.answer or {}).get("blanks") or []
        if blanks:
            return max(1, len(blanks))
        # 无答案数据时按题干占位符计数（连续下划线/全角或半角括号）
        markers = re.findall(r"_{2,}|（\s*）|\(\s*\)", obj.stem or "")
        return max(1, len(markers))


class AnswerRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnswerRecord
        fields = [
            "id", "student", "question", "scene", "scene_ref_id",
            "student_answer", "is_correct", "score", "submitted_at",
        ]
        read_only_fields = ["student", "is_correct", "score", "submitted_at"]


class WrongNoteSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source="course.name", read_only=True)
    catalog_title = serializers.CharField(source="catalog.title", read_only=True, default="")

    class Meta:
        from .models import WrongNote

        model = WrongNote
        fields = [
            "id", "course", "course_name", "catalog", "catalog_title", "stem", "my_answer",
            "correct_answer", "analysis", "created_at",
        ]
        read_only_fields = ["student"]
