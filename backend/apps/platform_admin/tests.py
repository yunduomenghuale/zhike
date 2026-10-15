"""管理端大模型配置（按能力）保存/回退行为测试。

覆盖「保存并应用」的关键路径：
- API Key 留空时回退环境变量已生效 Key 并物化进数据库（保存后不回落 mock）；
- 环境变量也没有 Key / 切换服务商时拒绝保存；
- 显式填写 Key 的新建与更新；
- 配置要素未变时保留历史测试结论，变更则作废。
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.ai.models import AICapabilityConfig, AITestRecord
from apps.ai.providers.factory import build_provider, get_runtime_config

User = get_user_model()

URL = "/api/admin-panel/ai-configuration/"

# 环境变量模式：通义千问已配好 Key（模拟生产 .env 形态，数据库无记录）
ENV_TONGYI = {
    "tongyi": {
        "api_key": "env-key-tongyi",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "chat_model": "env-chat",
        "embed_model": "env-embed",
        "tts_model": "env-tts",
    }
}
ENV_EMPTY = {"tongyi": {"api_key": "", "base_url": "", "chat_model": "", "embed_model": "", "tts_model": ""}}


@override_settings(AI_PROVIDER="tongyi", AI_SETTINGS=ENV_TONGYI, AI_CAPABILITY_ENV={})
class AdminAIConfigurationSaveTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_ai", password="pw123456!", role=User.Role.ADMIN
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _put(self, capabilities):
        return self.client.put(URL, {"capabilities": capabilities}, format="json")

    def _chat_item(self, **overrides):
        item = {
            "capability": "chat",
            "provider": "tongyi",
            "enabled": True,
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model_name": "qwen-plus",
        }
        item.update(overrides)
        return item

    # ---------- Key 留空：回退环境变量 ----------

    def test_save_without_key_falls_back_to_env_key(self):
        """Key 留空 → 回退环境变量 Key 并物化，保存后仍是真实 provider。"""
        resp = self._put([self._chat_item()])
        self.assertEqual(resp.status_code, 200, resp.data)

        row = AICapabilityConfig.objects.get(capability="chat")
        self.assertEqual(row.get_api_key(), "env-key-tongyi")

        provider, config, source = get_runtime_config("chat")
        self.assertEqual((provider, source), ("tongyi", "database"))
        self.assertEqual(config["api_key"], "env-key-tongyi")
        self.assertEqual(build_provider(provider, config, "chat").name, "tongyi")

    def test_payload_after_save_is_real_runtime(self):
        """保存后 GET 的负载：来源=管理端、实际运行时非 mock。"""
        self.assertEqual(self._put([self._chat_item()]).status_code, 200)
        item = self.client.get(URL).data["data"]["items"][0]
        self.assertEqual(item["capability"], "chat")
        self.assertEqual(item["source"], "database")
        self.assertFalse(item["runtime_is_mock"])
        self.assertTrue(item["api_key_configured"])
        self.assertTrue(item["api_key_masked"].endswith("ngyi"))

    def test_save_without_key_and_without_env_key_rejected(self):
        """环境变量也没有 Key 时拒绝保存，错误指向 api_key。"""
        with override_settings(AI_PROVIDER="tongyi", AI_SETTINGS=ENV_EMPTY, AI_CAPABILITY_ENV={}):
            resp = self._put([self._chat_item()])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("api_key", resp.data["data"])
        self.assertEqual(AICapabilityConfig.objects.count(), 0)

    def test_save_switching_provider_without_key_rejected(self):
        """切到环境变量未配 Key 的服务商且不填 Key → 拒绝（不能拿通义的 Key 充数）。"""
        resp = self._put([self._chat_item(provider="deepseek")])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("api_key", resp.data["data"])
        self.assertEqual(AICapabilityConfig.objects.count(), 0)

    # ---------- 显式 Key 的新建 / 更新 ----------

    def test_save_with_explicit_key_creates_record(self):
        """显式填 Key 的新建路径（api_key 是 write_only 字段，create 须单独加密落库）。"""
        resp = self._put([self._chat_item(api_key="sk-form-key")])
        self.assertEqual(resp.status_code, 200, resp.data)
        row = AICapabilityConfig.objects.get(capability="chat")
        self.assertEqual(row.get_api_key(), "sk-form-key")
        self.assertEqual(row.updated_by, self.admin)

    def test_update_keeps_existing_key_when_blank(self):
        """更新已有记录时 Key 留空 → 沿用已存 Key，不被清空。"""
        self.assertEqual(self._put([self._chat_item(api_key="sk-keep-me")]).status_code, 200)
        resp = self._put([self._chat_item(model_name="qwen-max")])  # 不传 api_key
        self.assertEqual(resp.status_code, 200, resp.data)
        row = AICapabilityConfig.objects.get(capability="chat")
        self.assertEqual(row.get_api_key(), "sk-keep-me")
        self.assertEqual(row.model_name, "qwen-max")

    def test_mock_provider_needs_no_key(self):
        """模拟模式不需要 Key。"""
        resp = self._put([self._chat_item(provider="mock", base_url="", model_name="")])
        self.assertEqual(resp.status_code, 200, resp.data)
        provider, _, source = get_runtime_config("chat")
        self.assertEqual((provider, source), ("mock", "database"))

    # ---------- 测试结论保留 / 作废 ----------

    def test_test_record_kept_when_config_unchanged(self):
        """刚测过就保存（表单值与环境变量生效值一致）：保留 success 结论。"""
        AITestRecord.objects.create(capability="chat", provider="tongyi", status="success", message="ok")
        self.assertEqual(self._put([self._chat_item(model_name="env-chat")]).status_code, 200)
        self.assertEqual(AITestRecord.objects.filter(capability="chat").count(), 1)

    def test_test_record_voided_when_model_changed(self):
        """改了模型再保存：旧测试结论作废。"""
        AITestRecord.objects.create(capability="chat", provider="tongyi", status="success", message="ok")
        self.assertEqual(self._put([self._chat_item(model_name="qwen-turbo")]).status_code, 200)
        self.assertEqual(AITestRecord.objects.filter(capability="chat").count(), 0)

    # ---------- 权限 ----------

    def test_non_admin_forbidden(self):
        teacher = User.objects.create_user(
            username="t_ai", password="pw123456!", role=User.Role.TEACHER
        )
        client = APIClient()
        client.force_authenticate(user=teacher)
        self.assertEqual(client.put(URL, {"capabilities": [self._chat_item()]}, format="json").status_code, 403)


@override_settings(AI_PROVIDER="tongyi", AI_SETTINGS=ENV_TONGYI, AI_CAPABILITY_ENV={})
class AdminAICapabilityTimeoutVoiceTests(TestCase):
    """管理端按能力配置超时(timeout)与发音人(voice)：保存、透传、校验。"""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_ai2", password="pw123456!", role=User.Role.ADMIN
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _tts_item(self, **overrides):
        item = {
            "capability": "tts",
            "provider": "openai",
            "enabled": True,
            "base_url": "http://127.0.0.1:8000/v1",
            "model_name": "tts-local",
            "api_key": "local-key",
            "timeout": 240,
            "voice": "speaker-01",
        }
        item.update(overrides)
        return item

    def test_save_timeout_voice_and_flow_to_runtime_config(self):
        """保存后 timeout/voice 落库，并随 get_runtime_config/build_provider 透传。"""
        resp = self.client.put(URL, {"capabilities": [self._tts_item()]}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)

        row = AICapabilityConfig.objects.get(capability="tts")
        self.assertEqual(row.timeout, 240)
        self.assertEqual(row.voice, "speaker-01")

        provider, config, source = get_runtime_config("tts")
        self.assertEqual((provider, source), ("openai", "database"))
        self.assertEqual(config["timeout"], 240)
        self.assertEqual(config["voice"], "speaker-01")

        built = build_provider(provider, config, "tts")
        self.assertEqual(built.timeout, 240)
        self.assertEqual(built.voice, "speaker-01")

        # GET 负载带回两个字段（前端生效表格/表单回显用）
        items = self.client.get(URL).data["data"]["items"]
        item = next(i for i in items if i["capability"] == "tts")
        self.assertEqual(item["timeout"], 240)
        self.assertEqual(item["voice"], "speaker-01")

    def test_blank_timeout_voice_falls_back_to_defaults(self):
        """不传 timeout/voice：存为空，provider 回退 settings 默认值。"""
        resp = self.client.put(
            URL,
            {"capabilities": [self._tts_item(timeout=None, voice="")]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        row = AICapabilityConfig.objects.get(capability="tts")
        self.assertIsNone(row.timeout)
        self.assertEqual(row.voice, "")
        _, config, _ = get_runtime_config("tts")
        built = build_provider("openai", config, "tts")
        self.assertIsNone(built.timeout)
        self.assertEqual(built.voice, "")

    def test_voice_ignored_for_non_tts_capability(self):
        """发音人仅对语音合成有效：对话能力传了也被清空。"""
        resp = self.client.put(
            URL,
            {"capabilities": [self._tts_item(capability="chat", provider="tongyi",
                                              base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                                              model_name="qwen-plus", voice="speaker-01")]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        row = AICapabilityConfig.objects.get(capability="chat")
        self.assertEqual(row.voice, "")
        self.assertEqual(row.timeout, 240)  # 超时对对话能力有效，保留

    def test_timeout_out_of_range_rejected(self):
        """超时必须在 1~3600 秒之间。"""
        for bad in (0, 3601):
            resp = self.client.put(
                URL, {"capabilities": [self._tts_item(timeout=bad)]}, format="json"
            )
            self.assertEqual(resp.status_code, 400, f"timeout={bad}")
            self.assertIn("timeout", resp.data["data"])
        self.assertEqual(AICapabilityConfig.objects.count(), 0)


@override_settings(AI_PROVIDER="tongyi", AI_SETTINGS=ENV_TONGYI, AI_CAPABILITY_ENV={})
class AdminAICapabilityProviderWhitelistTests(TestCase):
    """能力-服务商白名单：向量化/语音合成拒收 DeepSeek 与模拟模式；对话保留两者。"""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_ai3", password="pw123456!", role=User.Role.ADMIN
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _item(self, **overrides):
        item = {
            "capability": "embed",
            "provider": "tongyi",
            "enabled": True,
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model_name": "text-embedding-v3",
            "api_key": "sk-test",
        }
        item.update(overrides)
        return item

    def test_deepseek_rejected_for_embed_and_tts(self):
        for capability in ("embed", "tts"):
            resp = self.client.put(
                URL, {"capabilities": [self._item(capability=capability, provider="deepseek")]}, format="json"
            )
            self.assertEqual(resp.status_code, 400, capability)
            self.assertIn("provider", resp.data["data"])
            self.assertIn("通义千问", resp.data["data"]["provider"][0])
        self.assertEqual(AICapabilityConfig.objects.count(), 0)

    def test_mock_rejected_for_embed_and_tts(self):
        """模拟模式不产生真实向量/音频：向量化与语音合成拒收（对话仍允许）。"""
        for capability in ("embed", "tts"):
            resp = self.client.put(
                URL, {"capabilities": [self._item(capability=capability, provider="mock")]}, format="json"
            )
            self.assertEqual(resp.status_code, 400, capability)
            self.assertIn("provider", resp.data["data"])
            self.assertIn("通义千问", resp.data["data"]["provider"][0])
        self.assertEqual(AICapabilityConfig.objects.count(), 0)

        resp = self.client.put(
            URL, {"capabilities": [self._item(capability="chat", provider="mock")]}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(AICapabilityConfig.objects.get(capability="chat").provider, "mock")

    def test_deepseek_allowed_for_chat(self):
        """对话能力仍可选 DeepSeek。"""
        resp = self.client.put(
            URL,
            {"capabilities": [self._item(capability="chat", provider="deepseek",
                                         base_url="https://api.deepseek.com/v1",
                                         model_name="deepseek-chat", api_key="sk-ds")]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(AICapabilityConfig.objects.get(capability="chat").provider, "deepseek")

    def test_existing_deepseek_row_rejected_on_any_update(self):
        """库里历史遗留的 deepseek 向量化行：任何更新都被拒（逼纠正服务商）。"""
        AICapabilityConfig.objects.create(
            capability="embed", provider="deepseek", enabled=True,
            base_url="https://api.deepseek.com/v1", model_name="deepseek-chat",
        )
        item = self._item(model_name="text-embedding-v4")
        item.pop("provider")  # 不传 provider：validate 回退到实例旧值 deepseek → 拒收
        resp = self.client.put(URL, {"capabilities": [item]}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("provider", resp.data["data"])
        self.assertEqual(AICapabilityConfig.objects.get(capability="embed").model_name, "deepseek-chat")

    def test_connection_test_rejects_deepseek_for_embed(self):
        """测试连接接口同样校验白名单（防 API 层绕过前端下拉）。"""
        resp = self.client.post(
            "/api/admin-panel/ai-configuration/test/",
            {"capability": "embed", "provider": "deepseek", "base_url": "https://api.deepseek.com/v1",
             "model_name": "deepseek-chat", "api_key": "sk-ds"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("通义千问", resp.data["message"])

    def test_connection_test_rejects_mock_for_embed(self):
        resp = self.client.post(
            "/api/admin-panel/ai-configuration/test/",
            {"capability": "embed", "provider": "mock"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("通义千问", resp.data["message"])

    def test_deepseek_and_mock_rejected_for_rerank(self):
        """重排序仅通义千问（DashScope 原生 rerank 端点）：拒收 DeepSeek 与模拟模式。"""
        for provider in ("deepseek", "mock"):
            resp = self.client.put(
                URL,
                {"capabilities": [self._item(capability="rerank", provider=provider,
                                             base_url="https://api.deepseek.com/v1",
                                             model_name="gte-rerank-v2")]},
                format="json",
            )
            self.assertEqual(resp.status_code, 400, provider)
            self.assertIn("provider", resp.data["data"])
            self.assertIn("通义千问", resp.data["data"]["provider"][0])
        self.assertEqual(AICapabilityConfig.objects.count(), 0)

    def test_connection_test_rejects_deepseek_for_rerank(self):
        resp = self.client.post(
            "/api/admin-panel/ai-configuration/test/",
            {"capability": "rerank", "provider": "deepseek",
             "base_url": "https://api.deepseek.com/v1", "model_name": "gte-rerank-v2",
             "api_key": "sk-ds"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("通义千问", resp.data["message"])

    def test_rerank_saved_with_tongyi_maps_to_rerank_model(self):
        """重排序配通义千问可保存；运行时按能力把 model 映射到 rerank_model 字段。"""
        resp = self.client.put(
            URL,
            {"capabilities": [self._item(capability="rerank", model_name="gte-rerank-v2")]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        row = AICapabilityConfig.objects.get(capability="rerank")
        self.assertEqual(row.provider, "tongyi")
        self.assertEqual(row.model_name, "gte-rerank-v2")

        provider, config, _ = get_runtime_config("rerank")
        built = build_provider(provider, config, "rerank")
        self.assertEqual(built.name, "tongyi")
        self.assertEqual(built.rerank_model, "gte-rerank-v2")

    def test_connection_test_rerank_success(self):
        """重排序连接测试：走 provider.rerank，detail 带回相关性分明细。"""

        class _FakeRerankProvider:
            name = "tongyi"

            def rerank(self, query, documents, top_n=None):
                return [{"index": 1, "score": 0.87}, {"index": 0, "score": 0.12}]

        with patch("apps.platform_admin.views.build_provider", return_value=_FakeRerankProvider()):
            resp = self.client.post(
                "/api/admin-panel/ai-configuration/test/",
                {"capability": "rerank", "provider": "tongyi",
                 "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                 "model_name": "gte-rerank-v2", "api_key": "sk-test"},
                format="json",
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        detail = resp.data["data"]["detail"]
        self.assertIn("相关性", detail["response"])
        self.assertIn("0.87", detail["response"])
        record = AITestRecord.objects.get(capability="rerank")
        self.assertEqual(record.status, "success")

    def test_existing_mock_row_rejected_on_any_update(self):
        """库里历史遗留的 mock 向量化行：任何更新都被拒（逼换成真实服务商）。"""
        AICapabilityConfig.objects.create(
            capability="embed", provider="mock", enabled=True,
            base_url="", model_name="",
        )
        item = self._item(model_name="text-embedding-v4")
        item.pop("provider")  # 不传 provider：validate 回退到实例旧值 mock → 拒收
        resp = self.client.put(URL, {"capabilities": [item]}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("provider", resp.data["data"])
        self.assertEqual(AICapabilityConfig.objects.get(capability="embed").model_name, "")

    def test_local_saved_without_key_url_and_model_defaulted(self):
        """系统内置模型：向量化/重排序可保存，无需 Key/接口地址，模型名留空补默认。"""
        for capability, expected_model in (("embed", "BAAI/bge-m3"), ("rerank", "Qwen/Qwen3-Reranker-0.6B")):
            resp = self.client.put(
                URL,
                {"capabilities": [self._item(capability=capability, provider="local",
                                             base_url="", model_name="", api_key="")]},
                format="json",
            )
            self.assertEqual(resp.status_code, 200, resp.data)
            row = AICapabilityConfig.objects.get(capability=capability)
            self.assertEqual(row.provider, "local")
            self.assertEqual(row.model_name, expected_model)
            self.assertEqual(row.base_url, "")

            provider, config, _ = get_runtime_config(capability)
            built = build_provider(provider, config, capability)
            self.assertEqual(built.name, "local")
            self.assertEqual(built.model, expected_model)

    def test_local_rejected_for_chat_and_tts(self):
        """对话/语音暂无内置实现：拒收 local。"""
        for capability in ("chat", "tts"):
            resp = self.client.put(
                URL,
                {"capabilities": [self._item(capability=capability, provider="local",
                                             base_url="", model_name="")]},
                format="json",
            )
            self.assertEqual(resp.status_code, 400, capability)
            self.assertIn("provider", resp.data["data"])

    def test_connection_test_local_embed_success(self):
        """local 连接测试：无 Key 也走真实推理分支（不被当作模拟模式）。"""

        class _FakeLocalProvider:
            name = "local"

            def embed(self, texts, *, allow_fallback=True):
                return [[0.1] * 1024 for _ in texts]

        with patch("apps.platform_admin.views.build_provider", return_value=_FakeLocalProvider()):
            resp = self.client.post(
                "/api/admin-panel/ai-configuration/test/",
                {"capability": "embed", "provider": "local", "base_url": "", "model_name": ""},
                format="json",
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        detail = resp.data["data"]["detail"]
        self.assertEqual(resp.data["data"]["last_test_status"], "success")
        self.assertEqual(detail["model"], "BAAI/bge-m3")  # 留空补默认后再测
        self.assertIn("1024", detail["response"])

    def test_connection_test_local_rerank_success(self):
        class _FakeLocalRerank:
            name = "local"

            def rerank(self, query, documents, top_n=None):
                return [{"index": 1, "score": 0.91}, {"index": 0, "score": 0.2}]

        with patch("apps.platform_admin.views.build_provider", return_value=_FakeLocalRerank()):
            resp = self.client.post(
                "/api/admin-panel/ai-configuration/test/",
                {"capability": "rerank", "provider": "local", "base_url": "",
                 "model_name": "Qwen/Qwen3-Reranker-0.6B"},
                format="json",
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn("0.91", resp.data["data"]["detail"]["response"])
        record = AITestRecord.objects.get(capability="rerank")
        self.assertEqual(record.status, "success")
        self.assertEqual(record.provider, "local")
