from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.common.access import is_platform_admin
from apps.common.permissions import IsStudent, IsTeacher, IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet
from apps.homework.models import question_snapshot
from apps.questions.grading import grade_objective
from apps.questions.models import Question

from . import bridge, guide_preset, scoring, seedgen
from .models import (
    Lab,
    LabAnswer,
    LabGuide,
    LabQuestion,
    LabSchedule,
    LabSubmission,
    LabTemplate,
)
from .serializers import (
    LabAnswerSerializer,
    LabGuideSerializer,
    LabQuestionSerializer,
    LabScheduleSerializer,
    LabSerializer,
    LabSubmissionSerializer,
    LabTemplateSerializer,
)


class LabTemplateViewSet(BaseModelViewSet):
    """实验模板库（平台预置，只读）。"""

    serializer_class = LabTemplateSerializer
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        return LabTemplate.objects.filter(is_active=True)


class LabGuideViewSet(
    mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    """实验必读（平台级单例，路由走 detail）：登录用户可读；教师可编辑/恢复预设。

    GET    /lab-guide/1/        读取（content 为空自动回退平台预设内容）
    PATCH  /lab-guide/1/        教师更新标题/内容
    POST   /lab-guide/1/reset/  教师清空 content（恢复平台预设）
    """

    serializer_class = LabGuideSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        guide, _ = LabGuide.objects.get_or_create(
            pk=1, defaults={"title": guide_preset.PRESET_TITLE}
        )
        return guide

    def retrieve(self, request, *args, **kwargs):
        guide = self.get_object()
        data = LabGuideSerializer(guide, context={"request": request}).data
        if data["is_preset"]:
            data["title"] = data["title"] or guide_preset.PRESET_TITLE
            data["content"] = guide_preset.PRESET_CONTENT
        return api_response(data)

    def partial_update(self, request, *args, **kwargs):
        if not getattr(request.user, "is_teacher", False):
            raise PermissionDenied("只有教师可以编辑实验必读")
        guide = self.get_object()
        serializer = LabGuideSerializer(
            guide, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return api_response(serializer.data, message="实验必读已更新")

    @action(detail=True, methods=["post"], url_path="reset", permission_classes=[IsTeacher])
    def reset(self, request, pk=None):
        guide = self.get_object()
        guide.content = ""
        guide.title = guide_preset.PRESET_TITLE
        guide.updated_by = request.user
        guide.save(update_fields=["content", "title", "updated_by", "updated_at"])
        data = LabGuideSerializer(guide, context={"request": request}).data
        data["title"] = guide_preset.PRESET_TITLE
        data["content"] = guide_preset.PRESET_CONTENT
        return api_response(data, message="已恢复平台预设内容")


class LabViewSet(BaseModelViewSet):
    serializer_class = LabSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "catalog", "status"]

    def get_queryset(self):
        user = self.request.user
        qs = Lab.objects.select_related("template", "course", "catalog")
        if getattr(user, "is_student", False):
            # 学生可见：已发布 + 所在 active 班级被排课 + 班级关联该课程
            qs = qs.filter(
                status=Lab.Status.PUBLISHED,
                schedules__classroom__students__student=user,
                schedules__classroom__students__learn_status="active",
                course__classes__students__student=user,
                course__classes__students__learn_status="active",
            ).distinct()
        elif getattr(user, "is_teacher", False):
            qs = qs.filter(course__teacher=user)
        elif not is_platform_admin(user):
            qs = qs.none()
        return qs.distinct()

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=["post"], url_path="questions", permission_classes=[IsTeacher])
    def add_questions(self, request, pk=None):
        """从题库选题附为实验题目（草稿期；发布后禁止修改）。"""
        lab = self.get_object()
        if lab.status != Lab.Status.DRAFT:
            raise ValidationError("实验发布后不能修改题目")
        raw_ids = request.data.get("question_ids", [])
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ValidationError({"question_ids": "请至少选择一道题目"})
        try:
            question_ids = [int(qid) for qid in raw_ids]
        except (TypeError, ValueError) as exc:
            raise ValidationError({"question_ids": "题目 ID 格式不正确"}) from exc
        if len(question_ids) != len(set(question_ids)):
            raise ValidationError({"question_ids": "同一道题不能重复添加"})
        questions = Question.objects.filter(
            id__in=question_ids, course=lab.course, status=Question.Status.PUBLISHED
        )
        if questions.count() != len(question_ids):
            raise ValidationError({"question_ids": "包含其他课程、未发布或不存在的题目"})
        next_order = lab.questions.count()
        created = []
        for offset, q in enumerate(questions.order_by("id")):
            item = LabQuestion.objects.create(
                lab=lab, question=q, score=q.score, order=next_order + offset,
                snapshot=question_snapshot(q),
            )
            created.append(item)
        return api_response(LabQuestionSerializer(created, many=True).data, message=f"已添加 {len(created)} 道题")

    @action(detail=True, methods=["delete"], url_path="questions", permission_classes=[IsTeacher])
    def remove_question(self, request, pk=None):
        lab = self.get_object()
        if lab.status != Lab.Status.DRAFT:
            raise ValidationError("实验发布后不能修改题目")
        lab.questions.all().delete()
        return api_response(message="已清空实验题目")

    @action(detail=True, methods=["post"], url_path="publish", permission_classes=[IsTeacher])
    def publish(self, request, pk=None):
        lab = self.get_object()
        if lab.status == Lab.Status.PUBLISHED:
            return api_response(message="实验已是发布状态")
        if not lab.schedules.exists():
            raise ValidationError("请先给班级排课再发布实验")
        lab.status = Lab.Status.PUBLISHED
        lab.save(update_fields=["status", "updated_at"])
        self._notify_schedules(lab)
        return api_response(LabSerializer(lab, context={"request": request}).data, message="实验已发布")

    @action(detail=True, methods=["post"], url_path="close", permission_classes=[IsTeacher])
    def close(self, request, pk=None):
        lab = self.get_object()
        lab.status = Lab.Status.CLOSED
        lab.save(update_fields=["status", "updated_at"])
        return api_response(LabSerializer(lab, context={"request": request}).data, message="实验已下线")

    def _notify_schedules(self, lab):
        from apps.users.models import notify_class_students

        for schedule in lab.schedules.select_related("classroom").all():
            notify_class_students(
                schedule.classroom,
                ntype="lab",
                title=f"新实验发布：{lab.title}",
                content=f"《{lab.course.name}》发布了新实验「{lab.title}」，请在开放时间内完成。",
                link=f"/student/courses/{lab.course_id}/labs",
            )

    @action(detail=True, methods=["get"], url_path="my-schedule", permission_classes=[IsAuthenticated])
    def my_schedule(self, request, pk=None):
        """当前用户在该实验上的开放窗口。"""
        lab = self.get_object()
        schedules = lab.schedules.filter(
            classroom__students__student=request.user,
            classroom__students__learn_status="active",
        )
        now = timezone.now()
        data = [
            {
                "id": s.id, "classroom_id": s.classroom_id, "classroom": s.classroom.name,
                "open_at": s.open_at, "close_at": s.close_at, "is_open": s.is_open(now),
            }
            for s in schedules
        ]
        return api_response({"schedules": data, "now": now})


class LabScheduleViewSet(BaseModelViewSet):
    serializer_class = LabScheduleSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["lab", "classroom"]

    def get_queryset(self):
        user = self.request.user
        qs = LabSchedule.objects.select_related("lab", "classroom")
        if getattr(user, "is_teacher", False):
            qs = qs.filter(classroom__teacher=user, lab__course__teacher=user)
        elif getattr(user, "is_student", False):
            qs = qs.filter(
                classroom__students__student=user, classroom__students__learn_status="active"
            )
        elif not is_platform_admin(user):
            qs = qs.none()
        return qs.distinct()

    def create(self, request, *args, **kwargs):
        """同班重排 = 更新已有窗口（模型约束 lab+classroom 唯一，重开复用改时间）。"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attrs = serializer.validated_data
        existing = LabSchedule.objects.filter(
            lab=attrs["lab"], classroom=attrs["classroom"]
        ).first()
        if existing:
            for field in ("open_at", "close_at"):
                if field in attrs:
                    setattr(existing, field, attrs[field])
            # 复用 validate 的窗口时间校验
            check = LabScheduleSerializer(
                existing, data={"open_at": existing.open_at, "close_at": existing.close_at}, partial=True
            )
            check.is_valid(raise_exception=True)
            existing.save()
            return api_response(
                LabScheduleSerializer(existing).data, message="已更新该班级的开放窗口"
            )
        self.perform_create(serializer)
        return api_response(serializer.data, message="排课成功", status=201)


class LabSubmissionViewSet(BaseModelViewSet):
    serializer_class = LabSubmissionSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["lab", "student", "status"]

    def get_queryset(self):
        user = self.request.user
        qs = LabSubmission.objects.select_related("lab", "student", "lab__template", "lab__course")
        if getattr(user, "is_student", False):
            qs = qs.filter(student=user)
        elif getattr(user, "is_teacher", False):
            qs = qs.filter(lab__course__teacher=user)
        elif not is_platform_admin(user):
            qs = qs.none()
        return qs.distinct()

    # ---- 学生：开始实验 ----
    @action(detail=False, methods=["post"], url_path="start", permission_classes=[IsStudent])
    def start(self, request):
        lab_id = request.data.get("lab")
        lab = Lab.objects.select_related("template", "course").filter(id=lab_id).first()
        if not lab:
            raise ValidationError("实验不存在")
        if lab.status != Lab.Status.PUBLISHED:
            raise ValidationError("实验未发布或已下线")
        schedule = self._resolve_schedule(lab, request.user)
        if not schedule:
            raise ValidationError("你没有该实验的排课权限")
        if not schedule.is_open():
            raise ValidationError("当前不在实验开放时间内")

        now = timezone.now()
        with transaction.atomic():
            sub, created = LabSubmission.objects.select_for_update().get_or_create(
                lab=lab, student=request.user,
                defaults={
                    "schedule": schedule, "started_at": now,
                    "status": LabSubmission.Status.IN_PROGRESS,
                    "random_seed": seedgen.generate_seed(lab, request.user.id, 1),
                },
            )
            if not created and sub.status == LabSubmission.Status.SUBMITTED:
                if not lab.allow_resubmit:
                    raise ValidationError("实验已提交，如需重做请联系教师重置")
                self._reset_fields(sub, lab, request.user)
            if not sub.random_seed:
                sub.random_seed = seedgen.generate_seed(lab, request.user.id, sub.attempt)
            if sub.schedule_id != schedule.id:
                sub.schedule = schedule
            sub.started_at = sub.started_at or now
            sub.status = LabSubmission.Status.IN_PROGRESS
            sub.save()

        ticket = bridge.issue_token(sub)
        return api_response(
            {
                "submission": LabSubmissionSerializer(sub, context={"request": request}).data,
                "attempt_token": ticket.token,
                "expires_at": ticket.expires_at,
                "random_seed": sub.random_seed,
                "page_url": lab.template.page_url,
                "questions": self._build_for_taking(lab),
            },
            message="实验已开始",
        )

    def _resolve_schedule(self, lab, user):
        for s in lab.schedules.filter(
            classroom__students__student=user, classroom__students__learn_status="active"
        ).order_by("open_at"):
            if s.is_open():
                return s
        return None

    def _reset_fields(self, sub, lab, operator):
        """就地清分（保留记录与审计），重新生成随机参数。"""
        sub.attempt += 1
        sub.random_seed = seedgen.generate_seed(lab, sub.student_id, sub.attempt)
        sub.status = LabSubmission.Status.IN_PROGRESS
        sub.error_log = []
        sub.steps_result = {}
        sub.elapsed_seconds = 0
        sub.error_count = 0
        sub.passed_steps = 0
        sub.total_steps = 0
        sub.base_score = sub.accuracy_score = sub.efficiency_score = None
        sub.completion_score = sub.question_score = sub.total_score = None
        sub.score_breakdown = {}
        sub.subjective_scores = {}
        sub.reviewed = False
        sub.reviewed_by = None
        sub.reviewed_at = None
        sub.abnormal = False
        sub.submitted_at = None
        sub.started_at = timezone.now()
        sub.reset_by = operator
        sub.reset_at = timezone.now()
        sub.answers.all().delete()

    def _build_for_taking(self, lab):
        """学生作答视图的题目（不含答案）。"""
        result = []
        for lq in lab.questions.all().order_by("order"):
            snap = lq.snapshot or {}
            item = {
                "lab_question_id": lq.id,
                "order": lq.order,
                "score": str(lq.score),
                "qtype": snap.get("qtype"),
                "stem": snap.get("stem"),
                "options": snap.get("options", []),
            }
            result.append(item)
        return result

    # ---- 桥接：静态页换取随机参数 ----
    @action(detail=False, methods=["get"], url_path="bridge-validate", permission_classes=[IsAuthenticated])
    def bridge_validate(self, request):
        raw_token = request.query_params.get("token", "")
        try:
            ticket = bridge.validate_token(raw_token)
        except ValueError as exc:
            return api_response(message=str(exc), code=403, status=403)
        if ticket.student_id != request.user.id:
            return api_response(message="无权访问该实验票据", code=403, status=403)
        sub = ticket.submission
        lab = sub.lab
        return api_response(
            {
                "submission_id": sub.id,
                "lab": {"id": lab.id, "title": lab.title, "code": lab.template.code,
                        "standard_minutes": lab.effective_standard_minutes,
                        "time_limit_seconds": lab.time_limit_seconds},
                "random_seed": sub.random_seed,
                "expected": seedgen.derive_expected(sub.random_seed, lab.template.code),
                "questions": self._build_for_taking(lab),
                "status": sub.status,
            }
        )

    # ---- 学生：提交（服务端重算评分） ----
    @action(detail=True, methods=["post"], url_path="submit", permission_classes=[IsStudent])
    def submit(self, request, pk=None):
        sub = self.get_object()
        if sub.student_id != request.user.id:
            raise PermissionDenied("只能提交自己的实验")
        if sub.status != LabSubmission.Status.IN_PROGRESS:
            raise ValidationError("实验不在进行中状态")
        try:
            ticket = bridge.validate_token(request.data.get("attempt_token", ""))
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if ticket.submission_id != sub.id:
            raise ValidationError("票据与作答不匹配")
        schedule = sub.schedule
        if schedule and not schedule.is_open():
            raise ValidationError("实验已截止，无法提交")

        steps = request.data.get("steps_result") or {}
        error_log = request.data.get("error_log", []) or []
        answers = request.data.get("answers") or {}
        if not isinstance(steps, (dict, list)) or not isinstance(error_log, list):
            raise ValidationError("步骤结果或错误日志格式不正确")
        if not isinstance(answers, dict):
            raise ValidationError({"answers": "附题作答格式不正确（应为 {lab_question_id: answer}）"})
        try:
            elapsed = max(0, int(request.data.get("elapsed_seconds", 0)))
        except (TypeError, ValueError) as exc:
            raise ValidationError({"elapsed_seconds": "用时格式不正确"}) from exc

        # 步骤结果统一为 {step_id: "pass"/"fail"}
        if isinstance(steps, list):
            steps = {str(i + 1): str(v) for i, v in enumerate(steps)}
        passed = sum(1 for v in steps.values() if v == "pass")
        total = len(steps)
        error_count = len(error_log)

        now = timezone.now()
        with transaction.atomic():
            sub.steps_result = steps
            sub.error_log = error_log
            sub.elapsed_seconds = elapsed
            sub.error_count = error_count
            sub.passed_steps = passed
            sub.total_steps = total
            sub.status = LabSubmission.Status.SUBMITTED
            sub.submitted_at = now
            sub.save()

            # 附题作答落库：{lab_question_id: {key/keys/text/blanks,...}}，评分以题目快照为准
            if answers:
                valid_ids = set(
                    sub.lab.questions.values_list("id", flat=True)
                )
                LabAnswer.objects.filter(submission=sub).delete()
                for raw_id, stu_answer in answers.items():
                    try:
                        lq_id = int(raw_id)
                    except (TypeError, ValueError):
                        raise ValidationError({"answers": f"无效的附题编号：{raw_id}"})
                    if lq_id not in valid_ids:
                        continue  # 非本实验的题目直接忽略
                    if not isinstance(stu_answer, dict):
                        stu_answer = {"text": str(stu_answer)}
                    LabAnswer.objects.create(submission=sub, lab_question_id=lq_id, student_answer=stu_answer)

            lab = sub.lab
            step_scores = scoring.calc_step_scores(sub, lab.effective_standard_minutes, lab.total_score)
            question_total = scoring.grade_submission_questions(sub)
            total = scoring.calc_total(sub, step_scores, question_total, lab.question_weight, lab.total_score)
            sub.base_score = step_scores["base"]
            sub.accuracy_score = step_scores["accuracy"]
            sub.efficiency_score = step_scores["efficiency"]
            sub.completion_score = step_scores["completion"]
            sub.question_score = question_total
            sub.total_score = total
            sub.score_breakdown = scoring.build_breakdown(sub, step_scores, question_total, total)
            sub.save()

        bridge.consume_token(ticket)
        return api_response(
            LabSubmissionSerializer(sub, context={"request": request}).data,
            message=f"实验提交成功，得分 {sub.total_score}",
        )

    # ---- 学生：提交实验结论（二期报告的前置数据） ----
    @action(detail=True, methods=["post"], url_path="conclusion", permission_classes=[IsStudent])
    def conclusion(self, request, pk=None):
        sub = self.get_object()
        if sub.student_id != request.user.id:
            raise PermissionDenied("只能提交自己的实验结论")
        text = str(request.data.get("conclusion", "")).strip()
        if not text:
            raise ValidationError("请填写实验结论")
        from .models import LabReport

        report, _ = LabReport.objects.update_or_create(
            submission=sub, defaults={"conclusion": text}
        )
        return api_response({"id": report.id}, message="实验结论已提交")

    # ---- 教师：复核改分 ----
    @action(detail=True, methods=["post"], url_path="review", permission_classes=[IsTeacher])
    def review(self, request, pk=None):
        sub = self.get_object()
        if sub.lab.course.teacher_id != request.user.id:
            raise PermissionDenied("只能复核自己课程的实验")
        new_total = request.data.get("total_score")
        comment = str(request.data.get("comment", "")).strip()
        if new_total is not None:
            try:
                new_total = Decimal(str(new_total))
            except Exception as exc:
                raise ValidationError({"total_score": "分数格式不正确"}) from exc
            if new_total < 0 or new_total > sub.lab.total_score:
                raise ValidationError({"total_score": f"分数须在 0~{sub.lab.total_score} 之间"})
            sub.total_score = new_total
        sub.score_breakdown = {**(sub.score_breakdown or {}), "review_comment": comment,
                               "reviewed_total": str(sub.total_score)}
        sub.reviewed = True
        sub.reviewed_by = request.user
        sub.reviewed_at = timezone.now()
        sub.save()
        # 通知学生成绩已更新
        from apps.users.models import Notification

        Notification.objects.create(
            user=sub.student, ntype="lab",
            title=f"实验成绩已复核：{sub.lab.title}",
            content=f"你的实验「{sub.lab.title}」成绩经教师复核更新为 {sub.total_score} 分。" + (f"评语：{comment}" if comment else ""),
            link=f"/student/courses/{sub.lab.course_id}/labs",
        )
        return api_response(
            LabSubmissionSerializer(sub, context={"request": request}).data, message="复核完成"
        )

    # ---- 教师：重置学生实验 ----
    @action(detail=True, methods=["post"], url_path="reset", permission_classes=[IsTeacher])
    def reset(self, request, pk=None):
        sub = self.get_object()
        if sub.lab.course.teacher_id != request.user.id:
            raise PermissionDenied("只能重置自己课程的实验")
        with transaction.atomic():
            sub = LabSubmission.objects.select_for_update().get(pk=sub.pk)
            self._reset_fields(sub, sub.lab, request.user)
            sub.save()
        from apps.users.models import Notification

        Notification.objects.create(
            user=sub.student, ntype="lab",
            title=f"实验已重置：{sub.lab.title}",
            content=f"教师重置了你的实验「{sub.lab.title}」，可重新进入实验完成作答。",
            link=f"/student/courses/{sub.lab.course_id}/labs",
        )
        return api_response(
            LabSubmissionSerializer(sub, context={"request": request}).data, message="实验已重置，学生可重做"
        )

    # ---- 教师：主观题批改 ----
    @action(detail=True, methods=["post"], url_path="grade", permission_classes=[IsTeacher])
    def grade(self, request, pk=None):
        sub = self.get_object()
        if sub.lab.course.teacher_id != request.user.id:
            raise PermissionDenied("只能批改自己课程的实验")
        scores = request.data.get("scores", {})
        if not isinstance(scores, dict) or not scores:
            raise ValidationError({"scores": "请提供 {lab_question_id: score} 批改分"})
        subjective_total = Decimal("0")
        for lq in sub.lab.questions.filter(id__in=[int(k) for k in scores.keys()]):
            raw = scores.get(str(lq.id), scores.get(lq.id))
            try:
                value = Decimal(str(raw))
            except Exception as exc:
                raise ValidationError({str(lq.id): "分数格式不正确"}) from exc
            if value < 0 or value > lq.score:
                raise ValidationError({str(lq.id): f"分数须在 0~{lq.score} 之间"})
            answer = LabAnswer.objects.filter(submission=sub, lab_question=lq).first()
            if not answer:
                answer = LabAnswer.objects.create(submission=sub, lab_question=lq)
            answer.score = value
            answer.pending_review = False
            answer.graded_by = request.user
            answer.graded_at = timezone.now()
            answer.save(update_fields=["score", "pending_review", "graded_by", "graded_at", "updated_at"])
            subjective_total += value
        sub.subjective_scores = scores
        sub.question_score = subjective_total.quantize(Decimal("0.1"))
        sub.reviewed = True
        sub.reviewed_by = request.user
        sub.reviewed_at = timezone.now()
        # 重新合成总分
        lab = sub.lab
        step_scores = scoring.calc_step_scores(sub, lab.effective_standard_minutes, lab.total_score)
        total = scoring.calc_total(sub, step_scores, sub.question_score or Decimal("0"),
                                   lab.question_weight, lab.total_score)
        sub.total_score = total
        sub.score_breakdown = scoring.build_breakdown(sub, step_scores, sub.question_score or Decimal("0"), total)
        sub.save()
        return api_response(
            LabSubmissionSerializer(sub, context={"request": request}).data, message="批改完成"
        )

    @action(detail=True, methods=["get"], url_path="answers", permission_classes=[IsAuthenticated])
    def answers(self, request, pk=None):
        sub = self.get_object()
        if sub.student_id != request.user.id and not (
            getattr(request.user, "is_teacher", False) and sub.lab.course.teacher_id == request.user.id
        ):
            raise PermissionDenied("无权查看该作答")
        return api_response(LabAnswerSerializer(sub.answers.all(), many=True).data)

    # ---- 报告：生成（幂等） ----
    @action(detail=True, methods=["post"], url_path="generate-report", permission_classes=[IsAuthenticated])
    def generate_report(self, request, pk=None):
        """生成实验报告 DOCX+PDF（学生本人或课程教师）。需已提交且有结论。"""
        from .models import LabReport
        from .report_generator import generate_report

        sub = self.get_object()
        is_owner = sub.student_id == request.user.id
        is_course_teacher = (
            getattr(request.user, "is_teacher", False) and sub.lab.course.teacher_id == request.user.id
        )
        if not (is_owner or is_course_teacher):
            raise PermissionDenied("无权生成该实验报告")
        if sub.status != LabSubmission.Status.SUBMITTED:
            raise ValidationError("实验提交后才能生成报告")
        report = LabReport.objects.filter(submission=sub).first()
        if not report or not (report.conclusion or "").strip():
            raise ValidationError("请先填写实验结论")
        report = generate_report(sub)
        from .serializers import LabReportSerializer

        return api_response(LabReportSerializer(report).data, message="实验报告已生成")

    # ---- 报告：下载 ----
    @action(detail=True, methods=["get"], url_path="download-report", permission_classes=[IsAuthenticated])
    def download_report(self, request, pk=None):
        """下载报告：?type=docx|pdf（默认 pdf，注意 format 是 DRF 保留参数不能用）。
        本人/课程教师可下载。"""
        from django.http import FileResponse

        from .models import LabReport

        sub = self.get_object()
        is_owner = sub.student_id == request.user.id
        is_course_teacher = (
            getattr(request.user, "is_teacher", False) and sub.lab.course.teacher_id == request.user.id
        )
        if not (is_owner or is_course_teacher):
            raise PermissionDenied("无权下载该实验报告")
        report = LabReport.objects.filter(submission=sub).first()
        if not report:
            return api_response(message="报告尚未生成", code=404, status=404)
        fmt = request.query_params.get("type", "pdf").lower()
        field = report.file_docx if fmt == "docx" else report.file_pdf
        if not field:
            return api_response(message=f"报告 {fmt} 文件不存在", code=404, status=404)
        filename = f"{sub.student.username}_{sub.lab.title}.{fmt}"
        return FileResponse(
            field.open("rb"),
            as_attachment=True,
            filename=filename,
            content_type="application/pdf" if fmt == "pdf" else
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
