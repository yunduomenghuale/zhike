"""章节讲稿队列执行体（阶段 3）：整章循环，逐小块生成、即时页级合并落库。

与旧"一次一批、浏览器驱动循环"的区别（方案 §13.1-B6）：
- worker 内整章跑到完：每 AI_SCRIPT_CHUNK_PAGES（默认 3）页一小块，块内线程池
  并发（沿用 services 的 _request_script_batch），**每小块完成即 merge_pages 落库**
  （进度实时可见，中断不丢已完成页，重跑只补空页——幂等性来源）；
- **事务内绝不调 AI**：AI 调用在事务外，结果拿到后经 page_store.merge_pages
  短事务合并（评审 C2 三条纪律）；
- 每块开始前检查 cancel_requested（批次边界取消，§5.5）；PPT 换版本立即取消
  （payload.ppt_id 与 video 当前 ppt 不一致，课件方案自审 F6）；
- done 的分母用 len(ppt.parsed_pages)（坑 19），全部完成自动发布（D5），
  向量化拆为独立 embed_ingest 任务（评审 C11，priority=200）。

progress 结构（§7.3）：{"stage": "generating", "done": n, "total": N,
"message": "...", "fallback_pages": n}——归本流水线独占，队列层永不写。
"""
from __future__ import annotations

import logging

from django.conf import settings

from apps.ai import queue
from apps.ai.gate import gated
from apps.ai.models import AITask
from apps.ai.providers.factory import get_provider
from apps.ai.services import (
    _dedupe_page_body,
    _local_script_for_page,
    _polish_script_text,
    _request_script_batch,
)

from .models import PPTResource, TeachingVideo
from .page_store import count_filled, merge_pages

logger = logging.getLogger(__name__)


def _write_progress(task_id: int, *, done: int, total: int, fallback_pages: int = 0) -> None:
    """进度只写 progress 字段（单条 update，不碰队列元信息，评审 C5/坑 10）。"""
    AITask.objects.filter(id=task_id).update(
        progress={
            "stage": "generating",
            "done": done,
            "total": total,
            "message": f"第 {done}/{total} 页",
            "fallback_pages": fallback_pages,
        }
    )


def run_script_gen(task: AITask) -> None:
    """worker 分发入口（apps.ai.tasks._dispatch）。幂等：只补 script 为空的页。"""
    catalog = task.catalog
    payload = task.payload or {}
    if catalog is None:
        queue.cancel(task.id)
        return
    ppt_id = payload.get("ppt_id")
    ppt = PPTResource.objects.filter(id=ppt_id).first() if ppt_id else None
    if ppt is None:
        queue.mark_error(task.id, "课件不存在或已删除")
        return
    pages = ppt.parsed_pages or []
    if not pages:
        queue.mark_error(task.id, "课件没有可生成的解析页")
        return

    video = TeachingVideo.objects.filter(catalog=catalog).first()
    if video is None:
        video = TeachingVideo.objects.create(catalog=catalog, course=catalog.course, ppt=ppt)
    if video.ppt_id != ppt.id:
        # 换版本后旧任务不再匹配（F6）：取消，让教师对新版本重新提交
        queue.cancel(task.id)
        logger.info("[script_gen] cancel stale task=%s (ppt changed %s->%s)", task.id, ppt.id, video.ppt_id)
        return

    total = len(pages)
    page_map = {}
    for page in pages:
        try:
            page_map[int(page.get("page"))] = page
        except (TypeError, ValueError):
            continue

    # 占位：scripts 补齐全部解析页的空条目（merge 会创建缺失页），分母恒为 parsed_pages
    merge_pages(video.id, {pg: {} for pg in page_map})

    provider = get_provider("chat")
    timeout = getattr(provider, "timeout", None) or getattr(settings, "AI_SCRIPT_TIMEOUT", 45)
    chunk_pages = max(1, int(getattr(settings, "AI_SCRIPT_CHUNK_PAGES", 3) or 3))
    fallback_pages = 0

    while True:
        if queue.is_cancel_requested(task.id):
            logger.info("[script_gen] cancelled at batch boundary task=%s", task.id)
            queue.cancel(task.id)
            return
        # 不跨批次持有实例：每轮重取（C2 纪律 2）；换版随时可能发生在等待期间
        video.refresh_from_db(fields=["scripts", "ppt_id"])
        if video.ppt_id != ppt.id:
            queue.cancel(task.id)
            return
        scripts = video.scripts or []
        done, _ = count_filled(scripts)
        _write_progress(task.id, done=done, total=total, fallback_pages=fallback_pages)
        pending_items = [item for item in scripts if not str(item.get("script") or "").strip()]
        if not pending_items:
            break

        chunk_items = pending_items[:chunk_pages]
        compact = []
        for item in chunk_items:
            pg = int(item.get("page") or 0)
            page_data = page_map.get(pg, {})
            compact.append(
                {
                    "page": pg,
                    "title": (page_data.get("title") or "")[:80],
                    "body": _dedupe_page_body(page_data.get("body") or "")[:500],
                }
            )
        by_page: dict = {}
        try:
            with gated("chat"):  # 闸门挂流水线单次调用（坑 15），持锁期间纯 HTTP
                by_page = _request_script_batch(provider, compact, timeout) or {}
        except Exception:
            logger.exception("[script_gen] chunk request failed task=%s", task.id)
            by_page = {}
        # AI 没覆盖的页（失败/超时/漏页）：本地兜底文本补上
        updates = {}
        for entry in compact:
            pg = entry["page"]
            script = (by_page.get(pg) or "").strip()
            if not script:
                script = _local_script_for_page(page_map.get(pg, entry))["script"]
                fallback_pages += 1
            updates[pg] = {"script": _polish_script_text(script)}
        merge_pages(video.id, updates)

    # 终态：全部页有讲稿 → 自动发布（D5）+ 衍生向量入库任务（C11）
    video.refresh_from_db(fields=["scripts", "ppt_id"])
    if video.ppt_id != ppt.id:
        queue.cancel(task.id)
        return
    done, _ = count_filled(video.scripts)
    if done < total:
        raise RuntimeError(f"讲稿未完成：{done}/{total} 页")
    from django.utils import timezone

    video.gen_status = TeachingVideo.GenStatus.SCRIPT_READY
    video.is_published = True
    video.published_at = timezone.now()
    video.save(update_fields=["gen_status", "is_published", "published_at", "updated_at"])
    _write_progress(task.id, done=total, total=total, fallback_pages=fallback_pages)
    # 向量入库拆独立任务（priority=200 后台衍生）：不阻塞主任务、内存峰值可控
    task.refresh_from_db(fields=["trace_id"])
    queue.enqueue(
        task_type=AITask.TaskType.EMBED_INGEST,
        user=task.triggered_by,
        course=task.course or catalog.course,
        catalog=catalog,
        ppt=ppt,
        payload={"video_id": video.id, "from_task": task.id},
        priority=200,
        dedupe_key=f"embed_ingest:video:{video.id}",
    )
