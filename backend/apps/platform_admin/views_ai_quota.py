# -*- coding: utf-8 -*-
"""AI 日配额管理端接口（P5-B6）。

GET  /api/admin-panel/ai-quota/   查看全局默认与用户级覆盖
PUT  /api/admin-panel/ai-quota/   设置：{default_daily_limit, overrides:[{user_id, daily_limit}]}
     - default_daily_limit: null 表示不限（默认）
     - overrides 中 daily_limit: null 删除该用户覆盖（回到全局默认）
"""
from django.contrib.auth import get_user_model
from rest_framework.views import APIView

from apps.ai.models import AIQuotaPolicy
from apps.common.permissions import IsPlatformAdmin
from apps.common.response import api_response
from apps.platform_admin.audit import log_admin_action
from apps.platform_admin.models import AdminActionLog
from apps.platform_admin.throttles import AdminThrottleMixin

User = get_user_model()


class AdminAIQuotaView(AdminThrottleMixin, APIView):
    method_scopes = {"GET": "admin_read", "PUT": "admin_write"}
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        default_row = AIQuotaPolicy.objects.filter(user__isnull=True).first()
        overrides = []
        for row in AIQuotaPolicy.objects.filter(user__isnull=False).select_related("user"):
            overrides.append({
                "user_id": row.user_id,
                "username": row.user.username,
                "real_name": row.user.real_name,
                "role": row.user.role,
                "daily_limit": row.daily_limit,
            })
        return api_response({
            "default_daily_limit": default_row.daily_limit if default_row else None,
            "overrides": overrides,
        })

    def put(self, request):
        default_limit = request.data.get("default_daily_limit")
        if default_limit is not None and (not isinstance(default_limit, int) or default_limit < 0):
            return api_response(message="default_daily_limit 必须是非负整数或 null（不限）", code=400, status=400)
        overrides = request.data.get("overrides", [])
        if not isinstance(overrides, list):
            return api_response(message="overrides 必须是数组", code=400, status=400)

        # 全局默认
        default_row = AIQuotaPolicy.objects.filter(user__isnull=True).first()
        old_default = default_row.daily_limit if default_row else None
        if default_row is None:
            default_row = AIQuotaPolicy(user=None)
        default_row.daily_limit = default_limit
        default_row.save()

        # 用户级覆盖
        changed_users = []
        for item in overrides:
            user_id = item.get("user_id")
            limit = item.get("daily_limit")
            if limit is not None and (not isinstance(limit, int) or limit < 0):
                return api_response(message=f"用户 {user_id} 的 daily_limit 必须是非负整数或 null", code=400, status=400)
            user = User.objects.filter(pk=user_id).first()
            if not user:
                return api_response(message=f"用户不存在：{user_id}", code=400, status=400)
            if limit is None:
                AIQuotaPolicy.objects.filter(user=user).delete()
            else:
                row, _ = AIQuotaPolicy.objects.get_or_create(user=user)
                row.daily_limit = limit
                row.save()
            changed_users.append(user.username)

        log_admin_action(
            request.user,
            AdminActionLog.Action.AI_CONFIG_SAVE,
            target_type="ai_quota",
            target_label="AI 日配额",
            new_value={"default": old_default, "new_default": default_limit, "users": changed_users},
        )
        return api_response(message="AI 日配额已更新")
