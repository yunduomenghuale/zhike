"""清理学生端即时上传产生的孤儿暂存附件。

背景：学生提交前附件即上传到 media/homework_submit/，若最终未提交或提交前移除，
文件不会被引用，成为孤儿。本命令删除超过 --hours（默认 24）小时且未被任何提交
引用的暂存文件。

用法：python manage.py cleanup_submission_staging [--hours 24] [--dry-run]
"""
import time
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from apps.homework.models import HomeworkSubmission

STAGING_DIR = "homework_submit"


class Command(BaseCommand):
    help = "清理超过指定小时数且未被提交引用的孤儿暂存附件"

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24, help="文件年龄阈值（小时），默认 24")
        parser.add_argument("--dry-run", action="store_true", help="只列出将删除的文件，不实际删除")

    def handle(self, *args, **options):
        hours = max(0, int(options["hours"]))
        dry_run = options["dry_run"]
        cutoff = time.time() - hours * 3600

        # 收集所有被提交引用的暂存文件（attachments 列表 + 旧单附件字段）
        referenced = set()
        for submission in HomeworkSubmission.objects.all().only("id", "attachment", "attachments"):
            if submission.attachment:
                referenced.add(submission.attachment.name)
            for item in submission.attachments or []:
                url = str((item or {}).get("url") or "")
                if url.startswith(settings.MEDIA_URL):
                    referenced.add(url[len(settings.MEDIA_URL):])

        staging_root = Path(settings.MEDIA_ROOT) / STAGING_DIR
        if not staging_root.exists():
            self.stdout.write("暂存目录不存在，无需清理")
            return

        removed = 0
        freed = 0
        for path in staging_root.iterdir():
            if not path.is_file() or path.name in referenced:
                continue
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
            except OSError:
                continue
            size = path.stat().st_size
            if dry_run:
                self.stdout.write(f"[dry-run] 将删除: {path.name}（{size} 字节）")
                continue
            try:
                default_storage.delete(f"{STAGING_DIR}/{path.name}")
                removed += 1
                freed += size
            except OSError as exc:
                self.stderr.write(f"删除失败 {path.name}: {exc}")

        if dry_run:
            self.stdout.write(self.style.WARNING("dry-run 结束，未删除任何文件"))
        else:
            self.stdout.write(self.style.SUCCESS(f"已删除 {removed} 个孤儿暂存文件，释放 {freed} 字节"))
