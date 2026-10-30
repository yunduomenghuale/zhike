# -*- coding: utf-8 -*-
"""P5-A2：JWT 登出吊销准出。

- 登出后旧 access 401、旧 refresh 不能再换新；
- 作废线之后签发的新 token 可用；
- 被停用账号的未过期 token 同样失效；
- 不带 refresh 也能登出（access 作废线兜底）。

秒级边界说明：JWT iat 是整秒，作废线是微秒时刻——同秒内登出前签发的 token
也必拒（int(iat) < cutoff 恒成立）；「登出后重登录」用回拨作废线确定性验证。
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

User = get_user_model()


class JWTRevocationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="p5jwt-admin", password="pw123456!", role=User.Role.ADMIN)
        cls.student = User.objects.create_user(username="p5jwt-s", password="pw123456!", role=User.Role.STUDENT)

    def _login(self, username="p5jwt-s"):
        client = APIClient()
        resp = client.post("/api/auth/login/", {"username": username, "password": "pw123456!"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.data["data"]["token"]
        return data["access"], data["refresh"]

    def _authed_get(self, access):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        return client.get("/api/auth/me/")

    def test_logout_revokes_access_and_refresh(self):
        access, refresh = self._login()
        self.assertEqual(self._authed_get(access).status_code, 200)

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        resp = client.post("/api/auth/logout/", {"refresh": refresh}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data["data"]["refresh_revoked"])

        # 旧 access 401（作废线）
        self.assertEqual(self._authed_get(access).status_code, 401)
        # 旧 refresh 不能再换新（黑名单）
        resp = APIClient().post("/api/auth/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(resp.status_code, 401, resp.data)

    def test_new_login_after_logout_works(self):
        """作废线之后签发的新 token 可用（用回拨 2s 的作废线确定性验证秒级边界）。"""
        access, refresh = self._login()
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        client.post("/api/auth/logout/", {"refresh": refresh}, format="json")
        # 真实场景「登出后过一会儿再登录」：作废线在 2s 前，新 token iat 必大于它。
        # 不用 sleep 等时钟走秒——回拨字段等价模拟同一时间关系且确定
        self.student.refresh_from_db()
        self.student.tokens_invalid_before = self.student.tokens_invalid_before - timedelta(seconds=2)
        self.student.save(update_fields=["tokens_invalid_before"])
        access2, _ = self._login()
        self.assertEqual(self._authed_get(access2).status_code, 200)

    def test_logout_without_refresh_still_revokes_access(self):
        access, _ = self._login()
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        resp = client.post("/api/auth/logout/", {}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(resp.data["data"]["refresh_revoked"])
        self.assertEqual(self._authed_get(access).status_code, 401)

    def test_deactivated_user_token_invalid(self):
        """停用账号的未过期 token 立即失效（P5-A2 + X-26 联动）。"""
        access, _ = self._login()
        self.assertEqual(self._authed_get(access).status_code, 200)

        admin_client = APIClient()
        admin_client.force_authenticate(user=self.admin)
        resp = admin_client.patch(
            f"/api/admin-panel/users/{self.student.id}/", {"is_active": False}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self._authed_get(access).status_code, 401)
