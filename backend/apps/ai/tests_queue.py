"""队列内核单测：claim 原子性 / 防重 / 心跳回收 / 退避 / 取消 / 停机回置 /
上下文重建与身份隔离（测试方案 L1 的 Q1–Q7、Q10、Q11）。

基类必须是 TransactionTestCase：TestCase 的外层事务让 select_for_update 不阻塞，
并发断言会假绿（测了等于没测）——项目先例 tests_ai_task.py。
"""
from __future__ import annotations

import threading
import time
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from apps.ai import queue
from apps.ai.calllog import record_ai_call
from apps.ai.models import AICallLog, AITask
from apps.ai.tasks import run_task
from apps.users.models import User


def _user(username: str, role: str = User.Role.TEACHER) -> User:
    return User.objects.create_user(username=username, password="qtest123456", role=role, real_name=username)


class QueueKernelTests(TransactionTestCase):
    """Q1–Q7：队列内核状态机（不触发真实 AI，只断言 DB 状态迁移）。"""

    def setUp(self):
        self.teacher = _user("Q_t1")
        self.other = _user("Q_t2")
        from apps.courses.models import Course, Catalog

        self.course = Course.objects.create(name="Q队列测试课", teacher=self.teacher, status="active")
        self.catalog = Catalog.objects.create(course=self.course, title="Q章节", order=1)

    # -- Q1：双线程同时 claim 同一任务，只有一个成功 --------------------------------
    def test_q1_claim_atomicity(self):
        task = AITask.objects.create(
            task_type=AITask.TaskType.SCRIPT_GEN, status=AITask.Status.PENDING, catalog=self.catalog
        )
        results, lock = [], threading.Lock()

        def try_claim():
            got = queue.claim("worker-a", {"script_gen": 1})
            with lock:
                results.append(got.id if got else None)

        threads = [threading.Thread(target=try_claim) for _ in range(2)]
        [t.start() for t in threads]
        [t.join(timeout=30) for t in threads]

        self.assertEqual(len([r for r in results if r is None]), 1, f"claim 必须只有一个成功: {results}")
        self.assertEqual([r for r in results if r is not None], [task.id])
        task.refresh_from_db()
        self.assertEqual(task.status, AITask.Status.RUNNING)
        self.assertEqual(task.attempts, 1)

    # -- Q2：同章节并发入队 5 次 → 只产生 1 条任务，全部返回同一 task_id --------------
    def test_q2_enqueue_dedupe_concurrent(self):
        results, lock = [], threading.Lock()

        def submit():
            task, created = queue.enqueue(
                task_type=AITask.TaskType.SCRIPT_GEN, catalog=self.catalog, user=self.teacher
            )
            with lock:
                results.append((task.id, created))

        threads = [threading.Thread(target=submit) for _ in range(5)]
        [t.start() for t in threads]
        [t.join(timeout=30) for t in threads]

        self.assertEqual(len(results), 5)
        ids = {tid for tid, _ in results}
        self.assertEqual(len(ids), 1, f"5 次并发入队必须只建 1 条任务: {results}")
        self.assertEqual(sum(1 for _, created in results if created), 1, "只能有 1 次 created=True")
        self.assertEqual(AITask.objects.filter(task_type=AITask.TaskType.SCRIPT_GEN).count(), 1)

    # -- Q3：课件解析按 ppt 去重（第二版课件不被 catalog 挡住）----------------------
    def test_q3_ppt_parse_dedupe_by_ppt(self):
        from apps.courses.models import PPTResource

        ppt1 = PPTResource.objects.create(course=self.course, catalog=self.catalog, file_name="v1.pptx", version=1, parse_status="parsing")
        ppt2 = PPTResource.objects.create(course=self.course, catalog=self.catalog, file_name="v2.pptx", version=2, parse_status="parsing")

        t1, c1 = queue.enqueue(task_type=AITask.TaskType.PPT_PARSE, ppt=ppt1, user=self.teacher, priority=50)
        t1_dup, c1_dup = queue.enqueue(task_type=AITask.TaskType.PPT_PARSE, ppt=ppt1, user=self.teacher, priority=50)
        self.assertTrue(c1)
        self.assertFalse(c1_dup)
        self.assertEqual(t1.id, t1_dup.id)

        t2, c2 = queue.enqueue(task_type=AITask.TaskType.PPT_PARSE, ppt=ppt2, user=self.teacher, priority=50)
        self.assertTrue(c2, "同章节第二版课件必须能再入队（自审 F3）")
        self.assertNotEqual(t1.id, t2.id)

    # -- Q4：心跳超时回收 → 回 pending，attempts 不增 --------------------------------
    def test_q4_reap_stale(self):
        task = AITask.objects.create(
            task_type=AITask.TaskType.SCRIPT_GEN, status=AITask.Status.RUNNING, catalog=self.catalog,
            attempts=2, claimed_by="worker-x",
            heartbeat_at=timezone.now() - timedelta(seconds=600),
        )
        n = queue.reap_stale(stale_seconds=300)
        self.assertEqual(n, 1)
        task.refresh_from_db()
        self.assertEqual(task.status, AITask.Status.PENDING)
        self.assertEqual(task.attempts, 2, "回收不消耗重试次数")
        self.assertEqual(task.claimed_by, "")

    # -- Q5：退避重试间隔递增，超限落 failed ------------------------------------------
    def test_q5_backoff_and_max_attempts(self):
        task = AITask.objects.create(
            task_type=AITask.TaskType.SCRIPT_GEN, status=AITask.Status.RUNNING, catalog=self.catalog,
            attempts=1, max_attempts=3,
        )
        outcome = queue.mark_error(task.id, "第一次失败")
        self.assertEqual(outcome, "retry")
        task.refresh_from_db()
        delay1 = (task.next_run_at - timezone.now()).total_seconds()
        self.assertTrue(25 <= delay1 <= 40, f"attempts=1 退避应≈30s，实际 {delay1:.0f}s")

        task.status = AITask.Status.RUNNING
        task.attempts = 2
        task.save(update_fields=["status", "attempts"])
        queue.mark_error(task.id, "第二次失败")
        task.refresh_from_db()
        delay2 = (task.next_run_at - timezone.now()).total_seconds()
        self.assertTrue(55 <= delay2 <= 70, f"attempts=2 退避应≈60s，实际 {delay2:.0f}s")

        task.status = AITask.Status.RUNNING
        task.attempts = 3
        task.save(update_fields=["status", "attempts"])
        outcome = queue.mark_error(task.id, "第三次失败")
        self.assertEqual(outcome, "failed")
        task.refresh_from_db()
        self.assertEqual(task.status, AITask.Status.FAILED)
        self.assertIsNotNone(task.finished_at)

    # -- Q6：取消——pending 立即 cancelled；running 置 cancel_requested -----------------
    def test_q6_cancel_semantics(self):
        pending_task = AITask.objects.create(
            task_type=AITask.TaskType.SCRIPT_GEN, status=AITask.Status.PENDING, catalog=self.catalog
        )
        self.assertEqual(queue.cancel(pending_task.id), "cancelled")
        pending_task.refresh_from_db()
        self.assertEqual(pending_task.status, AITask.Status.CANCELLED)

        running_task = AITask.objects.create(
            task_type=AITask.TaskType.SCRIPT_GEN, status=AITask.Status.RUNNING, catalog=self.catalog
        )
        self.assertEqual(queue.cancel(running_task.id), "cancel_requested")
        running_task.refresh_from_db()
        self.assertEqual(running_task.status, AITask.Status.RUNNING, "running 不立即杀，批次边界退出")
        self.assertTrue(running_task.cancel_requested)
        self.assertTrue(queue.is_cancel_requested(running_task.id), "批次边界轮询口径")

        done_task = AITask.objects.create(
            task_type=AITask.TaskType.SCRIPT_GEN, status=AITask.Status.SUCCESS, catalog=self.catalog
        )
        self.assertEqual(queue.cancel(done_task.id), "invalid_state")

    # -- Q7：优雅停机回置——running → pending，attempts 不变，延迟可跑 -----------------
    def test_q7_release_interrupted(self):
        task = AITask.objects.create(
            task_type=AITask.TaskType.SCRIPT_GEN, status=AITask.Status.RUNNING, catalog=self.catalog,
            attempts=1, claimed_by="worker-x",
        )
        ok = queue.release_interrupted(task.id)
        self.assertTrue(ok)
        task.refresh_from_db()
        self.assertEqual(task.status, AITask.Status.PENDING)
        self.assertEqual(task.attempts, 1, "停机不是任务出错，不消耗重试次数")
        self.assertEqual(task.claimed_by, "")
        self.assertGreater(task.next_run_at, timezone.now())


class QueueContextTests(TransactionTestCase):
    """Q10/Q11：C1 上下文重建与长驻身份隔离（run_task 直跑，_dispatch 打桩）。"""

    def setUp(self):
        self.teacher_a = _user("Q_ta")
        self.teacher_b = _user("Q_tb")
        from apps.courses.models import Course, Catalog

        self.course = Course.objects.create(name="Q上下文课", teacher=self.teacher_a, status="active")
        self.catalog = Catalog.objects.create(course=self.course, title="Q章节", order=1)

    def _run_stub(self, task):
        """打桩 _dispatch：记一次调用流水（走 record_ai_call 的真实上下文解析）。"""
        from apps.ai import tasks as ai_tasks

        def stub(inner_task):
            with record_ai_call("chat", "stub", "stub-model"):
                pass

        original = ai_tasks._dispatch
        ai_tasks._dispatch = stub
        try:
            task.status = AITask.Status.RUNNING  # run_task 前置：已被 claim
            task.save(update_fields=["status"])
            run_task(task)
        finally:
            ai_tasks._dispatch = original

    # -- Q10：任务跑完后 AICallLog 的 triggered_by/scene/course_id 非空且 trace_id 一致 --
    def test_q10_context_rebuilt(self):
        task = AITask.objects.create(
            task_type=AITask.TaskType.SCRIPT_GEN, status=AITask.Status.PENDING,
            catalog=self.catalog, course=self.course, triggered_by=self.teacher_a,
        )
        self._run_stub(task)
        task.refresh_from_db()
        self.assertEqual(task.status, AITask.Status.SUCCESS)
        self.assertIsNotNone(task.trace_id, "trace_id 应回写到任务行（配额结算依据）")

        logs = AICallLog.objects.filter(trace_id=task.trace_id)
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertEqual(log.scene, AICallLog.Scene.SCRIPT_GEN)
        self.assertEqual(log.triggered_by_id, self.teacher_a.id)
        self.assertEqual(log.course_id, self.course.id)

    # -- Q11：连续两个任务的身份隔离——B 的日志 triggered_by 不能是 A -------------------
    def test_q11_identity_isolation_between_tasks(self):
        task_a = AITask.objects.create(
            task_type=AITask.TaskType.SCRIPT_GEN, status=AITask.Status.PENDING,
            catalog=self.catalog, course=self.course, triggered_by=self.teacher_a,
        )
        self._run_stub(task_a)
        task_b = AITask.objects.create(
            task_type=AITask.TaskType.SCRIPT_GEN, status=AITask.Status.PENDING,
            catalog=self.catalog, course=self.course, triggered_by=self.teacher_b,
        )
        self._run_stub(task_b)

        task_b.refresh_from_db()
        self.assertNotEqual(task_a.trace_id, task_b.trace_id, "每个任务独立 trace_id")
        log_b = AICallLog.objects.filter(trace_id=task_b.trace_id).first()
        self.assertIsNotNone(log_b)
        self.assertEqual(log_b.triggered_by_id, self.teacher_b.id, "A 的身份不得泄漏到 B 的日志")
