from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated

from apps.common.access import is_platform_admin
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
        if getattr(user, "is_student", False):
            # 学生仅见已发布、且自己所在班级的考试
            qs = qs.filter(
                status=Exam.Status.PUBLISHED,
                classroom__students__student=user,
                classroom__students__learn_status="active",
            )
        elif getattr(user, "is_teacher", False):
            qs = qs.filter(classroom__teacher=user, course__teacher=user)
        elif not is_platform_admin(user):
            qs = qs.none()
        return qs.distinct()

    def _notify_if_published(self, instance, previous_status):
        """考试首次进入「已发布」状态时通知班级学生。"""
        if instance.status != Exam.Status.PUBLISHED or previous_status == Exam.Status.PUBLISHED:
            return
        from apps.users.models import notify_class_students

        notify_class_students(
            instance.classroom,
            ntype="exam",
            title=f"新考试发布：{instance.name}",
            content=f"《{instance.course.name}》发布了新考试「{instance.name}」，请按时参加。",
            link=f"/student/courses/{instance.course_id}/exams",
        )

    def perform_create(self, serializer):
        instance = serializer.save()
        self._notify_if_published(instance, None)

    def perform_update(self, serializer):
        previous = serializer.instance.status
        instance = serializer.save()
        self._notify_if_published(instance, previous)

    @action(detail=True, methods=["post"], url_path="compose", permission_classes=[IsTeacher])
    def compose(self, request, pk=None):
        """随机 / 手动组卷（需求 T-E-02 / T-E-03 / 8.2）。"""
        exam = self.get_object()
        if exam.status != Exam.Status.DRAFT:
            raise ValidationError("考试发布后不能重新组卷")
        mode = request.data.get("mode", "random")
        try:
            if mode == "manual":
                raw_questions = request.data.get("questions", [])
                if not isinstance(raw_questions, list) or not raw_questions:
                    raise ValidationError({"questions": "请至少选择一道题目"})
                question_ids = [int(item["question_id"]) for item in raw_questions]
                if len(question_ids) != len(set(question_ids)):
                    raise ValidationError({"questions": "同一道题不能重复添加"})
                if any(Decimal(str(item.get("score", 5))) <= 0 for item in raw_questions):
                    raise ValidationError({"questions": "题目分值必须大于 0"})
                allowed = Question.objects.filter(
                    id__in=question_ids,
                    course=exam.course,
                    status=Question.Status.PUBLISHED,
                ).count()
                if allowed != len(question_ids):
                    raise ValidationError({"questions": "包含其他课程、未发布或不存在的题目"})
                items, total = compose_manual(raw_questions)
            elif mode == "random":
                items, total = compose_random(exam.course_id, request.data.get("rules", []))
            else:
                raise ValidationError({"mode": "组卷模式不正确"})
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ValidationError("组卷参数格式不正确") from exc
        if not items or total <= 0:
            raise ValidationError("没有选出有效题目，请检查组卷规则和题目分值")

        exam.papers.all().delete()
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
        return api_response(ExamSubmissionSerializer(subs, many=True, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="release-scores", permission_classes=[IsTeacher])
    def release_scores(self, request, pk=None):
        """统一出分：发布本场考试所有已完成批改的答卷成绩（需求 T-E-04）。

        返回发布数量与因主观题未批改而跳过的学生名单。
        """
        exam = self.get_object()
        subs = list(exam.submissions.select_related("student", "paper").filter(
            status__in=[ExamSubmission.Status.SUBMITTED, ExamSubmission.Status.TIMEOUT],
        ))
        short_qids_by_paper = {}
        for sub in subs:
            if sub.paper_id and sub.paper_id not in short_qids_by_paper:
                items = sub.paper.question_items or []
                qtypes = Question.objects.filter(
                    id__in=[i["question_id"] for i in items]
                ).values("id", "qtype")
                short_qids_by_paper[sub.paper_id] = {
                    str(q["id"]) for q in qtypes if q["qtype"] == Question.QType.SHORT
                }
        released, skipped = 0, []
        for sub in subs:
            need = short_qids_by_paper.get(sub.paper_id, set())
            graded = set((sub.subjective_scores or {}).keys())
            if need - graded:
                skipped.append(sub.student.real_name or sub.student.username)
                continue
            if not sub.score_released:
                sub.score_released = True
                sub.save(update_fields=["score_released", "updated_at"])
            released += 1
        return api_response(
            {"released": released, "skipped": skipped},
            message=f"已发布 {released} 份成绩" + (f"，{len(skipped)} 份因主观题未批改被跳过" if skipped else ""),
        )


class ExamSubmissionViewSet(BaseModelViewSet):
    serializer_class = ExamSubmissionSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["exam", "student", "status"]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs = ExamSubmission.objects.select_related("student", "exam")
        if getattr(user, "is_student", False):
            qs = qs.filter(student=user)
        elif getattr(user, "is_teacher", False):
            qs = qs.filter(exam__classroom__teacher=user, exam__course__teacher=user)
        elif not is_platform_admin(user):
            qs = qs.none()
        return qs

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed("POST", detail="请使用 start 接口开始考试")

    @action(detail=False, methods=["post"], url_path="start")
    @transaction.atomic
    def start(self, request):
        """学生开始考试，分配试卷（需求 S-E-02）。"""
        if not request.user.is_student:
            raise PermissionDenied("仅学生可开始考试")
        exam_id = request.data.get("exam")
        exam = get_object_or_404(
            Exam.objects.filter(
                status=Exam.Status.PUBLISHED,
                classroom__students__student=request.user,
                classroom__students__learn_status="active",
            ).distinct(),
            id=exam_id,
        )
        now = timezone.now()
        if exam.start_at and now < exam.start_at:
            return api_response(message="考试尚未开始", code=400, status=400)
        if exam.end_at and now > exam.end_at:
            return api_response(message="考试已结束", code=400, status=400)
        # per_student_paper：优先取学生专属卷，否则取共用卷
        paper = (
            exam.papers.filter(student=request.user).first()
            or exam.papers.filter(student__isnull=True).first()
        )
        if not paper:
            raise ValidationError("考试尚未完成组卷，请联系教师")
        sub, created = ExamSubmission.objects.select_for_update().get_or_create(
            exam=exam,
            student=request.user,
            defaults={"paper": paper, "started_at": now, "status": ExamSubmission.Status.IN_PROGRESS},
        )
        if not created and sub.status in (
            ExamSubmission.Status.SUBMITTED,
            ExamSubmission.Status.TIMEOUT,
        ):
            if not exam.allow_resubmit:
                raise ValidationError("本次考试已经提交，不能重复作答")
            sub.answers = {}
            sub.submitted_at = None
            sub.objective_score = None
            sub.total_score = None
            sub.subjective_scores = {}
            sub.score_released = False
            sub.abnormal = False
        if created or sub.status != ExamSubmission.Status.IN_PROGRESS or sub.started_at is None:
            sub.started_at = now
            sub.status = ExamSubmission.Status.IN_PROGRESS
            sub.paper = paper
            sub.save()
        return api_response(
            {
                "submission": ExamSubmissionSerializer(
                    sub, context={"request": request}
                ).data,
                "questions": build_for_taking(paper, exam),
                "anti_cheat": exam.anti_cheat,
                "duration": exam.duration,
            },
            message="考试已开始",
        )

    @action(detail=True, methods=["get"], url_path="review")
    def review(self, request, pk=None):
        """考后回看答卷与解析（需求 S-E-05）。仅本人、成绩已发布且考试允许展示时可见。"""
        sub = self.get_object()
        if sub.student_id != request.user.id:
            return api_response(message="无权查看", code=403, status=403)
        if not sub.score_released:
            return api_response(message="成绩尚未发布，请等待教师统一出分", code=403, status=403)
        if not sub.exam.show_analysis_after:
            return api_response(message="本次考试未开放解析", code=403, status=403)
        if sub.status not in (
            ExamSubmission.Status.SUBMITTED,
            ExamSubmission.Status.TIMEOUT,
        ):
            return api_response(message="交卷后才能查看", code=400, status=400)
        exam_finished = sub.exam.status == Exam.Status.FINISHED or (
            sub.exam.end_at and timezone.now() >= sub.exam.end_at
        )
        if not exam_finished:
            return api_response(message="考试结束后才能查看解析", code=403, status=403)
        return api_response(
            {
                "submission": ExamSubmissionSerializer(
                    sub, context={"request": request}
                ).data,
                "questions": build_for_review(sub.paper, sub),
            }
        )

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        """交卷：客观题自动评分，主观题留待教师批改（需求 S-E-04 / T-E-07）。"""
        if not request.user.is_student:
            raise PermissionDenied("仅学生可提交答卷")
        sub = self.get_object()
        if sub.status != ExamSubmission.Status.IN_PROGRESS or not sub.started_at:
            raise ValidationError("答卷不在作答状态，请先开始考试")
        if not sub.paper:
            raise ValidationError("答卷未分配试卷，请联系教师")
        answers = request.data.get("answers", sub.answers)
        if not isinstance(answers, dict):
            raise ValidationError({"answers": "答案格式不正确"})
        now = timezone.now()
        deadlines = [sub.started_at + timedelta(minutes=sub.exam.duration)]
        if sub.exam.end_at:
            deadlines.append(sub.exam.end_at)
        timeout = now > min(deadlines)

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
        sub.submitted_at = now
        sub.status = ExamSubmission.Status.TIMEOUT if timeout else ExamSubmission.Status.SUBMITTED
        sub.save()
        return api_response(
            ExamSubmissionSerializer(sub, context={"request": request}).data,
            message="交卷成功",
        )

    def _subjective_items(self, sub):
        """返回答卷试卷中的主观题（题目、卷面分值、学生答案）。"""
        items = sub.paper.question_items if sub.paper else []
        q_map = {q.id: q for q in Question.objects.filter(id__in=[i["question_id"] for i in items])}
        result = []
        answers = sub.answers or {}
        for item in sorted(items, key=lambda x: x.get("order", 0)):
            q = q_map.get(item["question_id"])
            if not q or q.qtype != Question.QType.SHORT:
                continue
            result.append({
                "question_id": q.id,
                "order": item.get("order", 0),
                "score": str(item.get("score", q.score)),
                "stem": q.stem,
                "reference_answer": q.answer,
                "analysis": q.analysis,
                "student_answer": answers.get(str(q.id)) or answers.get(q.id) or {},
            })
        return result

    @action(detail=True, methods=["get"], url_path="grading-detail", permission_classes=[IsTeacher])
    def grading_detail(self, request, pk=None):
        """教师查看答卷的主观题作答明细，用于批改（需求 T-E-07）。"""
        sub = self.get_object()
        return api_response({
            "submission": ExamSubmissionSerializer(sub, context={"request": request}).data,
            "subjective_questions": self._subjective_items(sub),
            "subjective_scores": sub.subjective_scores or {},
        })

    @action(detail=True, methods=["post"], url_path="grade", permission_classes=[IsTeacher])
    def grade(self, request, pk=None):
        """教师批改考试主观题并核算总分（需求 T-E-07）。

        参数：{"scores": {question_id: 得分}}，可多次提交直至全部主观题完成评分。
        """
        sub = self.get_object()
        if sub.status not in (ExamSubmission.Status.SUBMITTED, ExamSubmission.Status.TIMEOUT):
            return api_response(message="该答卷尚未提交，不能批改", code=400, status=400)

        subjective = self._subjective_items(sub)
        if not subjective:
            return api_response(message="该试卷没有主观题", code=400, status=400)

        full_map = {str(item["question_id"]): Decimal(str(item["score"])) for item in subjective}
        saved = {str(k): Decimal(str(v)) for k, v in (sub.subjective_scores or {}).items()}
        incoming = request.data.get("scores", {}) or {}
        for qid, raw in incoming.items():
            qid = str(qid)
            if qid not in full_map:
                return api_response(message=f"题目 {qid} 不是本卷主观题", code=400, status=400)
            try:
                score = Decimal(str(raw)).quantize(Decimal("0.1"))
            except Exception:
                return api_response(message="分值格式不正确", code=400, status=400)
            if score < 0 or score > full_map[qid]:
                return api_response(message=f"题目 {qid} 得分须在 0~{full_map[qid]} 之间", code=400, status=400)
            saved[qid] = score

        missing = [qid for qid in full_map if qid not in saved]
        sub.subjective_scores = {k: str(v) for k, v in saved.items()}
        if not missing:
            subjective_total = sum(saved.values(), Decimal("0"))
            sub.total_score = (sub.objective_score or Decimal("0")) + subjective_total
        sub.save(update_fields=["subjective_scores", "total_score", "updated_at"])
        return api_response(
            ExamSubmissionSerializer(sub, context={"request": request}).data,
            message="批改完成" if not missing else f"已保存，仍有 {len(missing)} 道主观题未评分",
        )

    @action(detail=True, methods=["post"], url_path="release", permission_classes=[IsTeacher])
    def release(self, request, pk=None):
        """发布单个学生成绩（统一出分，需求 T-E-04）。"""
        sub = self.get_object()
        if sub.status not in (ExamSubmission.Status.SUBMITTED, ExamSubmission.Status.TIMEOUT):
            return api_response(message="该答卷尚未提交", code=400, status=400)
        subjective = self._subjective_items(sub)
        graded = set((sub.subjective_scores or {}).keys())
        if any(str(item["question_id"]) not in graded for item in subjective):
            return api_response(message="尚有主观题未批改，不能发布成绩", code=400, status=400)
        sub.score_released = True
        sub.save(update_fields=["score_released", "updated_at"])
        return api_response(
            ExamSubmissionSerializer(sub, context={"request": request}).data,
            message="成绩已发布",
        )


class ExamLogViewSet(BaseModelViewSet):
    serializer_class = ExamLogSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["exam", "student", "action"]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs = ExamLog.objects.all()
        if getattr(user, "is_student", False):
            qs = qs.filter(student=user)
        elif getattr(user, "is_teacher", False):
            qs = qs.filter(exam__classroom__teacher=user, exam__course__teacher=user)
        elif not is_platform_admin(user):
            qs = qs.none()
        return qs

    def create(self, request, *args, **kwargs):
        """前端上报防作弊行为日志（需求 T-E-05）。异常行为同时标记答卷。"""
        if not request.user.is_student:
            raise PermissionDenied("仅学生可上报考试行为")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        exam = serializer.validated_data["exam"]
        submission = ExamSubmission.objects.filter(
            exam=exam,
            student=request.user,
            status=ExamSubmission.Status.IN_PROGRESS,
        ).first()
        if not submission:
            raise PermissionDenied("考试未开始、已结束或无权访问")
        log = serializer.save(
            student=request.user,
            ip=request.META.get("REMOTE_ADDR", ""),
            device=request.META.get("HTTP_USER_AGENT", "")[:255],
        )
        ExamSubmission.objects.filter(pk=submission.pk).update(abnormal=True)
        return api_response(self.get_serializer(log).data, message="已记录", status=201)
