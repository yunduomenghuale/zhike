from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.courses.models import Course
from apps.questions.models import Question

from .models import (
    Homework,
    HomeworkAnswer,
    HomeworkQuestion,
    HomeworkSubmission,
    question_snapshot,
)


def _snapshot_for_user(snapshot, user):
    data = dict(snapshot or {})
    if user and getattr(user, "is_student", False):
        if data.get("qtype") == Question.QType.BLANK:
            data["answer_blank_count"] = max(1, len((data.get("answer") or {}).get("blanks", [])))
        data.pop("answer", None)
        data.pop("analysis", None)
    return data


class HomeworkQuestionSerializer(serializers.ModelSerializer):
    snapshot = serializers.SerializerMethodField()

    class Meta:
        model = HomeworkQuestion
        fields = ["id", "question", "score", "order", "snapshot"]

    def get_snapshot(self, obj):
        request = self.context.get("request")
        return _snapshot_for_user(obj.snapshot, getattr(request, "user", None))


class HomeworkSerializer(serializers.ModelSerializer):
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.all(), required=False)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    mode_display = serializers.CharField(source="get_mode_display", read_only=True)
    submission_count = serializers.IntegerField(source="submissions.count", read_only=True)
    questions = HomeworkQuestionSerializer(many=True, read_only=True)
    question_items = serializers.ListField(
        child=serializers.DictField(), write_only=True, required=False
    )
    question_count = serializers.IntegerField(source="questions.count", read_only=True)
    total_score = serializers.DecimalField(max_digits=6, decimal_places=1, required=False)

    class Meta:
        model = Homework
        fields = [
            "id", "course", "classroom", "title", "description", "attachment",
            "mode", "mode_display", "start_time", "deadline", "total_score", "status", "status_display",
            "questions", "question_items", "question_count", "submission_count", "created_at",
        ]

    def validate_attachment(self, value):
        allowed = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".zip", ".rar"}
        if Path(value.name).suffix.lower() not in allowed:
            raise serializers.ValidationError("仅支持 PDF、Office 文档、TXT 或压缩包")
        if value.size > 20 * 1024 * 1024:
            raise serializers.ValidationError("附件大小不能超过 20MB")
        return value

    def validate(self, attrs):
        classroom = attrs.get("classroom", getattr(self.instance, "classroom", None))
        course = attrs.get("course", getattr(self.instance, "course", None))
        if classroom and not course:
            course = classroom.courses.order_by("id").first()
            if course:
                attrs["course"] = course
        if not course:
            raise serializers.ValidationError({"course": "请先为班级关联课程"})
        if classroom and not classroom.courses.filter(id=course.id).exists():
            raise serializers.ValidationError({"course": "该课程未关联到所选班级"})
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and getattr(user, "is_teacher", False):
            if course.teacher_id != user.id or (classroom and classroom.teacher_id != user.id):
                raise serializers.ValidationError("只能为自己负责的课程和班级创建作业")

        start_time = attrs.get("start_time", getattr(self.instance, "start_time", None))
        deadline = attrs.get("deadline", getattr(self.instance, "deadline", None))
        now = timezone.now()

        def field_changed(name, value):
            if not self.instance:
                return True
            return getattr(self.instance, name, None) != value

        if "start_time" in attrs and start_time and start_time < now and field_changed("start_time", start_time):
            raise serializers.ValidationError({"start_time": "开始时间不能早于当前时间"})
        if "deadline" in attrs and deadline and deadline < now and field_changed("deadline", deadline):
            raise serializers.ValidationError({"deadline": "截止时间不能早于当前时间"})
        if start_time and deadline and deadline <= start_time:
            raise serializers.ValidationError({"deadline": "截止时间必须晚于开始时间"})

        mode = attrs.get("mode", getattr(self.instance, "mode", Homework.Mode.ATTACHMENT))
        status = attrs.get("status", getattr(self.instance, "status", Homework.Status.DRAFT))
        items = attrs.get("question_items")
        if mode == Homework.Mode.ATTACHMENT and attrs.get(
            "total_score", getattr(self.instance, "total_score", Decimal("100"))
        ) <= 0:
            raise serializers.ValidationError({"total_score": "作业总分必须大于 0"})

        if self.instance and self.instance.status != Homework.Status.DRAFT:
            frozen_fields = {"course", "classroom", "mode"}
            if items is not None or any(name in attrs for name in frozen_fields):
                raise serializers.ValidationError("作业发布后不能修改模式或题目")

        normalized = []
        if items is not None:
            seen = set()
            for index, item in enumerate(items):
                question_id = item.get("question") or item.get("question_id")
                try:
                    question_id = int(question_id)
                except (TypeError, ValueError):
                    raise serializers.ValidationError({"question_items": f"第 {index + 1} 项缺少题目"})
                if question_id in seen:
                    raise serializers.ValidationError({"question_items": "同一道题不能重复添加"})
                seen.add(question_id)
                try:
                    score = Decimal(str(item.get("score", "0")))
                except (InvalidOperation, TypeError):
                    raise serializers.ValidationError({"question_items": f"第 {index + 1} 项分值不正确"})
                if score <= 0:
                    raise serializers.ValidationError({"question_items": "每道题分值必须大于 0"})
                normalized.append({"question_id": question_id, "score": score, "order": index})

            questions = {
                q.id: q
                for q in Question.objects.select_related("catalog").filter(id__in=seen)
            }
            if len(questions) != len(seen):
                raise serializers.ValidationError({"question_items": "所选题目不存在"})
            for item in normalized:
                question = questions[item["question_id"]]
                if question.course_id != course.id:
                    raise serializers.ValidationError({"question_items": "只能选择当前课程题库中的题目"})
                if question.status != Question.Status.PUBLISHED:
                    raise serializers.ValidationError({"question_items": "只能选择已发布题目"})
                item["question"] = question
            attrs["question_items"] = normalized

        existing_count = self.instance.questions.count() if self.instance else 0
        selected_count = len(normalized) if items is not None else existing_count
        if mode == Homework.Mode.QUESTIONS and status == Homework.Status.PUBLISHED and not selected_count:
            raise serializers.ValidationError({"question_items": "题库选题作业至少需要一道题"})
        return attrs

    @staticmethod
    def _replace_questions(homework, items):
        homework.questions.all().delete()
        HomeworkQuestion.objects.bulk_create([
            HomeworkQuestion(
                homework=homework,
                question=item["question"],
                score=item["score"],
                order=item["order"],
                snapshot=question_snapshot(item["question"]),
            )
            for item in items
        ])

    @staticmethod
    def _sync_total(homework):
        if homework.mode == Homework.Mode.QUESTIONS:
            total = sum((item.score for item in homework.questions.all()), Decimal("0"))
            homework.total_score = total
            homework.save(update_fields=["total_score", "updated_at"])

    @staticmethod
    def _freeze_snapshots(homework):
        for item in homework.questions.select_related("question", "question__catalog"):
            if item.question_id:
                item.snapshot = question_snapshot(item.question)
                item.save(update_fields=["snapshot", "updated_at"])

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("question_items", [])
        requested_status = validated_data.pop("status", Homework.Status.DRAFT)
        homework = Homework.objects.create(status=Homework.Status.DRAFT, **validated_data)
        self._replace_questions(homework, items)
        self._sync_total(homework)
        if requested_status == Homework.Status.PUBLISHED:
            self._freeze_snapshots(homework)
        homework.status = requested_status
        homework.save(update_fields=["status", "updated_at"])
        return homework

    @transaction.atomic
    def update(self, instance, validated_data):
        has_items = "question_items" in validated_data
        items = validated_data.pop("question_items", None)
        requested_status = validated_data.pop("status", instance.status)
        if has_items and instance.submissions.exists():
            raise serializers.ValidationError(
                {"question_items": "已有学生提交，不能修改题目；可调整标题、说明或截止时间"}
            )
        instance = super().update(instance, validated_data)
        if has_items:
            self._replace_questions(instance, items)
        self._sync_total(instance)
        if instance.status == Homework.Status.DRAFT and requested_status == Homework.Status.PUBLISHED:
            self._freeze_snapshots(instance)
        instance.status = requested_status
        instance.save(update_fields=["status", "updated_at"])
        return instance


class HomeworkAnswerSerializer(serializers.ModelSerializer):
    snapshot = serializers.SerializerMethodField()
    needs_manual_grading = serializers.SerializerMethodField()

    class Meta:
        model = HomeworkAnswer
        fields = [
            "id", "homework_question", "snapshot", "student_answer", "is_correct",
            "score", "comment", "graded_at", "needs_manual_grading",
        ]

    def get_snapshot(self, obj):
        request = self.context.get("request")
        return _snapshot_for_user(obj.homework_question.snapshot, getattr(request, "user", None))

    def get_needs_manual_grading(self, obj):
        return (obj.homework_question.snapshot or {}).get("qtype") == Question.QType.SHORT


class HomeworkSubmissionSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.real_name", read_only=True)
    correct_status_display = serializers.CharField(source="get_correct_status_display", read_only=True)
    answers = serializers.JSONField(write_only=True, required=False)
    answer_items = HomeworkAnswerSerializer(many=True, read_only=True)

    class Meta:
        model = HomeworkSubmission
        fields = [
            "id", "homework", "student", "student_name", "content", "attachment", "answers",
            "answer_items", "submitted_at", "is_late", "objective_score", "score", "comment",
            "correct_status", "correct_status_display", "auto_score", "auto_comment",
        ]
        read_only_fields = [
            "student", "submitted_at", "is_late", "objective_score", "score", "comment",
            "correct_status", "auto_score", "auto_comment",
        ]
