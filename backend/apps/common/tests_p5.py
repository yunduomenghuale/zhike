# -*- coding: utf-8 -*-
"""P5-C9：全站 throttle 分级准出。

- 全局匿名/登录用户两级默认节流生效（超速 429）；
- 登录端点按 IP 从严；
- AI 问答（ask）按用户从严；
- 节流类动态读 settings.GLOBAL_THROTTLE_RATES（ScopedSettingThrottle），
  测试用 override_settings 注入极小速率验证行为；正常运行速率见 settings。
注意：throttle 计数存 LocMem，跨用例残留——用例开始先清缓存。
"""
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.cache import cache as django_cache
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

User = get_user_model()

TINY = {
    "GLOBAL_THROTTLE_RATES": {
        "anon": "2/min",
        "user": "2/min",
        "login": "2/min",
        "ai_ask": "1/min",
    }
}


class GlobalThrottleTests(APITestCase):
    @override_settings(**TINY)
    def test_authenticated_user_rate_limited(self):
        user = User.objects.create_user(username="p5thr-u", password="pw123456!", role=User.Role.STUDENT)
        client = APIClient()
        client.force_authenticate(user=user)
        django_cache.clear()
        # 便宜且必然 200 的认证端点：/api/auth/me/
        for _ in range(2):
            resp = client.get("/api/auth/me/")
            self.assertNotEqual(resp.status_code, 429)
        resp = client.get("/api/auth/me/")
        self.assertEqual(resp.status_code, 429)
        self.assertIn("频繁", str(resp.data))

    @override_settings(**TINY)
    def test_anonymous_rate_limited(self):
        """/api/auth/config/ 是 AllowAny 匿名端点：第 3 次触发匿名档 429。

        注意：DRF initial 顺序是 认证→权限→节流，401 会先于节流短路，
        所以匿名档必须用放行匿名的端点才能观察到。
        """
        client = APIClient()
        django_cache.clear()
        codes = [client.get("/api/auth/config/").status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429], codes)


class LoginThrottleTests(APITestCase):
    @override_settings(**TINY)
    def test_login_rate_limited_per_ip(self):
        # 用户名每次随机：登录失败锁（login_fail 文件缓存）跨进程持久，
        # 固定用户名会被上一轮测试的失败计数锁出 429，污染本用例
        unique = f"p5thr-login-{uuid4().hex[:8]}"
        client = APIClient()
        django_cache.clear()
        payload = {"username": unique, "password": "wrong"}
        for _ in range(2):
            resp = client.post("/api/auth/login/", payload, format="json")
            self.assertNotEqual(resp.status_code, 429, resp.data)
        resp = client.post("/api/auth/login/", payload, format="json")
        self.assertEqual(resp.status_code, 429)


class AIAskThrottleTests(APITestCase):
    @override_settings(**TINY)
    def test_ask_rate_limited_per_user(self):
        user = User.objects.create_user(username="p5thr-ai", password="pw123456!", role=User.Role.STUDENT)
        client = APIClient()
        client.force_authenticate(user=user)
        django_cache.clear()
        resp = client.post("/api/qa-records/ask/", {"course": 1, "question": "q"}, format="json")
        self.assertNotEqual(resp.status_code, 429, resp.data)  # 第 1 次进业务校验
        resp = client.post("/api/qa-records/ask/", {"course": 1, "question": "q"}, format="json")
        self.assertEqual(resp.status_code, 429)  # 第 2 次被 ai_ask 档拦下

    def test_rates_disabled_in_test_mode(self):
        """测试模式（settings 置 None）下节流全放行：全量单测不误伤的保障。"""
        from apps.common.throttles import GlobalUserThrottle

        self.assertIsNone(GlobalUserThrottle().get_rate())
