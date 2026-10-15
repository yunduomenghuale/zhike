# -*- coding: utf-8 -*-
"""考试模块冒烟测试：考后即时回看（客观题出分/主观题待批）、教师批改出分、
教师结束考试后学生仍可见、多空填空空数量下发、允许重交、解析开关、
组卷状态流转（发布前必须组卷/发布后只读）、考试时间固定、监控异常次数、
乱序模式（类内题目乱序/选项乱序 key 重映射）、乱序固化（重进不重排）、
保存答案（不提交）。"""
from datetime import timedelta
from decimal import Decimal

from rest_framework.test import APIClient, APITestCase

from apps.classroom.models import ClassCourse, ClassRoom, ClassStudent
from apps.courses.models import Catalog, Course
from apps.exams.models import ExamSubmission
from apps.exams.resolver import blank_count_of
from apps.questions.models import Question
from apps.users.models import User


class ExamReviewFlowTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_exam", password="pw123456!", role=User.Role.TEACHER)
        cls.student = User.objects.create_user(username="s_exam", password="pw123456!", role=User.Role.STUDENT)
        cls.course = Course.objects.create(name="Java程序设计", teacher=cls.teacher)
        cls.classroom = ClassRoom.objects.create(name="计科测试班", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第一章")
        cls.single = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.SINGLE,
            stem="Java 中 int 占几个字节？",
            options=[{"key": "A", "text": "2"}, {"key": "B", "text": "4"}, {"key": "C", "text": "8"}],
            answer={"key": "B"}, analysis="int 为 4 字节", score=Decimal("5"),
            status=Question.Status.PUBLISHED,
        )
        # 三空填空题：题干含三个占位符
        cls.blank3 = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.BLANK,
            stem="Java 三大特征：____、____、____。",
            answer={"blanks": ["封装", "继承", "多态"]}, analysis="面向对象三大特征",
            score=Decimal("6"), status=Question.Status.PUBLISHED,
        )
        cls.short = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.SHORT,
            stem="请简述面向对象与面向过程的区别",
            answer={"text": "面向对象以对象为基本单位，强调封装继承多态"},
            analysis="面向对象更利于维护与复用", score=Decimal("10"),
            status=Question.Status.PUBLISHED,
        )

    def setUp(self):
        self.teacher_client = APIClient()
        self.teacher_client.force_authenticate(user=self.teacher)
        self.student_client = APIClient()
        self.student_client.force_authenticate(user=self.student)

    def _create_exam(self, **kwargs):
        payload = {
            "course": self.course.id, "classroom": self.classroom.id,
            "name": "期中考试", "duration": 60, "total_score": 100,
        }
        payload.update(kwargs)
        resp = self.teacher_client.post("/api/exams/", payload, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data["data"]["id"]

    def _compose_and_publish(self, exam_id, allow_resubmit=False):
        resp = self.teacher_client.post(
            f"/api/exams/{exam_id}/compose/",
            {
                "mode": "manual",
                "questions": [
                    {"question_id": self.single.id, "score": 2},   # 卷面 2 分（题库 5 分，测折算）
                    {"question_id": self.blank3.id, "score": 3},
                    {"question_id": self.short.id, "score": 10},
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        resp = self.teacher_client.patch(
            f"/api/exams/{exam_id}/",
            {"status": "published", "allow_resubmit": allow_resubmit},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

    def _start_and_submit(self, exam_id):
        resp = self.student_client.post("/api/exam-submissions/start/", {"exam": exam_id}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.data["data"]
        sub_id = data["submission"]["id"]
        answers = {
            str(self.single.id): {"key": "B"},                                     # 对
            str(self.blank3.id): {"blanks": ["封装", "继承", "多态"]},              # 对
            str(self.short.id): {"text": "面向对象以对象为单位，强调封装继承多态"},
        }
        resp = self.student_client.post(
            f"/api/exam-submissions/{sub_id}/submit/", {"answers": answers}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        return sub_id, resp.data["data"]

    # ---- 多空填空 ----

    def test_taking_multi_blank_gets_blank_count(self):
        """答题下发包含空数量（3），且不泄漏答案。"""
        exam_id = self._create_exam()
        self._compose_and_publish(exam_id)
        resp = self.student_client.post("/api/exam-submissions/start/", {"exam": exam_id}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        questions = resp.data["data"]["questions"]
        blank = next(q for q in questions if q["question_id"] == self.blank3.id)
        self.assertEqual(blank["blank_count"], 3)
        self.assertNotIn("answer", blank)
        single = next(q for q in questions if q["question_id"] == self.single.id)
        self.assertNotIn("answer", single)
        self.assertEqual(single["options"][0]["key"], "A")

    def test_blank_count_fallback_to_stem_markers(self):
        """无答案数据时按题干占位符计数。"""
        from types import SimpleNamespace

        q = SimpleNamespace(qtype=Question.QType.BLANK, stem="____、____。", answer={})
        self.assertEqual(blank_count_of(q), 2)

    # ---- 考后即时回看 ----

    def test_review_visible_immediately_after_submit(self):
        """交卷即可回看：客观题答案/解析/得分即时可见；主观题显示正确答案、待批阅、总分隐藏。"""
        exam_id = self._create_exam()
        self._compose_and_publish(exam_id)
        sub_id, submit_data = self._start_and_submit(exam_id)

        # 提交响应：客观题得分立即可见（2+3=5），总分未出
        self.assertEqual(submit_data["objective_score"], Decimal("5"))
        self.assertIsNone(submit_data["total_score"])

        resp = self.student_client.get(f"/api/exam-submissions/{sub_id}/review/")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.data["data"]
        by_id = {q["question_id"]: q for q in data["questions"]}

        single = by_id[self.single.id]
        self.assertEqual(single["is_correct"], True)
        self.assertEqual(single["my_score"], 2.0)  # 按卷面分值折算
        self.assertEqual(single["correct_answer"], {"key": "B"})
        self.assertEqual(single["analysis"], "int 为 4 字节")

        blank = by_id[self.blank3.id]
        self.assertEqual(blank["blank_count"], 3)
        self.assertEqual(blank["my_score"], 3.0)

        short = by_id[self.short.id]
        self.assertTrue(short["pending"])
        self.assertIsNone(short["my_score"])
        self.assertEqual(short["correct_answer"]["text"], "面向对象以对象为基本单位，强调封装继承多态")
        self.assertEqual(short["student_answer"]["text"], "面向对象以对象为单位，强调封装继承多态")

        # 总分未批阅前不可见
        self.assertIsNone(data["submission"]["total_score"])
        self.assertFalse(data["score_released"])

    def test_teacher_grades_then_total_visible(self):
        """教师批改主观题后，学生回看可见逐题得分与总分（无需手动发布）。"""
        exam_id = self._create_exam()
        self._compose_and_publish(exam_id)
        sub_id, _ = self._start_and_submit(exam_id)

        resp = self.teacher_client.post(
            f"/api/exam-submissions/{sub_id}/grade/", {"scores": {str(self.short.id): 8}}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        resp = self.student_client.get(f"/api/exam-submissions/{sub_id}/review/")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.data["data"]
        by_id = {q["question_id"]: q for q in data["questions"]}
        self.assertEqual(by_id[self.short.id]["my_score"], 8.0)
        self.assertFalse(by_id[self.short.id]["pending"])
        self.assertEqual(data["submission"]["total_score"], Decimal("13"))  # 2+3+8

    def test_grade_rejects_out_of_range_and_partial_save(self):
        """批改校验：超过卷面分值拒绝；分批保存允许。"""
        exam_id = self._create_exam()
        self._compose_and_publish(exam_id)
        sub_id, _ = self._start_and_submit(exam_id)
        resp = self.teacher_client.post(
            f"/api/exam-submissions/{sub_id}/grade/", {"scores": {str(self.short.id): 11}}, format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        # 分批：先存 0 分也算已批阅
        resp = self.teacher_client.post(
            f"/api/exam-submissions/{sub_id}/grade/", {"scores": {str(self.short.id): 0}}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        resp = self.student_client.get(f"/api/exam-submissions/{sub_id}/review/")
        self.assertEqual(resp.data["data"]["submission"]["total_score"], Decimal("5"))

    # ---- 教师结束考试后学生仍可见 ----

    def test_exam_still_visible_after_teacher_finishes(self):
        """教师结束考试后，已交卷学生仍能在列表看到该考试并回看答卷。"""
        exam_id = self._create_exam()
        self._compose_and_publish(exam_id)
        sub_id, _ = self._start_and_submit(exam_id)

        resp = self.teacher_client.patch(f"/api/exams/{exam_id}/", {"status": "finished"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)

        resp = self.student_client.get("/api/exams/")
        self.assertEqual(resp.status_code, 200, resp.data)
        rows = resp.data["data"]["results"]
        row = next((r for r in rows if r["id"] == exam_id), None)
        self.assertIsNotNone(row, "教师结束考试后学生列表应仍包含该考试")
        self.assertEqual(row["my_submission"]["status"], "submitted")
        self.assertEqual(row["my_submission"]["objective_score"], Decimal("5"))

        resp = self.student_client.get(f"/api/exam-submissions/{sub_id}/review/")
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_exam_list_my_submission_null_when_not_started(self):
        """未参加时 my_submission 为空。"""
        exam_id = self._create_exam(name="未开始考试")
        self._compose_and_publish(exam_id)
        resp = self.student_client.get("/api/exams/")
        row = next(r for r in resp.data["data"]["results"] if r["id"] == exam_id)
        self.assertIsNone(row["my_submission"])

    # ---- 解析开关 ----

    def test_analysis_hidden_when_disabled(self):
        """关闭「考后看解析」后解析不可见，但答案与得分仍可见。"""
        exam_id = self._create_exam()
        self._compose_and_publish(exam_id)
        resp = self.teacher_client.patch(f"/api/exams/{exam_id}/", {"show_analysis_after": False}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        sub_id, _ = self._start_and_submit(exam_id)
        resp = self.student_client.get(f"/api/exam-submissions/{sub_id}/review/")
        by_id = {q["question_id"]: q for q in resp.data["data"]["questions"]}
        self.assertEqual(by_id[self.single.id]["analysis"], "")
        self.assertEqual(by_id[self.single.id]["correct_answer"], {"key": "B"})
        self.assertEqual(by_id[self.single.id]["my_score"], 2.0)

    # ---- 重交 ----

    def test_resubmit_resets_when_allowed(self):
        """允许重交：再次开始重置答案并重新评分；不允许时拒绝。"""
        exam_id = self._create_exam()
        self._compose_and_publish(exam_id, allow_resubmit=True)
        sub_id, _ = self._start_and_submit(exam_id)
        resp = self.student_client.post("/api/exam-submissions/start/", {"exam": exam_id}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["data"]["submission"]["status"], "in_progress")
        sub = ExamSubmission.objects.get(id=sub_id)
        self.assertEqual(sub.answers, {})
        self.assertIsNone(sub.objective_score)

        exam_id2 = self._create_exam(name="不允许重交")
        self._compose_and_publish(exam_id2)
        self._start_and_submit(exam_id2)
        resp = self.student_client.post("/api/exam-submissions/start/", {"exam": exam_id2}, format="json")
        self.assertEqual(resp.status_code, 400, resp.data)

    # ---- 越权 ----

    def test_review_requires_own_submission(self):
        """他人答卷不可回看。"""
        other = User.objects.create_user(username="s_exam2", password="pw123456!", role=User.Role.STUDENT)
        exam_id = self._create_exam()
        self._compose_and_publish(exam_id)
        sub_id, _ = self._start_and_submit(exam_id)
        client = APIClient()
        client.force_authenticate(user=other)
        resp = client.get(f"/api/exam-submissions/{sub_id}/review/")
        self.assertEqual(resp.status_code, 404, resp.data)


class ExamComposeStateTests(APITestCase):
    """组卷状态流转：发布前必须组卷；组卷后可编辑；发布后只能查看不能再组卷。"""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_exam2", password="pw123456!", role=User.Role.TEACHER)
        cls.course = Course.objects.create(name="Java程序设计", teacher=cls.teacher)
        cls.classroom = ClassRoom.objects.create(name="计科测试班", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第一章")
        cls.single = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.SINGLE,
            stem="Java 中 int 占几个字节？",
            options=[{"key": "A", "text": "2"}, {"key": "B", "text": "4"}],
            answer={"key": "B"}, score=Decimal("5"), status=Question.Status.PUBLISHED,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.teacher)

    def _create_exam(self, **kwargs):
        payload = {"course": self.course.id, "classroom": self.classroom.id, "name": "期中考试", "duration": 60}
        payload.update(kwargs)
        resp = self.client.post("/api/exams/", payload, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data["data"]["id"]

    def _compose(self, exam_id):
        resp = self.client.post(
            f"/api/exams/{exam_id}/compose/",
            {"mode": "manual", "questions": [{"question_id": self.single.id, "score": 5}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data["data"]

    def test_publish_requires_composed_paper(self):
        """未组卷不能发布；组卷后可发布。"""
        exam_id = self._create_exam()
        resp = self.client.patch(f"/api/exams/{exam_id}/", {"status": "published"}, format="json")
        self.assertEqual(resp.status_code, 400, resp.data)
        self._compose(exam_id)
        resp = self.client.patch(f"/api/exams/{exam_id}/", {"status": "published"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_create_with_published_status_rejected(self):
        """创建时直接置为已发布被拒绝（必须先建草稿再组卷）。"""
        resp = self.client.post(
            "/api/exams/",
            {"course": self.course.id, "classroom": self.classroom.id, "name": "直接发布", "status": "published"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_compose_blocked_after_publish(self):
        """发布后不能重新组卷。"""
        exam_id = self._create_exam()
        self._compose(exam_id)
        self.client.patch(f"/api/exams/{exam_id}/", {"status": "published"}, format="json")
        resp = self.client.post(
            f"/api/exams/{exam_id}/compose/",
            {"mode": "manual", "questions": [{"question_id": self.single.id, "score": 5}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_exam_list_exposes_paper_state(self):
        """列表返回 has_paper / question_count，供按钮状态流转。"""
        exam_id = self._create_exam()
        resp = self.client.get("/api/exams/")
        row = next(r for r in resp.data["data"]["results"] if r["id"] == exam_id)
        self.assertFalse(row["has_paper"])
        self.assertEqual(row["question_count"], 0)
        self._compose(exam_id)
        resp = self.client.get("/api/exams/")
        row = next(r for r in resp.data["data"]["results"] if r["id"] == exam_id)
        self.assertTrue(row["has_paper"])
        self.assertEqual(row["question_count"], 1)

    def test_paper_detail_readonly(self):
        """查看试卷（只读）：返回题目清单；未组卷 404。"""
        exam_id = self._create_exam()
        resp = self.client.get(f"/api/exams/{exam_id}/paper/")
        self.assertEqual(resp.status_code, 404, resp.data)
        self._compose(exam_id)
        resp = self.client.get(f"/api/exams/{exam_id}/paper/")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.data["data"]
        self.assertEqual(data["total_score"], "5.0")
        self.assertEqual(len(data["questions"]), 1)
        self.assertEqual(data["questions"][0]["stem"], self.single.stem)
        self.assertEqual(data["questions"][0]["score"], 5)


class ExamTimerAndMonitorTests(APITestCase):
    """考试时间固定（重开不重置）与监控异常次数。"""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_exam3", password="pw123456!", role=User.Role.TEACHER)
        cls.student = User.objects.create_user(username="s_exam3", password="pw123456!", role=User.Role.STUDENT)
        cls.course = Course.objects.create(name="Java程序设计", teacher=cls.teacher)
        cls.classroom = ClassRoom.objects.create(name="计科测试班", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第一章")
        cls.single = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.SINGLE,
            stem="Java 中 int 占几个字节？",
            options=[{"key": "A", "text": "2"}, {"key": "B", "text": "4"}],
            answer={"key": "B"}, score=Decimal("5"), status=Question.Status.PUBLISHED,
        )

    def setUp(self):
        self.teacher_client = APIClient()
        self.teacher_client.force_authenticate(user=self.teacher)
        self.student_client = APIClient()
        self.student_client.force_authenticate(user=self.student)

    def _exam_published(self, duration=60):
        resp = self.teacher_client.post(
            "/api/exams/",
            {"course": self.course.id, "classroom": self.classroom.id, "name": "期中考试", "duration": duration},
            format="json",
        )
        exam_id = resp.data["data"]["id"]
        self.teacher_client.post(
            f"/api/exams/{exam_id}/compose/",
            {"mode": "manual", "questions": [{"question_id": self.single.id, "score": 5}]},
            format="json",
        )
        self.teacher_client.patch(f"/api/exams/{exam_id}/", {"status": "published"}, format="json")
        return exam_id

    def test_remaining_seconds_continues_after_reopen(self):
        """关闭页面后重开：从服务端开始时间续算剩余时间，不重置。"""
        exam_id = self._exam_published(duration=60)
        resp = self.student_client.post("/api/exam-submissions/start/", {"exam": exam_id}, format="json")
        self.assertEqual(resp.data["data"]["remaining_seconds"], 3600)
        sub = ExamSubmission.objects.get(exam_id=exam_id, student=self.student)
        started_at = sub.started_at

        # 模拟已过去 30 分钟（直接改库，避免 sleep）
        sub.started_at = started_at - timedelta(minutes=30)
        sub.save(update_fields=["started_at"])

        resp = self.student_client.post("/api/exam-submissions/start/", {"exam": exam_id}, format="json")
        # 秒级截断允许 1s 误差
        self.assertIn(resp.data["data"]["remaining_seconds"], range(1798, 1801))
        sub.refresh_from_db()
        self.assertEqual(sub.started_at, started_at - timedelta(minutes=30), "重开不应重置开始时间")

    def test_monitor_abnormal_count_and_grading_detail(self):
        """监控展示异常次数；批改明细含全卷回看。"""
        exam_id = self._exam_published()
        resp = self.student_client.post("/api/exam-submissions/start/", {"exam": exam_id}, format="json")
        sub_id = resp.data["data"]["submission"]["id"]

        # 上报两次异常行为
        for action in ("blur", "copy"):
            resp = self.student_client.post(
                "/api/exam-logs/", {"exam": exam_id, "action": action}, format="json",
            )
            self.assertEqual(resp.status_code, 201, resp.data)
        self.student_client.post(
            f"/api/exam-submissions/{sub_id}/submit/",
            {"answers": {str(self.single.id): {"key": "B"}}}, format="json",
        )

        resp = self.teacher_client.get(f"/api/exams/{exam_id}/monitor/")
        row = next(r for r in resp.data["data"] if r["id"] == sub_id)
        self.assertEqual(row["abnormal_count"], 2)
        self.assertTrue(row["abnormal"])
        self.assertFalse(row["has_subjective"])

        resp = self.teacher_client.get(f"/api/exam-submissions/{sub_id}/grading-detail/")
        self.assertEqual(resp.status_code, 200, resp.data)
        review = resp.data["data"]["answer_review"]
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]["my_score"], 5.0)
        self.assertTrue(review[0]["is_objective"])


class ExamShuffleAndSaveTests(APITestCase):
    """乱序模式（类内题目乱序 / 选项乱序 key 重映射）、乱序固化、保存答案。"""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_exam4", password="pw123456!", role=User.Role.TEACHER)
        cls.student = User.objects.create_user(username="s_exam4", password="pw123456!", role=User.Role.STUDENT)
        cls.course = Course.objects.create(name="Java程序设计", teacher=cls.teacher)
        cls.classroom = ClassRoom.objects.create(name="计科测试班", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第一章")
        # 五类题型各一题（选项乱序测试用 4 选项单选）
        cls.single = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.SINGLE,
            stem="int 占几个字节？",
            options=[{"key": "A", "text": "2"}, {"key": "B", "text": "4"}, {"key": "C", "text": "8"}, {"key": "D", "text": "16"}],
            answer={"key": "C"}, score=Decimal("5"), status=Question.Status.PUBLISHED,
        )
        cls.multi = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.MULTI,
            stem="以下哪些是 Java 基本类型？",
            options=[{"key": "A", "text": "int"}, {"key": "B", "text": "String"}, {"key": "C", "text": "double"}],
            answer={"keys": ["A", "C"]}, score=Decimal("5"), status=Question.Status.PUBLISHED,
        )
        cls.judge = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.JUDGE,
            stem="Java 是编译型语言。",
            options=[{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}],
            answer={"key": "A"}, score=Decimal("5"), status=Question.Status.PUBLISHED,
        )
        cls.blank = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.BLANK,
            stem="Java 三大特征：____、____。",
            answer={"blanks": ["封装", "继承"]}, score=Decimal("4"), status=Question.Status.PUBLISHED,
        )
        cls.short = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.SHORT,
            stem="简述面向对象特点",
            answer={"text": "封装、继承、多态"}, score=Decimal("10"), status=Question.Status.PUBLISHED,
        )

    def setUp(self):
        self.teacher_client = APIClient()
        self.teacher_client.force_authenticate(user=self.teacher)
        self.student_client = APIClient()
        self.student_client.force_authenticate(user=self.student)

    def _create_exam(self, **kwargs):
        payload = {"course": self.course.id, "classroom": self.classroom.id, "name": "乱序考试", "duration": 60}
        payload.update(kwargs)
        resp = self.teacher_client.post("/api/exams/", payload, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data["data"]["id"]

    def _compose_publish(self, exam_id, order=None):
        """手动组卷（默认按 简答→填空→判断→多选→单选 的乱序输入）并发布。"""
        qs = order or [self.short, self.blank, self.judge, self.multi, self.single]
        resp = self.teacher_client.post(
            f"/api/exams/{exam_id}/compose/",
            {"mode": "manual", "questions": [{"question_id": q.id, "score": 5} for q in qs]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        resp = self.teacher_client.patch(f"/api/exams/{exam_id}/", {"status": "published"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)

    def _start(self, exam_id):
        resp = self.student_client.post("/api/exam-submissions/start/", {"exam": exam_id}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data["data"]

    # ---- 题目乱序：类内打乱、类间顺序固定 ----

    def test_question_shuffle_keeps_type_order(self):
        """开启题目乱序：五类题型按 单选→多选→判断→填空→简答 分段，与组卷输入顺序无关。"""
        exam_id = self._create_exam(shuffle_questions=True)
        self._compose_publish(exam_id)  # 组卷顺序刻意打乱
        data = self._start(exam_id)
        seq = [q["qtype"] for q in data["questions"]]
        self.assertEqual(seq, ["single", "multi", "judge", "blank", "short"])
        # 乱序结果已固化到答卷
        sub = ExamSubmission.objects.get(exam_id=exam_id, student=self.student)
        self.assertEqual(sub.question_layout["order"], [q["question_id"] for q in data["questions"]])

    def test_no_shuffle_keeps_compose_order(self):
        """未开启乱序：保持组卷原序。"""
        exam_id = self._create_exam(shuffle_questions=False)
        self._compose_publish(exam_id, order=[self.short, self.single, self.multi])
        data = self._start(exam_id)
        self.assertEqual([q["question_id"] for q in data["questions"]], [self.short.id, self.single.id, self.multi.id])

    def test_layout_frozen_after_start(self):
        """开始考试后题目顺序固化：重复进入/刷新不再重排。"""
        exam_id = self._create_exam(shuffle_questions=True)
        self._compose_publish(exam_id)
        first = [q["question_id"] for q in self._start(exam_id)["questions"]]
        for _ in range(3):
            again = [q["question_id"] for q in self._start(exam_id)["questions"]]
            self.assertEqual(again, first, "重进考试不应重排题目")

    # ---- 选项乱序：内容随机排、标签固定、正确答案跟内容走 ----

    def test_option_shuffle_remaps_correct_answer(self):
        """开启选项乱序：A/B/C/D 标签位置固定、内容随机；
        按内容选（展示 key）判定正确，回看的正确答案 key 与学生所见一致。"""
        exam_id = self._create_exam(shuffle_options=True)
        self._compose_publish(exam_id, order=[self.single])
        data = self._start(exam_id)
        q = data["questions"][0]

        # 展示 key 恒为 A/B/C/D；内容为原始选项的乱排
        self.assertEqual([o["key"] for o in q["options"]], ["A", "B", "C", "D"])
        texts = [o["text"] for o in q["options"]]
        self.assertEqual(sorted(texts), sorted(o["text"] for o in self.single.options))

        sub = ExamSubmission.objects.get(exam_id=exam_id, student=self.student)
        perm = sub.question_layout["options"][str(self.single.id)]
        self.assertEqual(sorted(perm), [0, 1, 2, 3])

        # 原始正确答案 C（内容 "8"）被排到哪个展示位置，其展示 key 即「正确 key」
        original_index = next(i for i, o in enumerate(self.single.options) if o["key"] == "C")
        correct_display_key = chr(ord("A") + perm.index(original_index))
        self.assertEqual(q["options"][ord(correct_display_key) - ord("A")]["text"], "8")

        # 按展示 key 提交：选「正确内容」得满分，选错得 0
        resp = self.student_client.post(
            f"/api/exam-submissions/{sub.id}/submit/",
            {"answers": {str(self.single.id): {"key": correct_display_key}}}, format="json",
        )
        self.assertEqual(resp.data["data"]["objective_score"], Decimal("5"))
        resp = self.student_client.get(f"/api/exam-submissions/{sub.id}/review/")
        review = resp.data["data"]["questions"][0]
        self.assertTrue(review["is_correct"])
        # S4 回看归序：选项/正确答案/学生答案全部回到原题空间
        # （与解析文本按原题顺序书写的口径一致；答题时的展示 key 已 unmap 回原始 key）
        self.assertEqual([o["key"] for o in review["options"]], ["A", "B", "C", "D"])
        self.assertEqual([o["text"] for o in review["options"]], [o["text"] for o in self.single.options])
        self.assertEqual(review["correct_answer"]["key"], "C")
        self.assertEqual(review["student_answer"]["key"], "C")

    def test_option_shuffle_multi_and_judge(self):
        """多选/判断同样支持选项乱序，keys 逐个重映射后判分正确。"""
        exam_id = self._create_exam(shuffle_options=True)
        self._compose_publish(exam_id, order=[self.multi, self.judge])
        data = self._start(exam_id)
        by_id = {q["question_id"]: q for q in data["questions"]}
        sub = ExamSubmission.objects.get(exam_id=exam_id, student=self.student)

        # 多选：原始正确 keys=[A,C]（int / double），按展示 key 提交应判对
        perm_m = sub.question_layout["options"][str(self.multi.id)]
        display_keys = []
        for orig_key in ("A", "C"):
            j = next(i for i, o in enumerate(self.multi.options) if o["key"] == orig_key)
            display_keys.append(chr(ord("A") + perm_m.index(j)))
        # 判断：原始正确 key=A（正确）
        perm_j = sub.question_layout["options"][str(self.judge.id)]
        judge_key = chr(ord("A") + perm_j.index(0))

        resp = self.student_client.post(
            f"/api/exam-submissions/{sub.id}/submit/",
            {"answers": {
                str(self.multi.id): {"keys": display_keys},
                str(self.judge.id): {"key": judge_key},
            }}, format="json",
        )
        self.assertEqual(resp.data["data"]["objective_score"], Decimal("10"))

        # S4 回看归序：多选正确答案/学生答案均 unmap 回原始 key 且排序
        resp = self.student_client.get(f"/api/exam-submissions/{sub.id}/review/")
        by_id = {q["question_id"]: q for q in resp.data["data"]["questions"]}
        q = by_id[self.multi.id]
        self.assertEqual([(o["key"], o["text"]) for o in q["options"]],
                         [("A", "int"), ("B", "String"), ("C", "double")])
        self.assertEqual(q["correct_answer"]["keys"], ["A", "C"])
        self.assertEqual(q["student_answer"]["keys"], ["A", "C"])
        q = by_id[self.judge.id]
        self.assertEqual(q["correct_answer"]["key"], "A")
        self.assertEqual(q["student_answer"]["key"], "A")

    def test_review_restores_original_order_after_unmap(self):
        """S4 回看归序（确定性版）：手工固化非恒等 perm（random.shuffle 有极小概率恒等），
        学生按展示 key 作答且多选 keys 故意乱序提交，回看时选项顺序、正确答案、
        学生答案全部 unmap 回原始 key 空间并排序，判分不受影响。"""
        exam_id = self._create_exam(shuffle_options=True)
        self._compose_publish(exam_id, order=[self.single, self.multi, self.judge])
        data = self._start(exam_id)
        sub = ExamSubmission.objects.get(exam_id=exam_id, student=self.student)

        # 固定非恒等排列：perm[i] = 展示位置 i 的原始 options 下标
        perms = {
            str(self.single.id): [2, 0, 3, 1],  # 原始 C/D/A/B → 展示 A/B/C/D
            str(self.multi.id): [1, 2, 0],      # 原始 B/C/A → 展示 A/B/C
            str(self.judge.id): [1, 0],         # 原始 B/A → 展示 A/B
        }
        sub.question_layout = {
            "order": [q["question_id"] for q in data["questions"]],
            "options": perms,
        }
        sub.save(update_fields=["question_layout"])

        # 原始正确 → 展示 key：single 原始 C(下标2)在 perm 位置0 → "A"
        # multi 原始 [A(0),C(2)] → perm.index(0)=2 → "C"；perm.index(2)=1 → "B"
        # judge 原始 A(0) → perm.index(0)=1 → "B"
        resp = self.student_client.post(
            f"/api/exam-submissions/{sub.id}/submit/",
            {"answers": {
                str(self.single.id): {"key": "A"},
                str(self.multi.id): {"keys": ["C", "B"]},  # 乱序提交（模拟点击顺序）
                str(self.judge.id): {"key": "B"},
            }}, format="json",
        )
        self.assertEqual(resp.data["data"]["objective_score"], Decimal("15"))

        resp = self.student_client.get(f"/api/exam-submissions/{sub.id}/review/")
        self.assertEqual(resp.status_code, 200, resp.data)
        payload = resp.data["data"]
        self.assertTrue(payload["options_shuffled"])
        by_id = {q["question_id"]: q for q in payload["questions"]}

        # single：回看选项为原始顺序（key/text 原样），正确与学生答案均归序为 C
        q = by_id[self.single.id]
        self.assertEqual([(o["key"], o["text"]) for o in q["options"]],
                         [("A", "2"), ("B", "4"), ("C", "8"), ("D", "16")])
        self.assertEqual(q["correct_answer"]["key"], "C")
        self.assertEqual(q["student_answer"]["key"], "C")
        self.assertTrue(q["is_correct"])

        # multi：展示 keys [C,B] unmap 回 [A,C]（按提交顺序映射），下发展示排序 [A,C]
        q = by_id[self.multi.id]
        self.assertEqual([(o["key"], o["text"]) for o in q["options"]],
                         [("A", "int"), ("B", "String"), ("C", "double")])
        self.assertEqual(q["correct_answer"]["keys"], ["A", "C"])
        self.assertEqual(q["student_answer"]["keys"], ["A", "C"])
        self.assertTrue(q["is_correct"])

        # judge：原始 key=A
        q = by_id[self.judge.id]
        self.assertEqual(q["correct_answer"]["key"], "A")
        self.assertEqual(q["student_answer"]["key"], "A")
        self.assertTrue(q["is_correct"])

    # ---- 保存答案（不提交） ----

    def test_save_keeps_in_progress_and_restores(self):
        """保存答案：不算分、不提交；重进考试后答案回填，可继续作答后交卷。"""
        exam_id = self._create_exam()
        self._compose_publish(exam_id, order=[self.single, self.short])
        data = self._start(exam_id)
        sub_id = data["submission"]["id"]

        payload = {"answers": {str(self.single.id): {"key": "C"}, str(self.short.id): {"text": "封装继承多态"}}}
        resp = self.student_client.post(f"/api/exam-submissions/{sub_id}/save/", payload, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIsNone(resp.data["data"]["objective_score"], "保存不应出分")
        self.assertIsNone(resp.data["data"]["total_score"])
        self.assertIsNotNone(resp.data["data"]["saved_at"])

        sub = ExamSubmission.objects.get(id=sub_id)
        self.assertEqual(sub.status, "in_progress", "保存不应改变状态")
        self.assertIsNotNone(sub.saved_at)

        # 重进（模拟刷新）：已保存答案随 submission 返回，题目顺序不变
        data2 = self._start(exam_id)
        self.assertEqual(data2["submission"]["answers"][str(self.single.id)], {"key": "C"})
        self.assertEqual(
            [q["question_id"] for q in data2["questions"]],
            [q["question_id"] for q in data["questions"]],
        )

        # 继续作答并交卷：保存的答案参与评分
        resp = self.student_client.post(
            f"/api/exam-submissions/{sub_id}/submit/",
            {"answers": payload["answers"]}, format="json",
        )
        self.assertEqual(resp.data["data"]["objective_score"], Decimal("5"))

    def test_save_rejected_after_submit_or_timeout(self):
        """交卷后不能再保存。"""
        exam_id = self._create_exam()
        self._compose_publish(exam_id, order=[self.single])
        sub_id = self._start(exam_id)["submission"]["id"]
        self.student_client.post(
            f"/api/exam-submissions/{sub_id}/submit/", {"answers": {str(self.single.id): {"key": "B"}}}, format="json",
        )
        resp = self.student_client.post(
            f"/api/exam-submissions/{sub_id}/save/", {"answers": {}}, format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_save_rejected_when_time_up(self):
        """超过截止时间后保存被拒（应直接交卷）。"""
        from django.utils import timezone as tz

        exam_id = self._create_exam(duration=30)
        self._compose_publish(exam_id, order=[self.single])
        sub_id = self._start(exam_id)["submission"]["id"]
        sub = ExamSubmission.objects.get(id=sub_id)
        sub.started_at = tz.now() - timedelta(minutes=31)
        sub.save(update_fields=["started_at"])
        resp = self.student_client.post(
            f"/api/exam-submissions/{sub_id}/save/", {"answers": {}}, format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_save_requires_student(self):
        """教师不能调用保存接口。"""
        exam_id = self._create_exam()
        self._compose_publish(exam_id, order=[self.single])
        sub_id = self._start(exam_id)["submission"]["id"]
        resp = self.teacher_client.post(
            f"/api/exam-submissions/{sub_id}/save/", {"answers": {}}, format="json",
        )
        self.assertEqual(resp.status_code, 403, resp.data)


class ExamStatsTests(APITestCase):
    """考试统计接口（需求 T-E-07）：总览/分段/逐题/排名/权限。"""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_exam5", password="pw123456!", role=User.Role.TEACHER)
        cls.other_teacher = User.objects.create_user(username="t_exam5b", password="pw123456!", role=User.Role.TEACHER)
        cls.s1 = User.objects.create_user(username="s_exam5a", password="pw123456!", role=User.Role.STUDENT, real_name="张三")
        cls.s2 = User.objects.create_user(username="s_exam5b", password="pw123456!", role=User.Role.STUDENT, real_name="李四")
        cls.s3 = User.objects.create_user(username="s_exam5c", password="pw123456!", role=User.Role.STUDENT, real_name="王五")
        cls.course = Course.objects.create(name="Java程序设计", teacher=cls.teacher)
        cls.classroom = ClassRoom.objects.create(name="计科测试班", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        for s in (cls.s1, cls.s2, cls.s3):
            ClassStudent.objects.create(classroom=cls.classroom, student=s)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第一章")
        cls.single = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.SINGLE,
            stem="int 占几个字节？",
            options=[{"key": "A", "text": "2"}, {"key": "B", "text": "4"}, {"key": "C", "text": "8"}],
            answer={"key": "C"}, score=Decimal("5"), status=Question.Status.PUBLISHED,
        )
        cls.multi = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.MULTI,
            stem="以下哪些是 Java 基本类型？",
            options=[{"key": "A", "text": "int"}, {"key": "B", "text": "String"}, {"key": "C", "text": "double"}],
            answer={"keys": ["A", "C"]}, score=Decimal("5"), status=Question.Status.PUBLISHED,
        )

    def setUp(self):
        self.teacher_client = APIClient()
        self.teacher_client.force_authenticate(user=self.teacher)
        self.other_client = APIClient()
        self.other_client.force_authenticate(user=self.other_teacher)
        self.student_client = APIClient()
        self.student_client.force_authenticate(user=self.s1)

    def _exam_with_two_students(self, shuffle_options=False):
        """组卷发布 → 张三全对（10 分）、李四单选错+多选只选 A（0 分），王五缺考。

        选项乱序开启时按展示选项文本反查展示 key 提交（与学生真实作答一致）。
        """
        resp = self.teacher_client.post(
            "/api/exams/",
            {"course": self.course.id, "classroom": self.classroom.id, "name": "统计考试",
             "duration": 60, "shuffle_options": shuffle_options},
            format="json",
        )
        exam_id = resp.data["data"]["id"]
        self.teacher_client.post(
            f"/api/exams/{exam_id}/compose/",
            {"mode": "manual", "questions": [
                {"question_id": self.single.id, "score": 5},
                {"question_id": self.multi.id, "score": 5},
            ]},
            format="json",
        )
        self.teacher_client.patch(f"/api/exams/{exam_id}/", {"status": "published"}, format="json")

        def display_keys(data):
            """按展示选项文本反查展示 key：正确项 8、错误项 2、多选 int/double。"""
            by_id = {q["question_id"]: q for q in data["questions"]}

            def find_key(q, text):
                return next(o["key"] for o in q["options"] if o["text"] == text)

            return (
                find_key(by_id[self.single.id], "8"),
                find_key(by_id[self.single.id], "2"),
                find_key(by_id[self.multi.id], "int"),
                find_key(by_id[self.multi.id], "double"),
            )

        # 张三：全对
        c1 = APIClient(); c1.force_authenticate(user=self.s1)
        data = c1.post("/api/exam-submissions/start/", {"exam": exam_id}, format="json").data["data"]
        sc, sw, mi, md = display_keys(data)
        c1.post(f"/api/exam-submissions/{data['submission']['id']}/submit/",
                {"answers": {str(self.single.id): {"key": sc}, str(self.multi.id): {"keys": [mi, md]}}},
                format="json")
        # 李四：单选错（选 2）、多选只选 int（部分对不得分）
        c2 = APIClient(); c2.force_authenticate(user=self.s2)
        data = c2.post("/api/exam-submissions/start/", {"exam": exam_id}, format="json").data["data"]
        sc, sw, mi, md = display_keys(data)
        c2.post(f"/api/exam-submissions/{data['submission']['id']}/submit/",
                {"answers": {str(self.single.id): {"key": sw}, str(self.multi.id): {"keys": [mi]}}},
                format="json")
        return exam_id

    def test_stats_overview_and_rankings(self):
        """总览：应考 3 / 交卷 2 / 缺考 1；排名张三 1、李四 2；均分 5。"""
        exam_id = self._exam_with_two_students()
        resp = self.teacher_client.get(f"/api/exams/{exam_id}/stats/")
        self.assertEqual(resp.status_code, 200, resp.data)
        d = resp.data["data"]

        ov = d["overview"]
        self.assertEqual(ov["student_count"], 3)
        self.assertEqual(ov["submitted"], 2)
        self.assertEqual(ov["absent"], 1)
        self.assertEqual(ov["avg_total"], 5.0)
        self.assertEqual(ov["max_total"], 10.0)
        self.assertEqual(ov["min_total"], 0.0)
        # 及格线 10×60%=6：仅张三及格；优秀线 8.5：张三优秀
        self.assertEqual(ov["pass_rate"], 50.0)
        self.assertEqual(ov["excellent_rate"], 50.0)

        rows = d["rankings"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["student_name"], "张三")
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[0]["total_score"], 10.0)
        self.assertEqual(rows[1]["student_name"], "李四")
        self.assertEqual(rows[1]["rank"], 2)
        self.assertEqual(rows[1]["total_score"], 0.0)
        # 王五缺考排最后，无排名无分数
        self.assertEqual(rows[2]["student_name"], "王五")
        self.assertEqual(rows[2]["status"], "absent")
        self.assertIsNone(rows[2]["rank"])
        self.assertIsNone(rows[2]["total_score"])

    def test_stats_question_and_distribution(self):
        """逐题统计：单选正确率 50%、多选正确率 50%（部分对不得分）；
        选项分布按原始 key 空间计数；总分分段 90-100 1 人、60 以下 1 人。"""
        exam_id = self._exam_with_two_students()
        d = self.teacher_client.get(f"/api/exams/{exam_id}/stats/").data["data"]

        qs = {q["question_id"]: q for q in d["question_stats"]}
        single = qs[self.single.id]
        multi = qs[self.multi.id]
        # 单选：张三对、李四错 → 正确率 50%，平均分 2.5
        self.assertEqual(single["correct_rate"], 50.0)
        self.assertEqual(single["avg_score"], 2.5)
        self.assertEqual(single["unanswered"], 0)
        # 选项分布：A 1 人（李四）、C 1 人（张三）
        counts = {o["key"]: o["count"] for o in single["options"]}
        self.assertEqual(counts, {"A": 1, "B": 0, "C": 1})
        self.assertTrue(next(o for o in single["options"] if o["key"] == "C")["is_correct"])
        # 多选：张三全对、李四只选 A（不得分）→ 正确率 50%
        self.assertEqual(multi["correct_rate"], 50.0)
        self.assertEqual(multi["avg_score"], 2.5)

        dist = {item["range"]: item["count"] for item in d["score_distribution"]}
        # 总分 10：李四 0 分 → 60 以下；张三 10 分（100%）→ 90-100
        self.assertEqual(dist["60 以下"], 1)
        self.assertEqual(dist["90-100"], 1)
        self.assertEqual(dist["80-89"], 0)

    def test_stats_with_option_shuffle_unmaps_counts(self):
        """开启选项乱序后，选项分布仍按原始 key 空间统计（unmap 回原题）。"""
        exam_id = self._exam_with_two_students(shuffle_options=True)
        d = self.teacher_client.get(f"/api/exams/{exam_id}/stats/").data["data"]

        qs = {q["question_id"]: q for q in d["question_stats"]}
        single = qs[self.single.id]
        counts = {o["key"]: o["count"] for o in single["options"]}
        # 不管乱序结果如何，A（李四所选）与 C（张三所选）各 1 人
        self.assertEqual(counts.get("A"), 1)
        self.assertEqual(counts.get("C"), 1)
        self.assertEqual(single["correct_rate"], 50.0)

    def test_stats_same_score_same_rank(self):
        """同分同名次：两人均 10 分 → 并列第 1。"""
        resp = self.teacher_client.post(
            "/api/exams/",
            {"course": self.course.id, "classroom": self.classroom.id, "name": "同分考试", "duration": 60},
            format="json",
        )
        exam_id = resp.data["data"]["id"]
        self.teacher_client.post(
            f"/api/exams/{exam_id}/compose/",
            {"mode": "manual", "questions": [{"question_id": self.single.id, "score": 5}]},
            format="json",
        )
        self.teacher_client.patch(f"/api/exams/{exam_id}/", {"status": "published"}, format="json")
        for s in (self.s1, self.s2):
            c = APIClient(); c.force_authenticate(user=s)
            data = c.post("/api/exam-submissions/start/", {"exam": exam_id}, format="json").data["data"]
            c.post(f"/api/exam-submissions/{data['submission']['id']}/submit/",
                   {"answers": {str(self.single.id): {"key": "C"}}}, format="json")

        rows = self.teacher_client.get(f"/api/exams/{exam_id}/stats/").data["data"]["rankings"]
        self.assertEqual([r["rank"] for r in rows[:2]], [1, 1])

    def test_stats_permission(self):
        """权限：仅本班授课教师可查看；其他教师 404，学生 403。"""
        exam_id = self._exam_with_two_students()
        self.assertEqual(self.other_client.get(f"/api/exams/{exam_id}/stats/").status_code, 404)
        self.assertEqual(self.student_client.get(f"/api/exams/{exam_id}/stats/").status_code, 403)
