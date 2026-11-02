"""AI 长任务队列 worker（阶段 0：部署骨架）。

设计见 docs/AI长任务队列化改造方案.md v2.0 与交接书阶段 0。本阶段不实现消费循环
（claim / dispatch / 心跳在阶段 2 接入），只保证四件事：

1. 容器里跑的是 ai_worker 而不是第二个 gunicorn（评审 C3：必须显式覆盖
   Dockerfile 的 ENTRYPOINT，deploy/docker-compose.yml 的 worker 服务已处理）；
2. 启动就绪自检（队列表存在且可查），失败每 2s 重试、60 次后退出——
   worker 不跑 migrate，必须等 backend 把迁移做完，但不能比迁移先就绪就崩溃重启刷日志；
3. 首行日志固定格式 ``[ai_worker] pid=… slots(script=2,audio=2,analytics=2,ppt=2) poll=2s``
   ——发布后 ``docker logs --tail 5`` 一眼可辨身份，是防止"又变成 gunicorn"的最后一道人工检查；
4. ``--selftest`` 连库打印队列深度后退出，可单独跑通（CI / 发布验证用）。

用法::

    python manage.py ai_worker            # 常驻值守（阶段 2 起消费任务）
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


def _slot_config() -> dict:
    """作业槽位配置（settings 已由环境变量覆盖，见 config/settings.py 队列配置块）。"""
    return {
        "script": settings.AI_JOB_SLOTS_SCRIPT,
        "audio": settings.AI_JOB_SLOTS_AUDIO,
        "analytics": settings.AI_JOB_SLOTS_ANALYTICS,
        "ppt": settings.AI_JOB_SLOTS_PPT,
    }


class Command(BaseCommand):
    help = "AI 长任务队列 worker：消费 ai_task 表（阶段0为部署骨架，消费循环阶段2接入）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--selftest",
            action="store_true",
            help="连通性自检：连库查询 ai_task 队列深度后退出，不进入值守循环",
        )

    def handle(self, *args, **options):
        slots = _slot_config()
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

        stop = threading.Event()

        def _on_signal(signum, _frame):
            print(f"[ai_worker] 收到信号 {signum}，准备退出", flush=True)
            stop.set()

        signal.signal(signal.SIGTERM, _on_signal)
        signal.signal(signal.SIGINT, _on_signal)

        print("[ai_worker] 数据库就绪，进入值守（阶段0骨架：消费循环于阶段2接入）", flush=True)
        while not stop.wait(poll):
            # 阶段 2 在此接入：reap_stale → claim → 起任务线程 → 心跳
            pass
        print("[ai_worker] 已退出", flush=True)

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
        """连库打印队列深度。优先走 ORM（同时验证模型层可用），失败回退裸 SQL。"""
        try:
            from django.db.models import Count

            from apps.ai.models import AITask

            rows = list(AITask.objects.values("status").annotate(n=Count("id")))
            detail = ",".join(f"{r['status']}={r['n']}" for r in rows) or "empty"
            depth = sum(r["n"] for r in rows)
        except Exception as exc:  # noqa: BLE001 - 自检要给出可诊断的错误
            print(f"[ai_worker] selftest FAILED: {exc}", flush=True)
            sys.exit(1)
        db_name = connection.settings_dict.get("NAME", "?")
        print(f"[ai_worker] selftest ok db={db_name} queue_depth={depth} ({detail})", flush=True)
