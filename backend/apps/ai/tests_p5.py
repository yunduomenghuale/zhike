# -*- coding: utf-8 -*-
"""P5-B7：Mock 静默回退显性化准出。

- factory 静默回退点（缺 Key / 未知 provider）打标；显式配置 mock 不打标；
- OpenAICompatProvider chat 失败回退打标（last_chat_error 同步）；
- 问答响应体携带 provider_fallback；
- 管理端 ai-configuration 返回近 24h 回退告警聚合。
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.ai.models import AICallLog, AIQuotaPolicy
from apps.ai.providers.fallback import consume_fallback, mark_fallback
from apps.ai.providers.factory import build_provider
from apps.ai.providers.mock import MockProvider
from apps.ai.providers.openai_compat import OpenAICompatProvider
from apps.courses.models import Course
from apps.knowledge.models import QASession

User = get_user_model()


class FallbackMarkTests(APITestCase):
    def setUp(self):
        # 每个用例开始清空上下文标记
        consume_fallback()

    def tearDown(self):
        consume_fallback()

    def test_missing_key_marks_fallback(self):
        provider = build_provider("tongyi", {})
        self.assertIsInstance(provider, MockProvider)
        self.assertTrue(consume_fallback())
        # 消费后清空
        self.assertEqual(consume_fallback(), "")

    def test_unknown_provider_marks_fallback(self):
        provider = build_provider("mystery-llm", {"api_key": "sk-x"})
        self.assertIsInstance(provider, MockProvider)
        self.assertIn("mystery-llm", consume_fallback())

    def test_explicit_mock_not_marked(self):
        provider = build_provider("mock", {})
        self.assertIsInstance(provider, MockProvider)
        self.assertEqual(consume_fallback(), "")

    def test_first_reason_wins(self):
        mark_fallback("原因一")
        mark_fallback("原因二")
        self.assertEqual(consume_fallback(), "原因一")

    def test_chat_failure_marks_fallback(self):
        """真实调用失败 → Mock 内容 + 打标 + last_chat_error。"""
        provider = OpenAICompatProvider(
            {"api_key": "sk-test", "base_url": "http://127.0.0.1:1", "chat_model": "test-model"},
            name="openai",
        )
        with patch("apps.ai.providers.openai_compat.requests.post", side_effect=ConnectionError("连接失败")):
            result = provider.chat([{"role": "user", "content": "hi"}])
        self.assertIsInstance(result, str)  # Mock 占位内容
        self.assertTrue(provider.last_chat_error)
        self.assertIn("chat", consume_fallback())


class QAFallbackResponseTests(APITestCase):
    """问答响应体的 provider_fallback 字段。"""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="p5fb-t", password="pw123456!", role=User.Role.TEACHER)
        cls.student = User.objects.create_user(username="p5fb-s", password="pw123456!", role=User.Role.STUDENT)
        cls.course = Course.objects.create(name="P5回退课", teacher=cls.teacher)
        cls.session = QASession.objects.create(
            course=cls.course, student=cls.student, legacy_key="p5fb-legacy", title="P5回退会话"
        )

    def setUp(self):
        consume_fallback()

    def tearDown(self):
        consume_fallback()

    def _ask(self):
        client = APIClient()
        client.force_authenticate(user=self.student)
        with patch("apps.knowledge.views._resolve_qa_scope") as scope, \
             patch("apps.knowledge.views._resolve_qa_session", return_value=self.session), \
             patch("apps.knowledge.views.build_conversation_context", return_value=[]), \
             patch("apps.knowledge.views.maybe_update_session_summary"), \
             patch("apps.knowledge.views._prev_snapshot_chunks", return_value={}), \
             patch("apps.knowledge.views._next_turn_index", return_value=1), \
             patch("apps.knowledge.views._touch_session"):
            scope.return_value = (self.course, None, None, [])
            return client.post(
                "/api/qa-records/ask/", {"course": self.course.id, "question": "测试问题"}, format="json"
            )

    def test_ask_response_has_provider_fallback_false_by_default(self):
        """未发生回退（显式 mock 配置）时字段为 False，不误报。"""
        with patch(
            "apps.knowledge.views.knowledge_qa", return_value=("答案", [], "", {})
        ):
            resp = self._ask()
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(resp.data["data"]["provider_fallback"])

    def test_ask_response_marks_fallback(self):
        """回退发生时（contextvar 被底层置位）响应体带 provider_fallback=true。"""
        with patch(
            "apps.knowledge.views.knowledge_qa", side_effect=self._qa_with_fallback
        ):
            resp = self._ask()
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data["data"]["provider_fallback"])
        self.assertIn("回退", resp.data["data"]["fallback_reason"])

    @staticmethod
    def _qa_with_fallback(**kwargs):
        # 模拟 provider 层回退打标（真实场景由 openai_compat.chat 回退分支触发）
        mark_fallback("chat 调用失败已回退 Mock：测试注入")
        return "模拟答案", [], "", {}


class AdminFallbackAlertTests(APITestCase):
    """管理端回退告警聚合。"""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="p5fb-admin", password="pw123456!", role=User.Role.ADMIN)

    def test_alert_counts_recent_mock_calls(self):
        AICallLog.objects.create(
            capability="chat", scene=AICallLog.Scene.QA, provider="openai",
            is_mock=True, success=True, error="连接超时",
        )
        client = APIClient()
        client.force_authenticate(user=self.admin)
        resp = client.get("/api/admin-panel/ai-configuration/")
        self.assertEqual(resp.status_code, 200, resp.data)
        alert = resp.data["data"]["mock_fallback_alert"]
        self.assertGreaterEqual(alert["count_24h"], 1)
        self.assertEqual(alert["latest_error"], "连接超时")
        self.assertTrue(alert["latest_at"] and alert["latest_at"] <= timezone.now())


class AIQuotaTests(APITestCase):
    """P5-B6：AI 日配额（用户级覆盖 > 全局默认 > env 兜底），超限 429。"""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="p5q-admin", password="pw123456!", role=User.Role.ADMIN)
        cls.student = User.objects.create_user(username="p5q-s", password="pw123456!", role=User.Role.STUDENT)
        cls.course = Course.objects.create(name="P5配额课", teacher=cls.admin)
        cls.qa_session = QASession.objects.create(
            course=cls.course, student=cls.student, legacy_key="p5q-legacy", title="P5配额会话"
        )

    def setUp(self):
        AIQuotaPolicy.objects.all().delete()
        AICallLog.objects.filter(triggered_by__in=[self.admin, self.student]).delete()
        consume_fallback()

    def test_no_config_means_unlimited(self):
        from apps.ai.quota import check_ai_quota, get_effective_daily_limit
        self.assertIsNone(get_effective_daily_limit(self.student))
        self.assertIsNone(check_ai_quota(self.student))  # 不抛即放行

    def test_global_default_applies(self):
        from apps.ai.quota import get_effective_daily_limit
        AIQuotaPolicy.objects.create(user=None, daily_limit=5)
        self.assertEqual(get_effective_daily_limit(self.student), 5)
        self.assertEqual(get_effective_daily_limit(self.admin), 5)

    def test_user_override_beats_global(self):
        from apps.ai.quota import get_effective_daily_limit
        AIQuotaPolicy.objects.create(user=None, daily_limit=5)
        AIQuotaPolicy.objects.create(user=self.student, daily_limit=2)
        self.assertEqual(get_effective_daily_limit(self.student), 2)
        self.assertEqual(get_effective_daily_limit(self.admin), 5)

    def test_quota_blocks_and_recovers(self):
        """连续调用到上限触发 429，配额恢复（调高）后可用。"""
        AIQuotaPolicy.objects.create(user=None, daily_limit=2)
        for _ in range(2):
            AICallLog.objects.create(
                capability="chat", scene=AICallLog.Scene.QA, provider="openai",
                triggered_by=self.student, success=True,
            )
        client = APIClient()
        client.force_authenticate(user=self.student)
        # 配额检查在 scope 解析之前：429 分支无需任何业务 mock
        resp = client.post("/api/qa-records/ask/", {"course": self.course.id, "question": "q"}, format="json")
        self.assertEqual(resp.status_code, 429, resp.data)
        self.assertIn("上限", str(resp.data))

        # 配额恢复：调高全局默认后放行（走全 mock 业务链，200 即证明不是 429）
        row = AIQuotaPolicy.objects.filter(user__isnull=True).first()
        row.daily_limit = 100
        row.save()
        with patch("apps.knowledge.views.knowledge_qa", return_value=("答案", [], "", {})), \
             patch("apps.knowledge.views._resolve_qa_scope") as scope, \
             patch("apps.knowledge.views._resolve_qa_session", return_value=self.qa_session), \
             patch("apps.knowledge.views.build_conversation_context", return_value=[]), \
             patch("apps.knowledge.views.maybe_update_session_summary"), \
             patch("apps.knowledge.views._prev_snapshot_chunks", return_value={}), \
             patch("apps.knowledge.views._next_turn_index", return_value=1), \
             patch("apps.knowledge.views._touch_session"):
            scope.return_value = (self.course, None, None, [])
            resp = client.post("/api/qa-records/ask/", {"course": self.course.id, "question": "q"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_zero_limit_blocks_entirely(self):
        """limit=0 = 当天 0 次（封禁语义），与 None（不限）区分。"""
        AIQuotaPolicy.objects.create(user=self.student, daily_limit=0)
        client = APIClient()
        client.force_authenticate(user=self.student)
        resp = client.post("/api/qa-records/ask/", {"course": 1, "question": "q"}, format="json")
        self.assertEqual(resp.status_code, 429, resp.data)

    def test_admin_quota_api_roundtrip(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        resp = client.put("/api/admin-panel/ai-quota/", {
            "default_daily_limit": 50,
            "overrides": [{"user_id": self.student.id, "daily_limit": 3}],
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(AIQuotaPolicy.objects.filter(user=None, daily_limit=50).exists())
        self.assertTrue(AIQuotaPolicy.objects.filter(user=self.student, daily_limit=3).exists())

        resp = client.get("/api/admin-panel/ai-quota/")
        data = resp.data["data"]
        self.assertEqual(data["default_daily_limit"], 50)
        self.assertEqual(data["overrides"][0]["daily_limit"], 3)

        # 覆盖置 null = 删除覆盖
        resp = client.put("/api/admin-panel/ai-quota/", {
            "default_daily_limit": 50,
            "overrides": [{"user_id": self.student.id, "daily_limit": None}],
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(AIQuotaPolicy.objects.filter(user=self.student).exists())
