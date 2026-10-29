from decimal import Decimal

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.common.access import is_platform_admin
from apps.common.error_pages import render_block_page
from apps.common.permissions import IsStudent, IsTeacher, IsTeacherOrReadOnly
from apps.common.response import api_response
from rest_framework_simplejwt.authentication import JWTAuthentication
from .auth import LabTokenAuthentication
from apps.common.viewsets import BaseModelViewSet
from apps.courses import resource_gate

from . import bridge, gate, guide_preset, scoring, seedgen
from .models import (
    Lab,
    LabGuide,
    LabSchedule,
    LabSubmission,
    LabTemplate,
)
from .serializers import (
    LabGuideSerializer,
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
            qs = qs.filter(lab__course__teacher=user)
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
        # 训练型但保留排课硬控制：窗口内才可进入（票据一次性 + 2h 有效，
        # 窗口外旧链接/旧票据均无法进入）
        schedule = self._resolve_schedule(lab, request.user)
        if not schedule:
            raise ValidationError("你没有该实验的排课权限")

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
        # 页面层也进门控（签名含发布状态，下线即失效）；attempt_token 拼入 URL，
        # 实验页 bridge 从 location.search 读取（双层：门控管可读、票据管数据）
        gate_url = gate.sign_lab(lab)["url"]
        return api_response(
            {
                "submission": LabSubmissionSerializer(sub, context={"request": request}).data,
                "attempt_token": ticket.token,
                "expires_at": ticket.expires_at,
                "random_seed": sub.random_seed,
                "page_url": f"{gate_url}&token={ticket.token}",
            },
            message="实验已开始",
        )

    def _resolve_schedule(self, lab, user):
        """排课硬控制：仅窗口内的排课可进入。"""
        for s in lab.schedules.filter(
            classroom__students__student=user, classroom__students__learn_status="active"
        ).order_by("open_at"):
            if s.is_open():
                return s
        return None

    def _reset_fields(self, sub, lab, operator):
        """重做开始一轮：过程数据清零、状态回进行中；**成绩保留**——上一轮
        分数/明细/提交时间不动，学生仍可见，新提交后覆盖为最新成绩。"""
        sub.attempt += 1
        sub.random_seed = seedgen.generate_seed(lab, sub.student_id, sub.attempt)
        sub.status = LabSubmission.Status.IN_PROGRESS
        sub.error_log = []
        sub.steps_result = {}
        sub.elapsed_seconds = 0
        sub.error_count = 0
        sub.passed_steps = 0
        sub.total_steps = 0
        sub.started_at = timezone.now()
        sub.reset_by = operator
        sub.reset_at = timezone.now()

    # ---- 桥接：静态页换取随机参数 ----
    @action(detail=False, methods=["get"], url_path="bridge-validate",
            permission_classes=[IsAuthenticated],
            authentication_classes=[LabTokenAuthentication, JWTAuthentication])
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
        # 票据有效期内实验被下线也要拦截（门控签名已失效，票据层同步拒绝）
        if lab.status != Lab.Status.PUBLISHED:
            return api_response(message="实验已下线，请联系教师重新上线", code=403, status=403)
        return api_response(
            {
                "submission_id": sub.id,
                "lab": {"id": lab.id, "title": lab.title, "code": lab.template.code,
                        "standard_minutes": lab.effective_standard_minutes,
                        "time_limit_seconds": lab.time_limit_seconds},
                "random_seed": sub.random_seed,
                "expected": seedgen.derive_expected(sub.random_seed, lab.template.code),
                "status": sub.status,
            }
        )

    # ---- 学生：提交（服务端重算评分） ----
    @action(detail=True, methods=["post"], url_path="submit", permission_classes=[IsStudent],
            authentication_classes=[LabTokenAuthentication, JWTAuthentication])
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
        if not isinstance(steps, (dict, list)) or not isinstance(error_log, list):
            raise ValidationError("步骤结果或错误日志格式不正确")
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

            lab = sub.lab
            step_scores = scoring.calc_step_scores(sub, lab.effective_standard_minutes, lab.total_score)
            total = scoring.calc_total(step_scores, lab.total_score)
            sub.base_score = step_scores["base"]
            sub.accuracy_score = step_scores["accuracy"]
            sub.efficiency_score = step_scores["efficiency"]
            sub.completion_score = step_scores["completion"]
            sub.total_score = total
            sub.score_breakdown = scoring.build_breakdown(sub, step_scores, total)
            sub.save()

        bridge.consume_token(ticket)
        return api_response(
            LabSubmissionSerializer(sub, context={"request": request}).data,
            message=f"实验提交成功，得分 {sub.total_score}",
        )

    # ---- 学生：提交实验结论（二期报告的前置数据） ----
    @action(detail=True, methods=["post"], url_path="conclusion", permission_classes=[IsStudent],
            authentication_classes=[LabTokenAuthentication, JWTAuthentication])
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


# ---------------------------------------------------------------------------
# 实验页门控（普通 Django 视图，不进 router——资产路径无尾斜杠，同课程资源门控模式）
# ---------------------------------------------------------------------------

def lab_gate_page(request, token):
    """实验入口页：验签（含发布状态）→ 读静态 HTML → 注入 <base> 指向签名资产路由。"""
    lab = Lab.objects.select_related("template").filter(access_token=token).first()
    if lab is None or not gate.verify_lab(lab, request.GET.get("sig", ""), request.GET.get("exp", "")):
        return render_block_page(403, "实验链接无效或已失效", "实验已下线或链接已过期，请返回课程实验页重新进入。")
    html = gate.read_page(lab)
    if html is None:
        return render_block_page(404, "实验页面不存在", "平台尚未部署该实验页面，请联系管理员。")
    response = HttpResponse(
        resource_gate.inject_base(html, gate.asset_base(lab, request.GET.get("sig", ""), request.GET.get("exp", ""))),
        content_type="text/html; charset=utf-8",
    )
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    # 与课程资源入口页一致：允许同源 iframe 嵌入（clickjacking 中间件不覆盖已设置的响应头）
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response


def lab_gate_asset(request, token, sig, exp, rest):
    """实验页资产（lab-bridge.js 等）：同一令牌签名校验后从 LABS_ROOT 读出。"""
    lab = Lab.objects.filter(access_token=token).first()
    if lab is None or not gate.verify_lab(lab, sig, exp):
        return render_block_page(403, "实验链接无效或已失效", "实验已下线或链接已过期，请返回课程实验页重新进入。")
    path = gate.read_asset(rest)
    if path is None:
        return render_block_page(404, "实验资源文件不存在", "请返回课程实验页重新进入。")
    response = HttpResponse(path.read_bytes(), content_type=resource_gate.guess_content_type(path))
    response["Cache-Control"] = "private, max-age=7200"
    response["X-Content-Type-Options"] = "nosniff"
    return response
