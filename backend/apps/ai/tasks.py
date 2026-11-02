"""AI 异步任务框架：AITask 提交与 worker 侧执行（队列化改造，阶段 2）。

改造要点（见 docs/AI长任务队列化改造方案.md v2.0 §13.1-B5 与评审 C1）：
- submit_ai_task 只入队（apps/ai/queue.py），不再拉 daemon 线程——执行收拢到
  独立 worker 进程（manage.py ai_worker），请求线程秒返；
- 已删除进程内 _TASK_SEMAPHORE 与提交侧 copy_call_context()（跨进程复制不到
  任何东西，留着是死代码误导）；线程池内的 copy_call_context 仍然保留
  （同进程线程池，services.py 分批并发仍然必要）；
- worker 任务线程入口 run_task：set_current_user(task.triggered_by) +
  ai_scene(...) 显式重建调用上下文（评审 C1）——否则 AICallLog 的
  triggered_by/scene/trace_id 全部为空，QA 看板、成本统计、按教师用量
  三条线静默归零；每任务进出一次 ai_scene → 一个任务 = 一个 trace_id；
- 长驻循环里每任务结束 clear_current_user()，否则 A 教师身份串到 B 教师日志；
- 每线程入口/出口 close_old_connections()，防长驻进程连接泄漏（F11 同款）。
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import close_old_connections

from .calllog import ai_scene, clear_current_user, set_current_user
from .models import AICallLog, AITask
from .queue import enqueue, mark_error, mark_success

logger = logging.getLogger(__name__)

# task_type → AICallLog.Scene（C1 上下文重建的 scene 映射）
SCENE_OF = {
    AITask.TaskType.SCRIPT_GEN: AICallLog.Scene.SCRIPT_GEN,
    AITask.TaskType.AUDIO_GEN: AICallLog.Scene.TTS,
    AITask.TaskType.PPT_PARSE: AICallLog.Scene.PPT_EMBED,
    AITask.TaskType.EMBED_INGEST: AICallLog.Scene.MATERIAL_EMBED,
    AITask.TaskType.CLASS_ANALYTICS: AICallLog.Scene.ANALYTICS,
    AITask.TaskType.CHAPTER_SUMMARY: AICallLog.Scene.CHAPTER_SUMMARY,
    AITask.TaskType.QUESTION_GEN: AICallLog.Scene.QUESTION_GEN,
    AITask.TaskType.COURSE_REUSE: AICallLog.Scene.OTHER,
}


def submit_ai_task(task_type, *, user=None, **biz_fields) -> AITask:
    """建 PENDING 任务并入队（worker 消费）。返回任务对象（含 id）。

    task_type: AITask.TaskType 之一；biz_fields: course/classroom/catalog/
    student 等业务外键（按任务类型传其中一两个）。同键已有 pending/running
    任务时返回已有行（created 丢弃，dedupe 语义见 queue.enqueue）。

    AI_QUEUE_MODE=inline（测试/本地调试）：提交后在当前进程内同步执行
    （语义等价改造前的"daemon 线程同步化"，免起 worker）。
    """
    task, _ = enqueue(task_type=task_type, user=user, on_duplicate="raise", **biz_fields)
    if getattr(settings, "AI_QUEUE_MODE", "worker") == "inline" and task.status == AITask.Status.PENDING:
        from django.utils import timezone

        AITask.objects.filter(id=task.id, status=AITask.Status.PENDING).update(
            status=AITask.Status.RUNNING,
            attempts=1,
            started_at=timezone.now(),
            heartbeat_at=timezone.now(),
        )
        # 用 DB 新副本执行：流水线会改写传入实例的状态字段，而旧语义（daemon
        # 线程内重新加载任务）保证返回给调用方的是"提交时的未刷新快照"
        run_task(AITask.objects.get(id=task.id))
    return task


def run_task(task: AITask) -> None:
    """worker 任务线程入口：重建上下文 → 分发 → 终结（success / 退避重试 / failed）。

    幂等前提：调用前任务已被 claim 置 RUNNING；流水线若自行置 SUCCESS，
    mark_success 的条件更新不会二次改写。

    close_old_connections 只在真正的任务线程（非主线程）执行：worker 里每任务
    一线程必须清理防连接泄漏；inline/测试在主线程直调时清理只会误关调用方
    的事务连接（TestCase 的 atomic 块内关连接 = 毒化事务）。
    """
    import threading

    if threading.current_thread() is not threading.main_thread():
        close_old_connections()  # 线程入口清理残留连接（F11）
    set_current_user(task.triggered_by)
    try:
        if task.cancel_requested:
            # 排队期间被"取消并重新生成"替换掉的旧任务：放弃执行
            from .queue import cancel

            cancel(task.id)
            logger.info("[task] skip cancelled task=%s", task.id)
            return
        scene = SCENE_OF.get(task.task_type, AICallLog.Scene.OTHER)
        with ai_scene(scene, course_id=task.course_id) as scene_ctx:
            # 一个任务 = 一个 trace_id；回写供配额按它结算（评审 C7/D4）
            AITask.objects.filter(id=task.id).update(trace_id=scene_ctx["trace_id"])
            task.refresh_from_db(fields=["trace_id"])
            _dispatch(task)
        mark_success(task.id)
    except Exception as exc:  # 流水线未自行兜底的异常：退避重试或落 FAILED
        logger.exception("AI 任务执行失败（task_id=%s, type=%s）", task.id, task.task_type)
        mark_error(task.id, f"{type(exc).__name__}: {exc}")
    finally:
        clear_current_user()  # 防 A 教师身份串到 B 教师（评审 C1 补充）
        if threading.current_thread() is not threading.main_thread():
            close_old_connections()


def _dispatch(task: AITask) -> None:
    """按 task_type 分发到业务流水线（懒加载防环）。"""
    if task.task_type == AITask.TaskType.CLASS_ANALYTICS:
        from .analytics_ai import run_class_analytics

        run_class_analytics(task)
        return
    if task.task_type == AITask.TaskType.CHAPTER_SUMMARY:
        from .analytics_ai import run_chapter_summary

        run_chapter_summary(task)
        return
    if task.task_type == AITask.TaskType.QUESTION_GEN:
        from apps.questions.question_gen_ai import run_question_gen

        run_question_gen(task)
        return
    if task.task_type == AITask.TaskType.COURSE_REUSE:
        # 课程复用是 I/O 密集（复制课件页图/配音/资料本体），走同一套任务框架
        # 是为了「进度可见 + 失败落库 + 刷新不丢」，不占 AI 语义
        from apps.courses.reuse import run_course_reuse

        run_course_reuse(task)
        return
    if task.task_type == AITask.TaskType.SCRIPT_GEN:
        from apps.courses.gen_script import run_script_gen

        run_script_gen(task)
        return
    if task.task_type == AITask.TaskType.AUDIO_GEN:
        from apps.courses.gen_audio import run_audio_gen

        run_audio_gen(task)
        return
    if task.task_type == AITask.TaskType.PPT_PARSE:
        from apps.courses.ppt_parse import run_ppt_parse

        run_ppt_parse(task)
        return
    if task.task_type == AITask.TaskType.EMBED_INGEST:
        from apps.ai.embed_ingest import run_embed_ingest

        run_embed_ingest(task)
        return
    raise ValueError(f"未知任务类型：{task.task_type}")
