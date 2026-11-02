"""清理 AI 任务历史（评审 C12 / 方案 Q12）。

队列化后每次生成都落一行 AITask，不清理半年就是几十万行。规则：
- success：--days（默认 30）天前的删除，但每（章节 × 类型）保留最近
  --keep-per-catalog（默认 3）条（教师回看/排查的最低限度）；
- failed / cancelled：--failed-days（默认 90）天前的删除（失败行保留全量便于
  排查的窗口期）；
- 顺带释放孤儿配额预留（任务已终态/被删但预留仍 pending，§13.5 ⑤）。

用法：python manage.py prune_ai_tasks --days 30 --failed-days 90 --keep-per-catalog 3
挂 crontab 每日一次即可。
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Max
from django.utils import timezone


class Command(BaseCommand):
    help = "清理 AITask 历史：success 保留 N 天且每章节每类型留最近 K 条，failed/cancelled 保留 M 天"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30, help="success 保留天数（默认 30）")
        parser.add_argument("--failed-days", type=int, default=90, help="failed/cancelled 保留天数（默认 90）")
        parser.add_argument("--keep-per-catalog", type=int, default=3, help="每章节每类型保留的 success 条数（默认 3）")
        parser.add_argument("--dry-run", action="store_true", help="只统计不删除")

    def handle(self, *args, **options):
        from apps.ai.models import AITask

        days = options["days"]
        failed_days = options["failed_days"]
        keep = max(0, options["keep_per_catalog"])
        dry = options["dry_run"]
        now = timezone.now()

        # ---- success：过期删除，但每组 (catalog, task_type) 保留最近 keep 条 ----
        success_cutoff = now - timezone.timedelta(days=days)
        keep_ids: set[int] = set()
        if keep:
            groups = (
                AITask.objects.filter(status=AITask.Status.SUCCESS, catalog__isnull=False)
                .values("catalog_id", "task_type")
                .annotate(newest=Max("id"))
            )
            # 逐组取前 keep 条 id（组数量小，循环查询可接受；不用窗口函数兼容旧 MySQL 8.0.36 也行，但简单优先）
            for g in groups:
                ids = list(
                    AITask.objects.filter(
                        catalog_id=g["catalog_id"], task_type=g["task_type"], status=AITask.Status.SUCCESS
                    ).order_by("-id").values_list("id", flat=True)[:keep]
                )
                keep_ids.update(ids)
        success_qs = AITask.objects.filter(
            status=AITask.Status.SUCCESS, finished_at__lt=success_cutoff
        ).exclude(id__in=keep_ids)
        n_success = success_qs.count()

        # ---- failed / cancelled：更长的保留窗口 ----
        failed_cutoff = now - timezone.timedelta(days=failed_days)
        failed_qs = AITask.objects.filter(
            status__in=[AITask.Status.FAILED, AITask.Status.CANCELLED], finished_at__lt=failed_cutoff
        )
        n_failed = failed_qs.count()

        self.stdout.write(
            f"待删除：success {n_success} 条（>{days} 天，每组保留最近 {keep} 条），"
            f"failed/cancelled {n_failed} 条（>{failed_days} 天）"
        )
        if dry:
            self.stdout.write("dry-run：未删除")
            return

        deleted = 0
        for qs in (success_qs, failed_qs):
            # 级联一并清掉配额预留（OneToOne CASCADE）；分批删避免单条 IN 过大
            batch = list(qs.values_list("id", flat=True)[:500])
            while batch:
                _, per = AITask.objects.filter(id__in=batch).delete()
                deleted += per.get("ai.AITask", 0)
                batch = list(qs.values_list("id", flat=True)[:500])

        from apps.ai.quota import release_expired_reservations

        n_released = release_expired_reservations()
        self.stdout.write(f"已删除 {deleted} 条任务，释放孤儿预留 {n_released} 条")
