from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    # phone 已停止采集（合规最小必要）：列表/搜索/表单均不再露出，DB 列保留
    list_display = ("username", "real_name", "role", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("username", "real_name")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("平台信息", {"fields": ("role", "real_name", "avatar")}),
        (
            "权限",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("重要日期", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2", "role", "real_name"),
            },
        ),
    )
