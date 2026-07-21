from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "real_name", "role", "phone", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("username", "real_name", "phone")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("平台信息", {"fields": ("role", "real_name", "phone", "avatar")}),
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
                "fields": ("username", "password1", "password2", "role", "real_name", "phone"),
            },
        ),
    )
