from decimal import Decimal
import hashlib
import json
import os

from types import SimpleNamespace
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.access import is_platform_admin, student_submit_block_detail
from apps.common.error_pages import render_block_page
from apps.common.permissions import IsStudent, IsTeacher, IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.throttles import LabGradeThrottle
from rest_framework_simplejwt.authentication import JWTAuthentication
from .auth import LabTokenAuthentication
from apps.common.viewsets import BaseModelViewSet
from apps.courses import resource_gate

from . import bridge, gate, guide_preset, scoring, seedgen, services
from .integration_spec import GRADE_ENDPOINT, build_integration_spec
from .models import (
    Lab,
    LabGuide,
    LabPage,
    LabSchedule,
    LabSubmission,
    LabTemplate,
)
from .serializers import (
    LabGuideSerializer,
    LabPageSerializer,
    LabScheduleSerializer,
    LabSerializer,
    LabSubmissionSerializer,
    LabTemplateSerializer,
    scan_lab_page_html,
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

    def perform_destroy(self, instance):
        """删除实验：CASCADE 只删行不删盘，显式清自定义页面文件与报告文件（C7）。"""
        page = getattr(instance, "custom_page", None)
        if page is not None:
            page.file.delete(save=False)
        for sub in instance.submissions.all():
            report = getattr(sub, "report", None)
            if report is not None:
                if report.file_docx:
                    report.file_docx.delete(save=False)
                if report.file_pdf:
                    report.file_pdf.delete(save=False)
        instance.delete()

    # ---- 教师：自定义实验页面（上传 / 删除 / 预览；IsTeacher 不含 admin，C46） ----
    MAX_PAGE_SIZE = 50 * 1024 * 1024  # 50MB（本期只收单文件 HTML）

    def _notify_admins_page_scan(self, lab, hits):
        """S8 静态扫描命中：通知平台管理员（站内信）。"""
        from apps.users.models import Notification, User

        for admin in User.objects.filter(role=User.Role.ADMIN, is_active=True):
            Notification.objects.create(
                user=admin,
                ntype=Notification.Type.SYSTEM,
                title="自定义实验页面静态扫描命中",
                content=(
                    f"教师 {self.request.user.real_name or self.request.user.username} 上传的"
                    f"实验「{lab.title}」页面命中：{'、'.join(hits)}。请复核该实验页面源码。"
                ),
            )

    @action(detail=True, methods=["post", "delete"], url_path="page", permission_classes=[IsTeacher])
    def page(self, request, pk=None):
        """自定义实验页面：POST 上传/替换单 HTML；DELETE 删除并回退模板模式。"""
        if request.method == "DELETE":
            return self._delete_page(request)
        return self._upload_page(request)

    def _upload_page(self, request):
        """上传/替换单 HTML 实验页面：≤50MB、.html、非空；sha256/上传者留痕；S8 静态扫描。

        命中扫描规则时一律拒绝首次写入，前端展示命中项与源码后由教师显式 confirm=1
        二次确认才落库，并通知平台管理员。
        """
        lab = self.get_object()  # 行级：仅本人课程（get_queryset 已过滤）
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "请上传页面文件"})
        ext = os.path.splitext(upload.name or "")[1].lower()
        if ext not in (".html", ".htm"):
            raise ValidationError({"file": "仅支持单 .html 文件"})
        if upload.size > self.MAX_PAGE_SIZE:
            raise ValidationError({"file": "页面文件不能超过 50MB"})
        if upload.size == 0:
            raise ValidationError({"file": "文件为空"})
        content = b"".join(upload.chunks())
        html = content.decode("utf-8", errors="replace")

        hits = scan_lab_page_html(html)
        if hits and not str(request.data.get("confirm", "")).lower() in ("1", "true", "yes"):
            return api_response(
                {"hits": hits, "require_confirm": True, "size": upload.size},
                message="页面源码命中安全扫描规则，确认无误后请带 confirm=1 重新上传",
                code=400, status=400,
            )

        digest = hashlib.sha256(content).hexdigest()
        from django.core.files.base import ContentFile

        with transaction.atomic():
            old = getattr(lab, "custom_page", None)
            old_file = old.file if old is not None else None
            page, _ = LabPage.objects.update_or_create(
                lab=lab,
                defaults={
                    "kind": LabPage.Kind.SINGLE_HTML,
                    "original_name": (upload.name or "")[:255],
                    "size": upload.size,
                    "sha256": digest,
                    "uploaded_by": request.user,
                },
            )
            page.file.save(f"index{ext}", ContentFile(content), save=True)
        if old_file:
            old_file.delete(save=False)
        lab.page_source = Lab.PageSource.CUSTOM
        lab.save(update_fields=["page_source", "updated_at"])
        if hits:
            self._notify_admins_page_scan(lab, hits)
        return api_response(
            {
                "page": LabPageSerializer(page).data,
                "hits": hits,
                "sha256": digest,
                "page_source": lab.page_source,
            },
            message="页面已上传" + ("（扫描命中，已通知管理员）" if hits else ""),
        )

    def _delete_page(self, request):
        """删除自定义页面：删文件 + 删行；无模板可回退时拒绝（避免实验成「无页面」）。"""
        lab = self.get_object()
        page = getattr(lab, "custom_page", None)
        if page is None:
            raise ValidationError("该实验尚未上传自定义页面")
        if lab.template_id is None:
            raise ValidationError("该实验未绑定平台模板，删除页面后将无法访问，请先上传新页面")
        with transaction.atomic():
            page.file.delete(save=False)
            page.delete()
        lab.page_source = Lab.PageSource.TEMPLATE
        lab.save(update_fields=["page_source", "updated_at"])
        return api_response({"page_source": lab.page_source}, message="自定义页面已删除，实验回退为平台预置模式")

    @action(detail=True, methods=["get"], url_path="page/preview", permission_classes=[IsTeacher])
    def preview_page(self, request, pk=None):
        """教师预览：签发 2h 预览链接（verify_preview，草稿可预览，不取票据、不提交）。"""
        lab = self.get_object()
        if getattr(lab, "custom_page", None) is None:
            raise ValidationError("请先上传实验页面再预览")
        signed = gate.sign_preview(lab)
        return api_response(signed, message="预览链接已生成")

    @action(detail=True, methods=["get"], url_path="integration-spec", permission_classes=[IsTeacher])
    def integration_spec(self, request, pk=None):
        """动态接入说明（Stage 4 / §6.2）：按实验名 / 总分 / 上报地址渲染 Markdown。

        纯渲染：不新增表、不写库、不产生提交；末尾追加教师填写的 `report_note`。
        行级归属由 `get_queryset()` 保证；权限显式 `[IsTeacher]`（不含 admin，C46）。
        """
        lab = self.get_object()
        data = build_integration_spec(
            lab, absolute_grade_url=request.build_absolute_uri(GRADE_ENDPOINT)
        )
        return api_response(data, message="接入说明已生成")

    @action(detail=True, methods=["post"], url_path="grade-debug", permission_classes=[IsTeacher])
    def grade_debug(self, request, pk=None):
        """在线调试（dry-run）：用同一套极简校验跑模拟报文，逐项返回结果，不入库、不产生提交。"""
        lab = self.get_object()
        checks = []

        def check(name, ok, detail="", blocking=True):
            checks.append({
                "name": name, "ok": bool(ok), "detail": str(detail), "blocking": blocking,
            })

        # Stage 9 教师反馈：环境提示项（票据模拟/页面来源/发布状态）对排障没有信息量，全部移除；
        # 「页面文件」升级为页面静态健康检查——dry-run 必须能发现「页面没有接入桥接」这类问题，
        # 而不是无论页面长什么样都 PASS。草稿态依然可调试（创建 → 调试 → 发布的 UI 顺序不变）。
        is_custom = lab.page_source == Lab.PageSource.CUSTOM
        has_page = getattr(lab, "custom_page", None) is not None
        if is_custom and not has_page:
            check("页面文件", False, "尚未上传自定义页面，无法检查页面接入；请先在「实验页面」上传 HTML", blocking=True)
        elif is_custom and has_page:
            html_src = lab.custom_page.file.read().decode("utf-8", "replace")
            check("页面脚本", "<script" in html_src.lower(),
                  "已包含 <script>（页面可交互）" if "<script" in html_src.lower()
                  else "页面源码没有任何 <script>——纯静态页面无法判分与上报，请检查上传的文件是否完整",
                  blocking=True)
            has_validate = "LabBridge.validate" in html_src
            check("读取满分（LabBridge.validate）", has_validate,
                  "已通过 LabBridge.validate 读取满分" if has_validate
                  else "页面没有调用 LabBridge.validate()——满分应运行时从平台读取而不是写死",
                  blocking=True)
            has_report = "reportGrade" in html_src
            check("成绩上报（LabBridge.reportGrade）", has_report,
                  "已调用 LabBridge.reportGrade 上报成绩" if has_report
                  else "页面没有调用 LabBridge.reportGrade()——学生成绩将无法上报",
                  blocking=True)

        parsed = None
        try:
            parsed = services.parse_grade_payload(request.data, lab)
            check("总分格式与范围", True, f"0 ~ {lab.total_score}，最多 1 位小数")
            check("客户端用时", True, "非负数（只留痕，正式用时由服务端计算）")
            check("报文大小", True, f"{parsed['raw_bytes']} B ≤ {services.MAX_GRADE_BYTES} B")
        except ValidationError as exc:
            detail = str(exc.detail)
            check("总分格式与范围", False, detail)
            check("客户端用时", False, detail)
            check("报文大小", False, detail)

        passed = all(c["ok"] for c in checks if c["blocking"])
        preview = None
        if passed:
            # 「若正式提交会写入什么」：不落库，只描述服务端会补的字段
            preview = {
                "status": "submitted",
                "grading_source": "external",
                "total_score": float(parsed["total_score"]),
                "submitted_at": "服务端 timezone.now() 生成（页面传值一律忽略）",
                "elapsed_seconds": "服务端按 submitted_at - started_at 计算",
                "client_elapsed_seconds_in_grade_raw": parsed["client_elapsed_seconds"],
                "score_breakdown": {"total": float(parsed["total_score"]), "source": "external"},
                "message": "成绩已提交",
            }

        lab.last_debug = {
            "passed": passed,
            "at": timezone.now().isoformat(),
            "payload": {k: request.data.get(k) for k in ("total_score", "elapsed_seconds")},
            "checks": checks,
        }
        lab.save(update_fields=["last_debug", "updated_at"])
        return api_response(
            {"passed": passed, "checks": checks, "preview": preview, "dry_run": True},
            message="调试通过（未入库）" if passed else "调试未通过（未入库）",
        )

    @action(detail=True, methods=["post"], url_path="publish", permission_classes=[IsTeacher])
    def publish(self, request, pk=None):
        lab = self.get_object()
        if lab.status == Lab.Status.PUBLISHED:
            return api_response(message="实验已是发布状态")
        if not lab.schedules.exists():
            raise ValidationError("请先给班级排课再发布实验")
        # 页面来源前置校验：custom 必须先上传页面；template 必须绑定模板（设计 §5）
        if lab.page_source == Lab.PageSource.CUSTOM and not hasattr(lab, "custom_page"):
            raise ValidationError("自定义实验需先上传实验页面再发布")
        if lab.page_source == Lab.PageSource.TEMPLATE and lab.template_id is None:
            raise ValidationError("预置实验需选择实验模板")
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
        # 学籍门控（方案 §5.4）：毕业/休学/退学不能开始新实验（同「开考」语义；
        # 已开始的答卷/实验在 submit 侧另有机会交，不卡在中间态）。
        blocked = student_submit_block_detail(request.user, "开始实验")
        if blocked:
            raise PermissionDenied(blocked)
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
        """重做开始一轮：状态回进行中、attempt+1。
        Stage 6 计分规则为「保留历史最高分」，成绩与明细（分数/步骤/报文/用时）
        不再清空——在更高分出现之前，学生端与教师端看到的始终是最高分那次
        的完整记录。"""
        sub.attempt += 1
        sub.random_seed = seedgen.generate_seed(lab, sub.student_id, sub.attempt)
        sub.status = LabSubmission.Status.IN_PROGRESS
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
        sub = ticket.submission
        lab = sub.lab
        # C32：LabTokenAuthentication 已把 request.user 设成 ticket.student，
        # `ticket.student_id != request.user.id` 恒为假，等于没校验，故删除；
        # 身份靠「持有票据 + 服务端从票据反查 submission/lab」，并校验归属一致防数据被改。
        if ticket.student_id != sub.student_id:
            return api_response(message="票据与作答不匹配", code=403, status=403)
        # 票据有效期内实验被下线也要拦截（门控签名已失效，票据层同步拒绝）
        if lab.status != Lab.Status.PUBLISHED:
            return api_response(message="实验已下线，请联系教师重新上线", code=403, status=403)
        # S3：窗口关闭后持有有效票据也不能再取 context（预置实验同样生效，零回归风险见单测）
        schedule = sub.schedule
        if schedule and not schedule.is_open():
            return api_response(message="实验已截止，无法继续作答", code=403, status=403)
        context = {
            "labId": lab.id,
            "submissionId": sub.id,
            "totalScore": float(lab.total_score),
            "gradeEndpoint": "/api/lab-gate/grade/",
        }
        return api_response(
            {
                "submission_id": sub.id,
                "lab": {"id": lab.id, "title": lab.title,
                        "code": lab.template.code if lab.template_id else f"custom-{lab.id}",
                        "page_source": lab.page_source,
                        "total_score": float(lab.total_score),
                        "standard_minutes": lab.effective_standard_minutes,
                        "time_limit_seconds": lab.time_limit_seconds},
                "random_seed": sub.random_seed,
                "expected": seedgen.derive_expected(
                    sub.random_seed, lab.template.code
                ) if lab.template_id else {},
                "status": sub.status,
                "context": context,  # C45：父页面只映射这四字段给 iframe，绝不含票据
            }
        )

    # ---- 学生：提交（服务端重算评分） ----
    @action(detail=True, methods=["post"], url_path="submit", permission_classes=[IsStudent],
            authentication_classes=[LabTokenAuthentication, JWTAuthentication])
    def submit(self, request, pk=None):
        # 学籍门控（方案 §5.4）：毕业/休学/退学不能提交实验。
        # 与考试不同，实验没有「交卷不拦」的例外——实验没有开考倒计时，
        # 不存在「当天正在做」的卡场问题；进行中的实验随毕业一并关闭。
        blocked = student_submit_block_detail(request.user, "提交实验")
        if blocked:
            raise PermissionDenied(blocked)
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

        def apply_result(sub, now):
            # 计分规则（Stage 6 教师反馈）：首次提交的成绩即实验成绩，后续重做
            # 只保留历史最高分——低分重做不覆盖任何成绩字段（含报文/明细/用时），
            # 仅状态流转为 submitted（由 finalize_submission 统一处理）。
            lab = sub.lab
            # 用本轮上报的数据（而非 sub 上的上一轮旧值）预估新总分
            probe = SimpleNamespace(
                error_count=error_count, elapsed_seconds=elapsed,
                total_steps=total, passed_steps=min(passed, total),
            )
            step_scores = scoring.calc_step_scores(probe, lab.effective_standard_minutes, lab.total_score)
            new_total = scoring.calc_total(step_scores, lab.total_score)
            if sub.total_score is not None and sub.total_score >= new_total:
                return
            # 预置实验沿用客户端上报的用时（S1 只约束新增的 external 端点）
            sub.steps_result = steps
            sub.error_log = error_log
            sub.elapsed_seconds = elapsed
            sub.error_count = error_count
            sub.passed_steps = passed
            sub.total_steps = total
            sub.base_score = step_scores["base"]
            sub.accuracy_score = step_scores["accuracy"]
            sub.efficiency_score = step_scores["efficiency"]
            sub.completion_score = step_scores["completion"]
            sub.total_score = new_total
            sub.score_breakdown = scoring.build_breakdown(sub, step_scores, new_total)

        def validate(sub, locked_ticket, now):
            # S2 锁后复验：窗口可能在锁等待期间关闭
            schedule = sub.schedule
            if schedule and not schedule.is_open():
                raise ValidationError("实验已截止，无法提交")

        # S2：状态、分数、消费票据收敛到 services.finalize_submission 同一事务
        sub = services.finalize_submission(ticket, apply_result=apply_result, validate=validate)
        return api_response(
            LabSubmissionSerializer(sub, context={"request": request}).data,
            message=f"实验提交成功，得分 {sub.total_score}",
        )

    # ---- 学生：提交实验结论（二期报告的前置数据） ----
    @action(detail=True, methods=["post"], url_path="conclusion", permission_classes=[IsStudent],
            authentication_classes=[LabTokenAuthentication, JWTAuthentication])
    def conclusion(self, request, pk=None):
        # 学籍门控：实验结论是提交类行为（二期报告的前置数据），同 submit 处理
        blocked = student_submit_block_detail(request.user, "提交实验结论")
        if blocked:
            raise PermissionDenied(blocked)
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


class GradeReportView(APIView):
    """`POST /api/lab-gate/grade/`：自定义实验页面成绩上报（v3.2 / L2）。

    票据只由平台父页面 `lab-bridge-parent.js` 在 `X-Lab-Token` 头里附带；
    `LabTokenAuthentication` 把 `request.user` 设成 `ticket.student`、
    `request.auth` 设成票据本身。服务端**只从票据反查** submission / lab，
    绝不接受请求体指定实验 id 或学生身份（C23 / C32 / S3）。
    """

    authentication_classes = [LabTokenAuthentication]
    permission_classes = [IsStudent]

    def get_throttles(self):
        # 全局 user 限流之上叠加 lab_grade 独立档（按 user.pk 计数）
        return super().get_throttles() + [LabGradeThrottle()]

    def permission_denied(self, request, message=None, code=None):
        # 无票据时给出可操作的中文提示，而不是 IsStudent 的泛化 403
        if getattr(request, "auth", None) is None:
            raise AuthenticationFailed("实验票据无效")
        super().permission_denied(request, message=message, code=code)

    def post(self, request):
        ticket = request.auth
        # 票据有效性（存在 / 未消费 / 未过期）已由 LabTokenAuthentication 校验；
        # 锁后复验由 services.finalize_submission 再跑一遍，防并发重放。
        parsed = {}

        def validate(sub, locked_ticket, now):
            lab = sub.lab
            if lab.page_source != Lab.PageSource.CUSTOM:
                raise ValidationError("该实验不支持页面成绩上报")
            if lab.status != Lab.Status.PUBLISHED:
                raise ValidationError("实验已下线，请联系教师重新上线")
            schedule = sub.schedule
            if schedule and not schedule.is_open():
                raise ValidationError("实验已截止，无法提交")
            blocked = student_submit_block_detail(request.user, "提交实验成绩")
            if blocked:
                raise PermissionDenied(blocked)
            # 身份靠「持有票据 + 从票据反查」，再校验票据与作答归属一致防数据被改（C32）
            if locked_ticket.student_id != sub.student_id:
                raise ValidationError("票据与作答不匹配")
            parsed.update(services.parse_grade_payload(request.data, lab))

        def apply_result(sub, now):
            score = parsed["total_score"]
            # 计分规则（Stage 6 教师反馈）：只保留历史最高分，低分重做不覆盖成绩
            if sub.total_score is not None and sub.total_score >= score:
                return
            elapsed = services.server_elapsed_seconds(sub, now)
            abnormal = services.is_abnormal(score, sub.lab, elapsed)
            raw = {
                "request": {k: request.data.get(k) for k in ("total_score", "elapsed_seconds")},
                "server": {
                    "submission_id": sub.id,
                    "lab_id": sub.lab_id,
                    "student_id": sub.student_id,
                    "submitted_at": now.isoformat(),
                    "started_at": sub.started_at.isoformat() if sub.started_at else None,
                    "elapsed_seconds": elapsed,
                    "client_elapsed_seconds": parsed["client_elapsed_seconds"],
                    "raw_bytes": parsed["raw_bytes"],
                    "abnormal": abnormal,
                    "abnormal_reason": "满分且用时极短，建议复核" if abnormal else "",
                },
            }
            sub.elapsed_seconds = elapsed
            sub.total_score = score
            sub.score_breakdown = {
                "total": float(score), "source": "external", "elapsed_seconds": elapsed,
            }
            sub.grading_source = "external"
            sub.grade_raw = raw
            sub.grade_raw_digest = hashlib.sha256(
                json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
            ).hexdigest()
            sub.graded_at = now
            sub.abnormal = abnormal
            # 步骤指标保持 0（C17：analytics 按 grading_source 排除）

        sub = services.finalize_submission(ticket, apply_result=apply_result, validate=validate)
        return api_response(
            {
                "submission_id": sub.id,
                "total_score": float(sub.total_score),
                "status": sub.status,
                "submitted_at": sub.submitted_at.isoformat(),
                "graded_at": sub.graded_at.isoformat(),
            },
            message="成绩已提交",
        )


# ---------------------------------------------------------------------------
# 实验页门控（普通 Django 视图，不进 router——资产路径无尾斜杠，同课程资源门控模式）
# ---------------------------------------------------------------------------

# S6 严格 CSP：复用 apps/courses/views.py 门控串 + 补齐 form-action/base-uri/object-src。
# 用于 page_source=custom 的父页面与 frame 两个响应。
_GATE_CSP = (
    "default-src 'self' data: blob:; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self' blob:; "
    "frame-ancestors 'self'; "
    "form-action 'none'; "
    "base-uri 'self'; "
    "object-src 'none'"
)


def _gate_block(status, title, message):
    response = render_block_page(status, title, message)
    response["Content-Security-Policy"] = _GATE_CSP
    response["Referrer-Policy"] = "no-referrer"
    return response


def lab_gate_page(request, token):
    """实验入口页（三分流，v3.2/L2）：

    - preview=1（verify_preview，跳过发布状态）→ custom 渲染平台父页面（预览模式）；
    - template → 原逻辑：读预置静态页 + 注入 <base>（不验票据，C29）；
    - custom → 校验本次作答票据（有效/未消费/发布中/排课窗口开）后返回平台父页面
      （持票据 + sandbox iframe）；教师 HTML 由 lab_gate_frame 返回。
    """
    lab = Lab.objects.select_related("template").filter(access_token=token).first()
    sig, exp = request.GET.get("sig", ""), request.GET.get("exp", "")
    preview = request.GET.get("preview") == "1"
    if preview:
        if lab is None or not gate.verify_preview(lab, sig, exp):
            return _gate_block(403, "预览链接无效或已失效", "预览链接已过期，请重新获取。")
        if lab.page_source != Lab.PageSource.CUSTOM:
            return _gate_block(400, "该实验不支持页面预览", "预置实验页面由平台统一部署，无需预览。")
        html = gate.render_parent(lab, sig, exp, attempt_token=None, preview=True)
        if html is None:
            return _gate_block(404, "实验页面不存在", "教师尚未上传实验页面。")
        response = HttpResponse(html, content_type="text/html; charset=utf-8")
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "SAMEORIGIN"
        response["Content-Security-Policy"] = _GATE_CSP
        response["Referrer-Policy"] = "no-referrer"
        return response

    if lab is None or not gate.verify_lab(lab, sig, exp):
        return _gate_block(403, "实验链接无效或已失效", "实验已下线或链接已过期，请返回课程实验页重新进入。")
    if lab.page_source == Lab.PageSource.CUSTOM:
        # 父页面是票据唯一落点：无效票据直接 403，不进父页面
        try:
            ticket = bridge.validate_token(request.GET.get("token", ""))
        except ValueError as exc:
            return _gate_block(403, "实验票据无效", str(exc))
        if ticket.submission.lab_id != lab.id:
            return _gate_block(403, "实验票据无效", "票据与实验不匹配。")
        if lab.status != Lab.Status.PUBLISHED:
            return _gate_block(403, "实验已下线", "实验已下线，请联系教师重新上线。")
        schedule = ticket.submission.schedule
        if schedule and not schedule.is_open():
            return _gate_block(403, "实验不在开放时间", "当前不在实验开放时间内，请在开放时间重试。")
        html = gate.render_parent(lab, sig, exp, attempt_token=ticket.token, preview=False)
        if html is None:
            return _gate_block(404, "实验页面不存在", "教师尚未上传实验页面。")
        response = HttpResponse(html, content_type="text/html; charset=utf-8")
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "SAMEORIGIN"
        response["Content-Security-Policy"] = _GATE_CSP
        response["Referrer-Policy"] = "no-referrer"
        return response

    # template：原逻辑（读预置 HTML + 注入 <base>；页面本体自带 lab-bridge.js）
    html = gate.read_page(lab)
    if html is None:
        return _gate_block(404, "实验页面不存在", "平台尚未部署该实验页面，请联系管理员。")
    response = HttpResponse(
        gate.inject_bridge(html, "template", gate.asset_base(lab, sig, exp)),
        content_type="text/html; charset=utf-8",
    )
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    # 与课程资源入口页一致：允许同源 iframe 嵌入（clickjacking 中间件不覆盖已设置的响应头）
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response


def lab_gate_frame(request, token, sig, exp):
    """custom iframe 内容页：教师 HTML + <base> + 无票据 shim（C45/C25/C40）。

    只验签名与（预览或发布）状态，绝不验票据——iframe URL 与内容里都没有票据。
    预览模式（preview=1 + 预览签名）允许草稿预览。
    """
    lab = Lab.objects.filter(access_token=token).first()
    preview = request.GET.get("preview") == "1"
    verified = (
        gate.verify_preview(lab, sig, exp)
        if preview
        else gate.verify_lab(lab, sig, exp)
    ) if lab else False
    if not verified:
        return _gate_block(403, "实验链接无效或已失效", "实验已下线或链接已过期，请返回课程实验页重新进入。")
    if lab.page_source != Lab.PageSource.CUSTOM:
        return _gate_block(404, "实验页面不存在", "该实验没有自定义页面。")
    html = gate.render_frame(lab, sig, exp, preview=preview)
    if html is None:
        return _gate_block(404, "实验页面不存在", "教师尚未上传实验页面。")
    response = HttpResponse(html, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    # C40 双保险：CSP sandbox 与 iframe 属性取交集，绝不允许 allow-same-origin
    response["Content-Security-Policy"] = (
        "sandbox allow-scripts allow-forms allow-modals; " + _GATE_CSP
    )
    # C44：显式 SAMEORIGIN，避免中间件默认 DENY 依赖「CSP frame-ancestors 覆盖 XFO」的浏览器行为
    response["X-Frame-Options"] = "SAMEORIGIN"
    response["Referrer-Policy"] = "no-referrer"
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
