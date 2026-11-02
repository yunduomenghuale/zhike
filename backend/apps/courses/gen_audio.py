"""章节配音队列执行体（阶段 4）：整章循环补齐配音，逐页页级合并落库。

与讲稿执行体（gen_script.py）同构：
- 复用 services.synthesize_audio_for_video（批内 3 路并发 + 每页 merge_pages），
  worker 侧整章循环直到没有待合成页；每轮前检查 cancel_requested（批次边界）；
- **无进展即失败**：一轮下来成功 0 页且 audio_error 数无变化（provider 持续不可用），
  抛异常走 mark_error 退避重试，避免对注定失败的页无限循环；
- 全部页有音频 → gen_status=AUDIO_READY + 自动发布（D5，synthesize 内已处理）；
- progress：{"stage": "synthesizing", "done": 有音频页数, "total": 有讲稿页数}。
"""
from __future__ import annotations

import logging

from apps.ai import queue
from apps.ai.models import AITask
from apps.ai.services import synthesize_audio_for_video

from .page_store import count_audio

logger = logging.getLogger(__name__)


def _write_progress(task_id: int, *, scripts_list: list) -> None:
    audio, scripts_n = count_audio(scripts_list)
    AITask.objects.filter(id=task_id).update(
        progress={
            "stage": "synthesizing",
            "done": audio,
            "total": scripts_n,
            "message": f"配音 {audio}/{scripts_n} 页",
        }
    )


def run_audio_gen(task: AITask) -> None:
    """worker 分发入口。幂等：只补有讲稿且无音频的页。"""
    from .models import TeachingVideo

    catalog = task.catalog
    payload = task.payload or {}
    if catalog is None:
        queue.cancel(task.id)
        return
    video_id = payload.get("video_id")
    video = TeachingVideo.objects.filter(id=video_id).first() if video_id else None
    if video is None:
        video = TeachingVideo.objects.filter(catalog=catalog).first()
    if video is None:
        queue.mark_error(task.id, "教学视频不存在")
        return
    voice = payload.get("voice") or None

    while True:
        if queue.is_cancel_requested(task.id):
            logger.info("[audio_gen] cancelled at batch boundary task=%s", task.id)
            queue.cancel(task.id)
            return
        video.refresh_from_db(fields=["scripts"])
        scripts = video.scripts or []
        todo = [
            item
            for item in scripts
            if str(item.get("script") or "").strip() and not str(item.get("audio_url") or "").strip()
        ]
        if not todo:
            break
        errors_before = sum(1 for item in scripts if item.get("audio_error"))
        ok = synthesize_audio_for_video(video, voice=voice)
        video.refresh_from_db(fields=["scripts"])
        _write_progress(task.id, scripts_list=video.scripts or [])
        if ok == 0:
            errors_after = sum(1 for item in (video.scripts or []) if item.get("audio_error"))
            if errors_after >= errors_before:
                # 一轮无任何进展（成功 0、错误数不减）：provider 持续不可用，失败退出
                raise RuntimeError(f"配音无进展：{errors_after} 页合成失败（provider 不可用）")

    video.refresh_from_db(fields=["scripts", "gen_status", "is_published"])
    audio, scripts_n = count_audio(video.scripts)
    if scripts_n == 0:
        queue.mark_error(task.id, "没有可配音的讲稿")
        return
    if audio < scripts_n:
        raise RuntimeError(f"配音未完成：{audio}/{scripts_n} 页")
