import csv
import os
import time
from datetime import date, datetime, time as dtime, timedelta

from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.views import APIView
from .throttles import AdminThrottleMixin

from apps.classroom.models import ClassRoom, ClassStudent
from apps.ai.calllog import ai_scene
from apps.ai.models import (
    AICallLog,
    AICapabilityChangeLog,
    AICapabilityConfig,
    AITestRecord,
)
from apps.ai.providers.factory import (
    build_provider,
    chat_supports_vision,
    get_runtime_config,
    mask_api_key,
    model_name_suggests_vision,
)
from apps.common.permissions import IsPlatformAdmin
from apps.common.qa_stats import (
    BaseQAQualityStatsView,
    CallLogWindowError,
    call_log_qs as _call_log_qs,
    call_log_window as _call_log_window,
)
from apps.common.response import api_response
from apps.courses.models import Catalog, Course
from apps.exams.models import Exam
from apps.homework.models import Homework
from apps.knowledge.models import QARecord

from .audit import log_admin_action
from .models import AdminActionLog
from .serializers import (
    AdminClassSerializer,
    AdminCourseSerializer,
    AdminUserSerializer,
    AdminUserWriteSerializer,
    AICallLogSerializer,
    AICapabilityChangeLogSerializer,
    AICapabilityConfigSerializer,
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


class AdminOverviewView(AdminThrottleMixin, APIView):
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
                "open_classes": ClassRoom.objects.filter(status=ClassRoom.Status.ACTIVE).count(),
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


class AdminUserListCreateView(AdminThrottleMixin, APIView):
    method_scopes = {"GET": "admin_read", "POST": "admin_write"}
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
        log_admin_action(
            request.user,
            AdminActionLog.Action.USER_CREATE,
            target_type="user",
            target_id=user.id,
            target_label=f"{user.real_name or user.username}({user.username})",
            new_value={"username": user.username, "role": user.role},
        )
        return api_response(
            AdminUserSerializer(user).data,
            message="账号创建成功",
            status=status.HTTP_201_CREATED,
        )


class AdminUserDetailView(AdminThrottleMixin, APIView):
    method_scopes = {"PATCH": "admin_write"}
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
        # 变更前快照（仅审计关心的字段），用于 old→new 展示
        before = {
            field: getattr(user, field)
            for field in ("username", "real_name", "role", "is_active")
        }
        serializer.save()
        after = {
            field: getattr(user, field)
            for field in ("username", "real_name", "role", "is_active")
        }
        changed = {k: {"old": before[k], "new": after[k]} for k in after if before[k] != after[k]}
        if changed:
            log_admin_action(
                request.user,
                AdminActionLog.Action.USER_UPDATE,
                target_type="user",
                target_id=user.id,
                target_label=f"{user.real_name or user.username}({user.username})",
                new_value=changed,
            )
        return api_response(AdminUserSerializer(user).data, message="用户资料已更新")


class AdminPlatformSettingsView(AdminThrottleMixin, APIView):
    """平台系统设置（当前仅注册通道开关 register_open）。

    GET 返回全部设置项；PATCH 逐项更新并落审计（变更前后值）。
    公开侧读取走 /api/auth/config/（AllowAny），不暴露本端点。
    """

    method_scopes = {"PATCH": "admin_write"}
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        from .models import register_open

        return api_response({"register_open": register_open()})

    def patch(self, request):
        from .models import REGISTER_OPEN_KEY, register_open, set_setting

        if "register_open" not in request.data:
            return api_response(message="没有可更新的设置项", code=400, status=400)
        raw = request.data.get("register_open")
        if not isinstance(raw, bool):
            return api_response(message="register_open 必须是布尔值", code=400, status=400)
        old = register_open()
        set_setting(REGISTER_OPEN_KEY, raw, "注册通道开关：关闭后注册接口拒绝、登录页隐藏注册入口")
        log_admin_action(
            request.user,
            AdminActionLog.Action.SETTINGS_UPDATE,
            target_type="platform_setting",
            target_label="注册通道开关(register_open)",
            old_value={"register_open": old},
            new_value={"register_open": raw},
        )
        return api_response(
            {"register_open": raw},
            message="注册通道已开放" if raw else "注册通道已关闭",
        )


class AdminPasswordResetView(AdminThrottleMixin, APIView):
    method_scopes = {"POST": "admin_write"}
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
        log_admin_action(
            request.user,
            AdminActionLog.Action.USER_RESET_PWD,
            target_type="user",
            target_id=user.id,
            target_label=f"{user.real_name or user.username}({user.username})",
        )
        return api_response(message="密码已重置")


class AdminUserImportTemplateView(AdminThrottleMixin, APIView):
    """下载学生批量导入模板（xlsx）。"""

    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        response = HttpResponse(
            build_template(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = "attachment; filename=student_import_template.xlsx"
        return response


class AdminUserImportPreviewView(AdminThrottleMixin, APIView):
    """上传 Excel 真实解析，返回逐行校验结果供前端预览/修改。"""
    method_scopes = {"POST": "admin_heavy"}

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


class AdminUserImportConfirmView(AdminThrottleMixin, APIView):
    """确认导入：服务端对最终行重新全量校验，全部合法才在事务中批量创建。"""
    method_scopes = {"POST": "admin_heavy"}

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
        log_admin_action(
            request.user,
            AdminActionLog.Action.USER_IMPORT,
            target_type="user",
            target_label=f"批量导入 {len(annotated)} 个学生账号",
            new_value={"created": len(annotated)},
        )
        return api_response(
            {"created": len(annotated)},
            message=f"成功导入 {len(annotated)} 个学生账号",
            status=status.HTTP_201_CREATED,
        )


def _ai_capability_payload() -> list[dict]:
    """各能力（对话/向量/重排序/语音）的当前生效配置：provider/模型/Key 掩码/来源/实际运行时/最近测试。"""
    rows = {row.capability: row for row in AICapabilityConfig.objects.all()}
    tests = {record.capability: record for record in AITestRecord.objects.all()}
    # 对话能力的图片（多模态）开关：仅 chat 行有意义，其余能力恒 False
    chat_vision = chat_supports_vision()
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
            # 图片上传入口开关（仅 chat 有效）：supports_vision 为生效值，
            # model_suggests_vision 为模型名推断，供「疑似视觉模型但开关关闭」提示
            "supports_vision": (
                chat_vision if capability == AICapabilityConfig.Capability.CHAT else False
            ),
            "model_suggests_vision": model_name_suggests_vision(config.get("model", "")),
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


class AdminAIConfigurationView(AdminThrottleMixin, APIView):
    method_scopes = {"GET": "admin_read", "PUT": "admin_write"}
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        return api_response({"items": _ai_capability_payload()})

    def put(self, request):
        payload = request.data.get("capabilities")
        if not isinstance(payload, list) or not payload:
            return api_response(message="请求格式不正确：capabilities 不能为空", code=400, status=400)
        valid = dict(AICapabilityConfig.Capability.choices)
        saved_capabilities = []
        diff_groups = []
        with transaction.atomic():
            for item in payload:
                capability = item.get("capability")
                if capability not in valid:
                    return api_response(message=f"未知能力：{capability}", code=400, status=400)
                instance = AICapabilityConfig.objects.filter(capability=capability).first()
                if instance is None:
                    instance = AICapabilityConfig(capability=capability)
                # 保存前快照受跟踪字段：保存后对比出字段级 diff，随审计一并落库。
                # 单一审计轨（AdminActionLog.ai_config_save）；AICapabilityChangeLog 已停写。
                before = instance.tracked_snapshot()
                # 保存前快照生效配置：服务商/接口/模型三项均未变时保留历史测试结论
                before_provider, before_config, _ = get_runtime_config(capability)
                before_effective = (before_provider, before_config.get("base_url", ""), before_config.get("model", ""))
                serializer = AICapabilityConfigSerializer(
                    instance, data=item, partial=True, context={"request": request}
                )
                serializer.is_valid(raise_exception=True)
                serializer.save()
                saved_capabilities.append(capability)
                changes = AICapabilityConfig.diff_snapshots(before, instance.tracked_snapshot())
                if changes:
                    diff_groups.append({
                        "capability": capability,
                        "capability_display": valid[capability],
                        "changes": changes,
                    })
                after_provider, after_config, _ = get_runtime_config(capability)
                after_effective = (after_provider, after_config.get("base_url", ""), after_config.get("model", ""))
                if before_effective != after_effective:
                    # 配置变更后历史测试结果作废（避免展示过期结论）
                    AITestRecord.objects.filter(capability=capability).delete()
        # 审计：单一审计轨——字段级 diff 按能力分组进 new_value.changes，
        # 回答「为什么某天起讲稿/问答行为变了」（AICapabilityChangeLog 已停写，仅存历史）
        log_admin_action(
            request.user,
            AdminActionLog.Action.AI_CONFIG_SAVE,
            target_type="ai_config",
            target_label="、".join(
                dict(AICapabilityConfig.Capability.choices).get(c, c) for c in saved_capabilities
            ),
            new_value={"capabilities": saved_capabilities, "changes": diff_groups},
        )
        return api_response({"items": _ai_capability_payload()}, message="大模型配置已保存并生效")


class AdminAIConnectionTestView(AdminThrottleMixin, APIView):
    method_scopes = {"POST": "admin_heavy"}
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
                    with ai_scene(AICallLog.Scene.CONNECTION_TEST):
                        reply = built.chat(
                            [{"role": "user", "content": prompt}],
                            temperature=0, timeout=20, retries=1, fallback_to_mock=False, max_tokens=16,
                        )
                    if not str(reply or "").strip():
                        raise RuntimeError("模型返回内容为空")
                    detail["request"] = prompt
                    detail["response"] = str(reply).strip()[:500]
                elif capability == "embed":
                    with ai_scene(AICallLog.Scene.CONNECTION_TEST):
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
                    with ai_scene(AICallLog.Scene.CONNECTION_TEST):
                        ranked = built.rerank("这门课的考核方式是什么？", docs, top_n=3)
                    if not ranked:
                        raise RuntimeError("重排序接口返回为空")
                    detail["request"] = "query：这门课的考核方式是什么？；documents：3 条测试文档"
                    detail["response"] = "；".join(
                        f"#{item['index']} 相关性 {float(item['score']):.4f}" for item in ranked[:3]
                    )
                else:
                    with ai_scene(AICallLog.Scene.CONNECTION_TEST):
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
        log_admin_action(
            request.user,
            AdminActionLog.Action.AI_CONFIG_TEST,
            target_type="ai_config",
            target_label=dict(AICapabilityConfig.Capability.choices).get(capability, capability),
            new_value={
                "provider": provider,
                "model": config.get("model", ""),
                "status": record.status,
            },
        )
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


class AdminRebuildVectorsView(AdminThrottleMixin, APIView):
    """平台级知识库向量重建（换向量模型后必须执行）。

    覆盖教辅资料与课件 PPT（课件是向量库的主要内容）。
    范围：course / material / ppt / scope=all（全站，需显式声明防误操作）。
    出错处理同教师端：事前校验失败返回 400 不动数据；单项失败可续跑。
    """
    method_scopes = {"POST": "admin_heavy"}

    permission_classes = [IsPlatformAdmin]

    def post(self, request):
        from apps.courses.models import PPTResource, TeachingVideo
        from apps.knowledge.models import Material
        from apps.knowledge.services import rebuild_vectors

        scope = str(request.data.get("scope") or "").strip()
        course_id = request.data.get("course")
        material_id = request.data.get("material")
        ppt_id = request.data.get("ppt")
        qs = Material.objects.all()
        ppt_qs = PPTResource.objects.filter(is_active=True)
        video_qs = TeachingVideo.objects.all()
        materials = qs.none()
        ppts = ppt_qs.none()
        videos = video_qs.none()
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
            videos = video_qs.filter(course_id=course_id).exclude(scripts=[])
        elif scope == "all":
            materials = qs
            ppts = ppt_qs
            videos = video_qs.exclude(scripts=[])
        else:
            return api_response(
                message="请指定 course / material / ppt，或显式传 scope=all 重建全站向量",
                code=400,
                status=400,
            )

        report = rebuild_vectors(materials, ppts, videos)
        if report.get("error"):
            return api_response(report, message=report["error"], code=400, status=400)
        log_admin_action(
            request.user,
            AdminActionLog.Action.VECTOR_REBUILD,
            target_type="vector",
            target_label=(
                f"course#{course_id}" if course_id
                else f"material#{material_id}" if material_id
                else f"ppt#{ppt_id}" if ppt_id
                else "全站"
            ),
            new_value={
                "materials": report["materials"]["success"],
                "ppts": report["ppts"]["success"],
                "videos": report["videos"]["success"],
                "chunks": report["chunks"],
            },
        )
        message = (
            f"向量重建完成：资料 {report['materials']['success']}/{report['materials']['total']} 份，"
            f"课件 {report['ppts']['success']}/{report['ppts']['total']} 部，"
            f"讲稿 {report['videos']['success']}/{report['videos']['total']} 部，"
            f"共 {report['chunks']} 个片段"
        )
        if report["failed"]:
            message += f"，失败 {len(report['failed'])} 项（详见返回清单，可修复后重试）"
        return api_response(report, message=message)


# ---------------------------------------------------------------------------
# AI 调用统计与追溯（流水 / 汇总 / 导出 / 配置变更记录）
# ---------------------------------------------------------------------------
_CALL_LOG_MAX_EXPORT = 50000  # 导出上限保护，避免超长请求把 worker 拖死

# 场景业务域分组：分布卡按组渲染，回答「哪类业务在消耗模型额度」
_SCENE_GROUPS = {
    "catalog_gen": "授课生产",
    "script_gen": "授课生产",
    "tts": "授课生产",
    "tts_preview": "授课生产",
    "question_gen": "授课生产",
    "grading": "授课生产",
    "analytics": "授课生产",
    "qa": "学生学习",
    "material_embed": "知识库",
    "ppt_embed": "知识库",
    "vector_rebuild": "知识库",
    "rag_eval": "知识库",
    "connection_test": "平台运维",
    "other": "其他",
}



def _filter_ai_call_logs(request):
    """流水查询的公共筛选：时间范围 + 能力/场景/服务商/成败/触发人/课程/关键字。"""
    window = _call_log_window(request)
    queryset = _call_log_qs(window["start"], window["end"]).select_related(
        "triggered_by", "course"
    )
    for param, field in (
        ("capability", "capability"),
        ("scene", "scene"),
        ("provider", "provider"),
    ):
        value = request.query_params.get(param, "").strip()
        if value:
            queryset = queryset.filter(**{field: value})
    success = request.query_params.get("success", "").strip()
    if success in ("true", "false"):
        queryset = queryset.filter(success=(success == "true"))
    triggered_by = request.query_params.get("triggered_by", "").strip()
    if triggered_by.isdigit():
        queryset = queryset.filter(triggered_by_id=int(triggered_by))
    course_id = request.query_params.get("course_id", "").strip()
    if course_id.isdigit():
        queryset = queryset.filter(course_id=int(course_id))
    keyword = request.query_params.get("keyword", "").strip()
    if keyword:
        queryset = queryset.filter(
            Q(trace_id__icontains=keyword) | Q(input_preview__icontains=keyword)
        )
    return queryset


def _percentile(values: list[int], ratio: float) -> int:
    """Python 侧计算分位数（SQLite 无 percentile 函数；样本已限量）。"""
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(ratio * (len(ordered) - 1)))))
    return int(ordered[index])


def _call_log_breakdown(queryset, field: str) -> list[dict]:
    """按能力/场景等维度汇总（次数/失败/Mock/平均耗时/Token/条数）；场景附业务域分组。"""
    rows = list(
        queryset.values(field)
        .annotate(
            calls=Count("id"),
            failed=Count("id", filter=Q(success=False)),
            mock_calls=Count("id", filter=Q(is_mock=True)),
            avg_latency=Avg("latency_ms"),
            total_tokens=Sum("total_tokens"),
            item_count=Sum("item_count"),
        )
        .order_by("-calls")
    )
    if field == "scene":
        for row in rows:
            row["group"] = _SCENE_GROUPS.get(row["scene"], "其他")
    return rows


def _call_log_daily(queryset) -> list[dict]:
    """按日趋势（本地时区）：次数/失败/Token/平均耗时；day 输出 ISO 字符串。"""
    rows = list(
        queryset.annotate(day=TruncDate("created_at", tzinfo=timezone.get_current_timezone()))
        .values("day")
        .annotate(
            calls=Count("id"),
            failed=Count("id", filter=Q(success=False)),
            total_tokens=Sum("total_tokens"),
            avg_latency=Avg("latency_ms"),
        )
        .order_by("day")
    )
    return [
        {
            "day": row["day"].isoformat() if row["day"] else None,
            "calls": row["calls"],
            "failed": row["failed"],
            "total_tokens": row["total_tokens"] or 0,
            "avg_latency_ms": int(row["avg_latency"] or 0),
        }
        for row in rows
    ]


class AdminAICallLogListView(AdminThrottleMixin, APIView):
    """AI 调用流水明细：筛选 + 分页（默认近 7 天，支持 start/end 日历窗）。"""

    permission_classes = [IsPlatformAdmin]
    serializer_class = AICallLogSerializer

    def get(self, request):
        try:
            queryset = _filter_ai_call_logs(request)
        except CallLogWindowError as exc:
            return api_response(message=str(exc), code=400, status=400)
        return _paginated_response(queryset, request, AICallLogSerializer)


class AdminAICallLogExportView(AdminThrottleMixin, APIView):
    """流水导出 CSV（带 BOM，Excel 直接打开中文不乱码）。"""
    method_scopes = {"GET": "admin_export"}

    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        try:
            queryset = _filter_ai_call_logs(request).order_by("-created_at")[:_CALL_LOG_MAX_EXPORT]
        except CallLogWindowError as exc:
            return api_response(message=str(exc), code=400, status=400)
        response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
        filename = f"ai_call_logs_{timezone.now():%Y%m%d_%H%M}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "时间", "能力", "服务商", "模型", "场景", "成功", "Mock返回", "耗时(ms)",
                "输入token", "输出token", "token合计", "条数", "输入字符", "输出字符",
                "输入指纹", "追溯ID", "触发人", "课程", "错误摘要",
            ]
        )
        provider_labels = dict(AICapabilityConfig.Provider.choices)
        capability_labels = dict(AICapabilityConfig.Capability.choices)
        scene_labels = dict(AICallLog.Scene.choices)
        for log in queryset.iterator():
            writer.writerow(
                [
                    log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    capability_labels.get(log.capability, log.capability),
                    provider_labels.get(log.provider, log.provider),
                    log.model_name,
                    scene_labels.get(log.scene, log.scene),
                    "是" if log.success else "否",
                    "是" if log.is_mock else "否",
                    log.latency_ms,
                    log.prompt_tokens if log.prompt_tokens is not None else "",
                    log.completion_tokens if log.completion_tokens is not None else "",
                    log.total_tokens if log.total_tokens is not None else "",
                    log.item_count if log.item_count is not None else "",
                    log.input_chars if log.input_chars is not None else "",
                    log.output_chars if log.output_chars is not None else "",
                    log.input_digest,
                    log.trace_id,
                    log.triggered_by.username if log.triggered_by else "",
                    log.course.name if log.course else "",
                    log.error,
                ]
            )
        return response


class AdminAICallStatsView(AdminThrottleMixin, APIView):
    """调用汇总统计：总量 / 按能力 / 按场景 / 按日趋势 / TOP 触发人 / 异常告警。

    窗口：start+end 日历窗（YYYY-MM-DD）或 days 滚动窗（1~365）。
    除当前周期外，还返回紧邻其前一段等长周期的基线（totals_previous /
    daily_previous）供环比对比。
    """

    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        try:
            window = _call_log_window(request)
        except CallLogWindowError as exc:
            return api_response(message=str(exc), code=400, status=400)
        current = self._collect(window["start"], window["end"])
        previous = self._collect(window["previous_start"], window["previous_end"])
        return api_response({
            # 统一转本地时区输出：滚动窗源自 timezone.now()（UTC），
            # 直出 isoformat 会让前端按日期切片时错位一天
            "window": {
                "start": timezone.localtime(window["start"]).isoformat(),
                "end": timezone.localtime(window["end"]).isoformat(),
                "days": window["days"],
                "source": window["source"],
                "previous_start": timezone.localtime(window["previous_start"]).isoformat(),
                "previous_end": timezone.localtime(window["previous_end"]).isoformat(),
            },
            "totals": current["totals"],
            "totals_previous": previous["totals"],
            "by_capability": current["by_capability"],
            "by_scene": current["by_scene"],
            "top_triggered_by": current["top_triggered_by"],
            "daily": current["daily"],
            "daily_previous": previous["daily"],
            "alerts": self._alerts(_call_log_qs(window["start"], window["end"])),
        })

    @staticmethod
    def _collect(start, end) -> dict:
        """汇总一个时间窗的总量 / 分布 / 日趋势 / TOP 触发人。"""
        queryset = _call_log_qs(start, end)
        totals = queryset.aggregate(
            calls=Count("id"),
            # 注意：别名不能与 filter 引用的字段名同名（success 是布尔字段），
            # 否则编译期解析 filter 时会命中聚合别名报 FieldError
            success_count=Count("id", filter=Q(success=True)),
            failed=Count("id", filter=Q(success=False)),
            mock_calls=Count("id", filter=Q(is_mock=True)),
            avg_latency=Avg("latency_ms"),
            prompt_tokens=Sum("prompt_tokens"),
            completion_tokens=Sum("completion_tokens"),
            total_tokens=Sum("total_tokens"),
        )
        # P95：SQLite 无 percentile 函数，窗口内延迟样本（上限 2 万条）Python 侧计算
        latencies = list(queryset.values_list("latency_ms", flat=True)[:20000])
        calls = totals["calls"] or 0
        return {
            "totals": {
                "calls": calls,
                "success": totals["success_count"] or 0,
                "failed": totals["failed"] or 0,
                "success_rate": round((totals["success_count"] or 0) / calls, 4) if calls else None,
                "mock_calls": totals["mock_calls"] or 0,
                "avg_latency_ms": int(totals["avg_latency"] or 0),
                "p95_latency_ms": _percentile(latencies, 0.95),
                "prompt_tokens": totals["prompt_tokens"] or 0,
                "completion_tokens": totals["completion_tokens"] or 0,
                "total_tokens": totals["total_tokens"] or 0,
            },
            "by_capability": _call_log_breakdown(queryset, "capability"),
            "by_scene": _call_log_breakdown(queryset, "scene"),
            "top_triggered_by": list(
                queryset.exclude(triggered_by=None)
                .values("triggered_by", "triggered_by__username")
                .annotate(calls=Count("id"), failed=Count("id", filter=Q(success=False)))
                .order_by("-calls")[:10]
            ),
            "daily": _call_log_daily(queryset),
        }

    @staticmethod
    def _alerts(queryset):
        """近 24 小时的异常提示（页面展示，不做消息推送）。口径与平台待办异常共用。"""
        from .services import ai_health_alerts

        return ai_health_alerts(timezone.now() - timedelta(hours=24))


class AdminQAQualityStatsView(AdminThrottleMixin, BaseQAQualityStatsView):
    """问答质量统计（质量看板 Phase 1，2026-10-22）。

    指标口径（与管理端看板卡片 tooltip 文案一致）：
    - 检索为空率：cited_chunks=[] 且非纯图片默认文案（skip_retrieval）÷（总数 - skip）
    - 改写触发率：rewritten_question 非空 ÷ 总数（多轮追问才触发，首轮天然不触发）
    - 降级分布：context_snapshot.degraded_level 分桶 L0/L1/L2/L4
    - 好评率：feedback=1 ÷（feedback∈{1,-1}）；覆盖率：有评价 ÷ 总数
    - 兜底触发率：context_snapshot.fallback_used=True ÷ 总数（检索为空补上一轮片段）
    - 来源分布：cited_chunks[].source 计数（一条多引用各计一次）
    - 成本：AICallLog scene=QA 窗口内 token 合计（无单价字段，不折算金额）

    窗口与环比基线口径同 AdminAICallStatsView（复用 call_log_window：days 滚动窗
    或 start+end 日历窗，返回前一等长周期基线）。

    装配实现见 BaseQAQualityStatsView（共享口径 2026-10-22 从本类提取，教师端
    复用）；本端点特有：平台全量数据、含成本、平台级为空率告警与 AI 服务健康
    告警（extra_alerts）。
    """

    permission_classes = [IsPlatformAdmin]
    include_cost = True
    include_platform_alerts = True

    def qa_base_queryset(self, request):
        return QARecord.objects.all()

    def extra_alerts(self, request) -> list[dict]:
        """AI 失败率：复用 ai_health_alerts（近 24h，口径与调用统计页一致）。"""
        from .services import ai_health_alerts

        now = timezone.now()
        return [
            {
                "type": "ai_health",
                "level": item.get("level", "warning"),
                "title": "AI 服务异常",
                "detail": item.get("message", ""),
                "course_id": None,
            }
            for item in ai_health_alerts(now - timedelta(hours=24))
        ]


class AdminAIConfigChangeLogListView(AdminThrottleMixin, APIView):
    """大模型能力配置变更记录（字段级 old→new）——已废弃，仅查历史。

    审计双轨合并（2026-10-19）：新记录一律写 AdminActionLog（action=ai_config_save，
    new_value.changes 存按能力分组的字段级 diff，见 /action-logs/ 与操作审计页）。
    本端点仅用于查询合并前写入 AICapabilityChangeLog 的存量记录。
    """

    permission_classes = [IsPlatformAdmin]
    serializer_class = AICapabilityChangeLogSerializer

    def get(self, request):
        queryset = AICapabilityChangeLog.objects.select_related("changed_by").all()
        capability = request.query_params.get("capability", "").strip()
        if capability:
            queryset = queryset.filter(capability=capability)
        return _paginated_response(queryset, request, AICapabilityChangeLogSerializer)
