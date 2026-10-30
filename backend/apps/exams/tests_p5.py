# -*- coding: utf-8 -*-
"""P5-B8：交卷真行锁准出。

1. 交卷后再次提交（网络重试/竞态后到事务）被 400 拒绝，成绩与提交数不变；
2. 同一考试多线程并发提交：提交数恒为 1（唯一约束 + 行锁），成绩与提交的
   答案一致、状态为已交。SQLite 上 select_for_update 是 no-op（写锁在库层
   串行化），两线程可能都拿到 200——不变量（提交数/成绩/终态）是两种情况下
   都必须成立的硬结论；行锁的互斥语义在 Postgres/MySQL 生效（DATABASE_URL 可切）。
"""
from decimal import Decimal
from threading import Thread
import time

from django.db import OperationalError, connections
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.classroom.models import ClassCourse, ClassRoom, ClassStudent
from apps.courses.models import Catalog, Course
from apps.exams.models import Exam, ExamSubmission, Paper
from apps.questions.models import Question
from apps.users.models import User

ANSWERS_SINGLE = "single"  # 占位说明：answers 结构见 _answers()


class ExamSubmitLockTests(APITestCase):
    """串行行为：交卷后重试提交必须被拒，且不改动已提交答卷。"""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_p5lock", password="pw123456!", role=User.Role.TEACHER)
        cls.student = User.objects.create_user(username="s_p5lock", password="pw123456!", role=User.Role.STUDENT)
        cls.course = Course.objects.create(name="P5行锁课程", teacher=cls.teacher)
        cls.classroom = ClassRoom.objects.create(name="P5行锁班", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第一章")
        cls.single = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.SINGLE,
            stem="1+1=?",
            options=[{"key": "A", "text": "2"}, {"key": "B", "text": "3"}],
            answer={"key": "A"}, score=Decimal("5"), status=Question.Status.PUBLISHED,
        )

    def setUp(self):
        self.teacher_client = APIClient()
        self.teacher_client.force_authenticate(user=self.teacher)
        resp = self.teacher_client.post("/api/exams/", {
            "course": self.course.id, "classroom": self.classroom.id,
            "name": "P5行锁考试", "duration": 60, "total_score": 100,
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.exam_id = resp.data["data"]["id"]
        resp = self.teacher_client.post(f"/api/exams/{self.exam_id}/compose/", {
            "mode": "manual", "questions": [{"question_id": self.single.id, "score": 2}],
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        resp = self.teacher_client.patch(f"/api/exams/{self.exam_id}/", {"status": "published"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)

        self.student_client = APIClient()
        self.student_client.force_authenticate(user=self.student)
        resp = self.student_client.post("/api/exam-submissions/start/", {"exam": self.exam_id}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.sub_id = resp.data["data"]["submission"]["id"]

    def _answers(self):
        return {str(self.single.id): {"key": "A"}}

    def test_resubmit_after_submit_rejected_and_state_intact(self):
        """交卷成功后再次 submit（重试/竞态后到）返回 400，成绩与状态不变。"""
        resp = self.student_client.post(
            f"/api/exam-submissions/{self.sub_id}/submit/", {"answers": self._answers()}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        first_score = resp.data["data"]["objective_score"]

        resp = self.student_client.post(
            f"/api/exam-submissions/{self.sub_id}/submit/", {"answers": self._answers()}, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.data)

        sub = ExamSubmission.objects.get(pk=self.sub_id)
        self.assertEqual(sub.status, ExamSubmission.Status.SUBMITTED)
        self.assertEqual(sub.objective_score, first_score)
        self.assertEqual(ExamSubmission.objects.count(), 1)

    def test_concurrent_save_after_submit_cannot_overwrite(self):
        """暂存读到旧 IN_PROGRESS 也不会覆盖已提交答卷（行锁重取后状态校验拦截）。"""
        resp = self.student_client.post(
            f"/api/exam-submissions/{self.sub_id}/submit/", {"answers": self._answers()}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        original_answers = ExamSubmission.objects.get(pk=self.sub_id).answers

        resp = self.student_client.post(
            f"/api/exam-submissions/{self.sub_id}/save/", {"answers": {"tampered": True}}, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(ExamSubmission.objects.get(pk=self.sub_id).answers, original_answers)


class ExamSubmitThreadRaceTests(TransactionTestCase):
    """真线程并发交卷：提交数与成绩一致性（同一考试多线程提交）。"""

    def setUp(self):
        self.teacher = User.objects.create_user(username="t_p5race", password="pw123456!", role=User.Role.TEACHER)
        self.student = User.objects.create_user(username="s_p5race", password="pw123456!", role=User.Role.STUDENT)
        self.course = Course.objects.create(name="P5并发课程", teacher=self.teacher)
        classroom = ClassRoom.objects.create(name="P5并发班", teacher=self.teacher)
        ClassCourse.objects.create(classroom=classroom, course=self.course)
        ClassStudent.objects.create(classroom=classroom, student=self.student)
        catalog = Catalog.objects.create(course=self.course, title="第一章")
        self.single = Question.objects.create(
            course=self.course, catalog=catalog, qtype=Question.QType.SINGLE,
            stem="2+2=?",
            options=[{"key": "A", "text": "4"}, {"key": "B", "text": "5"}],
            answer={"key": "A"}, score=Decimal("5"), status=Question.Status.PUBLISHED,
        )
        self.exam = Exam.objects.create(
            course=self.course, classroom=classroom, name="P5并发考试",
            duration=60, total_score=100, status=Exam.Status.PUBLISHED,
        )
        self.paper = Paper.objects.create(
            course=self.course, exam=self.exam, student=None, mode="manual",
            question_items=[{"question_id": self.single.id, "score": 2, "order": 1}],
        )
        self.sub = ExamSubmission.objects.create(
            exam=self.exam, student=self.student, paper=self.paper,
            started_at=timezone.now(), status=ExamSubmission.Status.IN_PROGRESS,
        )

    # 测试基建限制：SQLite 测试库是共享缓存内存库，两个 transaction.atomic 并发
    # 升级写锁会立即抛 SQLITE_LOCKED（"database table is locked"，busy_timeout
    # 不适用于 shared-cache 表锁）。文件库/生产库（含 L2 真实服务）走 busy_timeout
    # 串行化，Postgres/MySQL 走行锁。这里对锁竞争做有限重试，只为了让两个提交都
    # 进入事务；不变量断言（提交数/成绩/终态）与锁语义本身不受重试影响。
    LOCK_RETRY = 4

    def _run_two_threads(self, answers_map=None):
        if answers_map is None:
            answers_map = {0: {"key": "A"}, 1: {"key": "A"}}
        results = {}

        def worker(idx):
            try:
                client = APIClient()
                client.force_authenticate(user=self.student)
                payload = {"answers": {str(self.single.id): answers_map[idx]}}
                url = f"/api/exam-submissions/{self.sub.id}/submit/"
                for attempt in range(self.LOCK_RETRY):
                    try:
                        resp = client.post(url, payload, format="json")
                        results[idx] = resp.status_code
                        break
                    except OperationalError as exc:
                        if "locked" not in str(exc) or attempt == self.LOCK_RETRY - 1:
                            raise
                        time.sleep(0.05 * (attempt + 1))
            except Exception as exc:  # 线程内异常必须暴露，不能静默吞掉
                results[idx] = f"{type(exc).__name__}: {exc}"
            finally:
                connections.close_all()

        threads = [Thread(target=worker, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        return results

    def test_threaded_submit_count_and_score_consistent(self):
        results = self._run_two_threads()
        # 并发下每个请求终态必须是明确结果（200 成功 / 400 后到被拒），不允许
        # 500 或未捕获异常；「恰好一次成功」以库中终态为准（下方不变量）。
        self.assertTrue(set(results.values()) <= {200, 400}, results)
        self.assertEqual(ExamSubmission.objects.filter(exam=self.exam).count(), 1)
        sub = ExamSubmission.objects.get(pk=self.sub.id)
        # 恰好一次成功落库：状态已交、成绩与提交的答案一致
        self.assertEqual(sub.status, ExamSubmission.Status.SUBMITTED)
        self.assertEqual(sub.objective_score, Decimal("2"))
        self.assertEqual(sub.total_score, Decimal("2"))
        # 答案与提交内容一致（两线程提交相同答案，不存在互相覆盖出不一致）
        self.assertEqual((sub.answers or {}).get(str(self.single.id)), {"key": "A"})

    def test_threaded_different_answers_exactly_one_final_state(self):
        """两线程提交不同答案：终态唯一（行锁保证后到者读不到 IN_PROGRESS）。"""
        results = self._run_two_threads(answers_map={0: {"key": "A"}, 1: {"key": "B"}})

        self.assertTrue(set(results.values()) <= {200, 400}, results)
        self.assertEqual(ExamSubmission.objects.filter(exam=self.exam).count(), 1)
        sub = ExamSubmission.objects.get(pk=self.sub.id)
        self.assertEqual(sub.status, ExamSubmission.Status.SUBMITTED)
        # 终态分数与终态答案自洽：答 A 得 2 分、答 B 得 0 分
        self.assertEqual(
            sub.objective_score,
            Decimal("2") if (sub.answers or {}).get(str(self.single.id)) == {"key": "A"} else Decimal("0"),
        )
