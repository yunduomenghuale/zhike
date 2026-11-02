"""课件解析队列执行体（阶段 6/W2）：文本解析 → 渲染页图 → 向量入库，全程在 worker。

上传端点只「存文件 + 建 PARSING 记录 + 入队」秒返（F9：override create()），
本执行体复用原同步链路的三段（parse_teaching_file_pages →
render_presentation_slide_images → ingest_ppt_pages），进度沿用
_make_parse_progress_writer 的 0.5s 节流（不要另写一套，课件方案 §5）。

关键语义：
- **先建后删（F5）**：新片段按 ppt 维度写入成功后才删旧版本片段；ingest
  返回 0（向量模型不可用）时保留旧片段——杜绝「QA 空窗」（异步化后窗口 =
  排队+解析+入库，且新增 worker 中途被杀的失败模式）；
- 取消 → parse_status=FAILED + error=已取消（F18）；任何异常出口同时写
  parse_status=FAILED + parse_progress.error（F13，任务与课件状态不脱节）；
- md5 在 worker 内算（F10）；命中同 md5 历史资源 → 复制页图目录与
  parsed_pages 跳过解析渲染，embed 仍重跑（E7：KnowledgeChunk 按课程归属）；
- 阶段边界检查 cancel_requested（文本解析后、渲染后、入库前）。
"""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from apps.ai import queue
from apps.ai.models import AITask

from .models import PPTResource
from .ppt_parser import (
    attach_slide_images,
    parse_teaching_file_pages,
    ppt_pages_dirname,
    render_presentation_slide_images,
)

logger = logging.getLogger(__name__)


def _compute_md5(file_path: str, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.md5()
    with open(file_path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _copy_pages_from(source: PPTResource, target: PPTResource) -> bool:
    """同 md5 复用（W5/E7）：复制页图目录与 parsed_pages；embed 仍由调用方重跑。"""
    import os

    from django.conf import settings

    if not source.parsed_pages:
        return False
    media_root = Path(str(settings.MEDIA_ROOT))
    src_rel = str(media_root / "ppt_pages" / ppt_pages_dirname(source.id))
    dst_rel_name = ppt_pages_dirname(target.id)
    dst_abs = media_root / "ppt_pages" / dst_rel_name
    try:
        if os.path.isdir(src_rel):
            if dst_abs.exists():
                shutil.rmtree(dst_abs, ignore_errors=True)
            shutil.copytree(src_rel, dst_abs)
        # 页图 URL 目录名随资源派生：无论目录是否复制都重写 parsed_pages 里的
        # image 路径（URL 与磁盘无关，只由资源 id 派生）
        pages = []
        for page in source.parsed_pages:
            item = dict(page)
            image = item.get("image")
            if image:
                item["image"] = re.sub(
                    r"(^|/)ppt_pages/[^/]+/", rf"\g<1>ppt_pages/{dst_rel_name}/", image
                )
            pages.append(item)
        target.parsed_pages = pages
        # 必须落库：调用方随后 refresh_from_db 取权威值，只改内存会被刷掉
        target.save(update_fields=["parsed_pages", "updated_at"])
        return True
    except Exception:
        logger.exception("[ppt_parse] md5 复用复制失败 source=%s target=%s", source.id, target.id)
        return False


def run_ppt_parse(task: AITask) -> None:
    """worker 分发入口。任何退出路径都同时落课件状态与错误（F13/F18）。"""
    from django.conf import settings

    from .views import _make_parse_progress_writer, _parse_progress_payload

    ppt_id = (task.payload or {}).get("ppt_id")
    ppt = PPTResource.objects.filter(id=ppt_id).first() if ppt_id else None
    if ppt is None:
        queue.mark_error(task.id, "课件不存在或已删除")
        return
    write_progress = _make_parse_progress_writer(ppt)

    def fail(message: str):
        try:
            ppt.parse_status = PPTResource.ParseStatus.FAILED
            ppt.parse_progress = _parse_progress_payload("failed", 0, 0, message[:200])
            ppt.save(update_fields=["parse_status", "parse_progress", "updated_at"])
        finally:
            queue.mark_error(task.id, message)

    try:
        if queue.is_cancel_requested(task.id):
            fail("已取消")
            queue.cancel(task.id)
            return
        if not ppt.file:
            fail("课件文件缺失")
            return

        # md5 在 worker 内算（F10）
        try:
            md5 = _compute_md5(ppt.file.path)
            PPTResource.objects.filter(id=ppt.id).update(file_md5=md5, updated_at=timezone.now())
        except Exception:
            md5 = ""

        # W5：同 md5 历史资源复用页图 + parsed_pages（embed 仍重跑，E7）
        reused = False
        if md5:
            source = (
                PPTResource.objects.filter(file_md5=md5, parse_status=PPTResource.ParseStatus.DONE)
                .exclude(id=ppt.id)
                .order_by("-id")
                .first()
            )
            if source is not None and _copy_pages_from(source, ppt):
                reused = True
                ppt.refresh_from_db(fields=["parsed_pages"])
                write_progress("render", len(ppt.parsed_pages), len(ppt.parsed_pages), force=True)

        if not reused:
            write_progress("text", force=True)
            pages = parse_teaching_file_pages(
                ppt.file.path,
                on_page=lambda done, total: write_progress("text", done, total),
            )
            if queue.is_cancel_requested(task.id):
                fail("已取消")
                queue.cancel(task.id)
                return
            # 页数在文本解析后已知：渲染阶段直接带总数，槽位排队期间也显示 0/N
            write_progress("render", 0, len(pages), force=True)
            images = render_presentation_slide_images(
                ppt.file.path,
                resource_id=ppt.id,
                on_progress=lambda done, total: write_progress("render", done, total),
            )
            pages = attach_slide_images(pages, images)
            ppt.parsed_pages = pages
            ppt.save(update_fields=["parsed_pages", "updated_at"])

        pages = ppt.parsed_pages or []
        if not pages:
            fail("解析无内容（文件可能损坏或格式不支持）")
            return

        with transaction.atomic():
            ppt.parse_status = PPTResource.ParseStatus.DONE
            ppt.is_active = True
            ppt.parse_progress = _parse_progress_payload("done", len(pages), len(pages))
            ppt.save(update_fields=["parse_status", "is_active", "parse_progress", "updated_at"])
            # 新版本转正：旧版本 is_active 下线（向量片段等入库成功后再删，F5）
            PPTResource.objects.filter(course_id=ppt.course_id, catalog_id=ppt.catalog_id).exclude(pk=ppt.pk).update(is_active=False)
            from .views import _invalidate_teaching_video_for_new_ppt

            _invalidate_teaching_video_for_new_ppt(ppt.catalog, ppt)

        if queue.is_cancel_requested(task.id):
            fail("已取消")
            queue.cancel(task.id)
            return

        # 向量入库（失败静默返回 0）；先建后删：入库成功才清旧版本片段（F5）
        from apps.ai.services import ingest_ppt_pages

        write_progress("embed", 0, len(pages), force=True)
        chunk_count = ingest_ppt_pages(ppt, on_progress=lambda d, t: write_progress("embed", d, t))
        if chunk_count > 0:
            from apps.knowledge.models import KnowledgeChunk

            old_ppts = PPTResource.objects.filter(
                course_id=ppt.course_id, catalog_id=ppt.catalog_id, version__lt=ppt.version
            )
            KnowledgeChunk.objects.filter(ppt__in=old_ppts).delete()
        else:
            logger.info("[ppt_parse] ingest=0，保留旧版本片段（QA 空窗保护，F5）ppt=%s", ppt.id)
        write_progress("done", len(pages), len(pages), force=True)
        logger.info("[ppt_parse] done ppt=%s pages=%s chunks=%s reused=%s", ppt.id, len(pages), chunk_count, reused)
    except Exception as exc:
        logger.exception("[ppt_parse] failed ppt=%s", ppt.id)
        fail(f"{type(exc).__name__}: {exc}")
