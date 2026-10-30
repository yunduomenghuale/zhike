from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.ai.vectorstore import search_chunks
from apps.classroom.models import ClassCourse, ClassRoom, ClassStudent
from apps.classroom.services import ClassServiceError, assign_students
from apps.courses.models import Catalog, Course
from apps.exams.models import Exam, ExamSubmission, Paper
from apps.knowledge.models import KnowledgeChunk, Material
from apps.questions.models import Question, WrongMastery


User = get_user_model()


class PlatformFixtureMixin:
    def setUp(self):
        self.teacher1 = User.objects.create_user(
            username="teacher-one", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.teacher2 = User.objects.create_user(
            username="teacher-two", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.student1 = User.objects.create_user(
            username="student-one", password="StrongPass!123", role=User.Role.STUDENT
        )
        self.student2 = User.objects.create_user(
            username="student-two", password="StrongPass!123", role=User.Role.STUDENT
        )
        self.course1 = Course.objects.create(name="Course 1", teacher=self.teacher1)
        self.course2 = Course.objects.create(name="Course 2", teacher=self.teacher2)
        self.catalog1 = Catalog.objects.create(
            course=self.course1, title="Chapter 1", is_published=True
        )
        self.catalog2 = Catalog.objects.create(
            course=self.course2, title="Chapter 2", is_published=True
        )
        self.class1 = ClassRoom.objects.create(name="Class 1", teacher=self.teacher1)
        self.class2 = ClassRoom.objects.create(name="Class 2", teacher=self.teacher2)
        ClassCourse.objects.create(classroom=self.class1, course=self.course1)
        ClassCourse.objects.create(classroom=self.class2, course=self.course2)
        self.member1 = ClassStudent.objects.create(
            classroom=self.class1, student=self.student1
        )
        self.member2 = ClassStudent.objects.create(
            classroom=self.class2, student=self.student2
        )
        self.question1 = Question.objects.create(
            course=self.course1,
            catalog=self.catalog1,
            qtype=Question.QType.SINGLE,
            stem="Q1",
            options=[{"key": "A", "text": "yes"}, {"key": "B", "text": "no"}],
            answer={"key": "A"},
            status=Question.Status.PUBLISHED,
            creator=self.teacher1,
        )
        self.question2 = Question.objects.create(
            course=self.course2,
            catalog=self.catalog2,
            qtype=Question.QType.SINGLE,
            stem="Q2",
            options=[{"key": "A", "text": "yes"}, {"key": "B", "text": "no"}],
            answer={"key": "A"},
            status=Question.Status.PUBLISHED,
            creator=self.teacher2,
        )

    def login_as(self, user):
        self.client.force_authenticate(user=user)

    def result_ids(self, response):
        return {item["id"] for item in response.data["data"]["results"]}


class AccessControlTests(PlatformFixtureMixin, APITestCase):

    def test_wrong_question_mastery_can_be_marked_and_unmarked(self):
        self.login_as(self.student1)

        marked = self.client.post(
            "/api/wrong-mastery/",
            {"question": self.question1.id},
            format="json",
        )

        self.assertEqual(marked.status_code, 200)
        self.assertTrue(marked.data["data"]["mastered"])
        self.assertTrue(
            WrongMastery.objects.filter(
                student=self.student1,
                question=self.question1,
                removed=False,
            ).exists()
        )

        unmarked = self.client.post(
            "/api/wrong-mastery/",
            {"question": self.question1.id},
            format="json",
        )

        self.assertEqual(unmarked.status_code, 200)
        self.assertFalse(unmarked.data["data"]["mastered"])
        self.assertFalse(
            WrongMastery.objects.filter(
                student=self.student1,
                question=self.question1,
            ).exists()
        )

    def test_invite_join_endpoint_is_gone(self):
        """邀请码入班已下线（方案 §4.4）：路由保留但返回 410，且不产生任何班级关系。

        保留路由而不是删掉，是为了让老客户端 / 收藏的旧链接拿到可读文案而不是 404。
        """
        self.student1.real_name = "Student One"
        self.student1.save(update_fields=["real_name"])
        self.login_as(self.student1)

        resp = self.client.post(
            "/api/classes/join/",
            {"invite_code": self.class2.invite_code},
            format="json",
        )
        self.assertEqual(resp.status_code, 410, resp.data)
        self.assertFalse(
            ClassStudent.objects.filter(classroom=self.class2, student=self.student1).exists()
        )

    def test_single_class_rule_enforced_by_service(self):
        """单班规则：已在 A 班的学生被分配到 B 班必须抛 409，且不产生第二条占用。

        入班只有 services.assign_students 一个写入口，规则在这里测；
        接口层（add-student / add-students-batch）只是把 409 透出来。
        """
        with self.assertRaises(ClassServiceError) as ctx:
            assign_students(self.class2, [self.student1])

        self.assertEqual(ctx.exception.code, 409)
        self.assertIn(self.class1.name, ctx.exception.detail)
        self.assertFalse(
            ClassStudent.objects.filter(
                classroom=self.class2,
                student=self.student1,
                learn_status__in=ClassStudent.OCCUPYING_STATUSES,
            ).exists()
        )

    def test_class_roster_writes_are_admin_only(self):
        """入班 / 加人是组织动作：教师调用得 403，管理员调用才进业务校验。

        同一接口上验两层：外层权限（IsPlatformAdmin）+ 内层资料完整度门禁（400）。
        """
        self.login_as(self.teacher1)
        denied = self.client.post(
            f"/api/classes/{self.class1.id}/add-student/",
            {"username": self.student2.username},
            format="json",
        )
        self.assertEqual(denied.status_code, 403, denied.data)

        admin = User.objects.create_user(
            username="p_admin_roster", password="pw123456!", role=User.Role.ADMIN
        )
        self.login_as(admin)
        # student2 未填姓名 → 管理员也加不进，且不落库
        incomplete = self.client.post(
            f"/api/classes/{self.class1.id}/add-student/",
            {"username": self.student2.username},
            format="json",
        )
        self.assertEqual(incomplete.status_code, 400, incomplete.data)
        self.assertFalse(
            ClassStudent.objects.filter(
                classroom=self.class1, student=self.student2
            ).exists()
        )

    def test_student_only_sees_enrolled_courses_and_questions(self):
        self.login_as(self.student1)

        courses = self.client.get("/api/courses/")
        questions = self.client.get("/api/questions/")

        self.assertEqual(courses.status_code, 200)
        self.assertEqual(self.result_ids(courses), {self.course1.id})
        self.assertEqual(self.result_ids(questions), {self.question1.id})

    def test_student_cannot_enumerate_other_class_members(self):
        self.login_as(self.student1)

        response = self.client.get("/api/class-students/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.result_ids(response), {self.member1.id})

    def test_teacher_cannot_modify_another_teachers_catalog(self):
        self.login_as(self.teacher1)

        response = self.client.patch(
            f"/api/catalogs/{self.catalog2.id}/", {"title": "stolen"}, format="json"
        )

        self.assertEqual(response.status_code, 404)
        self.catalog2.refresh_from_db()
        self.assertEqual(self.catalog2.title, "Chapter 2")

    def test_material_lists_respect_course_and_class_scope(self):
        global_material = Material.objects.create(
            course=self.course1, file_name="global.txt", qa_open=True
        )
        own_class_material = Material.objects.create(
            course=self.course1,
            classroom=self.class1,
            file_name="own.txt",
            qa_open=True,
        )
        other_material = Material.objects.create(
            course=self.course2,
            classroom=self.class2,
            file_name="other.txt",
            qa_open=True,
        )
        self.login_as(self.student1)

        response = self.client.get("/api/materials/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.result_ids(response), {global_material.id, own_class_material.id}
        )
        self.assertNotIn(other_material.id, self.result_ids(response))

    def test_student_rag_search_excludes_closed_and_other_class_materials(self):
        open_material = Material.objects.create(
            course=self.course1, classroom=self.class1, file_name="open", qa_open=True
        )
        closed_material = Material.objects.create(
            course=self.course1, classroom=self.class1, file_name="closed", qa_open=False
        )
        other_class = ClassRoom.objects.create(name="Other class", teacher=self.teacher1)
        ClassCourse.objects.create(classroom=other_class, course=self.course1)
        other_material = Material.objects.create(
            course=self.course1, classroom=other_class, file_name="other", qa_open=True
        )
        visible = KnowledgeChunk.objects.create(
            material=open_material, course=self.course1, content="visible", embedding=[1.0, 0.0]
        )
        KnowledgeChunk.objects.create(
            material=closed_material, course=self.course1, content="closed", embedding=[1.0, 0.0]
        )
        KnowledgeChunk.objects.create(
            material=other_material, course=self.course1, content="other", embedding=[1.0, 0.0]
        )

        results = search_chunks(
            self.course1.id,
            [1.0, 0.0],
            student_access=True,
            classroom_ids=[self.class1.id],
        )

        self.assertEqual([chunk.id for chunk, _ in results], [visible.id])


class ExamFlowTests(PlatformFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.exam = Exam.objects.create(
            course=self.course1,
            classroom=self.class1,
            name="Published exam",
            status=Exam.Status.PUBLISHED,
            start_at=now - timedelta(minutes=5),
            end_at=now + timedelta(hours=1),
            duration=30,
        )
        self.paper = Paper.objects.create(
            course=self.course1,
            exam=self.exam,
            question_items=[{"question_id": self.question1.id, "score": 5, "order": 0}],
            total_score=5,
        )
        self.other_exam = Exam.objects.create(
            course=self.course2,
            classroom=self.class2,
            name="Other exam",
            status=Exam.Status.PUBLISHED,
            start_at=now - timedelta(minutes=5),
            end_at=now + timedelta(hours=1),
        )

    def test_only_enrolled_student_can_start_published_exam(self):
        self.login_as(self.student1)
        denied = self.client.post(
            "/api/exam-submissions/start/", {"exam": self.other_exam.id}, format="json"
        )
        self.assertEqual(denied.status_code, 404)

        self.login_as(self.teacher1)
        teacher_denied = self.client.post(
            "/api/exam-submissions/start/", {"exam": self.exam.id}, format="json"
        )
        self.assertEqual(teacher_denied.status_code, 403)

    def test_client_cannot_fake_timeout_or_submit_twice(self):
        self.login_as(self.student1)
        started = self.client.post(
            "/api/exam-submissions/start/", {"exam": self.exam.id}, format="json"
        )
        self.assertEqual(started.status_code, 200)
        submission_id = started.data["data"]["submission"]["id"]

        submitted = self.client.post(
            f"/api/exam-submissions/{submission_id}/submit/",
            {"answers": {str(self.question1.id): {"key": "A"}}, "timeout": True},
            format="json",
        )
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.data["data"]["status"], ExamSubmission.Status.SUBMITTED)
        # 现行规则（提交即可查分）：客观题得分即时可见；本卷无主观题，总分同步可见
        self.assertEqual(submitted.data["data"]["objective_score"], Decimal("5"))
        self.assertEqual(submitted.data["data"]["total_score"], Decimal("5"))
        self.assertEqual(submitted.data["data"]["subjective_scores"], {})

        repeated = self.client.post(
            f"/api/exam-submissions/{submission_id}/submit/",
            {"answers": {}},
            format="json",
        )
        self.assertEqual(repeated.status_code, 400)

    def test_server_marks_submission_timed_out(self):
        sub = ExamSubmission.objects.create(
            exam=self.exam,
            paper=self.paper,
            student=self.student1,
            status=ExamSubmission.Status.IN_PROGRESS,
            started_at=timezone.now() - timedelta(hours=1),
        )
        self.login_as(self.student1)

        response = self.client.post(
            f"/api/exam-submissions/{sub.id}/submit/", {"answers": {}}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], ExamSubmission.Status.TIMEOUT)

    def test_review_visible_immediately_after_submit(self):
        """现行规则（交卷即可回看）：提交后无需等考试结束即可查看答卷。"""
        sub = ExamSubmission.objects.create(
            exam=self.exam,
            paper=self.paper,
            student=self.student1,
            status=ExamSubmission.Status.SUBMITTED,
            started_at=timezone.now() - timedelta(minutes=2),
            submitted_at=timezone.now(),
        )
        self.login_as(self.student1)

        response = self.client.get(f"/api/exam-submissions/{sub.id}/review/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["data"]["questions"])


class PasswordPolicyTests(APITestCase):
    def setUp(self):
        # 注册通道缺省关闭（见 RegisterToggleTests）：密码策略用例先显式打开
        from apps.platform_admin.models import REGISTER_OPEN_KEY, set_setting

        set_setting(REGISTER_OPEN_KEY, True)

    def test_registration_accepts_twelve_character_password(self):
        response = self.client.post(
            "/api/auth/register/",
            {
                "username": "usr2024a",
                "password": "Abcd!2345678",
                "role": "student",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

    def test_registration_rejects_password_longer_than_twelve_characters(self):
        response = self.client.post(
            "/api/auth/register/",
            {
                "username": "longpw01",
                "password": "Abcd!23456789",
                "role": "student",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_registration_rejects_weak_password(self):
        response = self.client.post(
            "/api/auth/register/",
            {
                "username": "weakus01",
                "password": "123456",
                "real_name": "Weak",
                "role": "student",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class RegisterToggleTests(APITestCase):
    """注册通道开关：管理端 PlatformSetting register_open 控制注册接口与登录页入口（缺省关闭）。"""

    def _register_payload(self, username="toggle01"):
        return {"username": username, "password": "Passw0rd!", "role": "student"}

    def test_register_closed_by_default(self):
        """无任何设置行时缺省关闭：新部署环境自助注册默认关停。"""
        response = self.client.post("/api/auth/register/", self._register_payload(), format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["message"], "注册通道已暂时关闭，请联系管理员开通账号")
        self.assertFalse(User.objects.filter(username="toggle01").exists())

    def test_register_accepted_when_opened(self):
        from apps.platform_admin.models import REGISTER_OPEN_KEY, set_setting

        set_setting(REGISTER_OPEN_KEY, True)
        response = self.client.post("/api/auth/register/", self._register_payload(), format="json")
        self.assertEqual(response.status_code, 201)

    def test_register_rejected_when_closed(self):
        from apps.platform_admin.models import REGISTER_OPEN_KEY, set_setting

        set_setting(REGISTER_OPEN_KEY, True)  # 先开再关，覆盖显式关闭路径
        set_setting(REGISTER_OPEN_KEY, False)
        response = self.client.post("/api/auth/register/", self._register_payload(), format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["message"], "注册通道已暂时关闭，请联系管理员开通账号")
        self.assertFalse(User.objects.filter(username="toggle01").exists())

    def test_auth_config_reflects_toggle_and_is_anonymous(self):
        from apps.platform_admin.models import REGISTER_OPEN_KEY, set_setting

        resp = self.client.get("/api/auth/config/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["data"]["register_open"])  # 缺省关闭

        set_setting(REGISTER_OPEN_KEY, True)
        resp = self.client.get("/api/auth/config/")
        self.assertTrue(resp.data["data"]["register_open"])

    def test_admin_settings_get_patch_and_audit(self):
        from apps.platform_admin.models import AdminActionLog

        admin = User.objects.create_user(username="p_admin", password="pw123456!", role=User.Role.ADMIN)
        self.client.force_authenticate(user=admin)

        resp = self.client.get("/api/admin-panel/settings/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["data"]["register_open"])  # 缺省关闭

        # 打开后注册恢复；再关闭立即拒绝
        resp = self.client.patch("/api/admin-panel/settings/", {"register_open": True}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["data"]["register_open"])
        self.assertEqual(
            self.client.post("/api/auth/register/", self._register_payload(), format="json").status_code, 201
        )
        resp = self.client.patch("/api/admin-panel/settings/", {"register_open": False}, format="json")
        self.assertFalse(resp.data["data"]["register_open"])
        self.assertEqual(
            self.client.post(
                "/api/auth/register/", self._register_payload("toggle-user-2"), format="json"
            ).status_code,
            403,
        )
        logs = AdminActionLog.objects.filter(action=AdminActionLog.Action.SETTINGS_UPDATE)
        self.assertEqual(logs.count(), 2)
        self.assertEqual(logs.first().new_value, {"register_open": False})

    def test_admin_settings_rejects_non_bool_and_forbidden_for_teacher(self):
        teacher = User.objects.create_user(username="p_teacher", password="pw123456!", role=User.Role.TEACHER)
        admin = User.objects.create_user(username="p_admin2", password="pw123456!", role=User.Role.ADMIN)

        self.client.force_authenticate(user=admin)
        resp = self.client.patch("/api/admin-panel/settings/", {"register_open": "关"}, format="json")
        self.assertEqual(resp.status_code, 400)

        self.client.force_authenticate(user=teacher)
        self.assertEqual(self.client.get("/api/admin-panel/settings/").status_code, 403)
        self.assertEqual(
            self.client.patch("/api/admin-panel/settings/", {"register_open": False}, format="json").status_code,
            403,
        )


class TeacherCourseBindTests(PlatformFixtureMixin, APITestCase):
    """教师把自己的课挂进班级（P3 选班抽屉的后端通路）。

    追加语义是 P1 的硬要求：一个班有多位教师时，A 挂自己的课不能把 B 的课踢掉。
    这里额外锁住「响应体必须反映新增」——列表/详情接口 prefetch 了 course_links，
    写入后不清缓存的话接口会回改动前的列表，前端拿响应渲染就会静默回退。
    """

    def setUp(self):
        super().setUp()
        self.course3 = Course.objects.create(name="Course 3", teacher=self.teacher1)
        self.client.force_authenticate(user=self.teacher1)

    def test_append_course_and_response_reflects_it(self):
        resp = self.client.patch(
            f"/api/classes/{self.class1.id}/", {"courses": [self.course3.id]}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.json()["data"]
        self.assertIn(self.course3.id, data["courses"], "响应体未反映新增课程（prefetch 缓存未清）")
        self.assertIn(self.course1.id, data["courses"], "原课程被踢掉了")
        self.assertIn("Course 3", data["course_names"])
        self.assertEqual(
            set(ClassCourse.objects.filter(classroom=self.class1).values_list("course_id", flat=True)),
            {self.course1.id, self.course3.id},
        )

    def test_append_keeps_other_teachers_course(self):
        ClassCourse.objects.create(classroom=self.class1, course=self.course2)
        resp = self.client.patch(
            f"/api/classes/{self.class1.id}/", {"courses": [self.course3.id]}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        bound = set(ClassCourse.objects.filter(classroom=self.class1).values_list("course_id", flat=True))
        self.assertEqual(bound, {self.course1.id, self.course2.id, self.course3.id})

    def test_append_is_idempotent(self):
        payload = {"courses": [self.course3.id]}
        self.client.patch(f"/api/classes/{self.class1.id}/", payload, format="json")
        resp = self.client.patch(f"/api/classes/{self.class1.id}/", payload, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(
            ClassCourse.objects.filter(classroom=self.class1, course=self.course3).count(), 1
        )

    def test_teacher_cannot_change_org_fields(self):
        resp = self.client.patch(
            f"/api/classes/{self.class1.id}/",
            {"name": "改名", "courses": [self.course3.id]},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.class1.refresh_from_db()
        self.assertEqual(self.class1.name, "Class 1")

    def test_teacher_cannot_remove_course_by_omitting_it(self):
        """追加语义：只提交一门课不会把班内其他课删掉（撤课归管理员）。"""
        resp = self.client.patch(
            f"/api/classes/{self.class1.id}/", {"courses": [self.course1.id]}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(
            ClassCourse.objects.filter(classroom=self.class1, course=self.course1).exists()
        )

    def test_other_teacher_cannot_patch_class(self):
        """别人的班不在我的可见范围内，直接 404。"""
        self.client.force_authenticate(user=self.teacher2)
        resp = self.client.patch(
            f"/api/classes/{self.class1.id}/", {"courses": [self.course2.id]}, format="json"
        )
        self.assertEqual(resp.status_code, 404)
