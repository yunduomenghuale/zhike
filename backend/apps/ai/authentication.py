"""JWTAuthentication 子类：认证成功时把用户写进 contextvars。

DRF 的认证发生在视图内部，普通中间件在请求早期还拿不到已认证用户；
在这里挂钩，AI 调用流水（AICallLog.triggered_by）才能落到真实触发人。
仅做记录，不改变任何认证行为。
"""
from __future__ import annotations

from rest_framework_simplejwt.authentication import JWTAuthentication

from .calllog import set_current_user


class AiCallJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            set_current_user(result[0])
        return result
