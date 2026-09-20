"""实验票据认证：静态实验页（lab-bridge.js）无 JWT 登录态，
以一次性票据（X-Lab-Token 头或 ?token= 参数）换取学生身份。

仅用于 labs 的 bridge 相关端点（submit / bridge-validate / conclusion），
票据本身即凭证：一次签发、可吊销、可审计（见 LabAttemptToken）。
"""
from rest_framework import authentication, exceptions

from .models import LabAttemptToken


class LabTokenAuthentication(authentication.BaseAuthentication):
    keyword = "X-Lab-Token"

    def authenticate(self, request):
        raw = request.META.get("HTTP_X_LAB_TOKEN") or request.query_params.get("token", "")
        if not raw:
            return None  # 交给后续认证类（JWT）
        from . import bridge as lab_bridge

        try:
            ticket = lab_bridge.validate_token(raw)
        except ValueError as exc:
            raise exceptions.AuthenticationFailed(str(exc)) from exc
        # 票据与请求学生强绑定；挂到 request 供视图复用（免二次查询）
        request.lab_ticket = ticket
        return (ticket.student, ticket)

    def authenticate_header(self, request):
        return 'X-Lab-Token realm="lab"'
