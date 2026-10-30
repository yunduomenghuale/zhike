"""AI 调用日配额校验（P5-B6）。

- 有效上限 = 用户级覆盖（AIQuotaPolicy.user=本人）> 全局默认（user=None）
  > 环境变量 AI_DAILY_CHAT_QUOTA（默认 0 = 不限，生产由管理端配置）；
- 用量 = 当天 AICallLog（capability=chat、triggered_by=本人）条数；
- 超限抛 DRF Throttled（429 + 中文提示）。

事前校验放在业务入口（问答 ask/ask_stream、AI 生题、讲稿/目录生成、TTS 试听），
异步入库的 AITask 不重复拦（入口已拦）。全局默认 0 = 不限，测试与开发不受影响。
"""
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import Throttled

from .models import AICallLog, AIQuotaPolicy


def _day_start():
    return timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)


def get_effective_daily_limit(user) -> int | None:
    """有效日上限；None 表示不限。"""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    override = AIQuotaPolicy.objects.filter(user=user).first()
    if override is not None and override.daily_limit is not None:
        return override.daily_limit
    default_row = AIQuotaPolicy.objects.filter(user__isnull=True).first()
    if default_row is not None and default_row.daily_limit is not None:
        return default_row.daily_limit
    env_value = getattr(settings, "AI_DAILY_CHAT_QUOTA", None)
    if env_value:
        return int(env_value)
    return None


def chat_calls_today(user) -> int:
    return AICallLog.objects.filter(
        capability="chat", triggered_by=user, created_at__gte=_day_start()
    ).count()


def check_ai_quota(user):
    """超限抛 429；返回 None 表示放行。

    limit=0 的语义是「当天 0 次」即完全封禁（区别于 None 不限），
    管理端可临时封禁某账号的 AI 调用。
    code="ai_quota"：异常处理器据此透传本业务文案，而非泛化频控提示。
    """
    limit = get_effective_daily_limit(user)
    if limit is None:
        return
    if chat_calls_today(user) >= limit:
        raise Throttled(
            detail=f"今日 AI 调用次数已达上限（{limit} 次），请明天再试或联系管理员调整配额",
            code="ai_quota",
        )
