"""embed_ingest 队列执行体：讲稿/课件向量入库的后台衍生任务（评审 C11）。

从讲稿任务尾部拆出来的独立任务（方案 Q11）：ingest 不再阻塞主任务的成败，
本地向量模型（BGE-M3 ≈ 2.3GB）的内存峰值由 worker 按 priority=200 调度控制。
"""
from __future__ import annotations

import logging

from apps.ai.models import AITask

logger = logging.getLogger(__name__)


def run_embed_ingest(task: AITask) -> None:
    """把视频逐页讲稿向量化写入知识库（失败静默，QA 侧有原文兜底）。"""
    from apps.ai.services import ingest_video_scripts
    from apps.courses.models import TeachingVideo

    video_id = (task.payload or {}).get("video_id")
    video = TeachingVideo.objects.filter(id=video_id).first() if video_id else None
    if video is None:
        logger.info("[embed_ingest] video %s gone, skip", video_id)
        return
    try:
        ingest_video_scripts(video)
    except Exception:
        logger.exception("[embed_ingest] video=%s ingest failed（静默，QA 有兜底）", video_id)
