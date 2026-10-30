"""P5-A4：catalogs/generate-from-plan 权限准出。

该动作直接消耗一次大模型调用，必须与兄弟动作 preview-from-file 一样显式
`IsTeacher`（P4 遗留的权限缺口）。验证：学生 403、未登录 401、教师 200。

P5-B5：Course.teacher PROTECT（方案 X-25）——有课的教师不可物理删除，
必须先转移课程归属；无课教师/转移后可删。
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from rest_framework.test import APITestCase

from apps.courses.models import Course

User = get_user_model()


class GenerateFromPlanPermissionTests(APITestCase):
    def setUp(self):
        self.url = "/api/catalogs/generate-from-plan/"
        self.teacher = User.objects.create_user(
            username="p5-cat-teacher", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.student = User.objects.create_user(
            username="p5-cat-student", password="StrongPass!123", role=User.Role.STUDENT
        )
        self.course = Course.objects.create(name="P5权限课程", teacher=self.teacher)

    @patch("apps.courses.views.generate_catalog_from_plan", return_value=[{"title": "第一章"}])
    def test_teacher_ok(self, _mock):
        self.client.force_authenticate(self.teacher)
        res = self.client.post(self.url, {"course": self.course.id, "plan_text": "计划"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["code"], 0)

    def test_student_forbidden(self):
        self.client.force_authenticate(self.student)
        res = self.client.post(self.url, {"course": self.course.id, "plan_text": "计划"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_anonymous_unauthorized(self):
        res = self.client.post(self.url, {"course": self.course.id, "plan_text": "计划"}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_admin_also_teacher_only(self):
        """IsTeacher 不含管理员是 P1 全站既定口径（教师 AI 动作均如此），管理员也 403。"""
        admin = User.objects.create_user(
            username="p5-cat-admin", password="StrongPass!123", role=User.Role.ADMIN
        )
        self.client.force_authenticate(admin)
        res = self.client.post(self.url, {"course": self.course.id, "plan_text": "计划"}, format="json")
        self.assertEqual(res.status_code, 403)


class CourseTeacherProtectTests(APITestCase):
    """P5-B5 / X-25：Course.teacher 由 CASCADE 改 PROTECT。"""

    def test_deleting_teacher_with_courses_raises(self):
        teacher = User.objects.create_user(username="p5tp-t1", password="pw123456!", role=User.Role.TEACHER)
        course = Course.objects.create(name="P5保护课", teacher=teacher)
        with self.assertRaises(ProtectedError):
            User.objects.filter(pk=teacher.pk).delete()
        self.assertTrue(Course.objects.filter(pk=course.pk).exists())

    def test_deleting_teacher_after_transfer_works(self):
        """先转移课程归属，再删离职教师，正常。"""
        t_old = User.objects.create_user(username="p5tp-t2", password="pw123456!", role=User.Role.TEACHER)
        t_new = User.objects.create_user(username="p5tp-t3", password="pw123456!", role=User.Role.TEACHER)
        course = Course.objects.create(name="P5转移课", teacher=t_old)
        course.teacher = t_new
        course.save(update_fields=["teacher"])
        User.objects.filter(pk=t_old.pk).delete()
        self.assertFalse(User.objects.filter(pk=t_old.pk).exists())
        course.refresh_from_db()
        self.assertEqual(course.teacher_id, t_new.id)

    def test_course_deletion_feature_unaffected(self):
        """教师删除自己的课程仍是产品功能，不受 PROTECT 影响。"""
        teacher = User.objects.create_user(username="p5tp-t4", password="pw123456!", role=User.Role.TEACHER)
        course = Course.objects.create(name="P5自删课", teacher=teacher)
        course.delete()
        self.assertFalse(Course.objects.filter(pk=course.pk).exists())
