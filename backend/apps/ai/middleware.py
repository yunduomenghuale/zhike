"""AI 调用流水的请求级上下文中间件。

两个职责：
1. 请求开始时清理上一个请求可能残留的 contextvars（同线程复用）；
2. 暂存请求对象引用，供落库时解析触发人——DRF 认证在视图内部完成，
   中间件阶段还拿不到已认证用户（生产路径由 AiCallJWTAuthentication
   显式写入，这里作为 session / 测试 force_authenticate 等路径的兜底）。

管理命令等无请求场景用户为 None（触发人为空），不影响记录。
"""
from __future__ import annotations

from .calllog import clear_current_user, set_request_ref


class AiCallUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        clear_current_user()
        token = set_request_ref(request)
        try:
            return self.get_response(request)
        finally:
            from .calllog import reset_request_ref

            reset_request_ref(token)
