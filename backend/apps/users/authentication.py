"""可吊销 JWT 认证（P5-A2）。

在 AiCallJWTAuthentication（contextvars 埋点）之上增加吊销校验：
`User.tokens_invalid_before` 之后签发的旧 access 一律 401。登出与账号停用
都会推进作废线——SimpleJWT 黑名单只管 refresh，access 的吊销靠该字段
单用户 O(1) 判定，无需每 token 一行记录。
"""
from datetime import datetime, timezone as dt_timezone

from rest_framework_simplejwt.exceptions import AuthenticationFailed

from apps.ai.authentication import AiCallJWTAuthentication


class RevocableJWTAuthentication(AiCallJWTAuthentication):
    """校验 token 签发时间早于用户作废线时拒绝（登出/停用语义）。"""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        cutoff = getattr(user, "tokens_invalid_before", None)
        if cutoff is not None:
            iat = validated_token.get("iat")
            if iat is not None:
                issued_at = datetime.fromtimestamp(int(iat), tz=dt_timezone.utc)
                # 等号边界：作废线时刻本身签发的 token 允许通过（logout 后立即
                # 重新登录拿到的 token iat==cutoff 必须可用），只严格早于才拒
                if issued_at < cutoff:
                    raise AuthenticationFailed(
                        "登录凭证已失效，请重新登录", code="token_revoked"
                    )
        return user
