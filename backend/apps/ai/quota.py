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


def check_ai_quota(user, extra_reserved: int = 0):
    """超限抛 429；返回 None 表示放行。

    limit=0 的语义是「当天 0 次」即完全封禁（区别于 None 不限），
    管理端可临时封禁某账号的 AI 调用。
    code="ai_quota"：异常处理器据此透传本业务文案，而非泛化频控提示。

    extra_reserved（D4/评审 C7）：长任务提交时把本次预估占用并入校验——
    口径 = 已用 + 预留中 + 本次预估 >= 上限 → 429。普通入口（问答/试听）不传，
    行为与改造前完全一致。
    """
    limit = get_effective_daily_limit(user)
    if limit is None:
        return
    if chat_calls_today(user) + active_reserved(user) + max(0, int(extra_reserved or 0)) >= limit:
        raise Throttled(
            detail=f"今日 AI 调用次数已达上限（{limit} 次），请明天再试或联系管理员调整配额",
            code="ai_quota",
        )


# ---------------------------------------------------------------------------
# 长任务配额预留（D4/评审 C7，§13.5）
# ---------------------------------------------------------------------------
RESERVATION_TTL_HOURS = 6


def active_reserved(user) -> int:
    """该用户当前「预留中」的总量（先把过期行释放掉，再求和）。"""
    release_expired_reservations()
    if user is None or not getattr(user, "is_authenticated", False):
        return 0
    from django.db.models import Sum

    from .models import AIQuotaReservation

    total = AIQuotaReservation.objects.filter(
        user=user, status=AIQuotaReservation.Status.PENDING
    ).aggregate(s=Sum("amount"))["s"]
    return int(total or 0)


def reserve_quota(task, user, amount: int) -> None:
    """提交成功后在任务上登记预留（与任务行同生共死，CASCADE）。"""
    from .models import AIQuotaReservation

    AIQuotaReservation.objects.update_or_create(
        task=task,
        defaults={
            "user": user,
            "amount": max(1, int(amount)),
            "settled_amount": 0,
            "status": AIQuotaReservation.Status.PENDING,
            "expires_at": timezone.now() + timezone.timedelta(hours=RESERVATION_TTL_HOURS),
        },
    )


def settle_quota(task) -> None:
    """任务终结：按 trace_id 数 AICallLog 实际条数结算（一个任务=一个 trace_id，C1）。

    只在终态调用一次；重试期间预留保持 pending，继续占额度（防超额提交）。
    """
    from .models import AIQuotaReservation

    reservation = getattr(task, "quota_reservation", None)
    if reservation is None or reservation.status != AIQuotaReservation.Status.PENDING:
        return
    settled = AICallLog.objects.filter(trace_id=task.trace_id).count() if task.trace_id else 0
    AIQuotaReservation.objects.filter(id=reservation.id, status=AIQuotaReservation.Status.PENDING).update(
        settled_amount=settled,
        status=AIQuotaReservation.Status.SETTLED,
    )


def release_expired_reservations() -> int:
    """过期/孤儿释放（§13.5 ⑤）：expires_at 到期仍 pending，或任务已终态但预留未结。"""
    from .models import AIQuotaReservation

    now = timezone.now()
    n1 = AIQuotaReservation.objects.filter(
        status=AIQuotaReservation.Status.PENDING, expires_at__lt=now
    ).update(status=AIQuotaReservation.Status.RELEASED)
    n2 = AIQuotaReservation.objects.filter(
        status=AIQuotaReservation.Status.PENDING,
        task__status__in=["success", "failed", "cancelled"],
    ).update(status=AIQuotaReservation.Status.RELEASED)
    return n1 + n2
