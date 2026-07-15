from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "real_name", "role", "phone", "email", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("username", "real_name", "phone", "email")
    fieldsets = UserAdmin.fieldsets + (
        ("平台信息", {"fields": ("role", "real_name", "phone", "avatar")}),
    )
