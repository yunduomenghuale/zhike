# -*- coding: utf-8 -*-
"""P5-B5：用户删除保护与停用语义准出（方案 X-25 / X-26）。

- User 实例 delete() 抛异常（物理删改停用）；
- 管理端停用学生：is_active=False 且 edu_status 联动 withdrawn；
- 停用账号无法登录；停用后不出现在业务里（登录/JWT 即失效，统计分母 P4 已排除）。
"""
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from apps.common.delete_protection import UserProtectedError
from apps.users.models import User

User = get_user_model()


class UserDeleteProtectionTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="p5u-admin", password="pw123456!", role=User.Role.ADMIN)
        cls.student = User.objects.create_user(username="p5u-s1", password="pw123456!", role=User.Role.STUDENT)

    def test_instance_delete_raises(self):
        with self.assertRaises(UserProtectedError):
            self.student.delete()

    def test_queryset_delete_channel_works(self):
        """运维脚本通道：queryset 删除可用（测试数据回收）。"""
        u = User.objects.create_user(username="p5u-tmp", password="pw123456!", role=User.Role.STUDENT)
        User.objects.filter(pk=u.pk).delete()
        self.assertFalse(User.objects.filter(pk=u.pk).exists())

    def test_deactivate_student_links_withdrawn(self):
        """X-26：停用学生联动 edu_status=withdrawn。"""
        client = APIClient()
        client.force_authenticate(user=self.admin)
        resp = client.patch(
            f"/api/admin-panel/users/{self.student.id}/", {"is_active": False}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.student.refresh_from_db()
        self.assertFalse(self.student.is_active)
        self.assertEqual(self.student.edu_status, User.EduStatus.WITHDRAWN)

    def test_deactivated_student_cannot_login(self):
        """停用账号登录被拒（先走 X-26 停用流程）。"""
        client = APIClient()
        client.force_authenticate(user=self.admin)
        resp = client.patch(
            f"/api/admin-panel/users/{self.student.id}/", {"is_active": False}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        login_client = APIClient()
        resp = login_client.post(
            "/api/auth/login/", {"username": "p5u-s1", "password": "pw123456!"}, format="json"
        )
        self.assertEqual(resp.status_code, 401, resp.data)
