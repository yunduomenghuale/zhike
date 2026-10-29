"""P4 流转（毕业 + 统计口径）测试。

六项准出逐条对应：
1. 毕业预览名单准确（不含已转走学生，X-29）→ GraduatePreviewTests
2. 整班毕业后状态一致 → GraduateClassTests
3. 毕业生权限（看历史/不可提交）→ GraduatedAccessTests
4. 转班（旧课消失、旧班成绩可查）→ TransferVisibilityTests
5. 统计分母（毕业/休学不计入）→ StatsDenominatorTests
6. 延期毕业（先转班再毕业，不误伤）→ DeferredGraduationTests

另覆盖撤销毕业与审计（方案 §5.5）。
"""

from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient

from apps.analytics.export import build_class_export_workbook
from apps.analytics.services import build_class_stats
from apps.classroom.models import ClassRoom, ClassStudent
from apps.classroom import graduation, services
from apps.courses.models import Catalog, Course, TeachingVideo
from apps.exams.models import Exam, ExamSubmission, Paper
from apps.homework.models import Homework
from apps.labs.models import Lab, LabTemplate
from apps.platform_admin.models import AdminActionLog
from apps.users.models import User


class GraduationTestBase(TestCase):
    """夹具：一个「到期班」（2020 级 4 年制，2024 应毕业）+ 五种学籍/关系状态的学生。"""
    def setUp(self):
        self.admin = User.objects.create_user(
            username="adm_g", password="pw123456!", role=User.Role.ADMIN
        )
        self.teacher = User.objects.create_user(
            username="t_g", password="pw123456!", role=User.Role.TEACHER, real_name="毕业教师"
        )
        # enrollment 2020 + 4 年 = 2024 应毕业（早于当前年份，year_reached=True）
        self.classroom = ClassRoom.objects.create(
            name="计科2020级", code="JSJ-2020", teacher=self.teacher,
            enrollment_year=2020, duration_years=4,
        )
        self.class_next = ClassRoom.objects.create(
            name="计科2021级", code="JSJ-2021", teacher=self.teacher,
            enrollment_year=2021, duration_years=4,
        )
        self.course = Course.objects.create(name="毕业课程", teacher=self.teacher)
        self.classroom.courses.add(self.course)
        # 下一届班挂另一门课：转班生应看到新课、看不到旧课（两个班课程不重叠，
        # 否则「旧课消失」会被新课掩盖）
        self.course_next = Course.objects.create(name="进阶课程", teacher=self.teacher)
        self.class_next.courses.add(self.course_next)
        self.catalog = Catalog.objects.create(
            course=self.course, title="第一章", order=1, is_published=True
        )

        # s1/s2：正常在读（应被毕业）
        self.s1 = self._student("s_g1", "学生一")
        self.s2 = self._student("s_g2", "学生二")
        services.assign_students(self.classroom, [self.s1, self.s2], operator=self.admin)
        # s3：已转走到下一届（绝不能被原班毕业，X-29）
        self.s3 = self._student("s_g3", "转走生")
        services.assign_students(self.classroom, [self.s3], operator=self.admin)
        services.transfer_students(self.class_next, [self.s3], operator=self.admin)
        # s4：休学（排除）
        self.s4 = self._student("s_g4", "休学生")
        services.assign_students(self.classroom, [self.s4], operator=self.admin)
        services.change_edu_status(self.s4, User.EduStatus.SUSPENDED, operator=self.admin, note="休学")
        # s5：已提前毕业（排除，不重复处理）
        self.s5 = self._student("s_g5", "提前毕业")
        services.assign_students(self.classroom, [self.s5], operator=self.admin)
        services.change_edu_status(self.s5, User.EduStatus.GRADUATED, operator=self.admin, note="提前毕业")

    def _student(self, username, name):
        return User.objects.create_user(
            username=username, password="pw123456!", role=User.Role.STUDENT, real_name=name
        )

    @staticmethod
    def _rows(payload):
        """列表接口统一取行：DRF 分页时是 {results:[...]}，未分页是 [...]。"""
        if isinstance(payload, dict):
            return payload.get("results", [])
        return payload


# ---------------------------------------------------------------------------
# 准出 1：毕业预览名单准确（X-29）
# ---------------------------------------------------------------------------
class GraduatePreviewTests(GraduationTestBase):
    def test_preview_lists_only_occupied_enrolled_students(self):
        data = graduation.graduate_preview(self.classroom)
        self.assertEqual(
            sorted(u["username"] for u in data["students"]), ["s_g1", "s_g2"]
        )
        self.assertEqual(data["student_count"], 2)
        self.assertTrue(data["classroom"]["year_reached"])

    def test_preview_excludes_transferred_but_shows_them(self):
        """转走的学生不被毕业，且必须在预览里可见——否则管理员无法确认排除正确。"""
        data = graduation.graduate_preview(self.classroom)
        self.assertNotIn("s_g3", [u["username"] for u in data["students"]])
        self.assertEqual([t["username"] for t in data["transferred"]], ["s_g3"])
        self.assertEqual(data["transferred"][0]["learn_status"], ClassStudent.LearnStatus.TRANSFERRED)

    def test_preview_lists_blockers(self):
        exam = self._published_exam()
        ExamSubmission.objects.create(
            exam=exam, student=self.s1, status=ExamSubmission.Status.IN_PROGRESS,
            started_at=self._now(),
        )
        Homework.objects.create(
            classroom=self.classroom, course=self.course, title="未截止作业",
            mode=Homework.Mode.ATTACHMENT, status=Homework.Status.PUBLISHED,
            total_score=Decimal("100"), deadline=self._now_plus(days=1),
        )
        data = graduation.graduate_preview(self.classroom)
        self.assertEqual(len(data["blockers"]["in_progress_exams"]), 1)
        self.assertEqual(data["blockers"]["in_progress_exams"][0]["student"], "学生一")
        self.assertEqual(len(data["blockers"]["open_homeworks"]), 1)

    def test_preview_does_not_write(self):
        before = (self.classroom.status, self.s1.edu_status)
        graduation.graduate_preview(self.classroom)
        self.classroom.refresh_from_db()
        self.s1.refresh_from_db()
        self.assertEqual((self.classroom.status, self.s1.edu_status), before)

    # -- 夹具辅助 --
    def _now(self):
        from django.utils import timezone
        return timezone.now()

    def _now_plus(self, **kw):
        from django.utils import timezone
        return timezone.now() + timezone.timedelta(**kw)

    def _published_exam(self):
        exam = Exam.objects.create(
            name="在途考试", course=self.course, classroom=self.classroom,
            status=Exam.Status.PUBLISHED, duration=60,
        )
        Paper.objects.create(
            exam=exam, course=self.course, student=None,
            question_items=[], total_score=Decimal("100"),
        )
        return exam


# ---------------------------------------------------------------------------
# 准出 2：整班毕业后状态一致
# ---------------------------------------------------------------------------
class GraduateClassTests(GraduationTestBase):
    def test_graduate_sets_class_and_students_consistently(self):
        result = graduation.graduate_class(self.classroom, operator=self.admin)
        self.assertEqual(result["graduated_count"], 2)

        self.classroom.refresh_from_db()
        self.assertEqual(self.classroom.status, ClassRoom.Status.GRADUATED)

        for stu in (self.s1, self.s2):
            stu.refresh_from_db()
            self.assertEqual(stu.edu_status, User.EduStatus.GRADUATED)
            self.assertIsNotNone(stu.status_changed_at)
            self.assertIn("计科2020级", stu.status_note)
            # 班级关系保持 active：毕业生才看得到历史课程与成绩
            rel = ClassStudent.objects.get(classroom=self.classroom, student=stu)
            self.assertEqual(rel.learn_status, ClassStudent.LearnStatus.ACTIVE)

    def test_graduate_excludes_suspended_and_already_graduated(self):
        graduation.graduate_class(self.classroom, operator=self.admin)
        self.s4.refresh_from_db()
        self.s5.refresh_from_db()
        self.assertEqual(self.s4.edu_status, User.EduStatus.SUSPENDED)
        self.assertEqual(self.s5.edu_status, User.EduStatus.GRADUATED)  # 提前毕业的 note 不被覆盖

    def test_graduate_twice_returns_409(self):
        graduation.graduate_class(self.classroom, operator=self.admin)
        with self.assertRaises(graduation.GraduationError) as ctx:
            graduation.graduate_class(self.classroom, operator=self.admin)
        self.assertEqual(ctx.exception.code, 409)

    def test_graduate_class_without_students_returns_400(self):
        empty = ClassRoom.objects.create(
            name="空班", code="KONG-2020", teacher=self.teacher, enrollment_year=2020, duration_years=4
        )
        with self.assertRaises(graduation.GraduationError) as ctx:
            graduation.graduate_class(empty, operator=self.admin)
        self.assertEqual(ctx.exception.code, 400)

    def test_in_progress_exam_blocks_until_forced(self):
        exam = Exam.objects.create(
            name="在途考试", course=self.course, classroom=self.classroom,
            status=Exam.Status.PUBLISHED, duration=60,
        )
        ExamSubmission.objects.create(
            exam=exam, student=self.s1, status=ExamSubmission.Status.IN_PROGRESS,
            started_at=self._now(),
        )
        with self.assertRaises(graduation.GraduationError) as ctx:
            graduation.graduate_class(self.classroom, operator=self.admin)
        self.assertEqual(ctx.exception.code, 409)
        self.assertIn("in_progress_exams", ctx.exception.data)

        result = graduation.graduate_class(self.classroom, operator=self.admin, force=True)
        self.assertEqual(result["graduated_count"], 2)
        self.assertTrue(result["forced"])

    def test_open_homework_blocks_until_forced(self):
        Homework.objects.create(
            classroom=self.classroom, course=self.course, title="未截止作业",
            mode=Homework.Mode.ATTACHMENT, status=Homework.Status.PUBLISHED,
            total_score=Decimal("100"), deadline=self._now_plus(days=1),
        )
        with self.assertRaises(graduation.GraduationError) as ctx:
            graduation.graduate_class(self.classroom, operator=self.admin)
        self.assertEqual(ctx.exception.code, 409)
        self.assertIn("open_homeworks", ctx.exception.data)

    def test_not_due_year_blocks_until_forced(self):
        future = ClassRoom.objects.create(
            name="计科2030级", code="JSJ-2030", teacher=self.teacher,
            enrollment_year=2030, duration_years=4,
        )
        future.courses.add(self.course)
        # 用工位学生：s1 已在「计科2020级」占用，直接入 future 会撞单班约束
        s6 = self._student("s_g6", "未来生")
        services.assign_students(future, [s6], operator=self.admin)
        with self.assertRaises(graduation.GraduationError) as ctx:
            graduation.graduate_class(future, operator=self.admin)
        self.assertEqual(ctx.exception.code, 409)
        self.assertEqual(ctx.exception.data["expected_graduate_year"], 2034)

        graduation.graduate_class(future, operator=self.admin, force=True)
        future.refresh_from_db()
        self.assertEqual(future.status, ClassRoom.Status.GRADUATED)

    def test_graduated_student_keeps_history_relation(self):
        """毕业生关系保持 active 是「看历史」的前提，删了就等于撕档案。"""
        graduation.graduate_class(self.classroom, operator=self.admin)
        self.assertEqual(
            ClassStudent.objects.filter(
                classroom=self.classroom, student=self.s1, learn_status=ClassStudent.LearnStatus.ACTIVE
            ).count(),
            1,
        )

    def test_audit_log_with_snapshot(self):
        graduation.graduate_class(self.classroom, operator=self.admin, note="学位办审核通过")
        log = AdminActionLog.objects.get(action="class_graduate", target_id=self.classroom.id)
        self.assertEqual(log.actor, self.admin)
        self.assertEqual(log.new_value["count"], 2)
        self.assertEqual(sorted(log.new_value["students"]), ["s_g1", "s_g2"])
        self.assertEqual(log.old_value["status"], "active")

    def _now(self):
        from django.utils import timezone
        return timezone.now()

    def _now_plus(self, **kw):
        from django.utils import timezone
        return timezone.now() + timezone.timedelta(**kw)


# ---------------------------------------------------------------------------
# 撤销毕业（方案 §5.5：授位审核退回）
# ---------------------------------------------------------------------------
class RevokeGraduationTests(GraduationTestBase):
    def test_revoke_restores_class_and_students(self):
        graduation.graduate_class(self.classroom, operator=self.admin)
        result = graduation.revoke_graduation(self.classroom, operator=self.admin, note="审核退回")
        self.assertEqual(sorted(result["students"]), ["s_g1", "s_g2"])

        self.classroom.refresh_from_db()
        self.assertEqual(self.classroom.status, ClassRoom.Status.ACTIVE)
        for stu in (self.s1, self.s2):
            stu.refresh_from_db()
            self.assertEqual(stu.edu_status, User.EduStatus.ENROLLED)

    def test_revoke_non_graduated_class_returns_400(self):
        with self.assertRaises(graduation.GraduationError) as ctx:
            graduation.revoke_graduation(self.classroom, operator=self.admin)
        self.assertEqual(ctx.exception.code, 400)

    def test_revoke_does_not_un_graduate_early_graduated_student(self):
        """个别提前毕业的学生（note 是当时单独写的）不能被整班撤销摘掉学位。"""
        graduation.graduate_class(self.classroom, operator=self.admin)
        graduation.revoke_graduation(self.classroom, operator=self.admin)
        self.s5.refresh_from_db()
        self.assertEqual(self.s5.edu_status, User.EduStatus.GRADUATED)
        # 本批的两个确实回滚了
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.edu_status, User.EduStatus.ENROLLED)


# ---------------------------------------------------------------------------
# 个别学籍变更入口（P0 service 的管理端 API，P4 补齐）
# ---------------------------------------------------------------------------
class EduStatusApiTests(GraduationTestBase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_admin_can_change_student_edu_status(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            f"/api/classes/{self.classroom.id}/edu-status/",
            {"student": self.s1.pk, "edu_status": "suspended", "note": "因病休学"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.edu_status, User.EduStatus.SUSPENDED)
        self.assertEqual(self.s1.status_note, "因病休学")
        log = AdminActionLog.objects.filter(
            action="class_member_status", target_id=self.s1.pk
        ).latest("id")
        self.assertEqual(log.new_value["edu_status"], "suspended")

    def test_teacher_cannot_change_edu_status(self):
        self.client.force_authenticate(user=self.teacher)
        resp = self.client.post(
            f"/api/classes/{self.classroom.id}/edu-status/",
            {"student": self.s1.pk, "edu_status": "suspended"}, format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_student_outside_class_rejected(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            f"/api/classes/{self.classroom.id}/edu-status/",
            {"student": self.s3.pk, "edu_status": "suspended"}, format="json",
        )
        # s3 已转走，不在本班占用关系里
        self.assertEqual(resp.status_code, 400)

    def test_invalid_edu_status_rejected(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            f"/api/classes/{self.classroom.id}/edu-status/",
            {"student": self.s1.pk, "edu_status": "flying"}, format="json",
        )
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# 准出 3：毕业生权限（登录/看历史/提交 403/AI 403）
# ---------------------------------------------------------------------------
class GraduatedAccessTests(GraduationTestBase):
    def setUp(self):
        super().setUp()
        graduation.graduate_class(self.classroom, operator=self.admin)
        # graduate_class 从库里重新查学生并落库，内存里的夹具对象不会自动更新；
        # force_authenticate 传的是内存对象（真实请求走 JWT，取到的永远是最新的），
        # 所以这里必须显式刷新，否则测的是「在读学生」的行为。
        self.s1.refresh_from_db()
        self.s4.refresh_from_db()
        self.client = APIClient()
        self.homework = Homework.objects.create(
            classroom=self.classroom, course=self.course, title="历史作业",
            mode=Homework.Mode.ATTACHMENT, status=Homework.Status.PUBLISHED,
            total_score=Decimal("100"),
        )
        self.video = TeachingVideo.objects.create(
            course=self.course, catalog=self.catalog, is_published=True
        )
        self.exam = Exam.objects.create(
            name="毕业考试", course=self.course, classroom=self.classroom,
            status=Exam.Status.PUBLISHED, duration=60,
        )
        Paper.objects.create(
            exam=self.exam, course=self.course, student=None,
            question_items=[], total_score=Decimal("100"),
        )
        self.lab = Lab.objects.create(
            course=self.course, catalog=self.catalog, title="毕业实验",
            status=Lab.Status.PUBLISHED,
            template=LabTemplate.objects.create(code="grad-lab", title="毕业实验模板"),
        )

    # ---- 看得到：登录、课程、视频、进度上报 ----
    def test_graduated_student_can_login(self):
        resp = self.client.post(
            "/api/auth/login/", {"username": "s_g1", "password": "pw123456!"}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn("token", resp.data["data"])

    def test_graduated_student_sees_history_course(self):
        self.client.force_authenticate(user=self.s1)
        resp = self.client.get("/api/courses/")
        self.assertEqual(resp.status_code, 200)
        names = [c["name"] for c in self._rows(resp.data["data"])]
        self.assertIn("毕业课程", names)

    def test_graduated_student_can_report_progress(self):
        """X-31：进度上报对毕业生照常开放，否则播放器断点续播失效=看不了。"""
        self.client.force_authenticate(user=self.s1)
        resp = self.client.post(
            f"/api/videos/{self.video.id}/report-progress/",
            {"last_page": 0, "duration_delta": 30}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

    # ---- 提交类一律 403 ----
    def test_graduated_student_cannot_submit_homework(self):
        self.client.force_authenticate(user=self.s1)
        resp = self.client.post(
            "/api/homework-submissions/",
            {"homework": self.homework.id, "content": "补交"}, format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("已毕业", str(resp.data["message"]))

    def test_graduated_student_cannot_stage_attachments(self):
        self.client.force_authenticate(user=self.s1)
        resp = self.client.post("/api/homework-submissions/attachments/", {}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_graduated_student_cannot_start_exam(self):
        self.client.force_authenticate(user=self.s1)
        resp = self.client.post(
            "/api/exam-submissions/start/", {"exam": self.exam.id}, format="json"
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("已毕业", str(resp.data["message"]))

    def test_graduated_student_cannot_start_lab(self):
        self.client.force_authenticate(user=self.s1)
        resp = self.client.post(
            "/api/lab-submissions/start/", {"lab": self.lab.id}, format="json"
        )
        self.assertEqual(resp.status_code, 403)

    def test_graduated_student_cannot_ask(self):
        self.client.force_authenticate(user=self.s1)
        resp = self.client.post(
            "/api/qa-records/ask/",
            {"course": self.course.id, "question": "毕业了还能问吗"}, format="json",
        )
        self.assertEqual(resp.status_code, 403)
        resp2 = self.client.post(
            "/api/qa-records/ask-stream/",
            {"course": self.course.id, "question": "流式呢"}, format="json",
        )
        self.assertEqual(resp2.status_code, 403)

    # ---- 休学：内容入口也关 ----
    def test_suspended_student_sees_no_courses_or_homework(self):
        self.client.force_authenticate(user=self.s4)
        resp = self.client.get("/api/courses/")
        self.assertEqual(self._rows(resp.data["data"]), [])
        resp = self.client.get("/api/homeworks/")
        self.assertEqual(self._rows(resp.data["data"]), [])

    def test_suspended_student_cannot_report_progress(self):
        self.client.force_authenticate(user=self.s4)
        resp = self.client.post(
            f"/api/videos/{self.video.id}/report-progress/",
            {"last_page": 0, "duration_delta": 30}, format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("休学", str(resp.data["message"]))


# ---------------------------------------------------------------------------
# 考试交卷例外：已开考的答卷必须能交（设计 §5.4）
# ---------------------------------------------------------------------------
class ExamSubmitNotBlockedTests(GraduationTestBase):
    def test_submit_allowed_after_student_graduates_midway(self):
        exam = Exam.objects.create(
            name="进行中考试", course=self.course, classroom=self.classroom,
            status=Exam.Status.PUBLISHED, duration=60,
        )
        Paper.objects.create(
            exam=exam, course=self.course, student=None,
            question_items=[], total_score=Decimal("100"),
        )
        client = APIClient()
        client.force_authenticate(user=self.s1)
        start = client.post("/api/exam-submissions/start/", {"exam": exam.id}, format="json")
        self.assertEqual(start.status_code, 200, start.data)
        submission_id = start.data["data"]["submission"]["id"]

        # 开考后整班毕业（休学当天正在考试的同款场景）
        graduation.graduate_class(self.classroom, operator=self.admin, force=True)
        self.s1.refresh_from_db()

        resp = client.post(
            f"/api/exam-submissions/{submission_id}/submit/",
            {"answers": {}}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_resume_in_progress_allowed_but_new_exam_blocked(self):
        """start 双语义：恢复在途答卷放行（交卷不拦的延伸），开新考试仍 403。"""
        exam = Exam.objects.create(
            name="在途考试", course=self.course, classroom=self.classroom,
            status=Exam.Status.PUBLISHED, duration=60,
        )
        Paper.objects.create(
            exam=exam, course=self.course, student=None,
            question_items=[], total_score=Decimal("100"),
        )
        client = APIClient()
        client.force_authenticate(user=self.s1)
        start = client.post("/api/exam-submissions/start/", {"exam": exam.id}, format="json")
        self.assertEqual(start.status_code, 200, start.data)

        # 另一门没开过考的：毕业后 start 必须 403
        exam_new = Exam.objects.create(
            name="未开考试", course=self.course, classroom=self.classroom,
            status=Exam.Status.PUBLISHED, duration=60,
        )
        Paper.objects.create(
            exam=exam_new, course=self.course, student=None,
            question_items=[], total_score=Decimal("100"),
        )
        graduation.graduate_class(self.classroom, operator=self.admin, force=True)
        self.s1.refresh_from_db()

        # 恢复在途答卷：200（否则答题页打不开，交卷不拦形同虚设）
        resume = client.post("/api/exam-submissions/start/", {"exam": exam.id}, format="json")
        self.assertEqual(resume.status_code, 200, resume.data)
        self.assertEqual(resume.data["data"]["submission"]["status"], "in_progress")

        # 开新考试：403
        blocked = client.post("/api/exam-submissions/start/", {"exam": exam_new.id}, format="json")
        self.assertEqual(blocked.status_code, 403, blocked.data)


# ---------------------------------------------------------------------------
# 准出 4：转班（旧课从列表消失；旧班成绩仍可在「我的考试」查到）
# ---------------------------------------------------------------------------
class TransferVisibilityTests(GraduationTestBase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        # s3 已在 base 里从 classroom 转到 class_next
        self.homework = Homework.objects.create(
            classroom=self.classroom, course=self.course, title="旧班作业",
            mode=Homework.Mode.ATTACHMENT, status=Homework.Status.PUBLISHED,
            total_score=Decimal("100"),
        )
        self.exam = Exam.objects.create(
            name="旧班考试", course=self.course, classroom=self.classroom,
            status=Exam.Status.PUBLISHED, duration=60,
        )
        Paper.objects.create(
            exam=self.exam, course=self.course, student=None,
            question_items=[], total_score=Decimal("100"),
        )

    def test_transferred_student_loses_old_course(self):
        from apps.common.access import courses_for_user
        # 转班生只看到新班的课；旧班的「毕业课程」从列表消失（决策 6）
        self.assertEqual(
            [c.name for c in courses_for_user(self.s3)], ["进阶课程"]
        )

    def test_transferred_student_loses_old_homework_todo(self):
        self.client.force_authenticate(user=self.s3)
        resp = self.client.get("/api/homeworks/")
        self.assertEqual(self._rows(resp.data["data"]), [])

    def test_transferred_student_cannot_submit_old_homework(self):
        self.client.force_authenticate(user=self.s3)
        resp = self.client.post(
            "/api/homework-submissions/",
            {"homework": self.homework.id, "content": "补交旧班作业"}, format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_transferred_student_keeps_old_exam_record(self):
        """旧班成绩仍可在「我的考试」查到：submissions__student 分支不筛班级关系。"""
        self.client.force_authenticate(user=self.s3)
        sub = ExamSubmission.objects.create(
            exam=self.exam, student=self.s3, status=ExamSubmission.Status.SUBMITTED,
            submitted_at=self._now(),
        )
        self.assertIsNotNone(sub)
        resp = self.client.get("/api/exams/")
        names = [e["name"] for e in self._rows(resp.data["data"])]
        self.assertIn("旧班考试", names)

    def _now(self):
        from django.utils import timezone
        return timezone.now()


# ---------------------------------------------------------------------------
# 准出 5：统计分母（毕业/休学学生不计入，完成率随之变化）
# ---------------------------------------------------------------------------
class StatsDenominatorTests(GraduationTestBase):
    def setUp(self):
        super().setUp()
        self.homework = Homework.objects.create(
            classroom=self.classroom, course=self.course, title="唯一作业",
            mode=Homework.Mode.ATTACHMENT, status=Homework.Status.PUBLISHED,
            total_score=Decimal("100"),
        )

    def _submit(self, student):
        from apps.homework.models import HomeworkSubmission
        HomeworkSubmission.objects.create(
            homework=self.homework, student=student, content="已交"
        )

    def test_graduated_student_excluded_from_class_stats(self):
        # 毕业前：2 人在读，1 人已交 → 完成率 50%
        self._submit(self.s1)
        before = build_class_stats(self.classroom, self.course.id)
        self.assertEqual(before["summary"]["student_count"], 2)
        self.assertEqual(before["summary"]["homework_rate"], 50)

        # s2 个别毕业后：分母只剩 s1（已交）→ 完成率 100%
        services.change_edu_status(self.s2, User.EduStatus.GRADUATED, operator=self.admin, note="个别毕业")
        after = build_class_stats(self.classroom, self.course.id)
        self.assertEqual(after["summary"]["student_count"], 1)
        self.assertEqual(after["summary"]["homework_rate"], 100)
        self.assertNotIn("s_g2", [r["username"] for r in after["students"]])

    def test_suspended_student_excluded_from_class_stats(self):
        self._submit(self.s1)
        stats = build_class_stats(self.classroom, self.course.id)
        usernames = [r["username"] for r in stats["students"]]
        # s4 休学、s5 已毕业 → 都不进分母；s1/s2 在读 → 分母 2
        self.assertNotIn("s_g4", usernames)
        self.assertNotIn("s_g5", usernames)
        self.assertEqual(stats["summary"]["student_count"], 2)

    def test_export_excludes_graduated_students(self):
        self._submit(self.s1)
        services.change_edu_status(self.s2, User.EduStatus.GRADUATED, operator=self.admin, note="个别毕业")
        wb = build_class_export_workbook(self.classroom, self.course, None, None)
        sheet = wb["成绩总览"]
        # 表头第 1 列是学号（第 2 列才是姓名）
        usernames = [sheet.cell(row=r, column=1).value for r in range(3, sheet.max_row + 1)]
        self.assertIn("s_g1", usernames)
        self.assertNotIn("s_g2", usernames)

    def test_class_progress_summary_denominator(self):
        from apps.platform_admin.services import class_progress_summary

        self._submit(self.s1)
        before = class_progress_summary(self.classroom)
        self.assertEqual(before["homework_rate"], 50)  # 1/2

        services.change_edu_status(self.s2, User.EduStatus.GRADUATED, operator=self.admin, note="个别毕业")
        after = class_progress_summary(self.classroom)
        self.assertEqual(after["homework_rate"], 100)  # 1/1


# ---------------------------------------------------------------------------
# 准出 6：延期毕业（先转班再毕业，不误伤）
# ---------------------------------------------------------------------------
class DeferredGraduationTests(GraduationTestBase):
    def test_deferred_student_survives_batch_graduation(self):
        """延期学生先转到下一届，原班整班毕业不能把他带上。"""
        services.transfer_students(self.class_next, [self.s1], operator=self.admin)

        preview = graduation.graduate_preview(self.classroom)
        self.assertNotIn("s_g1", [u["username"] for u in preview["students"]])
        self.assertIn("s_g1", [t["username"] for t in preview["transferred"]])

        result = graduation.graduate_class(self.classroom, operator=self.admin)
        self.assertEqual(sorted(result["students"]), ["s_g2"])

        # 延期生在新班仍是在读，学习动作不受影响
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.edu_status, User.EduStatus.ENROLLED)
        homework = Homework.objects.create(
            classroom=self.class_next, course=self.course_next, title="新班作业",
            mode=Homework.Mode.ATTACHMENT, status=Homework.Status.PUBLISHED,
            total_score=Decimal("100"),
        )
        client = APIClient()
        client.force_authenticate(user=self.s1)
        resp = client.post(
            "/api/homework-submissions/",
            {"homework": homework.id, "content": "延期生的作业"}, format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
