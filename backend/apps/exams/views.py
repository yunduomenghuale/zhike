from decimal import Decimal

from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.common.permissions import IsTeacher, IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet
from apps.questions.grading import grade_objective
from apps.questions.models import Question

from .composer import compose_manual, compose_random
from .models import Exam, ExamLog, ExamSubmission, Paper
from .resolver import build_for_review, build_for_taking
from .serializers import (
    ExamLogSerializer,
    ExamSerializer,
    ExamSubmissionSerializer,
    PaperSerializer,
)


class ExamViewSet(BaseModelViewSet):
    serializer_class = ExamSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "classroom", "status"]

    def get_queryset(self):
        user = self.request.user
        qs = Exam.objects.select_related("classroom")
        if user.is_authenticated and user.is_student:
            # 学生仅见已发布、且自己所在班级的考试
            qs = qs.filter(status=Exam.Status.PUBLISHED, classroom__students__student=user)
        return qs.distinct()

    @action(detail=True, methods=["post"], url_path="compose", permission_classes=[IsTeacher])
    def compose(self, request, pk=None):
        """随机 / 手动组卷（需求 T-E-02 / T-E-03 / 8.2）。"""
        exam = self.get_object()
        mode = request.data.get("mode", "random")
        if mode == "manual":
            items, total = compose_manual(request.data.get("questions", []))
        else:
            items, total = compose_random(exam.course_id, request.data.get("rules", []))

        paper = Paper.objects.create(
            course_id=exam.course_id,
            exam=exam,
            mode=mode,
            question_items=items,
            total_score=total,
        )
        exam.total_score = total
        exam.save(update_fields=["total_score", "updated_at"])
        return api_response(PaperSerializer(paper).data, message=f"组卷完成，共 {len(items)} 题")

    @action(detail=True, methods=["get"], url_path="monitor", permission_classes=[IsTeacher])
    def monitor(self, request, pk=None):
        """考试监控：各学生答卷状态（需求 T-E-06）。"""
        exam = self.get_object()
        subs = exam.submissions.select_related("student")
        return api_response(ExamSubmissionSerializer(subs, many=True).data)


class ExamSubmissionViewSet(BaseModelViewSet):
    serializer_class = ExamSubmissionSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["exam", "student", "status"]

    def get_queryset(self):
        user = self.request.user
        qs = ExamSubmission.objects.select_related("student", "exam")
        if user.is_authenticated and user.is_student:
            qs = qs.filter(student=user)
        return qs

    @action(detail=False, methods=["post"], url_path="start")
    def start(self, request):
        """学生开始考试，分配试卷（需求 S-E-02）。"""
        exam_id = request.data.get("exam")
        exam = Exam.objects.get(id=exam_id)
        # per_student_paper：优先取学生专属卷，否则取共用卷
        paper = (
            exam.papers.filter(student=request.user).first()
            or exam.papers.filter(student__isnull=True).first()
        )
        sub, _ = ExamSubmission.objects.get_or_create(
            exam=exam,
            student=request.user,
            defaults={"paper": paper, "started_at": timezone.now(), "status": ExamSubmission.Status.IN_PROGRESS},
        )
        if sub.started_at is None:
            sub.started_at = timezone.now()
            sub.status = ExamSubmission.Status.IN_PROGRESS
            sub.paper = paper
            sub.save(update_fields=["started_at", "status", "paper", "updated_at"])
        return api_response(
            {
                "submission": ExamSubmissionSerializer(sub).data,
                "questions": build_for_taking(paper, exam),
                "anti_cheat": exam.anti_cheat,
                "duration": exam.duration,
            },
            message="考试已开始",
        )

    @action(detail=True, methods=["get"], url_path="review")
    def review(self, request, pk=None):
        """考后回看答卷与解析（需求 S-E-05）。仅本人、且考试允许展示时可见。"""
        sub = self.get_object()
        if sub.student_id != request.user.id:
            return api_response(message="无权查看", code=403, status=403)
        if not sub.exam.show_analysis_after:
            return api_response(message="本次考试未开放解析", code=403, status=403)
        if sub.status not in (
            ExamSubmission.Status.SUBMITTED,
            ExamSubmission.Status.TIMEOUT,
        ):
            return api_response(message="交卷后才能查看", code=400, status=400)
        return api_response(
            {
                "submission": ExamSubmissionSerializer(sub).data,
                "questions": build_for_review(sub.paper, sub),
            }
        )

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        """交卷：客观题自动评分，主观题留待教师批改（需求 S-E-04 / T-E-07）。"""
        sub = self.get_object()
        answers = request.data.get("answers", sub.answers)
        timeout = bool(request.data.get("timeout", False))

        objective_total = Decimal("0")
        items = sub.paper.question_items if sub.paper else []
        q_map = {q.id: q for q in Question.objects.filter(id__in=[i["question_id"] for i in items])}
        for item in items:
            q = q_map.get(item["question_id"])
            if not q:
                continue
            stu_ans = answers.get(str(q.id)) or answers.get(q.id) or {}
            is_correct, score = grade_objective(q, stu_ans)
            if score is not None:
                # 按试卷题目分值折算（题库分值与试卷分值可能不同）
                full = Decimal(str(q.score)) or Decimal("1")
                ratio = Decimal(str(item.get("score", q.score))) / full if full else Decimal("0")
                objective_total += (score * ratio)

        sub.answers = answers
        sub.objective_score = objective_total
        sub.total_score = objective_total  # 含主观题时，教师批改后再累加
        sub.submitted_at = timezone.now()
        sub.status = ExamSubmission.Status.TIMEOUT if timeout else ExamSubmission.Status.SUBMITTED
        sub.save()
        return api_response(ExamSubmissionSerializer(sub).data, message="交卷成功")


class ExamLogViewSet(BaseModelViewSet):
    serializer_class = ExamLogSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["exam", "student", "action"]

    def get_queryset(self):
        user = self.request.user
        qs = ExamLog.objects.all()
        if user.is_authenticated and user.is_student:
            qs = qs.filter(student=user)
        return qs

    def create(self, request, *args, **kwargs):
        """前端上报防作弊行为日志（需求 T-E-05）。异常行为同时标记答卷。"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        log = serializer.save(
            student=request.user,
            ip=request.META.get("REMOTE_ADDR", ""),
            device=request.META.get("HTTP_USER_AGENT", "")[:255],
        )
        ExamSubmission.objects.filter(exam=log.exam, student=request.user).update(abnormal=True)
        return api_response(self.get_serializer(log).data, message="已记录", status=201)
