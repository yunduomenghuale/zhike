from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.common.permissions import IsStudent, IsTeacher, IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet
from apps.questions.grading import grade_objective
from apps.questions.models import AnswerRecord, Question

from .models import Homework, HomeworkAnswer, HomeworkSubmission
from .serializers import HomeworkSerializer, HomeworkSubmissionSerializer


class HomeworkViewSet(BaseModelViewSet):
    serializer_class = HomeworkSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "classroom", "status", "mode"]

    def get_queryset(self):
        user = self.request.user
        qs = Homework.objects.select_related("course", "classroom").prefetch_related("questions")
        if user.is_authenticated and user.is_student:
            qs = qs.filter(classroom__students__student=user, status=Homework.Status.PUBLISHED)
        elif user.is_authenticated and user.is_teacher:
            qs = qs.filter(classroom__teacher=user)
        return qs.distinct()

    def perform_destroy(self, instance):
        # HomeworkAnswer 对题目为 PROTECT 外键，先清理各题作答记录再删除作业
        HomeworkAnswer.objects.filter(homework_question__homework=instance).delete()
        super().perform_destroy(instance)


class HomeworkSubmissionViewSet(BaseModelViewSet):
    serializer_class = HomeworkSubmissionSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["homework", "student", "correct_status"]

    def get_queryset(self):
        user = self.request.user
        qs = HomeworkSubmission.objects.select_related("student", "homework").prefetch_related(
            "answer_items__homework_question"
        )
        if user.is_authenticated and user.is_student:
            qs = qs.filter(student=user)
        elif user.is_authenticated and user.is_teacher:
            qs = qs.filter(homework__classroom__teacher=user)
        return qs

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """学生交作业；题库作业逐题留痕并自动批改客观题。"""
        if not request.user.is_student:
            raise PermissionDenied("仅学生可提交作业")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        homework = serializer.validated_data["homework"]
        if homework.status != Homework.Status.PUBLISHED:
            raise ValidationError({"homework": "作业尚未发布"})
        if homework.start_time and timezone.now() < homework.start_time:
            raise ValidationError({"homework": "作业尚未开始"})
        if not homework.classroom.students.filter(student=request.user).exists():
            raise PermissionDenied("你不在该作业所属班级中")

        answers = serializer.validated_data.pop("answers", {}) or {}
        content = serializer.validated_data.get("content", "")
        attachment = serializer.validated_data.get("attachment")
        if homework.mode == Homework.Mode.ATTACHMENT and not str(content).strip() and not attachment:
            raise ValidationError("请填写作业内容或上传附件")

        is_late = bool(homework.deadline and timezone.now() > homework.deadline)
        submission = serializer.save(
            student=request.user,
            is_late=is_late,
            objective_score=Decimal("0"),
        )

        if homework.mode == Homework.Mode.QUESTIONS:
            objective_total = Decimal("0")
            has_subjective = False
            for item in homework.questions.order_by("order", "id"):
                snapshot = item.snapshot or {}
                student_answer = answers.get(str(item.id), answers.get(item.id, {})) or {}
                qtype = snapshot.get("qtype")
                if qtype == Question.QType.SHORT:
                    is_correct, score = None, None
                    has_subjective = True
                else:
                    frozen_question = SimpleNamespace(
                        qtype=qtype,
                        answer=snapshot.get("answer") or {},
                        score=item.score,
                    )
                    is_correct, score = grade_objective(frozen_question, student_answer)
                    if score is None:
                        has_subjective = True
                    else:
                        objective_total += score

                HomeworkAnswer.objects.create(
                    submission=submission,
                    homework_question=item,
                    student_answer=student_answer,
                    is_correct=is_correct,
                    score=score,
                    graded_at=timezone.now() if score is not None else None,
                )
                if item.question_id:
                    AnswerRecord.objects.create(
                        student=request.user,
                        question_id=item.question_id,
                        scene=AnswerRecord.Scene.HOMEWORK,
                        scene_ref_id=homework.id,
                        student_answer=student_answer,
                        is_correct=is_correct,
                        score=score,
                    )

            submission.objective_score = objective_total
            submission.score = objective_total
            submission.correct_status = (
                HomeworkSubmission.CorrectStatus.SUBMITTED
                if has_subjective
                else HomeworkSubmission.CorrectStatus.GRADED
            )
            submission.save(update_fields=["objective_score", "score", "correct_status", "updated_at"])

        return api_response(
            self.get_serializer(submission).data,
            message="提交成功，客观题已自动批改" if homework.mode == Homework.Mode.QUESTIONS else "提交成功",
            status=201,
        )

    @action(detail=True, methods=["post"], url_path="grade", permission_classes=[IsTeacher])
    @transaction.atomic
    def grade(self, request, pk=None):
        """教师批改附件作业或题库作业中的主观题。"""
        submission = self.get_object()
        homework = submission.homework

        if homework.mode == Homework.Mode.QUESTIONS:
            answer_scores = request.data.get("answer_scores", {}) or {}
            manual_items = submission.answer_items.select_related("homework_question").filter(
                homework_question__snapshot__qtype=Question.QType.SHORT
            )
            for answer_item in manual_items:
                data = answer_scores.get(str(answer_item.id), answer_scores.get(answer_item.id))
                if data is None:
                    if answer_item.score is None:
                        raise ValidationError({"answer_scores": "请完成所有主观题评分"})
                    continue
                raw_score = data.get("score") if isinstance(data, dict) else data
                try:
                    score = Decimal(str(raw_score))
                except (InvalidOperation, TypeError):
                    raise ValidationError({"answer_scores": "主观题分值格式不正确"})
                if score < 0 or score > answer_item.homework_question.score:
                    raise ValidationError({"answer_scores": "主观题得分不能超过题目分值"})
                answer_item.score = score
                answer_item.comment = data.get("comment", "") if isinstance(data, dict) else ""
                answer_item.graded_at = timezone.now()
                answer_item.save(update_fields=["score", "comment", "graded_at", "updated_at"])
                if answer_item.homework_question.question_id:
                    AnswerRecord.objects.filter(
                        student=submission.student,
                        question_id=answer_item.homework_question.question_id,
                        scene=AnswerRecord.Scene.HOMEWORK,
                        scene_ref_id=homework.id,
                    ).order_by("-id").update(score=score)

            if manual_items.filter(score__isnull=True).exists():
                raise ValidationError({"answer_scores": "请完成所有主观题评分"})
            total = submission.answer_items.aggregate(total=Sum("score"))["total"] or Decimal("0")
            submission.score = total
        else:
            try:
                score = Decimal(str(request.data.get("score")))
            except (InvalidOperation, TypeError):
                raise ValidationError({"score": "请输入有效分数"})
            if score < 0 or score > homework.total_score:
                raise ValidationError({"score": "得分不能超过作业总分"})
            submission.score = score

        submission.comment = request.data.get("comment", submission.comment)
        submission.correct_status = HomeworkSubmission.CorrectStatus.GRADED
        submission.save(update_fields=["score", "comment", "correct_status", "updated_at"])
        return api_response(self.get_serializer(submission).data, message="批改完成")
