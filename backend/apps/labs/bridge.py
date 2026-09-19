"""静态实验页桥接票据：签发 / 校验 / 消费。"""
import secrets
from datetime import timedelta

from django.utils import timezone

TOKEN_TTL_HOURS = 2

from .models import LabAttemptToken, LabSubmission


def issue_token(submission: LabSubmission) -> LabAttemptToken:
    """为一次作答签发桥接种子票据。submission 与 token 一对一：重做时覆写换新票。"""
    raw = secrets.token_urlsafe(32)
    ticket, _ = LabAttemptToken.objects.update_or_create(
        submission=submission,
        defaults={
            "token": raw,
            "student": submission.student,
            "expires_at": timezone.now() + timedelta(hours=TOKEN_TTL_HOURS),
            "consumed": False,
        },
    )
    return ticket


def validate_token(raw_token: str) -> LabAttemptToken:
    """校验票据：存在、未消费、未过期、归属当前学生。失败抛 ValueError。"""
    try:
        ticket = LabAttemptToken.objects.select_related(
            "submission", "submission__lab", "submission__lab__template"
        ).get(token=raw_token)
    except LabAttemptToken.DoesNotExist as exc:
        raise ValueError("实验票据无效") from exc
    if ticket.consumed:
        raise ValueError("实验票据已使用")
    if ticket.expires_at and timezone.now() > ticket.expires_at:
        raise ValueError("实验票据已过期")
    return ticket


def consume_token(ticket: LabAttemptToken) -> None:
    ticket.consumed = True
    ticket.save(update_fields=["consumed", "updated_at"])
