"""AI 长任务队列内核：入队 / 认领 / 心跳 / 回收 / 取消 / 终结。

设计见 docs/AI长任务队列化改造方案.md §4-§6 与交接书坑清单 §4.3：

- **防重只能靠捕获 IntegrityError**（坑 11）：禁止"先查后插"——两个并发请求会
  同时通过 exists() 检查（学情分析双跑窗口同款竞态）；
- **claim = SKIP LOCKED + 条件更新 rowcount==1**（坑 9）：不用内存锁；条件更新是
  防御性不变量，覆盖"心跳回收改回 pending 时消费者还攥着旧 running 快照"的竞争；
- **心跳单条 update()**（坑 10）：绝不 task.save()，否则整行（含 progress JSON）
  写回与业务字段级写入互覆盖（question_gen_ai.py:59 同款坑）；
- **progress 归业务流水线独占**（评审 C5）：队列层永不写 progress；
- 用户并发：claim 时子查询排除"该触发人已有 running ≥ 上限"的任务（§5.3）；
  triggered_by 为 NULL 的任务不参与互斥（孤儿任务不会饿死）。
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from django.utils import timezone

from .models import AITask

logger = logging.getLogger(__name__)


class QueueError(Exception):
    """队列层业务错误基类（提交端点映射为 429/中文提示）。"""


class QueueFullError(QueueError):
    """全局 pending 超过 AI_QUEUE_MAX。"""


class UserPendingCapError(QueueError):
    """同用户 pending 超过 AI_USER_PENDING_CAP。"""


def enqueue(
    *,
    task_type: str,
    user=None,
    payload: dict | None = None,
    priority: int | None = None,
    dedupe_key: str | None = None,
    on_duplicate: str = "return",
    **biz_fields,
) -> tuple[AITask, bool]:
    """建 PENDING 任务，返回 (task, created)。

    防重协议（§6.1 的 force=0 分支）：唯一索引冲突 → 由 on_duplicate 决定：
    - "return"：返回已有 pending/running 任务，created=False（队列端点回
      dedupe_hit，讲稿/配音/课件用）；
    - "raise"：原样上抛 IntegrityError（既有 4 类 AITask 的既有契约——如生题
      端点依赖它返回 400「已有进行中的生题任务」，不能变成 200 dedupe_hit）。
    force 协议（pending 原子替换 / running 拒绝 409）由提交端点在阶段 3 实现。

    容量（软上限，竞态下允许瞬时超 1，唯一索引才是硬不变量）：
    - 全局 pending ≥ AI_QUEUE_MAX → QueueFullError
    - 同用户 pending ≥ AI_USER_PENDING_CAP → UserPendingCapError
    """
    now = timezone.now()
    # user 与 biz_fields 里的显式 triggered_by 不得冲突：user 优先，显式值兜底
    explicit_user = biz_fields.pop("triggered_by", None)
    if user is None:
        user = explicit_user
    base = dict(
        task_type=task_type,
        status=AITask.Status.PENDING,
        triggered_by=user,
        payload=payload or {},
        dedupe_key=dedupe_key,
        **biz_fields,
    )
    if priority is not None:
        base["priority"] = priority

    pending = AITask.objects.filter(status=AITask.Status.PENDING)
    if pending.count() >= settings.AI_QUEUE_MAX:
        raise QueueFullError("系统任务队列已满，请稍后")
    if user is not None:
        mine = pending.filter(triggered_by=user).count()
        if mine >= settings.AI_USER_PENDING_CAP:
            raise UserPendingCapError(f"你已有 {settings.AI_USER_PENDING_CAP} 个任务在排队，请等待完成")

    try:
        with transaction.atomic():
            task = AITask.objects.create(**base)
    except Exception as exc:
        from django.db import IntegrityError

        if not isinstance(exc, IntegrityError):
            raise
        if on_duplicate == "raise":
            raise
        # 命中唯一索引：返回已有 pending/running 任务（坑 11：只在这里兜，不先查）。
        # 只用调用方实际传入的自然键字段收窄；None 字段不参与（NULL 匹配会误中）。
        conds = Q()
        for field in ("catalog", "ppt", "course", "student", "classroom"):
            value = biz_fields.get(field)
            if value is not None:
                conds &= Q(**{field: value})
        if not conds:
            raise
        existing = (
            AITask.objects.filter(task_type=task_type, status__in=[AITask.Status.PENDING, AITask.Status.RUNNING])
            .filter(conds)
            .order_by("id")
            .first()
        )
        if existing is None:
            raise
        return existing, False
    return task, True


def claim(worker_id: str, available_slots: dict[str, int]) -> AITask | None:
    """认领一条可执行任务（worker 主循环专用，任务线程不得自行 claim）。

    available_slots: {task_type: 剩余槽位数}，由调用方按作业槽位现状计算；
    只取有槽位的类型。返回认领成功的任务（status 已置 RUNNING），本轮无任务返回 None。

    单查询完成"类型有槽 + 用户无在跑 + 到点可跑"三重过滤（§5.2/§5.3）。
    """
    types = [t for t, n in available_slots.items() if n > 0]
    if not types:
        return None
    now = timezone.now()
    qs = AITask.objects.select_for_update(skip_locked=True).filter(
        status=AITask.Status.PENDING,
        task_type__in=types,
    )
    due = Q(next_run_at__isnull=True) | Q(next_run_at__lte=now)
    qs = qs.filter(due)

    cap = max(1, settings.AI_USER_RUNNING_CAP)
    mine_running = (
        AITask.objects.filter(status=AITask.Status.RUNNING, triggered_by=OuterRef("triggered_by"))
        .exclude(triggered_by=None)
        .values("triggered_by")
        .annotate(n=Count("id"))
        .filter(n__gte=cap)
    )
    qs = qs.annotate(user_blocked=Exists(mine_running)).filter(user_blocked=False)
    qs = qs.order_by("priority", "id")

    with transaction.atomic():
        task = qs[:1].first()
        if task is None:
            return None
        # 防御性不变量（坑 9）：pending→running 只能成功一次
        updated = AITask.objects.filter(id=task.id, status=AITask.Status.PENDING).update(
            status=AITask.Status.RUNNING,
            claimed_by=worker_id,
            heartbeat_at=now,
            started_at=task.started_at or now,
            attempts=F("attempts") + 1,
        )
        if updated != 1:
            return None
    task.refresh_from_db()
    logger.info("[queue] claimed task=%s type=%s user=%s attempt=%s", task.id, task.task_type, task.triggered_by_id, task.attempts)
    return task


def heartbeat(task_id: int) -> None:
    """心跳：单条 UPDATE（坑 10）。只在仍 RUNNING 时更新，防"复活已终结任务"。"""
    AITask.objects.filter(id=task_id, status=AITask.Status.RUNNING).update(heartbeat_at=timezone.now())


def reap_stale(stale_seconds: int | None = None) -> int:
    """回收卡死任务：running 且心跳超时 → 回 pending（attempts 不增，§6）。

    增量落库保证重跑只补剩余页，不算任务出错，不消耗重试次数。
    """
    stale = stale_seconds or settings.AI_WORKER_STALE_SECONDS
    cutoff = timezone.now() - timedelta(seconds=stale)
    n = AITask.objects.filter(status=AITask.Status.RUNNING, heartbeat_at__lt=cutoff).update(
        status=AITask.Status.PENDING,
        claimed_by="",
        next_run_at=timezone.now(),
        heartbeat_at=None,
    )
    if n:
        logger.warning("[queue] reaped %s stale running task(s) (> %ss no heartbeat)", n, stale)
    return n


def release_interrupted(task_id: int, delay_seconds: int = 30) -> bool:
    """优雅停机/意外存活线程的收尾：running → pending（attempts 不增，§5.5）。

    只在仍是 RUNNING 时生效（任务可能已自然终结）；与 mark_success/mark_error
    的条件更新互斥，不会双写状态。
    """
    n = AITask.objects.filter(id=task_id, status=AITask.Status.RUNNING).update(
        status=AITask.Status.PENDING,
        claimed_by="",
        heartbeat_at=None,
        next_run_at=timezone.now() + timedelta(seconds=delay_seconds),
    )
    return n == 1


def cancel(task_id: int) -> str:
    """取消任务：pending → 立即 cancelled；running → 置 cancel_requested
    （执行体在批次边界检查后退出，已完成页保留，§6）；终态 → 拒绝。"""
    now = timezone.now()
    n = AITask.objects.filter(id=task_id, status=AITask.Status.PENDING).update(
        status=AITask.Status.CANCELLED, finished_at=now
    )
    if n == 1:
        return "cancelled"
    n = AITask.objects.filter(id=task_id, status=AITask.Status.RUNNING).update(cancel_requested=True)
    if n == 1:
        return "cancel_requested"
    return "invalid_state"


def is_cancel_requested(task_id: int) -> bool:
    """执行体批次边界调用：检查取消标志（读单字段，不带整行缓存）。"""
    return bool(
        AITask.objects.filter(id=task_id).values_list("cancel_requested", flat=True).first()
    )


def mark_success(task_id: int) -> None:
    """任务正常结束：仅置状态与完成时间（条件更新；流水线可能已自行置过 SUCCESS）。

    不写 progress/result——那归业务流水线（评审 C5）。
    """
    AITask.objects.filter(id=task_id, status=AITask.Status.RUNNING).update(
        status=AITask.Status.SUCCESS, finished_at=timezone.now(), heartbeat_at=None
    )


def mark_error(task_id: int, error: str) -> str:
    """整任务异常：未达 max_attempts → 回 pending 退避重试；超限 → failed（§6）。"""
    task = AITask.objects.filter(id=task_id).values("attempts", "max_attempts").first()
    if task is None:
        return "gone"
    if task["attempts"] < task["max_attempts"]:
        base = settings.AI_TASK_RETRY_BASE_SECONDS
        delay = base * (2 ** max(0, task["attempts"] - 1))
        AITask.objects.filter(id=task_id, status=AITask.Status.RUNNING).update(
            status=AITask.Status.PENDING,
            claimed_by="",
            heartbeat_at=None,
            next_run_at=timezone.now() + timedelta(seconds=delay),
            error=str(error or "")[:300],
        )
        return "retry"
    AITask.objects.filter(id=task_id, status=AITask.Status.RUNNING).update(
        status=AITask.Status.FAILED,
        finished_at=timezone.now(),
        heartbeat_at=None,
        error=str(error or "")[:300],
    )
    return "failed"


def queue_position(task: AITask) -> int | None:
    """读时现算排队位置（§7.3，不落库）：同类型 pending 中 (priority, id) 排前面的条数。"""
    if task.status != AITask.Status.PENDING:
        return None
    ahead = AITask.objects.filter(
        status=AITask.Status.PENDING,
        task_type=task.task_type,
    ).filter(
        Q(priority__lt=task.priority)
        | Q(priority=task.priority, id__lt=task.id)
    ).count()
    return ahead + 1
