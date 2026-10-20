"""analytics 服务层（build_class_stats 平移）一致性测试。

平移验收标准：教师端班级学情统计接口行为不变（services 化不改口径）。
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.courses.models import Course
from apps.classroom.models import ClassRoom, ClassStudent

from .services import build_class_stats

User = get_user_model()


class BuildClassStatsTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username="t_stats", password="pw123456!", role=User.Role.TEACHER
        )
        self.student = User.objects.create_user(
            username="s_stats", password="pw123456!", role=User.Role.STUDENT
        )
        self.course = Course.objects.create(name="统计课程", teacher=self.teacher)
        self.classroom = ClassRoom.objects.create(name="统计班级", teacher=self.teacher)
        self.classroom.courses.add(self.course)
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)

    def test_service_direct_call(self):
        stats = build_class_stats(self.classroom, self.course.id)
        self.assertEqual(stats["class_name"], "统计班级")
        self.assertEqual(stats["summary"]["student_count"], 1)
        self.assertEqual(len(stats["students"]), 1)
        self.assertEqual(stats["students"][0]["username"], "s_stats")

    def test_teacher_endpoint_matches_service(self):
        """教师端接口与服务函数输出一致（平移不改口径）。"""
        client = APIClient()
        client.force_authenticate(user=self.teacher)
        resp = client.get(f"/api/analytics/class/{self.classroom.id}/")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(
            resp.data["data"], build_class_stats(self.classroom, self.course.id)
        )
