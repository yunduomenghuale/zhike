"""历史 media 文件不可预测化（一次性迁移，可重复执行）。

背景：修复前 media 下存在两类可猜测路径——
1. PPT 页图目录 ppt_pages/<自增资源ID>/，可按 ID 枚举批量下载全部课件页图；
2. 附件（ppt/、materials/、homework/、homework_submit/）保留用户原始文件名，可按中文名猜测。

修复后新上传已改为 hash 目录 / uuid 文件名（见 ppt_parser.ppt_pages_dirname 与各模型
upload_to callable），本命令把存量数据一并迁移到位，迁移后旧 URL 全部 404。

幂等性：已是 hash 目录 / 32 位 hex 文件名的记录自动跳过，重跑无害。
"""
import json
import re
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.courses.models import PPTResource, TeachingVideo
from apps.courses.ppt_parser import ppt_pages_dirname
from apps.homework.models import Homework, HomeworkSubmission
from apps.knowledge.models import Material

_HEX_FILENAME = re.compile(r"^[0-9a-f]{32}\.\w+$")


def _replace_in(value, old: str, new: str):
    """递归替换 str / list / dict 中的路径前缀。"""
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_replace_in(v, old, new) for v in value]
    if isinstance(value, dict):
        return {k: _replace_in(v, old, new) for k, v in value.items()}
    return value


class Command(BaseCommand):
    help = "存量 media 路径不可预测化：ppt_pages/<ID> 目录改 hash 名并重写引用；附件原名改 uuid 名"

    def handle(self, *args, **options):
        media_root = Path(settings.MEDIA_ROOT)
        self._migrate_ppt_pages(media_root)
        self._migrate_attachments(media_root)
        self.stdout.write(self.style.SUCCESS("obfuscate_media 完成"))

    # ------------------------------------------------------------------
    # 1. ppt_pages/<自增ID>/ → ppt_pages/<hash>/
    # ------------------------------------------------------------------
    def _migrate_ppt_pages(self, media_root: Path):
        pages_root = media_root / "ppt_pages"
        if not pages_root.exists():
            self.stdout.write("ppt_pages 目录不存在，跳过")
            return
        moved = refs = 0
        for entry in sorted(pages_root.iterdir()):
            if not entry.is_dir() or not entry.name.isdigit():
                continue
            resource_id = int(entry.name)
            new_dirname = ppt_pages_dirname(resource_id)
            old_prefix = f"/media/ppt_pages/{resource_id}/"
            new_prefix = f"/media/ppt_pages/{new_dirname}/"
            target = pages_root / new_dirname
            if target.exists() and not any(target.iterdir()):
                target.rmdir()
            if target.exists():
                # 极端情况：hash 冲突或残留，跳过并提示人工处理
                self.stdout.write(self.style.WARNING(f"目标目录已存在，跳过 {entry.name} -> {new_dirname}"))
                continue
            entry.rename(target)
            moved += 1
            refs += self._rewrite_refs(resource_id, old_prefix, new_prefix)
        self.stdout.write(f"ppt_pages：迁移目录 {moved} 个，更新引用字段 {refs} 处")

    def _rewrite_refs(self, resource_id: int, old_prefix: str, new_prefix: str) -> int:
        """重写 PPTResource.parsed_pages 与关联 TeachingVideo 中的页图 URL 前缀。"""
        changed = 0
        try:
            resource = PPTResource.objects.get(pk=resource_id)
        except PPTResource.DoesNotExist:
            return 0  # 资源已删（parsed_pages 随之删除），无可重写引用
        if old_prefix in json.dumps(resource.parsed_pages or [], ensure_ascii=False):
            resource.parsed_pages = _replace_in(resource.parsed_pages, old_prefix, new_prefix)
            resource.save(update_fields=["parsed_pages"])
            changed += 1
        for video in TeachingVideo.objects.filter(catalog_id=resource.catalog_id):
            fields = []
            for field in ("scripts", "audio_url", "subtitle_url", "video_url"):
                old_value = getattr(video, field)
                new_value = _replace_in(old_value, old_prefix, new_prefix)
                if new_value != old_value:
                    setattr(video, field, new_value)
                    fields.append(field)
            if fields:
                video.save(update_fields=fields)
                changed += 1
        return changed

    # ------------------------------------------------------------------
    # 2. 附件原始文件名 → uuid 文件名
    # ------------------------------------------------------------------
    def _migrate_attachments(self, media_root: Path):
        targets = [
            (PPTResource.objects.all(), "file", "ppt"),
            (Material.objects.all(), "file", "materials"),
            (Homework.objects.all(), "attachment", "homework"),
            (HomeworkSubmission.objects.all(), "attachment", "homework_submit"),
        ]
        for qs, field_name, label in targets:
            renamed = skipped = missing = 0
            for obj in qs:
                f = getattr(obj, field_name)
                if not f:
                    continue
                name = Path(f.name)
                if _HEX_FILENAME.match(name.name):
                    skipped += 1  # 已是 uuid 命名
                    continue
                old_path = media_root / name
                if not old_path.exists():
                    missing += 1
                    continue
                new_rel = f"{name.parent.as_posix()}/{uuid4().hex}{name.suffix.lower()}"
                old_path.rename(media_root / new_rel)
                setattr(obj, field_name, new_rel)
                obj.save(update_fields=[field_name])
                renamed += 1
            self.stdout.write(
                f"{label}: 重命名 {renamed}，已是uuid跳过={skipped}，磁盘缺失={missing}"
            )
