# -*- coding: utf-8 -*-
"""P5-B5：班级删除保护准出（方案 X-04）。

- 模型层实例 delete() 抛异常；管理端 API DELETE 返回明确中文错误；
- 归档（PATCH status=archived）是唯一下线通道；
- 运维脚本通道（queryset delete）保留可用。
"""
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from apps.classroom.models import ClassRoom
from apps.common.delete_protection import ClassRoomProtectedError

User = get_user_model()


class ClassRoomDeleteProtectionTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="p5cls-admin", password="pw123456!", role=User.Role.ADMIN)
        cls.classroom = ClassRoom.objects.create(name="P5保护班", code="P5-PROT-01")

    def test_instance_delete_raises(self):
        """实例 delete() 被拦截（X-04 模型层兜底）。"""
        with self.assertRaises(ClassRoomProtectedError):
            self.classroom.delete()

    def test_queryset_delete_still_works(self):
        """运维脚本通道：queryset 删除不经过实例 delete()，仍可用。"""
        room = ClassRoom.objects.create(name="P5脚本班", code="P5-SCRIPT-01")
        deleted, _ = ClassRoom.objects.filter(pk=room.pk).delete()
        self.assertGreaterEqual(deleted, 1)
        self.assertFalse(ClassRoom.objects.filter(pk=room.pk).exists())

    def test_api_delete_returns_friendly_error(self):
        """管理端 DELETE 返回明确中文错误，班级仍在。"""
        client = APIClient()
        client.force_authenticate(user=self.admin)
        resp = client.delete(f"/api/classes/{self.classroom.id}/")
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("归档", resp.data.get("message", ""))
        self.assertTrue(ClassRoom.objects.filter(pk=self.classroom.id).exists())

    def test_archive_via_patch_works(self):
        """归档是唯一下线通道：PATCH status=archived 正常。"""
        client = APIClient()
        client.force_authenticate(user=self.admin)
        resp = client.patch(f"/api/classes/{self.classroom.id}/", {"status": "archived"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.classroom.refresh_from_db()
        self.assertEqual(self.classroom.status, ClassRoom.Status.ARCHIVED)


class ClassStudentRosterFilterTests(APITestCase):
    """transferred/removed 是历史留痕，不出现在教师/管理端名单里。

    生产现场问题：迁移处置的转出学生在名单里可见（学习状态列显示「未活跃」），
    点详情却因 build_class_stats 只算占用中学生而报「该学生不在此班级」。
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="p5ros-admin", password="pw123456!", role=User.Role.ADMIN)
        cls.classroom = ClassRoom.objects.create(name="P5名单班", code="P5-ROSTER-01")
        cls.staying = User.objects.create_user(username="p5ros-stay", password="pw123456!", role=User.Role.STUDENT)
        cls.transferred = User.objects.create_user(username="p5ros-gone", password="pw123456!", role=User.Role.STUDENT)
        from apps.classroom.models import ClassStudent

        ClassStudent.objects.create(classroom=cls.classroom, student=cls.staying, learn_status="active")
        ClassStudent.objects.create(
            classroom=cls.classroom, student=cls.transferred, learn_status="transferred"
        )

    def test_roster_excludes_transferred(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        resp = client.get(f"/api/class-students/?classroom={self.classroom.id}")
        self.assertEqual(resp.status_code, 200, resp.data)
        rows = resp.data["data"]["results"] if isinstance(resp.data.get("data"), dict) else resp.data["data"]
        usernames = {r["username"] for r in rows}
        self.assertIn("p5ros-stay", usernames)
        self.assertNotIn("p5ros-gone", usernames)

    def test_all_status_filter_still_shows_occupying_only(self):
        """「全部状态」也只能看到占用中学生，不会带出历史留痕。"""
        client = APIClient()
        client.force_authenticate(user=self.admin)
        resp = client.get(f"/api/class-students/?classroom={self.classroom.id}&learn_status=")
        rows = resp.data["data"]["results"] if isinstance(resp.data.get("data"), dict) else resp.data["data"]
        usernames = {r["username"] for r in rows}
        self.assertNotIn("p5ros-gone", usernames)
