"""AI 长任务队列 worker。

设计见 docs/AI长任务队列化改造方案.md §5.5（线程模型与停机协议）：
- 主线程（调度）：每 AI_WORKER_POLL_SECONDS 轮询 reap_stale → 回收已退出线程的
  槽位 → 按有空闲槽位的类型 claim → 起任务线程；每 AI_WORKER_HEARTBEAT_SECONDS
  给在跑任务打心跳（单条 UPDATE，queue.py）；
- 任务线程 ×N（N = 各类型槽位之和）：apps/ai/tasks.py run_task —— 重建调用
  上下文（评审 C1）→ 分发业务流水线 → mark_success / mark_error；
- 停机：SIGTERM/SIGINT → 停止 claim → join 任务线程 8s（docker 10s 后 SIGKILL）
  → 仍存活的任务回置 pending（attempts 不增，§5.5），由下个副本从断点续跑；
- 自检/身份：首行日志 [ai_worker] pid/slots/poll；--selftest 打印队列深度。

阶段 0 骨架确认容器跑的是 ai_worker 而不是第二个 gunicorn（评审 C3）；
阶段 2 起消费任务。槽位为进程内计数——worker 单副本（取任务走 DB 原子 claim，
未来扩副本时槽位需改 DB 计数，见方案 §5.1）。

用法::

    python manage.py ai_worker            # 常驻消费
    python manage.py ai_worker --selftest # 连通性自检
"""

import os
import signal
import socket
import sys
import threading
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

# task_type → 作业槽位组（settings.AI_JOB_SLOTS_*，见 config/settings.py）。
# embed_ingest 与分析类共享槽位（后台衍生任务，priority=200 自然靠后）。
SLOT_GROUPS = {
    "script_gen": "script",
    "audio_gen": "audio",
    "ppt_parse": "ppt",
    "embed_ingest": "analytics",
    "class_analytics": "analytics",
    "chapter_summary": "analytics",
    "question_gen": "analytics",
    "course_reuse": "analytics",
}


def _slot_totals() -> dict:
    """各槽位组的总数（settings 已由环境变量覆盖）。"""
    return {
        "script": max(1, settings.AI_JOB_SLOTS_SCRIPT),
        "audio": max(1, settings.AI_JOB_SLOTS_AUDIO),
        "analytics": max(1, settings.AI_JOB_SLOTS_ANALYTICS),
        "ppt": max(1, settings.AI_JOB_SLOTS_PPT),
    }


class _SlotBook:
    """进程内槽位账本（坑：调度集中在一处，任务线程不得自行 claim——§5.5）。"""

    def __init__(self, totals: dict):
        self._totals = totals
        self._used = {g: 0 for g in totals}
        self._lock = threading.Lock()

    def acquire(self, group: str) -> bool:
        with self._lock:
            if self._used[group] >= self._totals[group]:
                return False
            self._used[group] += 1
            return True

    def release(self, group: str) -> None:
        with self._lock:
            self._used[group] = max(0, self._used[group] - 1)

    def available_by_type(self) -> dict:
        """{task_type: 剩余槽位}，供 queue.claim 过滤。"""
        with self._lock:
            free = {g: self._totals[g] - self._used[g] for g in self._totals}
        return {t: free.get(g, 0) for t, g in SLOT_GROUPS.items()}

    def snapshot(self) -> dict:
        with self._lock:
            return {g: f"{self._used[g]}/{self._totals[g]}" for g in self._totals}


class Command(BaseCommand):
    help = "AI 长任务队列 worker：消费 ai_task 表"

    def add_arguments(self, parser):
        parser.add_argument(
            "--selftest",
            action="store_true",
            help="连通性自检：连库查询 ai_task 队列深度后退出，不进入消费循环",
        )

    def handle(self, *args, **options):
        slots = _slot_totals()
        poll = max(1, settings.AI_WORKER_POLL_SECONDS)
        worker_id = f"{socket.gethostname()}:{os.getpid()}"
        slots_str = ",".join(f"{k}={v}" for k, v in slots.items())
        # 身份自报必须打在任何自检重试日志之前，保证它是容器日志首行（评审 C3 验证口径）
        print(
            f"[ai_worker] pid={os.getpid()} worker_id={worker_id} "
            f"slots({slots_str}) poll={poll}s",
            flush=True,
        )

        if options["selftest"]:
            self._selftest()
            return

        if not self._wait_ready():
            sys.exit(1)

        from apps.ai import queue as ai_queue

        stop = threading.Event()
        book = _SlotBook(slots)
        running: dict[int, dict] = {}  # task_id -> {"thread": Thread, "group": str}
        running_lock = threading.Lock()
        last_heartbeat = 0.0
        last_stats = 0.0

        def _on_signal(signum, _frame):
            print(f"[ai_worker] 收到信号 {signum}，停止认领并等待任务收尾", flush=True)
            stop.set()

        signal.signal(signal.SIGTERM, _on_signal)
        signal.signal(signal.SIGINT, _on_signal)

        print("[ai_worker] 就绪，进入消费循环", flush=True)
        while not stop.wait(poll):
            now = time.monotonic()
            try:
                ai_queue.reap_stale()
            except Exception:  # noqa: BLE001 - 回收失败不该拖垮主循环
                self._err("reap_stale")
            try:
                from apps.ai.quota import release_expired_reservations

                release_expired_reservations()
            except Exception:  # noqa: BLE001
                self._err("release_expired_reservations")

            # 回收已退出线程的槽位
            with running_lock:
                dead = [tid for tid, info in running.items() if not info["thread"].is_alive()]
            for tid in dead:
                with running_lock:
                    info = running.pop(tid, None)
                if info:
                    book.release(info["group"])

            # 心跳：对仍登记在册的在跑任务单条 UPDATE（间隔 AI_WORKER_HEARTBEAT_SECONDS）
            hb_interval = max(5, settings.AI_WORKER_HEARTBEAT_SECONDS)
            if now - last_heartbeat >= hb_interval:
                last_heartbeat = now
                with running_lock:
                    alive_ids = list(running.keys())
                for tid in alive_ids:
                    try:
                        ai_queue.heartbeat(tid)
                    except Exception:  # noqa: BLE001
                        self._err(f"heartbeat task={tid}")

            # claim 并分发
            try:
                task = ai_queue.claim(worker_id, book.available_by_type())
            except Exception:  # noqa: BLE001 - claim 失败不该拖垮主循环
                self._err("claim")
                task = None
            if task is not None:
                group = SLOT_GROUPS.get(task.task_type, "analytics")
                book.acquire(group)  # claim 已见有空位，此处登记占用（单调度线程，无竞态）
                with running_lock:
                    running[task.id] = {
                        "thread": self._spawn_task_thread(task, group, book),
                        "group": group,
                    }

            # 周期性一行统计（可观测：grep [ai_worker] stats）
            if now - last_stats >= 30:
                last_stats = now
                try:
                    depth = ai_queue.AITask.objects.filter(status="pending").count()
                except Exception:  # noqa: BLE001
                    depth = "?"
                print(
                    f"[ai_worker] stats pending={depth} slots={book.snapshot()} running={len(running)}",
                    flush=True,
                )

        # ---- 停机：join 8s，存活的任务回置 pending（attempts 不增，§5.5）----
        print("[ai_worker] 停机：等待任务线程收尾（最多 8s）", flush=True)
        deadline = time.monotonic() + 8
        with running_lock:
            threads = [(tid, info) for tid, info in running.items()]
        for _tid, info in threads:
            info["thread"].join(timeout=max(0, deadline - time.monotonic()))
        for tid, info in threads:
            if info["thread"].is_alive():
                try:
                    ai_queue.release_interrupted(tid)
                    print(f"[ai_worker] 任务 {tid} 回置 pending（断点续跑）", flush=True)
                except Exception:  # noqa: BLE001
                    self._err(f"release_interrupted task={tid}")
        print("[ai_worker] 已退出", flush=True)

    def _spawn_task_thread(self, task, group, book) -> threading.Thread:
        from apps.ai import tasks as ai_tasks

        def _target():
            try:
                ai_tasks.run_task(task)
            except Exception:  # noqa: BLE001 - run_task 内部已兜底，双保险防线程泄漏
                self._err(f"run_task task={task.id}")
            finally:
                book.release(group)

        th = threading.Thread(target=_target, name=f"ai-task-{task.id}", daemon=True)
        th.start()
        return th

    def _err(self, what: str):
        import logging
        import traceback

        logging.getLogger("ai_worker").error("[ai_worker] %s 失败\n%s", what, traceback.format_exc(limit=5))

    def _wait_ready(self, attempts: int = 60, interval: float = 2.0) -> bool:
        """就绪自检：队列表存在且可查（= 迁移已完成）。失败重试，超限退出由编排重启。"""
        from apps.ai.models import AITask

        # 用 _meta.db_table 而非硬编码表名（真实表名是 ai_aitask，评审文档里的
        # "SELECT 1 FROM ai_task" 是笔误；意图是"队列表已迁移"，按元数据查最稳）。
        table = AITask._meta.db_table
        for attempt in range(1, attempts + 1):
            try:
                with connection.cursor() as cursor:
                    cursor.execute(f"SELECT 1 FROM {table} LIMIT 1")
                    cursor.fetchall()
                print(f"[ai_worker] 数据库自检通过（第 {attempt} 次尝试）", flush=True)
                connection.close()
                return True
            except Exception as exc:  # noqa: BLE001 - 启动期只关心能否连上
                print(f"[ai_worker] 第 {attempt}/{attempts} 次自检失败：{exc}", flush=True)
                connection.close()
                time.sleep(interval)
        print("[ai_worker] 数据库自检 60 次仍失败，退出", flush=True)
        return False

    def _selftest(self):
        """连库打印队列深度。优先走 ORM（同时验证模型层可用），失败如实报错。"""
        from django.db.models import Count

        from apps.ai.models import AITask

        try:
            rows = list(AITask.objects.values("status").annotate(n=Count("id")))
            detail = ",".join(f"{r['status']}={r['n']}" for r in rows) or "empty"
            depth = sum(r["n"] for r in rows)
        except Exception as exc:  # noqa: BLE001 - 自检要给出可诊断的错误
            print(f"[ai_worker] selftest FAILED: {exc}", flush=True)
            sys.exit(1)
        db_name = connection.settings_dict.get("NAME", "?")
        print(f"[ai_worker] selftest ok db={db_name} queue_depth={depth} ({detail})", flush=True)
