import os
import time

from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.views import APIView

from apps.classroom.models import ClassRoom, ClassStudent
from apps.ai.models import AICapabilityConfig, AITestRecord
from apps.ai.providers.factory import build_provider, get_runtime_config, mask_api_key
from apps.common.permissions import IsPlatformAdmin
from apps.common.response import api_response
from apps.courses.models import Catalog, Course
from apps.exams.models import Exam
from apps.homework.models import Homework

from .serializers import (
    AdminClassSerializer,
    AdminCourseSerializer,
    AdminUserSerializer,
    AdminUserWriteSerializer,
    AICapabilityConfigSerializer,
    CourseStatusSerializer,
    PasswordResetSerializer,
)
from .user_import import (
    MAX_FILE_SIZE,
    MAX_IMPORT_ROWS,
    annotate_rows,
    build_template,
    initial_password_for,
    parse_excel,
)

User = get_user_model()


def _page_params(request):
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(100, max(1, int(request.query_params.get("page_size", 10))))
    except (TypeError, ValueError):
        page, page_size = 1, 10
    return page, page_size


def _paginated_response(queryset, request, serializer_class):
    page, page_size = _page_params(request)
    total = queryset.count()
    start = (page - 1) * page_size
    items = queryset[start:start + page_size]
    return api_response({
        "items": serializer_class(items, many=True).data,
        "total": total,
        "page": page,
        "page_size": page_size,
    })


class AdminOverviewView(APIView):
    permission_classes = [IsPlatformAdmin]
    serializer_class = AdminCourseSerializer

    def get(self, request):
        admin_filter = Q(role=User.Role.ADMIN) | Q(is_superuser=True)
        data = {
            "meta": {
                "source": "database",
                "refreshed_at": timezone.now(),
            },
            "users": {
                "total": User.objects.count(),
                "active": User.objects.filter(is_active=True).count(),
                "teachers": User.objects.filter(role=User.Role.TEACHER).count(),
                "students": User.objects.filter(role=User.Role.STUDENT, is_superuser=False).count(),
                "admins": User.objects.filter(admin_filter).distinct().count(),
            },
            "teaching": {
                "courses": Course.objects.count(),
                "active_courses": Course.objects.filter(status=Course.Status.ACTIVE).count(),
                "classes": ClassRoom.objects.count(),
                "open_classes": ClassRoom.objects.filter(status=ClassRoom.Status.OPEN).count(),
                "enrollments": ClassStudent.objects.exclude(
                    learn_status=ClassStudent.LearnStatus.REMOVED
                ).count(),
                "chapters": Catalog.objects.count(),
                "homeworks": Homework.objects.count(),
                "exams": Exam.objects.count(),
            },
            "recent_users": AdminUserSerializer(
                User.objects.order_by("-date_joined")[:6], many=True
            ).data,
            "recent_courses": AdminCourseSerializer(
                Course.objects.select_related("teacher").annotate(
                    class_count=Count("classes", distinct=True),
                    student_count=Count("classes__students", distinct=True),
                ).order_by("-created_at")[:6],
                many=True,
            ).data,
        }
        return api_response(data)


class AdminUserListCreateView(APIView):
    permission_classes = [IsPlatformAdmin]
    serializer_class = AdminUserWriteSerializer

    def get(self, request):
        queryset = User.objects.all().order_by("-date_joined")
        keyword = request.query_params.get("search", "").strip()
        role = request.query_params.get("role", "").strip()
        state = request.query_params.get("status", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(username__icontains=keyword)
                | Q(real_name__icontains=keyword)
                | Q(phone__icontains=keyword)
            )
        if role:
            if role == User.Role.ADMIN:
                queryset = queryset.filter(Q(role=role) | Q(is_superuser=True))
            else:
                queryset = queryset.filter(role=role, is_superuser=False)
        if state in {"active", "disabled"}:
            queryset = queryset.filter(is_active=(state == "active"))
        return _paginated_response(queryset, request, AdminUserSerializer)

    def post(self, request):
        serializer = AdminUserWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return api_response(
            AdminUserSerializer(user).data,
            message="账号创建成功",
            status=status.HTTP_201_CREATED,
        )


class AdminUserDetailView(APIView):
    permission_classes = [IsPlatformAdmin]
    serializer_class = AdminUserWriteSerializer

    def patch(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        if user.is_superuser and not request.user.is_superuser:
            return api_response(message="只有超级管理员可以修改超级管理员账号", code=403, status=403)
        if user.pk == request.user.pk:
            if request.data.get("is_active") is False:
                return api_response(message="不能停用当前登录账号", code=400, status=400)
            if request.data.get("role") and request.data.get("role") != User.Role.ADMIN:
                return api_response(message="不能移除当前账号的管理员角色", code=400, status=400)
        serializer = AdminUserWriteSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return api_response(AdminUserSerializer(user).data, message="用户资料已更新")


class AdminPasswordResetView(APIView):
    permission_classes = [IsPlatformAdmin]
    serializer_class = PasswordResetSerializer

    def post(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        if user.is_superuser and not request.user.is_superuser:
            return api_response(message="只有超级管理员可以重置超级管理员密码", code=403, status=403)
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user.set_password(serializer.validated_data["password"])
        # 管理员代设密码后，提示用户下次登录自行修改（前端弹窗可跳过）
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])
        return api_response(message="密码已重置")


class AdminUserImportTemplateView(APIView):
    """下载学生批量导入模板（xlsx）。"""

    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        response = HttpResponse(
            build_template(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = "attachment; filename=student_import_template.xlsx"
        return response


class AdminUserImportPreviewView(APIView):
    """上传 Excel 真实解析，返回逐行校验结果供前端预览/修改。"""

    permission_classes = [IsPlatformAdmin]

    def post(self, request):
        file = request.FILES.get("file")
        if not file:
            return api_response(message="请上传 Excel 文件", code=400, status=400)
        if not str(file.name).lower().endswith(".xlsx"):
            return api_response(message="仅支持 .xlsx 文件，请使用系统模板", code=400, status=400)
        if file.size > MAX_FILE_SIZE:
            return api_response(message="文件大小不能超过 5MB", code=400, status=400)
        try:
            rows = parse_excel(file)
        except ValueError as exc:
            return api_response(message=str(exc), code=400, status=400)
        annotated = annotate_rows(rows)
        return api_response({
            "rows": annotated,
            "total": len(annotated),
            "valid": sum(1 for row in annotated if row["status"] == "ok"),
        })


class AdminUserImportConfirmView(APIView):
    """确认导入：服务端对最终行重新全量校验，全部合法才在事务中批量创建。"""

    permission_classes = [IsPlatformAdmin]

    def post(self, request):
        rows = request.data.get("rows")
        if not isinstance(rows, list) or not rows:
            return api_response(message="没有可导入的数据", code=400, status=400)
        if len(rows) > MAX_IMPORT_ROWS:
            return api_response(message=f"单次最多导入 {MAX_IMPORT_ROWS} 行", code=400, status=400)
        cleaned = [row for row in rows if isinstance(row, dict)]
        annotated = annotate_rows(cleaned)
        errors = [row for row in annotated if row["status"] != "ok"]
        if errors:
            return api_response(
                {"rows": annotated},
                message="存在无效或冲突的数据行，请修正后重新提交",
                code=400,
                status=400,
            )
        with transaction.atomic():
            for row in annotated:
                user = User(
                    username=row["username"],
                    real_name=row["real_name"],
                    role=User.Role.STUDENT,
                    must_change_password=True,
                )
                user.set_password(initial_password_for(row["username"]))
                user.save()
        return api_response(
            {"created": len(annotated)},
            message=f"成功导入 {len(annotated)} 个学生账号",
            status=status.HTTP_201_CREATED,
        )


class AdminCourseListView(APIView):
    permission_classes = [IsPlatformAdmin]
    serializer_class = AdminCourseSerializer

    def get(self, request):
        queryset = Course.objects.select_related("teacher").annotate(
            class_count=Count("classes", distinct=True),
            student_count=Count("classes__students", distinct=True),
        ).order_by("-created_at")
        keyword = request.query_params.get("search", "").strip()
        state = request.query_params.get("status", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(name__icontains=keyword)
                | Q(teacher__username__icontains=keyword)
                | Q(teacher__real_name__icontains=keyword)
            )
        if state:
            queryset = queryset.filter(status=state)
        return _paginated_response(queryset, request, AdminCourseSerializer)


class AdminCourseStatusView(APIView):
    permission_classes = [IsPlatformAdmin]
    serializer_class = CourseStatusSerializer

    def patch(self, request, course_id):
        course = get_object_or_404(Course, pk=course_id)
        serializer = CourseStatusSerializer(course, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        annotated = Course.objects.select_related("teacher").annotate(
            class_count=Count("classes", distinct=True),
            student_count=Count("classes__students", distinct=True),
        ).get(pk=course.pk)
        return api_response(AdminCourseSerializer(annotated).data, message="课程状态已更新")


class AdminClassListView(APIView):
    permission_classes = [IsPlatformAdmin]
    serializer_class = AdminClassSerializer

    def get(self, request):
        queryset = ClassRoom.objects.select_related("teacher").annotate(
            course_count=Count("courses", distinct=True),
            student_count=Count("students", distinct=True),
        ).order_by("-created_at")
        keyword = request.query_params.get("search", "").strip()
        state = request.query_params.get("status", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(name__icontains=keyword)
                | Q(teacher__username__icontains=keyword)
                | Q(teacher__real_name__icontains=keyword)
            )
        if state:
            queryset = queryset.filter(status=state)
        return _paginated_response(queryset, request, AdminClassSerializer)


def _ai_capability_payload() -> list[dict]:
    """各能力（对话/向量/重排序/语音）的当前生效配置：provider/模型/Key 掩码/来源/实际运行时/最近测试。"""
    rows = {row.capability: row for row in AICapabilityConfig.objects.all()}
    tests = {record.capability: record for record in AITestRecord.objects.all()}
    items = []
    for capability, label in AICapabilityConfig.Capability.choices:
        row = rows.get(capability)
        provider, config, source = get_runtime_config(capability)
        runtime = build_provider(provider, config, capability)
        key = config.get("api_key", "")
        test = tests.get(capability)
        items.append({
            "capability": capability,
            "capability_display": label,
            "provider": provider,
            "provider_display": dict(AICapabilityConfig.Provider.choices).get(provider, provider),
            "enabled": bool(row.enabled) if row else (provider != "mock" and (provider == "local" or bool(key))),
            "base_url": config.get("base_url", ""),
            "model_name": config.get("model", ""),
            "timeout": config.get("timeout"),
            "voice": config.get("voice", ""),
            "api_key_configured": bool(key),
            "api_key_masked": mask_api_key(key),
            "source": source,
            "runtime_provider": runtime.name,
            "runtime_is_mock": runtime.name == "mock",
            "last_test_status": test.status if test else "untested",
            "last_test_message": test.message if test else "",
            "last_tested_at": test.tested_at if test else None,
            "updated_at": row.updated_at if row else None,
            "updated_by_name": row.updated_by.username if row and row.updated_by else None,
        })
    return items


class AdminAIConfigurationView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        return api_response({"items": _ai_capability_payload()})

    def put(self, request):
        payload = request.data.get("capabilities")
        if not isinstance(payload, list) or not payload:
            return api_response(message="请求格式不正确：capabilities 不能为空", code=400, status=400)
        valid = dict(AICapabilityConfig.Capability.choices)
        with transaction.atomic():
            for item in payload:
                capability = item.get("capability")
                if capability not in valid:
                    return api_response(message=f"未知能力：{capability}", code=400, status=400)
                instance = AICapabilityConfig.objects.filter(capability=capability).first()
                if instance is None:
                    instance = AICapabilityConfig(capability=capability)
                # 保存前快照生效配置：服务商/接口/模型三项均未变时保留历史测试结论
                before_provider, before_config, _ = get_runtime_config(capability)
                before = (before_provider, before_config.get("base_url", ""), before_config.get("model", ""))
                serializer = AICapabilityConfigSerializer(
                    instance, data=item, partial=True, context={"request": request}
                )
                serializer.is_valid(raise_exception=True)
                serializer.save()
                after_provider, after_config, _ = get_runtime_config(capability)
                after = (after_provider, after_config.get("base_url", ""), after_config.get("model", ""))
                if before != after:
                    # 配置变更后历史测试结果作废（避免展示过期结论）
                    AITestRecord.objects.filter(capability=capability).delete()
        return api_response({"items": _ai_capability_payload()}, message="大模型配置已保存并生效")


class AdminAIConnectionTestView(APIView):
    permission_classes = [IsPlatformAdmin]
    def post(self, request):
        capability = request.data.get("capability", "chat")
        if capability not in dict(AICapabilityConfig.Capability.choices):
            return api_response(message=f"未知能力：{capability}", code=400, status=400)

        # 能力-服务商白名单（与保存接口一致）：表单值同样可能越界，直接拒验
        form_provider_precheck = str(request.data.get("provider") or "").strip()
        if form_provider_precheck:
            allowed = AICapabilityConfig.CAPABILITY_PROVIDERS.get(capability)
            if allowed and form_provider_precheck not in allowed:
                capability_label = dict(AICapabilityConfig.Capability.choices).get(capability, capability)
                allowed_labels = "、".join(
                    dict(AICapabilityConfig.Provider.choices).get(p, p) for p in allowed
                )
                return api_response(
                    message=f"该服务商暂不支持{capability_label}，请选择：{allowed_labels}",
                    code=400,
                    status=400,
                )

        # 优先测试前端传入的表单值——用户在卡片上刚改的模型/接口应当可测，
        # 不必先保存；未传或字段为空时回退到当前生效配置（管理端行 > 环境变量）。
        # API Key 表单恒为空（密码框不留值），留空即沿用已生效配置的 Key。
        form_provider = str(request.data.get("provider") or "").strip()
        form_base_url = str(request.data.get("base_url") or "").strip()
        form_model = str(request.data.get("model_name") or "").strip()
        form_api_key = str(request.data.get("api_key") or "").strip()
        form_timeout = request.data.get("timeout")
        form_voice = str(request.data.get("voice") or "").strip()
        from_form = bool(form_provider or form_base_url or form_model or form_api_key or form_timeout or form_voice)

        provider, config, source = get_runtime_config(capability)
        if from_form:
            provider = form_provider or provider
            config = {
                "api_key": form_api_key or config.get("api_key", ""),
                "base_url": form_base_url or config.get("base_url", ""),
                "model": form_model or config.get("model", ""),
                # 表单填了超时/发音人就按表单测；空值沿用生效配置（再由 provider 回退默认）
                "timeout": form_timeout if form_timeout not in (None, "") else config.get("timeout"),
                "voice": form_voice or config.get("voice", ""),
            }
            source = "form"

        now = timezone.now()
        provider_display = dict(AICapabilityConfig.Provider.choices).get(provider, provider)
        detail = {
            "provider": provider,
            "provider_display": provider_display,
            "model": config.get("model") or "",
            "base_url": config.get("base_url", ""),
            "source": source,
            "from_form": from_form,
            "request": "",
            "response": "",
            "elapsed_ms": 0,
        }
        started = time.monotonic()
        try:
            if provider == "mock" or (provider != "local" and not config.get("api_key")):
                message = "模拟模式可用；当前不会调用真实大模型"
                detail["request"] = "—"
                detail["response"] = "模拟模式不发起真实请求"
            else:
                if provider != "local" and not config.get("base_url"):
                    raise RuntimeError("请先填写接口地址")
                if provider == "local":
                    # 系统内置模型：模型名优先级 = 表单显式填写 > 运行时已是 local 的
                    # 生效值 > 内置默认（BGE-M3 / Qwen3-Reranker）。不能无差别沿用运行时
                    # 模型——运行时可能是线上服务商的模型名（如 text-embedding-v3）。
                    # 权重缺失会惰性下载，连接测试可能因下载+加载耗时较长（数分钟）
                    from apps.ai.local_models import default_model

                    runtime_provider, runtime_config, _ = get_runtime_config(capability)
                    carried = runtime_config.get("model", "") if runtime_provider == "local" else ""
                    config["model"] = form_model or carried or (
                        default_model(capability) if capability in ("embed", "rerank") else ""
                    )
                    detail["model"] = config["model"]  # detail 在 try 前已建好，同步修正展示值
                elif not config.get("model"):
                    raise RuntimeError("请先填写模型名称")
                built = build_provider(provider, config, capability)
                if capability == "chat":
                    prompt = "请只回复：连接成功"
                    reply = built.chat(
                        [{"role": "user", "content": prompt}],
                        temperature=0, timeout=20, retries=1, fallback_to_mock=False, max_tokens=16,
                    )
                    if not str(reply or "").strip():
                        raise RuntimeError("模型返回内容为空")
                    detail["request"] = prompt
                    detail["response"] = str(reply).strip()[:500]
                elif capability == "embed":
                    vectors = built.embed(["连接测试"], allow_fallback=False)
                    if not vectors or not vectors[0]:
                        raise RuntimeError("向量接口返回为空")
                    detail["request"] = "连接测试"
                    detail["response"] = f"返回 {len(vectors)} 条向量，维度 {len(vectors[0])}"
                elif capability == "rerank":
                    docs = [
                        "Java 程序设计课程总学时 64，其中讲授 48 学时、实验 16 学时。",
                        "考核方式为平时成绩 30% + 实验 20% + 期末考试 50%。",
                        "路由器根据路由表转发 IP 分组，ICMP 用于网络层差错报告。",
                    ]
                    ranked = built.rerank("这门课的考核方式是什么？", docs, top_n=3)
                    if not ranked:
                        raise RuntimeError("重排序接口返回为空")
                    detail["request"] = "query：这门课的考核方式是什么？；documents：3 条测试文档"
                    detail["response"] = "；".join(
                        f"#{item['index']} 相关性 {float(item['score']):.4f}" for item in ranked[:3]
                    )
                else:
                    url = built.tts("连接测试")
                    if not url:
                        raise RuntimeError("语音接口未返回音频地址")
                    voice_used = getattr(built, "voice", "") or getattr(settings, "AI_TTS_VOICE", "Cherry")
                    detail["request"] = f"文本：连接测试（发音人 {voice_used}）"
                    size = ""
                    try:
                        rel = url.split(settings.MEDIA_URL, 1)[-1] if settings.MEDIA_URL in url else ""
                        if rel:
                            size = f"，文件 {os.path.getsize(os.path.join(settings.MEDIA_ROOT, rel)) / 1024:.1f} KB"
                    except OSError:
                        pass
                    detail["response"] = f"音频已生成{size}：{url}"
                model_label = config.get("model") or "未设置模型"
                message = f"{provider_display} · {model_label} 连接成功"
            test_status = AICapabilityConfig.TestStatus.SUCCESS
        except Exception as exc:
            # 失败信息必须带上「实际测试的服务商·模型」——否则使用者无法判断
            # 测的到底是表单新值还是旧生效值（如 Model not exist 是模型名问题）
            model_label = config.get("model") or "未设置模型"
            message = f"连接失败：{provider_display} · {model_label} → {str(exc)[:240]}"
            test_status = AICapabilityConfig.TestStatus.FAILED
        detail["elapsed_ms"] = int((time.monotonic() - started) * 1000)

        # 测试结果写入独立记录表，不改变 runtime 生效配置（环境变量模式下同样可测可记录）
        record, _ = AITestRecord.objects.update_or_create(
            capability=capability,
            defaults={
                "provider": provider,
                "status": test_status,
                "message": message,
                "tested_at": now,
                "tested_by": request.user,
            },
        )
        # 测试动作本身已成功执行（连没连上都是有效结果），统一 200 走 data，
        # 由前端弹窗按 last_test_status 呈现，避免拦截器 toast 与弹窗重复提示
        return api_response(
            {
                "capability": capability,
                "last_test_status": record.status,
                "last_test_message": record.message,
                "last_tested_at": record.tested_at,
                "detail": detail,
            },
            message=message,
        )


class AdminRebuildVectorsView(APIView):
    """平台级知识库向量重建（换向量模型后必须执行）。

    覆盖教辅资料与课件 PPT（课件是向量库的主要内容）。
    范围：course / material / ppt / scope=all（全站，需显式声明防误操作）。
    出错处理同教师端：事前校验失败返回 400 不动数据；单项失败可续跑。
    """

    permission_classes = [IsPlatformAdmin]

    def post(self, request):
        from apps.courses.models import PPTResource
        from apps.knowledge.models import Material
        from apps.knowledge.services import rebuild_vectors

        scope = str(request.data.get("scope") or "").strip()
        course_id = request.data.get("course")
        material_id = request.data.get("material")
        ppt_id = request.data.get("ppt")
        qs = Material.objects.all()
        ppt_qs = PPTResource.objects.filter(is_active=True)
        materials = qs.none()
        ppts = ppt_qs.none()
        if material_id:
            materials = qs.filter(pk=material_id)
            if not materials.exists():
                return api_response(message="资料不存在", code=400, status=400)
        elif ppt_id:
            ppts = ppt_qs.filter(pk=ppt_id)
            if not ppts.exists():
                return api_response(message="课件不存在", code=400, status=400)
        elif course_id:
            materials = qs.filter(course_id=course_id)
            ppts = ppt_qs.filter(course_id=course_id)
        elif scope == "all":
            materials = qs
            ppts = ppt_qs
        else:
            return api_response(
                message="请指定 course / material / ppt，或显式传 scope=all 重建全站向量",
                code=400,
                status=400,
            )

        report = rebuild_vectors(materials, ppts)
        if report.get("error"):
            return api_response(report, message=report["error"], code=400, status=400)
        message = (
            f"向量重建完成：资料 {report['materials']['success']}/{report['materials']['total']} 份，"
            f"课件 {report['ppts']['success']}/{report['ppts']['total']} 部，"
            f"共 {report['chunks']} 个片段"
        )
        if report["failed"]:
            message += f"，失败 {len(report['failed'])} 项（详见返回清单，可修复后重试）"
        return api_response(report, message=message)
