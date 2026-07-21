from pathlib import Path
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.db.models import Q
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.response import api_response

from .serializers import (
    AvatarUploadSerializer,
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
    """注册（教师 / 学生）。"""

    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return api_response(
            {"user": UserSerializer(user).data, "token": tokens_for(user)},
            message="注册成功",
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    """用户名或手机号加密码登录，返回 JWT。"""

    permission_classes = [AllowAny]

    def post(self, request):
        identifier = str(request.data.get("username") or "").strip()
        password = request.data.get("password")
        normalized_phone = identifier.replace(" ", "").replace("-", "")
        matches = list(User.objects.filter(
            Q(username__iexact=identifier) | Q(phone=normalized_phone)
        )[:2])
        user = matches[0] if len(matches) == 1 else None
        if user is None or not user.is_active or not user.check_password(password or ""):
            return api_response(message="用户名、手机号或密码错误", code=401, status=401)
        return api_response(
            {"user": UserSerializer(user).data, "token": tokens_for(user)},
            message="登录成功",
        )


class MeView(APIView):
    """获取或更新当前登录用户信息。"""

    permission_classes = [IsAuthenticated]

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


class AvatarUploadView(APIView):
    """上传当前用户头像，文件保存在 media/avatars 下。"""

    permission_classes = [IsAuthenticated]

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

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return api_response(message="密码修改成功")
