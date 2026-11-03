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


class MergePagesTests(TransactionTestCase):
    """Q9：page_store.merge_pages 合并语义（评审 C2 的页级覆盖矩阵）。"""

    def setUp(self):
        from apps.courses.models import Catalog, Course, TeachingVideo

        from apps.courses.page_store import merge_pages

        self.merge_pages = merge_pages
        self.teacher = _user("Q_merge")
        self.course = Course.objects.create(name="Q合并课", teacher=self.teacher, status="active")
        self.catalog = Catalog.objects.create(course=self.course, title="Q章节", order=1)
        self.video = TeachingVideo.objects.create(
            catalog=self.catalog,
            course=self.course,
            scripts=[
                {"page": 1, "script": "教师手改的一页"},
                {"page": 2, "script": ""},
                {"page": 3, "script": "第三页", "audio_url": "https://old/audio.mp3"},
            ],
        )

    def _page(self, n):
        self.video.refresh_from_db(fields=["scripts"])
        return next(item for item in self.video.scripts if item["page"] == n)

    # -- Q9-①：worker 不覆盖已有非空 script / audio_url，只填空页 ------------------
    def test_q9_worker_fill_only_empty(self):
        self.merge_pages(
            self.video.id,
            {
                1: {"script": "worker 的新文本"},          # 已有非空 → 跳过
                2: {"script": "worker 填充第二页"},        # 空 → 写入
                3: {"audio_url": "https://new/audio.mp3"}, # 已有非空 → 跳过
            },
        )
        self.assertEqual(self._page(1)["script"], "教师手改的一页")
        self.assertEqual(self._page(2)["script"], "worker 填充第二页")
        self.assertEqual(self._page(3)["audio_url"], "https://old/audio.mp3")

    # -- Q9-②：overwrite_pages 才覆盖（教师显式重生成/手改/重配音）----------------
    def test_q9_overwrite_pages(self):
        self.merge_pages(
            self.video.id,
            {
                1: {"script": "重新生成的版本", "audio_url": None, "audio_error": None},
                3: {"audio_url": "https://new/audio.mp3"},
            },
            overwrite_pages={1, 3},
        )
        p1 = self._page(1)
        self.assertEqual(p1["script"], "重新生成的版本")
        self.assertNotIn("audio_url", p1)  # None 值 = 删除键（配音失效）
        self.assertEqual(self._page(3)["audio_url"], "https://new/audio.mp3")

    # -- Q9-③：audio_url 独立判定——写 script 不动 audio，清 audio 不动 script ----
    def test_q9_audio_independent(self):
        self.merge_pages(self.video.id, {3: {"script": "worker 想改但被跳过"}})
        self.assertEqual(self._page(3)["script"], "第三页")
        self.assertEqual(self._page(3)["audio_url"], "https://old/audio.mp3")
        # 教师手改第 3 页：清 audio_url，script 覆盖
        self.merge_pages(self.video.id, {3: {"script": "手改三", "audio_url": None}}, overwrite_pages={3})
        p3 = self._page(3)
        self.assertEqual(p3["script"], "手改三")
        self.assertNotIn("audio_url", p3)

    # -- 缺失页自动建条目并按页码排序 ------------------------------------------------
    def test_q9_creates_missing_page_sorted(self):
        self.merge_pages(self.video.id, {5: {"script": "新页"}})
        self.video.refresh_from_db(fields=["scripts"])
        self.assertEqual([item["page"] for item in self.video.scripts], [1, 2, 3, 5])


class QuotaReservationTests(TransactionTestCase):
    """Q8：配额预留/结算/过期释放（D4/评审 C7，§13.5 五步生命周期）。"""

    def setUp(self):
        self.teacher = _user("Q_quota")
        from apps.courses.models import Course, Catalog

        self.course = Course.objects.create(name="Q配额课", teacher=self.teacher, status="active")
        self.catalog = Catalog.objects.create(course=self.course, title="Q章节", order=1)

    def _task(self, trace=""):
        return AITask.objects.create(
            task_type=AITask.TaskType.SCRIPT_GEN, status=AITask.Status.RUNNING,
            catalog=self.catalog, course=self.course, triggered_by=self.teacher, trace_id=trace,
        )

    def test_q8_reserve_settle_and_release(self):
        from apps.ai.models import AIQuotaReservation
        from apps.ai.quota import (
            active_reserved,
            release_expired_reservations,
            reserve_quota,
            settle_quota,
        )

        task = self._task(trace="q8trace")
        reserve_quota(task, self.teacher, 10)
        self.assertEqual(active_reserved(self.teacher), 10, "预留中应计入占用")

        # 结算 = 同 trace_id 的 AICallLog 实际条数（一个任务 = 一个 trace_id，C1）
        from apps.ai.models import AICallLog

        AICallLog.objects.create(scene="script_gen", capability="chat", provider="q8", trace_id="q8trace", triggered_by=self.teacher)
        AICallLog.objects.create(scene="script_gen", capability="chat", provider="q8", trace_id="q8trace", triggered_by=self.teacher)
        settle_quota(task)
        reservation = AIQuotaReservation.objects.get(task=task)
        self.assertEqual(reservation.status, AIQuotaReservation.Status.SETTLED)
        self.assertEqual(reservation.settled_amount, 2)
        self.assertEqual(active_reserved(self.teacher), 0, "结算后不再占用")

        # 过期释放：预留 6h 到期仍 pending → 释放（泄漏兜底）。
        # 换一个章节建第二个任务——同一章节同时只允许一条 running 讲稿（唯一索引）
        from apps.courses.models import Catalog

        catalog2 = Catalog.objects.create(course=self.course, title="Q章节2", order=2)
        task2 = AITask.objects.create(
            task_type=AITask.TaskType.SCRIPT_GEN, status=AITask.Status.RUNNING,
            catalog=catalog2, course=self.course, triggered_by=self.teacher, trace_id="q8t2",
        )
        reserve_quota(task2, self.teacher, 5)
        AIQuotaReservation.objects.filter(task=task2).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )
        released = release_expired_reservations()
        self.assertGreaterEqual(released, 1)
        self.assertEqual(active_reserved(self.teacher), 0)

    def test_q8_check_includes_active_reserved(self):
        """校验口径 = 已用 + 预留中 >= 上限（D4）：预留占满即 429。"""
        from apps.ai.models import AIQuotaPolicy
        from apps.ai.quota import check_ai_quota, reserve_quota
        from rest_framework.exceptions import Throttled

        AIQuotaPolicy.objects.create(user=self.teacher, daily_limit=10)
        task = self._task()
        reserve_quota(task, self.teacher, 10)
        try:
            check_ai_quota(self.teacher)
            self.fail("预留占满上限后应 429")
        except Throttled as exc:
            self.assertEqual(exc.get_codes(), "ai_quota")


class QueueCapCategoryTests(TransactionTestCase):
    """Q12：pending 上限分类——解析/入库（课程建设，本地资源）不与 AI 调用类共用名额。"""

    def setUp(self):
        self.teacher = _user("Q_cap")
        from apps.courses.models import Course, Catalog

        self.course = Course.objects.create(name="Q上限课", teacher=self.teacher, status="active")
        self.catalog = Catalog.objects.create(course=self.course, title="Q章节", order=1)

    def test_cap_separate_by_category(self):
        from django.test import override_settings

        from apps.ai.queue import UserPendingCapError, enqueue

        with override_settings(AI_USER_PENDING_CAP=2, AI_USER_PENDING_CAP_LOCAL=4, AI_QUEUE_MAX=100):
            # AI 类 2 个即满
            enqueue(task_type=AITask.TaskType.SCRIPT_GEN, user=self.teacher, catalog=self.catalog, course=self.course)
            enqueue(task_type=AITask.TaskType.AUDIO_GEN, user=self.teacher, catalog=self.catalog, course=self.course)
            try:
                enqueue(task_type=AITask.TaskType.SCRIPT_GEN, user=self.teacher, catalog=self.catalog, course=self.course)
                self.fail("AI 类第 3 个应触发上限")
            except UserPendingCapError as exc:
                self.assertIn("2 个任务", str(exc))
            # 解析类独立名额：4 个都能入队（不受 AI 类 2 个占满影响）
            for i in range(4):
                c2 = type(self.catalog).objects.create(course=self.course, title=f"Q章节{i+2}", order=i + 2)
                enqueue(task_type=AITask.TaskType.PPT_PARSE, user=self.teacher, catalog=c2, course=self.course)
            # 解析类第 5 个才触发 LOCAL 上限
            c6 = type(self.catalog).objects.create(course=self.course, title="Q章节6", order=9)
            try:
                enqueue(task_type=AITask.TaskType.PPT_PARSE, user=self.teacher, catalog=c6, course=self.course)
                self.fail("解析类第 5 个应触发 LOCAL 上限")
            except UserPendingCapError as exc:
                self.assertIn("4 个任务", str(exc))


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
