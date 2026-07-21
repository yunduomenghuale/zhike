from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.views import APIView

from apps.classroom.models import ClassRoom, ClassStudent
from apps.ai.models import AIConfiguration
from apps.ai.providers.factory import build_provider, get_runtime_config
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
    CourseStatusSerializer,
    PasswordResetSerializer,
    AdminAIConfigurationSerializer,
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

    def post(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        if user.is_superuser and not request.user.is_superuser:
            return api_response(message="只有超级管理员可以重置超级管理员密码", code=403, status=403)
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user.set_password(serializer.validated_data["password"])
        user.save(update_fields=["password"])
        return api_response(message="密码已重置")


class AdminCourseListView(APIView):
    permission_classes = [IsPlatformAdmin]

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


class AdminAIConfigurationView(APIView):
    permission_classes = [IsPlatformAdmin]

    def _instance_or_environment(self):
        saved = AIConfiguration.objects.order_by("id").first()
        if saved:
            return saved, "database"
        provider, config, source = get_runtime_config()
        transient = AIConfiguration(
            provider=provider if provider in AIConfiguration.Provider.values else AIConfiguration.Provider.MOCK,
            enabled=provider != AIConfiguration.Provider.MOCK and bool(config.get("api_key")),
            base_url=config.get("base_url", ""),
            chat_model=config.get("chat_model", ""),
            embed_model=config.get("embed_model", ""),
            tts_model=config.get("tts_model", ""),
            api_key_ciphertext="environment" if config.get("api_key") else "",
        )
        return transient, source

    def get(self, request):
        instance, source = self._instance_or_environment()
        data = AdminAIConfigurationSerializer(instance).data
        data["source"] = source
        return api_response(data)

    def put(self, request):
        instance = AIConfiguration.objects.order_by("id").first()
        if instance is None:
            instance = AIConfiguration()
        serializer = AdminAIConfigurationSerializer(
            instance, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        saved = serializer.save()
        data = AdminAIConfigurationSerializer(saved).data
        data["source"] = "database"
        return api_response(data, message="大模型配置已保存并生效")


class AdminAIConnectionTestView(APIView):
    permission_classes = [IsPlatformAdmin]

    def post(self, request):
        config = AIConfiguration.objects.order_by("id").first()
        if not config:
            return api_response(message="请先保存大模型配置", code=400, status=400)

        now = timezone.now()
        try:
            if not config.enabled or config.provider == AIConfiguration.Provider.MOCK:
                message = "模拟模式可用；当前不会调用真实大模型"
            else:
                provider = build_provider(config.provider, {
                    "api_key": config.get_api_key(),
                    "base_url": config.base_url,
                    "chat_model": config.chat_model,
                    "embed_model": config.embed_model,
                    "tts_model": config.tts_model,
                })
                reply = provider.chat(
                    [{"role": "user", "content": "请只回复：连接成功"}],
                    temperature=0,
                    timeout=20,
                    retries=1,
                    fallback_to_mock=False,
                    max_tokens=16,
                )
                if not str(reply or "").strip():
                    raise RuntimeError("模型返回内容为空")
                message = f"{config.get_provider_display()} / {config.chat_model} 连接成功"
            config.last_test_status = AIConfiguration.TestStatus.SUCCESS
            config.last_test_message = message
            http_status = 200
            code = 0
        except Exception as exc:
            message = f"连接失败：{str(exc)[:300]}"
            config.last_test_status = AIConfiguration.TestStatus.FAILED
            config.last_test_message = message
            http_status = 400
            code = 400
        config.last_tested_at = now
        config.save(update_fields=["last_test_status", "last_test_message", "last_tested_at", "updated_at"])
        return api_response(
            AdminAIConfigurationSerializer(config).data,
            message=message,
            code=code,
            status=http_status,
        )
