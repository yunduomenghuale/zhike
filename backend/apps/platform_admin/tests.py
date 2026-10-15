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
from django.utils import timezone
from datetime import datetime, time as dtime, timedelta
from rest_framework.test import APIClient

from apps.ai.models import (
    AICallLog,
    AICapabilityChangeLog,
    AICapabilityConfig,
    AITestRecord,
)
from apps.ai.providers.factory import build_provider, chat_supports_vision, get_runtime_config
from apps.courses.models import Course

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
class AdminAICapabilityVisionTests(TestCase):
    """对话「支持图片（多模态）」开关：保存、GET 负载、非 chat 强制关闭、变更留痕。"""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_vision", password="pw123456!", role=User.Role.ADMIN
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
            "model_name": "qwen3.7-plus",
            "api_key": "sk-vision",
            "supports_vision": True,
        }
        item.update(overrides)
        return item

    def test_save_and_payload_and_runtime(self):
        """保存后落库、GET 负载带开关与模型名推断、chat_supports_vision 生效。"""
        resp = self._put([self._chat_item()])
        self.assertEqual(resp.status_code, 200, resp.data)

        self.assertTrue(AICapabilityConfig.objects.get(capability="chat").supports_vision)
        item = [i for i in self.client.get(URL).data["data"]["items"] if i["capability"] == "chat"][0]
        self.assertTrue(item["supports_vision"])
        # qwen3.7-plus 名称不带视觉特征：推断为 False 但开关为 True（实测支持视觉）
        self.assertFalse(item["model_suggests_vision"])
        self.assertTrue(chat_supports_vision())

    def test_supports_vision_forced_off_for_non_chat(self):
        """embed/tts 传 supports_vision 也被强制关闭（仅对话有意义）。"""
        resp = self._put([
            {
                "capability": "embed", "provider": "tongyi", "enabled": True,
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model_name": "text-embedding-v3", "api_key": "sk-embed",
                "supports_vision": True,
            },
            {
                "capability": "tts", "provider": "tongyi", "enabled": True,
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model_name": "qwen3-tts-flash", "api_key": "sk-tts",
                "supports_vision": True,
            },
        ])
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(AICapabilityConfig.objects.get(capability="embed").supports_vision)
        self.assertFalse(AICapabilityConfig.objects.get(capability="tts").supports_vision)
        self.assertFalse(chat_supports_vision())

    def test_change_log_records_supports_vision(self):
        """开关变更写入字段级留痕（回答「为什么某天起问答能发图片了」）。"""
        self._put([self._chat_item(supports_vision=False)])
        self._put([self._chat_item(supports_vision=True)])
        # 首次保存 False=默认值不产生 diff；仅第二次 True 记一条
        logs = [
            log for log in AICapabilityChangeLog.objects.filter(capability="chat")
            if any(c["field"] == "supports_vision" for c in log.changes)
        ]
        self.assertEqual(len(logs), 1)
        change = next(c for c in logs[0].changes if c["field"] == "supports_vision")
        self.assertEqual(change["label"], "支持图片")
        # 布尔旧值为 False 时按既有约定记空串（str(value or "")）
        self.assertEqual((change["old"], change["new"]), ("", "True"))


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


# ---------------------------------------------------------------------------
# AI 调用统计与追溯（流水 / 汇总 / 导出 / 配置变更记录）
# ---------------------------------------------------------------------------
class AdminAICallLogAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="admin_log", password="pw123456!", role=User.Role.ADMIN
        )
        self.teacher = User.objects.create_user(
            username="teacher_log", password="pw123456!", role=User.Role.TEACHER
        )
        self.student = User.objects.create_user(
            username="student_log", password="pw123456!", role=User.Role.STUDENT
        )
        self.course = Course.objects.create(name="Java 程序设计", teacher=self.teacher)
        now = timezone.now()

        # 近 7 天窗口内的正常流水（覆盖两类计量口径）
        AICallLog.objects.create(
            capability="chat", provider="deepseek", model_name="deepseek-chat",
            scene="qa", success=True, latency_ms=1200, attempts=1,
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
            input_digest="a" * 64, input_preview="你好", trace_id="trace-1",
            triggered_by=self.student, course=self.course,
        )
        AICallLog.objects.create(
            capability="chat", provider="mock", model_name="mock-chat",
            scene="script_gen", success=True, is_mock=True, latency_ms=30,
            input_digest="b" * 64, input_preview="生成讲稿", trace_id="trace-2",
            triggered_by=self.teacher, course=self.course,
        )
        AICallLog.objects.create(
            capability="embed", provider="tongyi", model_name="text-embedding-v3",
            scene="material_embed", success=True, latency_ms=800,
            item_count=10, input_chars=2000, total_tokens=None,
            input_digest="c" * 64, trace_id="trace-3",
        )
        # 失败调用（失败率告警数据）
        AICallLog.objects.create(
            capability="chat", provider="deepseek", model_name="deepseek-chat",
            scene="qa", success=False, latency_ms=5000, attempts=2,
            error="upstream timeout", input_digest="d" * 64, trace_id="trace-4",
            triggered_by=self.student, course=self.course,
        )
        # 超出默认 7 天窗口（应被默认过滤）；auto_now_add 会覆盖 create 传值，
        # 须先创建再 update 回填时间
        old_log = AICallLog.objects.create(
            capability="tts", provider="tongyi", model_name="cosyvoice",
            scene="tts", success=True, latency_ms=100,
        )
        AICallLog.objects.filter(pk=old_log.pk).update(
            created_at=now - timedelta(days=10)
        )

    # ---- 流水列表 ----

    def test_logs_list_default_window_and_pagination(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get("/api/admin-panel/ai-call-logs/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()["data"]
        self.assertEqual(body["total"], 4)  # 默认近 7 天，排除 10 天前那条
        self.assertLessEqual(len(body["items"]), body["page_size"])
        by_trace = {item["trace_id"]: item for item in body["items"]}
        self.assertEqual(by_trace["trace-1"]["capability"], "chat")
        self.assertEqual(by_trace["trace-1"]["triggered_by_name"], "student_log")
        self.assertEqual(by_trace["trace-1"]["course_name"], "Java 程序设计")

    def test_logs_list_filters(self):
        self.client.force_authenticate(user=self.admin)
        base = "/api/admin-panel/ai-call-logs/"
        cases = [
            ({"capability": "chat"}, 3),
            ({"scene": "qa"}, 2),
            ({"provider": "mock"}, 1),
            ({"success": "false"}, 1),
            ({"success": "true"}, 3),
            ({"triggered_by": str(self.student.id)}, 2),
            ({"course_id": str(self.course.id)}, 3),
            ({"keyword": "trace-3"}, 1),
            ({"keyword": "生成讲稿"}, 1),
        ]
        for params, expected in cases:
            resp = self.client.get(base, params)
            self.assertEqual(resp.status_code, 200, params)
            self.assertEqual(resp.json()["data"]["total"], expected, params)

    def test_logs_list_days_param_widens_window(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get("/api/admin-panel/ai-call-logs/", {"days": 30})
        self.assertEqual(resp.json()["data"]["total"], 5)

    # ---- 统计汇总 ----

    def test_stats_totals(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get("/api/admin-panel/ai-call-stats/", {"days": 7})
        self.assertEqual(resp.status_code, 200)
        totals = resp.json()["data"]["totals"]
        self.assertEqual(totals["calls"], 4)
        self.assertEqual(totals["success"], 3)
        self.assertEqual(totals["failed"], 1)
        self.assertEqual(totals["success_rate"], 0.75)
        self.assertEqual(totals["mock_calls"], 1)
        self.assertEqual(totals["prompt_tokens"], 100)
        self.assertEqual(totals["completion_tokens"], 50)
        self.assertEqual(totals["total_tokens"], 150)
        self.assertGreater(totals["p95_latency_ms"], 0)
        self.assertGreaterEqual(totals["avg_latency_ms"], 0)

    def test_stats_breakdowns_and_daily_and_top_users(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get("/api/admin-panel/ai-call-stats/", {"days": 7})
        data = resp.json()["data"]
        by_capability = {row["capability"]: row for row in data["by_capability"]}
        self.assertEqual(by_capability["chat"]["calls"], 3)
        self.assertEqual(by_capability["chat"]["failed"], 1)
        self.assertEqual(by_capability["chat"]["mock_calls"], 1)
        self.assertEqual(by_capability["chat"]["total_tokens"], 150)
        self.assertEqual(by_capability["embed"]["item_count"], 10)
        by_scene = {row["scene"]: row for row in data["by_scene"]}
        self.assertEqual(by_scene["qa"]["calls"], 2)
        self.assertEqual(len(data["daily"]), 1)
        self.assertEqual(data["daily"][0]["calls"], 4)
        top = {row["triggered_by"]: row for row in data["top_triggered_by"]}
        self.assertEqual(top[self.student.id]["calls"], 2)
        self.assertEqual(top[self.student.id]["failed"], 1)
        self.assertEqual(top[self.teacher.id]["calls"], 1)

    def test_stats_alerts_on_failure_and_mock_fallback(self):
        # 失败率告警要求 24h 内 >=5 次调用且失败率 >20%：补 1 次失败（2/5=40%）
        AICallLog.objects.create(
            capability="chat", provider="deepseek", model_name="deepseek-chat",
            scene="qa", success=False, latency_ms=100, error="boom",
        )
        # Mock 回退告警的判定是「真实服务商回退模拟」：is_mock=True 但 provider 非 mock
        AICallLog.objects.create(
            capability="chat", provider="deepseek", model_name="deepseek-chat",
            scene="qa", success=True, is_mock=True, latency_ms=5,
        )
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get("/api/admin-panel/ai-call-stats/", {"days": 7})
        alerts = resp.json()["data"]["alerts"]
        messages = [a["message"] for a in alerts]
        self.assertTrue(any("失败率" in m for m in messages))
        self.assertTrue(any("回退到模拟模式" in m for m in messages))

    def test_stats_empty_range_returns_nulls_not_500(self):
        AICallLog.objects.all().delete()
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get("/api/admin-panel/ai-call-stats/", {"days": 1})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["totals"]["calls"], 0)
        self.assertIsNone(data["totals"]["success_rate"])
        self.assertEqual(data["by_capability"], [])
        self.assertEqual(data["alerts"], [])

    # ---- 自定义窗口（start/end 日历窗）与上周期对比 ----

    def _today(self):
        return timezone.now().astimezone(timezone.get_current_timezone()).date()

    def _backfill(self, log, day, hour=12):
        """auto_now_add 会覆盖 create 传值，须先创建再 update 回填到指定本地日期。"""
        tz = timezone.get_current_timezone()
        moment = timezone.make_aware(datetime.combine(day, dtime(hour, 0, 0)), tz)
        AICallLog.objects.filter(pk=log.pk).update(created_at=moment)

    def test_stats_custom_range_window_with_previous_period(self):
        today = self._today()
        yesterday = today - timedelta(days=1)
        # 上周期基线数据：1 条回填到昨天中午
        prev_log = AICallLog.objects.create(
            capability="chat", provider="deepseek", model_name="deepseek-chat",
            scene="qa", success=True, latency_ms=2000,
            input_digest="e" * 64, trace_id="trace-prev",
        )
        self._backfill(prev_log, yesterday)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(
            "/api/admin-panel/ai-call-stats/",
            {"start": today.isoformat(), "end": today.isoformat()},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        window = data["window"]
        self.assertEqual(window["days"], 1)
        self.assertEqual(window["source"], "range")
        self.assertTrue(window["start"].startswith(today.isoformat()))
        self.assertTrue(window["end"].startswith(today.isoformat()))
        self.assertEqual(data["totals"]["calls"], 4)  # 当天 4 条
        # 上周期 = 紧邻今天前一段等长周期（昨天全天）
        self.assertEqual(data["totals_previous"]["calls"], 1)
        self.assertTrue(window["previous_start"].startswith(yesterday.isoformat()))
        self.assertTrue(window["previous_end"].startswith(yesterday.isoformat()))
        prev_daily = {row["day"]: row for row in data["daily_previous"]}
        self.assertEqual(prev_daily[yesterday.isoformat()]["calls"], 1)

    def test_stats_start_end_takes_priority_over_days(self):
        today = self._today()
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(
            "/api/admin-panel/ai-call-stats/",
            {"start": today.isoformat(), "end": today.isoformat(), "days": 30},
        )
        data = resp.json()["data"]
        self.assertEqual(data["window"]["source"], "range")
        self.assertEqual(data["window"]["days"], 1)
        # days=30 被忽略：10 天前那条仍不入窗
        self.assertEqual(data["totals"]["calls"], 4)

    def test_stats_range_with_single_side_defaults(self):
        today = self._today()
        self.client.force_authenticate(user=self.admin)
        for params in ({"start": today.isoformat()}, {"end": today.isoformat()}):
            resp = self.client.get("/api/admin-panel/ai-call-stats/", params)
            self.assertEqual(resp.status_code, 200, params)
            data = resp.json()["data"]
            self.assertEqual(data["window"]["days"], 1, params)
            self.assertEqual(data["totals"]["calls"], 4, params)

    def test_stats_future_end_truncated_to_now(self):
        today = self._today()
        future = today + timedelta(days=5)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(
            "/api/admin-panel/ai-call-stats/",
            {"start": today.isoformat(), "end": future.isoformat()},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["window"]["days"], 6)  # 跨度仍按请求的 6 天计
        self.assertEqual(data["totals"]["calls"], 4)  # 当天数据仍在（截断不丢已积累数据）

    def test_logs_list_custom_range_window(self):
        today = self._today()
        yesterday = today - timedelta(days=1)
        prev_log = AICallLog.objects.create(
            capability="chat", provider="deepseek", model_name="deepseek-chat",
            scene="qa", success=True, latency_ms=100,
            input_digest="f" * 64, trace_id="trace-yesterday",
        )
        self._backfill(prev_log, yesterday)
        self.client.force_authenticate(user=self.admin)
        base = "/api/admin-panel/ai-call-logs/"
        resp = self.client.get(base, {"start": today.isoformat(), "end": today.isoformat()})
        self.assertEqual(resp.json()["data"]["total"], 4)
        resp = self.client.get(base, {"start": yesterday.isoformat(), "end": yesterday.isoformat()})
        self.assertEqual(resp.json()["data"]["total"], 1)

    def test_invalid_window_returns_400(self):
        today = self._today()
        too_long_start = (today - timedelta(days=400)).isoformat()
        cases = [
            ({"start": "2026-13-01"}, "日期格式不正确"),
            ({"start": "not-a-date"}, "日期格式不正确"),
            ({"start": (today + timedelta(days=1)).isoformat(), "end": today.isoformat()}, "开始日期不能晚于结束日期"),
            ({"start": too_long_start, "end": today.isoformat()}, "时间范围不能超过"),
        ]
        self.client.force_authenticate(user=self.admin)
        for params, expect in cases:
            for url in (
                "/api/admin-panel/ai-call-stats/",
                "/api/admin-panel/ai-call-logs/",
                "/api/admin-panel/ai-call-logs/export/",
            ):
                resp = self.client.get(url, params)
                self.assertEqual(resp.status_code, 400, (url, params))
                self.assertIn(expect, resp.json()["message"], (url, params))

    def test_by_scene_rows_carry_business_group(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get("/api/admin-panel/ai-call-stats/", {"days": 7})
        by_scene = {row["scene"]: row for row in resp.json()["data"]["by_scene"]}
        self.assertEqual(by_scene["qa"]["group"], "学生学习")
        self.assertEqual(by_scene["script_gen"]["group"], "授课生产")
        self.assertEqual(by_scene["material_embed"]["group"], "知识库")

    def test_daily_rows_have_avg_latency_and_iso_day(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get("/api/admin-panel/ai-call-stats/", {"days": 7})
        daily = resp.json()["data"]["daily"]
        self.assertEqual(len(daily), 1)
        row = daily[0]
        self.assertRegex(row["day"], r"^\d{4}-\d{2}-\d{2}$")
        # 4 条延迟 1200/30/800/5000 → 均值 1757.5 → int 1757
        self.assertEqual(row["avg_latency_ms"], 1757)
        self.assertEqual(row["failed"], 1)
        self.assertEqual(row["total_tokens"], 150)

    # ---- CSV 导出 ----

    def test_export_csv_has_bom_and_rows(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get("/api/admin-panel/ai-call-logs/export/", {"days": 7})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        content = resp.content.decode("utf-8-sig")
        lines = [line for line in content.splitlines() if line.strip()]
        self.assertEqual(len(lines), 5)  # 表头 + 4 条
        self.assertIn("追溯ID", lines[0])
        self.assertTrue(any("upstream timeout" in line for line in lines))

    # ---- 配置变更记录 ----

    def test_config_change_log_records_field_diff_without_key(self):
        self.client.force_authenticate(user=self.admin)
        # 首次创建即以默认值为旧值记录 diff
        cfg = AICapabilityConfig.objects.create(
            capability="chat", provider="deepseek",
            model_name="deepseek-chat", base_url="https://api.deepseek.com",
        )
        # 更新模型 + 首次配置 Key（updated_by 模拟序列化器保存前写入）
        cfg.model_name = "deepseek-reasoner"
        cfg.set_api_key("sk-new-secret")
        cfg.updated_by = self.admin
        cfg.save()

        resp = self.client.get("/api/admin-panel/ai-config-changes/")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["data"]["items"]
        self.assertGreaterEqual(len(items), 1)
        latest = items[0]  # 按创建时间倒序
        changes = latest["changes"]
        serialized = str(changes)
        self.assertNotIn("sk-new-secret", serialized)
        by_field = {c["field"]: c for c in changes}
        self.assertEqual(set(by_field), {"model_name", "api_key"})
        self.assertEqual(by_field["model_name"]["old"], "deepseek-chat")
        self.assertEqual(by_field["model_name"]["new"], "deepseek-reasoner")
        self.assertEqual(by_field["api_key"]["old"], "未配置")
        self.assertEqual(by_field["api_key"]["new"], "已配置")
        self.assertEqual(latest["changed_by_name"], "admin_log")

    def test_config_change_log_filter_by_capability(self):
        AICapabilityChangeLog.objects.create(
            capability="chat", changes=[{"field": "model_name", "old": "a", "new": "b"}]
        )
        AICapabilityChangeLog.objects.create(
            capability="embed", changes=[{"field": "model_name", "old": "a", "new": "b"}]
        )
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(
            "/api/admin-panel/ai-config-changes/", {"capability": "embed"}
        )
        self.assertEqual(resp.json()["data"]["total"], 1)

    # ---- 权限 ----

    def test_non_admin_forbidden(self):
        for user in (self.teacher, self.student):
            self.client.force_authenticate(user=user)
            for url in (
                "/api/admin-panel/ai-call-logs/",
                "/api/admin-panel/ai-call-logs/export/",
                "/api/admin-panel/ai-call-stats/",
                "/api/admin-panel/ai-config-changes/",
            ):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 403, (user.username, url))

    def test_anonymous_unauthorized(self):
        resp = self.client.get("/api/admin-panel/ai-call-stats/")
        self.assertIn(resp.status_code, (401, 403))
