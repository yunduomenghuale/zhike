from pathlib import Path
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.core.files.storage import default_storage
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.response import api_response
from apps.common.throttles import LoginThrottle

from .serializers import (
    AvatarUploadSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    UserSerializer,
)

User = get_user_model()


def tokens_for(user):
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


class RegisterView(GenericAPIView):
    """注册（教师 / 学生）。

    注册通道由管理端「用户管理 → 开放注册」开关控制（PlatformSetting
    register_open，**缺省关闭**：新部署环境需管理员显式打开）；
    关闭后本接口 403，登录页隐藏注册入口（见 AuthConfigView）。
    """

    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    def post(self, request):
        from apps.platform_admin.models import register_open

        if not register_open():
            return api_response(
                message="注册通道已暂时关闭，请联系管理员开通账号", code=403, status=403
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return api_response(
            {"user": UserSerializer(user).data, "token": tokens_for(user)},
            message="注册成功",
            status=status.HTTP_201_CREATED,
        )


class AuthConfigView(APIView):
    """登录页公开配置（AllowAny）：注册通道开关等匿名可见的全局开关。"""

    permission_classes = [AllowAny]

    def get(self, request):
        from apps.platform_admin.models import register_open

        return api_response({"register_open": register_open()})


# 登录失败锁定：同一 用户名+IP 连续失败 5 次锁 15 分钟（仅对失败计数，
# 不影响学校 NAT 出口下多人正常登录；计数用跨 worker 共享的文件缓存，保证阈值稳定）
LOGIN_FAIL_LIMIT = 5
LOGIN_FAIL_LOCK_SECONDS = 15 * 60


def _client_ip(request) -> str:
    """取客户端真实 IP（生产经 nginx 反代，取 X-Forwarded-For 首段）。"""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


class LoginView(APIView):
    """使用唯一用户名和密码登录，返回 JWT。"""

    permission_classes = [AllowAny]
    serializer_class = LoginSerializer
    # P5-C9：登录端点按 IP 从严（全局 anon/user 之上叠加；失败锁定另行兜底）
    throttle_classes = [LoginThrottle]

    def post(self, request):
        identifier = str(request.data.get("username") or "").strip()
        password = request.data.get("password")
        fail_cache = caches["login_fail"]
        fail_key = f"login:fail:{identifier.lower()}:{_client_ip(request)}"
        fails = fail_cache.get(fail_key, 0)
        if fails >= LOGIN_FAIL_LIMIT:
            return api_response(
                message="登录失败次数过多，请15分钟后再试", code=429, status=429
            )
        user = User.objects.filter(username__iexact=identifier).first()
        if user is None or not user.is_active or not user.check_password(password or ""):
            fail_cache.set(fail_key, fails + 1, LOGIN_FAIL_LOCK_SECONDS)
            return api_response(message="用户名或密码错误", code=401, status=401)
        fail_cache.delete(fail_key)
        return api_response(
            {"user": UserSerializer(user).data, "token": tokens_for(user)},
            message="登录成功",
        )


class MeView(APIView):
    """获取或更新当前登录用户信息。"""

    permission_classes = [IsAuthenticated]
    serializer_class = ProfileUpdateSerializer

    def get(self, request):
        return api_response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = ProfileUpdateSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return api_response(UserSerializer(request.user).data, message="个人资料已更新")


class LogoutView(APIView):
    """登出（P5-A2）：吊销当前账号的全部未过期 token。

    - refresh token（若携带）进 SimpleJWT 黑名单，不能再用它换新 access；
    - access token 无法进黑名单（黑名单只管 refresh），改为推进用户的
      `tokens_invalid_before` 作废线：该时刻前签发的 access 全部 401。
      语义是「全设备登出」——同一账号其他已登录端也会随之下线，取保守安全。
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh = str(request.data.get("refresh") or "")
        revoked_refresh = False
        if refresh:
            try:
                RefreshToken(refresh).blacklist()
                revoked_refresh = True
            except TokenError:
                pass  # 无效/过期 refresh 不影响登出（作废线已经兜住 access）
        user = request.user
        # 作废线取精确时刻（微秒）：JWT iat 是秒级整数，签发早于登出时刻的
        # token 必有 int(iat) < cutoff，同秒内登出也立即生效。
        # 已知取舍：登出后同一秒内重新登录，新 token 也会被拒（iat 整秒仍小于
        # cutoff），前端再登一次即恢复；真实交互（页面跳转+手动登录）远大于 1s。
        user.tokens_invalid_before = timezone.now()
        user.save(update_fields=["tokens_invalid_before"])
        return api_response(
            {"refresh_revoked": revoked_refresh},
            message="已退出登录",
        )


class AvatarUploadView(APIView):
    """上传当前用户头像，文件保存在 media/avatars 下。"""

    permission_classes = [IsAuthenticated]
    serializer_class = AvatarUploadSerializer

    def post(self, request):
        serializer = AvatarUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        avatar = serializer.validated_data["avatar"]

        extension = {
            "JPEG": ".jpg",
            "PNG": ".png",
            "WEBP": ".webp",
        }[avatar.image.format]
        saved_name = default_storage.save(
            f"avatars/{request.user.pk}/{uuid4().hex}{extension}",
            avatar,
        )

        old_avatar = request.user.avatar
        avatar_url = default_storage.url(saved_name)
        if not avatar_url.startswith("/"):
            avatar_url = f"/{avatar_url}"
        request.user.avatar = avatar_url
        request.user.save(update_fields=["avatar"])

        media_prefix = "/media/"
        if old_avatar.startswith(media_prefix):
            old_name = old_avatar.removeprefix(media_prefix)
            if old_name.startswith("avatars/") and old_name != saved_name:
                default_storage.delete(Path(old_name).as_posix())

        return api_response(UserSerializer(request.user).data, message="头像已更新")


class PasswordChangeView(APIView):
    """校验当前密码后设置新密码。"""

    permission_classes = [IsAuthenticated]
    serializer_class = PasswordChangeSerializer

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.must_change_password = False
        request.user.save(update_fields=["password", "must_change_password"])
        return api_response(message="密码修改成功")


from rest_framework.decorators import action

from apps.common.viewsets import BaseModelViewSet

from .models import Notification
from .serializers import NotificationSerializer


class NotificationViewSet(BaseModelViewSet):
    """我的站内通知：列表 + 标记已读。"""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user).order_by("-id")

    @action(detail=True, methods=["post"], url_path="read")
    def read_one(self, request, pk=None):
        obj = self.get_object()
        if not obj.is_read:
            obj.is_read = True
            obj.save(update_fields=["is_read", "updated_at"])
        return api_response(message="已读")

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        n = self.get_queryset().filter(is_read=False).update(is_read=True)
        return api_response({"count": n}, message="已全部标记为已读")
