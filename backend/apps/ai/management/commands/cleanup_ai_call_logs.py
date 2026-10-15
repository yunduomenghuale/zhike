"""清理过期的 AI 调用流水（AICallLog）。

默认保留 settings.AI_CALL_LOG_RETENTION_DAYS 天（未配 90 天），
可用 --days 覆盖；生产建议放入 crontab 每日执行，例如：

    0 4 * * * cd /data/zhike-v2/backend && ./venv/bin/python manage.py cleanup_ai_call_logs
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "清理过期的 AI 调用流水（默认保留 AI_CALL_LOG_RETENTION_DAYS 天）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="保留天数，覆盖 settings.AI_CALL_LOG_RETENTION_DAYS",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只统计将删除的条数，不实际删除",
        )

    def handle(self, *args, **options):
        from django.conf import settings

        from apps.ai.models import AICallLog

        days = options.get("days") or getattr(settings, "AI_CALL_LOG_RETENTION_DAYS", 90)
        days = max(1, int(days))
        cutoff = timezone.now() - timedelta(days=days)
        queryset = AICallLog.objects.filter(created_at__lt=cutoff)
        count = queryset.count()
        if options["dry_run"]:
            self.stdout.write(
                f"将删除 {count} 条 {cutoff:%Y-%m-%d %H:%M} 之前的调用流水（保留 {days} 天）"
            )
            return
        deleted, _ = queryset.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"已删除 {deleted} 条过期调用流水（截止 {cutoff:%Y-%m-%d %H:%M}，保留 {days} 天）"
            )
        )
