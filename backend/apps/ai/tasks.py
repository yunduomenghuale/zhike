"""AI 异步任务框架：AITask 提交与后台执行（班级学情分析 / 章节学习总结）。

设计要点（见 docs/AI学情分析深化与章节学习总结设计方案.md §2.2）：
- submit_ai_task：建 PENDING 任务记录并拉起 daemon 线程执行，秒级返回；
- 线程不继承 contextvars：提交时 copy_call_context() 带进线程，在 _run_task
  内经 run_in_context 恢复，否则流水线内的 AICallLog 丢场景/触发人/trace_id（F3）；
- 入口 close_old_connections()：daemon 线程复用进程内 DB 连接前先清理残留（F11）；
- 全局 BoundedSemaphore(2) 限制并发分析任务数（LLM 端 QPS 有限），超限任务
  保持 PENDING，由前端轮询自然排队；
- 执行体按 task_type 分发到 apps/ai/analytics_ai.py（学情分析/章节总结）
   或 apps/questions/question_gen_ai.py（AI 多类型生题）（懒加载防环），
   单任务失败只落自身 error，不影响其它任务；
- 不上 Celery：当前无任务队列基础设施，daemon 线程 + 进度轮询与项目现有
  形态（讲稿/配音分批）一致；规模化后把 _run_task 换成队列 consumer 即可，
  对外接口不变。
"""
from __future__ import annotations

import logging
import threading

from django.db import close_old_connections

from .calllog import copy_call_context, run_in_context
from .models import AITask

logger = logging.getLogger(__name__)

# 全局并发上限：分析类任务输入长（约 6k tokens）、单次跑时长，同时 2 个
# 已是 DashScope/本地模型 QPS 友好上限；超限任务在线程内阻塞等待（保持
# PENDING），worker 结束释放，前端 2.5s 轮询自然看到排队推进。
_TASK_SEMAPHORE = threading.BoundedSemaphore(2)


def submit_ai_task(task_type, *, user=None, **biz_fields) -> AITask:
    """建任务记录（PENDING）并拉起 daemon 线程执行。

    task_type: AITask.TaskType 之一；biz_fields: course/classroom/catalog/
    student 等业务外键（按任务类型传其中一两个）。返回任务对象（含 id）。
    """
    task = AITask.objects.create(
        task_type=task_type,
        status=AITask.Status.PENDING,
        triggered_by=user,
        **biz_fields,
    )
    # 提交时复制请求上下文（触发人/请求引用）带进线程；pipeline 内再经
    # ai_scene 生成 trace_id，与分批讲稿的线程池做法一致
    ctx = copy_call_context()
    threading.Thread(
        target=_run_task,
        args=(task.id, ctx),
        daemon=True,
        name=f"ai-task-{task.id}",
    ).start()
    return task


def _run_task(task_id: int, ctx) -> None:
    """daemon 线程入口：排队 → 恢复上下文 → 分发执行 → 异常落 FAILED。"""
    close_old_connections()  # 线程入口清理残留连接（F11）
    acquired = _TASK_SEMAPHORE.acquire(timeout=600)
    try:
        if not acquired:
            # 排队超时（10 分钟）：极少发生（前面任务卡死），标记失败可重试
            _mark_failed(task_id, "排队超时，请重试")
            return
        _execute(task_id, ctx)
    finally:
        if acquired:
            _TASK_SEMAPHORE.release()
        close_old_connections()


def _execute(task_id: int, ctx) -> None:
    """加载任务、切 RUNNING、在恢复的上下文中分发到业务流水线。"""
    try:
        task = AITask.objects.get(id=task_id)
    except AITask.DoesNotExist:
        return
    # 幂等：任务已被终结（如清理任务删除 FAILED 行）则不再执行
    if task.status not in (AITask.Status.PENDING,):
        return
    task.status = AITask.Status.RUNNING
    task.started_at = _now()
    task.save(update_fields=["status", "started_at", "updated_at"])
    try:
        run_in_context(ctx, _dispatch, task)
    except Exception as exc:  # 流水线未自行兜底的异常：落库可诊断
        logger.exception("AI 任务执行失败（task_id=%s, type=%s）", task_id, task.task_type)
        _mark_failed(task_id, f"{type(exc).__name__}: {exc}"[:300])


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
    _mark_failed(task.id, f"未知任务类型：{task.task_type}")


def _mark_failed(task_id: int, error: str) -> None:
    """把任务标记为失败（行可能已被删除，静默处理）。"""
    from django.utils import timezone

    AITask.objects.filter(id=task_id).update(
        status=AITask.Status.FAILED,
        error=str(error or "")[:300],
        finished_at=timezone.now(),
    )


def _now():
    from django.utils import timezone

    return timezone.now()
