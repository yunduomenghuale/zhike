from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.response import api_response

from .serializers import RegisterSerializer, UserSerializer


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
    """账号密码登录，返回 JWT。"""

    permission_classes = [AllowAny]

    def post(self, request):
        from django.contrib.auth import authenticate

        username = request.data.get("username")
        password = request.data.get("password")
        user = authenticate(username=username, password=password)
        if user is None:
            return api_response(message="用户名或密码错误", code=401, status=401)
        return api_response(
            {"user": UserSerializer(user).data, "token": tokens_for(user)},
            message="登录成功",
        )


class MeView(APIView):
    """获取当前登录用户信息。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return api_response(UserSerializer(request.user).data)
