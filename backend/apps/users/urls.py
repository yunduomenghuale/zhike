from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import AvatarUploadView, LoginView, MeView, PasswordChangeView, RegisterView

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("me/", MeView.as_view(), name="me"),
    path("avatar/", AvatarUploadView.as_view(), name="avatar_upload"),
    path("password/", PasswordChangeView.as_view(), name="password_change"),
]
