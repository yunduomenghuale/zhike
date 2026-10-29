"""管理端大模型配置（按能力）保存/回退行为测试。

覆盖「保存并应用」的关键路径：
- API Key 留空时回退环境变量已生效 Key 并物化进数据库（保存后不回落 mock）；
- 环境变量也没有 Key / 切换服务商时拒绝保存；
- 显式填写 Key 的新建与更新；
- 配置要素未变时保留历史测试结论，变更则作废。
"""
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import caches
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
from apps.ai.services import IMAGE_ONLY_DEFAULT_QUESTION, knowledge_qa
from apps.courses.models import Course
from apps.knowledge.models import QARecord

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

    def test_audit_log_records_supports_vision_change(self):
        """开关变更写入单一审计轨（AdminActionLog.ai_config_save 字段级 diff）。

        审计双轨合并后模型层停写 AICapabilityChangeLog，留痕只落审计表。
        """
        self._put([self._chat_item(supports_vision=False)])
        self._put([self._chat_item(supports_vision=True)])
        # 首次保存 False=默认值不产生 diff；仅第二次 True 记一条
        logs = [
            log for log in AdminActionLog.objects.filter(
                action=AdminActionLog.Action.AI_CONFIG_SAVE)
            if any(
                g["capability"] == "chat"
                and any(c["field"] == "supports_vision" for c in g["changes"])
                for g in (log.new_value or {}).get("changes", [])
            )
        ]
        self.assertEqual(len(logs), 1)
        group = next(
            g for g in logs[0].new_value["changes"] if g["capability"] == "chat"
        )
        change = next(c for c in group["changes"] if c["field"] == "supports_vision")
        self.assertEqual(change["label"], "支持图片")
        # 布尔旧值为 False 时按既有约定记空串（str(value or "")）
        self.assertEqual((change["old"], change["new"]), ("", "True"))
        self.assertEqual(group["capability_display"], "对话生成")
        # 模型层不再双写 AICapabilityChangeLog（单一审计轨）
        self.assertFalse(AICapabilityChangeLog.objects.exists())

    def test_model_save_alone_writes_no_changelog(self):
        """单一审计轨：绕过视图直接 save 模型不再产生任何留痕（diff 由视图采集）。"""
        AICapabilityConfig.objects.create(
            capability="chat", provider="deepseek", model_name="deepseek-chat"
        )
        cfg = AICapabilityConfig.objects.get(capability="chat")
        cfg.model_name = "deepseek-reasoner"
        cfg.save()
        self.assertFalse(AICapabilityChangeLog.objects.exists())
        self.assertFalse(
            AdminActionLog.objects.filter(action=AdminActionLog.Action.AI_CONFIG_SAVE).exists()
        )


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

    def test_audit_log_records_field_diff_without_key(self):
        """保存写入单一审计轨：字段级 old→new，API Key 只记存在性不落明文。"""
        self.client.force_authenticate(user=self.admin)
        # 首次保存（停用状态免 Key 校验）：以默认值为旧值
        resp = self.client.put(URL, {"capabilities": [{
            "capability": "chat", "provider": "deepseek", "enabled": False,
            "base_url": "https://api.deepseek.com", "model_name": "deepseek-chat",
        }]}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        # 更新模型 + 首次配置 Key（仍停用：diff 只含这两项）
        resp = self.client.put(URL, {"capabilities": [{
            "capability": "chat", "provider": "deepseek", "enabled": False,
            "base_url": "https://api.deepseek.com", "model_name": "deepseek-reasoner",
            "api_key": "sk-new-secret",
        }]}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)

        latest = AdminActionLog.objects.filter(
            action=AdminActionLog.Action.AI_CONFIG_SAVE).order_by("-id").first()
        self.assertEqual(latest.actor, self.admin)
        self.assertEqual(latest.target_label, "对话生成")
        self.assertEqual(latest.new_value["capabilities"], ["chat"])
        group = next(g for g in latest.new_value["changes"] if g["capability"] == "chat")
        by_field = {c["field"]: c for c in group["changes"]}
        self.assertEqual(set(by_field), {"model_name", "api_key"})
        self.assertEqual(by_field["model_name"]["old"], "deepseek-chat")
        self.assertEqual(by_field["model_name"]["new"], "deepseek-reasoner")
        self.assertEqual(by_field["api_key"]["old"], "未配置")
        self.assertEqual(by_field["api_key"]["new"], "已配置")
        self.assertNotIn("sk-new-secret", str(latest.new_value))
        # 单一审计轨：模型层未双写 AICapabilityChangeLog
        self.assertFalse(AICapabilityChangeLog.objects.exists())

    def test_config_change_log_filter_by_capability(self):
        """遗留端点（仅查合并前存量）：按能力筛选 AICapabilityChangeLog。"""
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


# ---------------------------------------------------------------------------
# 督管增强（趋势/异常/三维监管/操作审计）——2026-10-19
# ---------------------------------------------------------------------------
from apps.classroom.models import ClassRoom, ClassStudent  # noqa: E402
from apps.courses.models import Catalog, PPTResource  # noqa: E402
from apps.courses.terms import ensure_term  # noqa: E402
from apps.exams.models import Exam, ExamSubmission  # noqa: E402
from apps.homework.models import Homework, HomeworkSubmission  # noqa: E402

from .models import AdminActionLog  # noqa: E402


class OversightFixtureMixin:
    """督管测试公共数据：管理员/教师/学生 + 课程/班级/章节。"""

    def setUp(self):
        # 概览缓存（trends/alerts 短 TTL）切到 LocMem 并在每个用例前清空，
        # 避免跨用例读到上一次的聚合结果（如 test_trends_counts_today 依赖新造用户）
        self._oversight_cache_ctx = override_settings(
            CACHES={
                **settings.CACHES,
                "oversight": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
            }
        )
        self._oversight_cache_ctx.enable()
        self.addCleanup(self._oversight_cache_ctx.disable)
        caches["oversight"].clear()

        self.admin = User.objects.create_user(
            username="admin_ov", password="pw123456!", role=User.Role.ADMIN
        )
        self.teacher = User.objects.create_user(
            username="t_ov", password="pw123456!", role=User.Role.TEACHER,
            real_name="督管教师",
        )
        self.student = User.objects.create_user(
            username="s_ov", password="pw123456!", role=User.Role.STUDENT,
            real_name="督管学生",
        )
        self.course = Course.objects.create(
            name="督管课程", teacher=self.teacher, term=ensure_term("2026秋")
        )
        self.classroom = ClassRoom.objects.create(
            name="督管班级", teacher=self.teacher
        )
        self.classroom.courses.add(self.course)
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        self.catalog = Catalog.objects.create(
            course=self.course, title="第一章", order=1
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)


class OversightOverviewTests(OversightFixtureMixin, TestCase):
    """A1 趋势 / A2 待办异常。"""

    def test_trends_zero_filled_and_summary(self):
        resp = self.client.get("/api/admin-panel/overview/trends/", {"days": 7})
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.data["data"]
        self.assertIn(len(data["daily"]), (7, 8))  # 滚动窗跨 7~8 个日历日
        for field in ("new_users", "new_courses", "new_classes", "active_students"):
            self.assertIn(field, data["daily"][0])
            self.assertIn(field, data["summary"])
            self.assertIn("delta", data["summary"][field])

    def test_trends_counts_today(self):
        User.objects.create_user(username="s_new", password="pw123456!", role=User.Role.STUDENT)
        resp = self.client.get("/api/admin-panel/overview/trends/", {"days": 1})
        today = resp.data["data"]["daily"][-1]["date"]
        row = resp.data["data"]["daily"][-1]
        self.assertGreaterEqual(row["new_users"], 1, (today, row))

    def test_trends_days_out_of_range(self):
        self.assertEqual(self.client.get(
            "/api/admin-panel/overview/trends/", {"days": 400}).status_code, 400)
        # 非法值回退默认 30 天（与 _page_params 的宽容策略一致）
        resp = self.client.get("/api/admin-panel/overview/trends/", {"days": "abc"})
        self.assertEqual(resp.data["data"]["days"], 30)

    def test_alerts_counts(self):
        # 待批改作业 1 份
        hw = Homework.objects.create(
            classroom=self.classroom, course=self.course, title="作业甲",
            status=Homework.Status.PUBLISHED,
        )
        HomeworkSubmission.objects.create(homework=hw, student=self.student)
        # 成绩未发布考试 1 场
        exam = Exam.objects.create(
            course=self.course, classroom=self.classroom, name="考试甲",
            status=Exam.Status.FINISHED,
        )
        ExamSubmission.objects.create(
            exam=exam, student=self.student,
            status=ExamSubmission.Status.SUBMITTED, score_released=False,
        )
        # 解析失败课件 1 部
        PPTResource.objects.create(
            course=self.course, catalog=self.catalog, file_name="坏课件.pptx",
            parse_status=PPTResource.ParseStatus.FAILED,
        )
        items = {i["key"]: i for i in
                 self.client.get("/api/admin-panel/overview/alerts/").data["data"]["items"]}
        self.assertEqual(items["pending_grading"]["count"], 1)
        self.assertEqual(items["unreleased_exams"]["count"], 1)
        self.assertEqual(items["failed_ppt"]["count"], 1)
        self.assertTrue(all("jump_url" in i for i in items.values()))

    def test_trends_cached_second_call_is_hit(self):
        from apps.platform_admin import services

        calls = []
        real = services.platform_trends

        def counting(days):
            calls.append(days)
            return real(days)

        with patch.object(services, "platform_trends", counting):
            r1 = self.client.get("/api/admin-panel/overview/trends/", {"days": 7})
            r2 = self.client.get("/api/admin-panel/overview/trends/", {"days": 7})
            r3 = self.client.get("/api/admin-panel/overview/trends/", {"days": 30})
        # days=7 第二次命中缓存（不重算），days=30 是另一个 key 正常重算
        self.assertEqual(calls, [7, 30])
        self.assertEqual(r1.data["data"], r2.data["data"])

    def test_alerts_cached_second_call_is_hit(self):
        from apps.platform_admin import services

        calls = []
        real = services.platform_alerts

        def counting():
            calls.append(1)
            return real()

        with patch.object(services, "platform_alerts", counting):
            r1 = self.client.get("/api/admin-panel/overview/alerts/")
            r2 = self.client.get("/api/admin-panel/overview/alerts/")
        self.assertEqual(calls, [1])
        self.assertEqual(r1.data["data"], r2.data["data"])

    def test_cache_key_and_version_prefix(self):
        from apps.platform_admin.services import _CACHE_VERSION, cached_platform_trends

        cached_platform_trends(7)
        self.assertIsNotNone(caches["oversight"].get(f"{_CACHE_VERSION}:trends:7"))
        self.assertIsNone(caches["oversight"].get(f"{_CACHE_VERSION}:trends:30"))


class OversightCourseTests(OversightFixtureMixin, TestCase):
    """A3/A4 课程监管。"""

    def test_course_list_asset_counts(self):
        PPTResource.objects.create(
            course=self.course, catalog=self.catalog, file_name="课件.pptx",
            parse_status=PPTResource.ParseStatus.DONE,
        )
        items = self.client.get(
            "/api/admin-panel/courses/", {"page_size": 10}).data["data"]["items"]
        row = next(i for i in items if i["id"] == self.course.id)
        self.assertEqual(row["catalog_count"], 1)
        self.assertEqual(row["ppt_count"], 1)
        self.assertIn("last_content_update", row)

    def test_course_detail_structure(self):
        hw = Homework.objects.create(
            classroom=self.classroom, course=self.course, title="作业甲",
            status=Homework.Status.PUBLISHED,
        )
        HomeworkSubmission.objects.create(homework=hw, student=self.student)
        data = self.client.get(
            f"/api/admin-panel/courses/{self.course.id}/detail/").data["data"]
        self.assertEqual(data["name"], "督管课程")
        self.assertEqual(data["stats"]["catalogs"], 1)
        self.assertEqual(len(data["catalog_tree"]), 1)
        self.assertEqual(data["catalog_tree"][0]["ppt_status"], None)
        self.assertEqual(len(data["homeworks"]), 1)
        self.assertEqual(data["homeworks"][0]["submitted"], 1)
        self.assertEqual(len(data["classes"]), 1)
        self.assertIn("homework_rate", data["classes"][0])

    def test_course_status_change_audit_and_affected(self):
        resp = self.client.patch(
            f"/api/admin-panel/courses/{self.course.id}/status/",
            {"status": "archived"}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["data"]["status"], "archived")
        self.assertEqual(resp.data["data"]["affected"]["classes"], 1)
        self.assertEqual(resp.data["data"]["affected"]["students"], 1)
        log = AdminActionLog.objects.get(action=AdminActionLog.Action.COURSE_STATUS)
        self.assertEqual(log.old_value, {"status": "active"})
        self.assertEqual(log.new_value, {"status": "archived"})
        self.assertEqual(log.actor, self.admin)

    def test_course_status_no_change_no_audit(self):
        self.client.patch(
            f"/api/admin-panel/courses/{self.course.id}/status/",
            {"status": "active"}, format="json",
        )
        self.assertEqual(AdminActionLog.objects.count(), 0)


class OversightClassTests(OversightFixtureMixin, TestCase):
    """A6/A7/A8 班级监管：复用教师端聚合 + 干预审计。"""

    def test_class_detail_matches_teacher_endpoint(self):
        """平台端班级详情与教师端学情统计口径一致（复用同一聚合实现）。"""
        teacher_client = APIClient()
        teacher_client.force_authenticate(user=self.teacher)
        teacher_resp = teacher_client.get(f"/api/analytics/class/{self.classroom.id}/")
        self.assertEqual(teacher_resp.status_code, 200, teacher_resp.data)
        admin_resp = self.client.get(
            f"/api/admin-panel/classes/{self.classroom.id}/detail/")
        self.assertEqual(admin_resp.status_code, 200, admin_resp.data)
        self.assertEqual(
            admin_resp.data["data"]["summary"], teacher_resp.data["data"]["summary"]
        )
        self.assertEqual(
            admin_resp.data["data"]["students"], teacher_resp.data["data"]["students"]
        )

    def test_class_status_change_audit(self):
        resp = self.client.patch(
            f"/api/admin-panel/classes/{self.classroom.id}/status/",
            {"status": "archived"}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["data"]["status"], "archived")
        self.assertIn("affected", resp.data["data"])
        self.assertEqual(AdminActionLog.objects.filter(
            action=AdminActionLog.Action.CLASS_STATUS).count(), 1)

    def test_class_status_invalid_no_audit(self):
        resp = self.client.patch(
            f"/api/admin-panel/classes/{self.classroom.id}/status/",
            {"status": "bogus"}, format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(AdminActionLog.objects.count(), 0)

    def test_class_list_progress_summary(self):
        hw = Homework.objects.create(
            classroom=self.classroom, course=self.course, title="作业甲",
            status=Homework.Status.PUBLISHED,
        )
        HomeworkSubmission.objects.create(homework=hw, student=self.student)
        items = self.client.get(
            "/api/admin-panel/classes/", {"page_size": 10}).data["data"]["items"]
        row = next(i for i in items if i["id"] == self.classroom.id)
        self.assertEqual(row["homework_rate"], 100)
        self.assertEqual(row["warning_count"], 0)


class OversightTeacherTests(OversightFixtureMixin, TestCase):
    """A9/A10 教师监管。"""

    def test_teacher_list_counts(self):
        items = self.client.get("/api/admin-panel/teachers/").data["data"]["items"]
        row = next(i for i in items if i["id"] == self.teacher.id)
        self.assertEqual(row["course_count"], 1)
        self.assertEqual(row["class_count"], 1)
        self.assertEqual(row["student_count"], 1)
        self.assertIn("ai_calls", row)

    def test_teacher_list_search(self):
        items = self.client.get(
            "/api/admin-panel/teachers/", {"search": "督管"}).data["data"]["items"]
        self.assertEqual(len(items), 1)

    def test_teacher_detail(self):
        data = self.client.get(
            f"/api/admin-panel/teachers/{self.teacher.id}/detail/").data["data"]
        self.assertEqual(data["username"], "t_ov")
        self.assertEqual(len(data["courses"]), 1)
        self.assertEqual(len(data["classes"]), 1)
        self.assertEqual(data["ai_by_capability"], [])


class OversightAuditTests(OversightFixtureMixin, TestCase):
    """A12 操作审计 + 存量写操作埋点。"""

    def test_user_create_update_reset_audit(self):
        # 创建
        resp = self.client.post("/api/admin-panel/users/", {
            "username": "s_audit", "real_name": "审计生",
            "role": "student", "password": "pw123456!",
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        uid = resp.data["data"]["id"]
        log = AdminActionLog.objects.get(action=AdminActionLog.Action.USER_CREATE)
        self.assertEqual(log.target_id, uid)
        # 编辑（字段 diff）
        self.client.patch(f"/api/admin-panel/users/{uid}/",
                          {"real_name": "审计生改"}, format="json")
        log = AdminActionLog.objects.get(action=AdminActionLog.Action.USER_UPDATE)
        self.assertEqual(log.new_value["real_name"], {"old": "审计生", "new": "审计生改"})
        # 无字段变化的编辑不落库
        count = AdminActionLog.objects.count()
        self.client.patch(f"/api/admin-panel/users/{uid}/",
                          {"real_name": "审计生改"}, format="json")
        self.assertEqual(AdminActionLog.objects.count(), count)
        # 重置密码
        self.client.post(f"/api/admin-panel/users/{uid}/reset-password/",
                         {"password": "pw654321!"}, format="json")
        self.assertEqual(AdminActionLog.objects.filter(
            action=AdminActionLog.Action.USER_RESET_PWD).count(), 1)

    def test_import_confirm_audit(self):
        resp = self.client.post("/api/admin-panel/users/import-confirm/", {
            "rows": [{"username": "imp001", "real_name": "导入生"}],
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        log = AdminActionLog.objects.get(action=AdminActionLog.Action.USER_IMPORT)
        # 审计明细统一口径：账号数 / 新建班级 / 入班人数（P2 导入 service 起）
        self.assertEqual(log.new_value["created_users"], 1)

    def test_import_failed_no_audit(self):
        resp = self.client.post("/api/admin-panel/users/import-confirm/", {
            "rows": [{"username": "x", "real_name": "太短"}],
        }, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(AdminActionLog.objects.count(), 0)

    def test_action_log_filters(self):
        AdminActionLog.objects.create(
            actor=self.admin, action=AdminActionLog.Action.COURSE_STATUS,
            target_type="course", target_id=1, target_label="课程A",
            old_value={"status": "active"}, new_value={"status": "archived"},
        )
        resp = self.client.get("/api/admin-panel/action-logs/",
                               {"action": "course_status"})
        self.assertEqual(resp.data["data"]["total"], 1)
        item = resp.data["data"]["items"][0]
        self.assertEqual(item["action_display"], "课程状态变更")
        self.assertEqual(item["actor_name"], "admin_ov")

    def test_export_csv_has_bom(self):
        for url in ("/api/admin-panel/courses/export/",
                    "/api/admin-panel/classes/export/",
                    "/api/admin-panel/teachers/export/",
                    "/api/admin-panel/action-logs/export/"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            self.assertTrue(resp.content.startswith(b"\xef\xbb\xbf"), url)

    def test_export_csv_renders_ai_config_changes(self):
        """CSV 变更列渲染 ai_config_save 的按能力分组 diff（单一审计轨形状）。"""
        AdminActionLog.objects.create(
            actor=self.admin, action=AdminActionLog.Action.AI_CONFIG_SAVE,
            target_type="ai_config", target_label="对话生成",
            new_value={
                "capabilities": ["chat"],
                "changes": [{
                    "capability": "chat",
                    "capability_display": "对话生成",
                    "changes": [
                        {"field": "model_name", "label": "模型名称", "old": "a", "new": "b"},
                        {"field": "api_key", "label": "API Key", "old": "未配置", "new": "已配置"},
                    ],
                }],
            },
        )
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get("/api/admin-panel/action-logs/export/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8-sig")
        self.assertIn("对话生成·模型名称: a → b", content)
        self.assertIn("对话生成·API Key: 未配置 → 已配置", content)


class OversightPermissionTests(OversightFixtureMixin, TestCase):
    """新端点全部仅平台管理员可用。"""

    URLS = (
        "/api/admin-panel/overview/trends/",
        "/api/admin-panel/overview/alerts/",
        "/api/admin-panel/courses/",
        "/api/admin-panel/courses/export/",
        f"/api/admin-panel/classes/",
        "/api/admin-panel/classes/export/",
        "/api/admin-panel/teachers/",
        "/api/admin-panel/teachers/export/",
        "/api/admin-panel/action-logs/",
        "/api/admin-panel/action-logs/export/",
    )

    def test_non_admin_forbidden(self):
        for user in (self.teacher, self.student):
            self.client.force_authenticate(user=user)
            for url in self.URLS:
                self.assertEqual(self.client.get(url).status_code, 403, (user.username, url))

    def test_anonymous_unauthorized(self):
        self.client.force_authenticate(user=None)
        for url in self.URLS[:3]:
            self.assertIn(self.client.get(url).status_code, (401, 403))


# ---------------------------------------------------------------------------
# 管理端限流（督管增强三期）：分档计数 / 429 本地化 / scope 独立 / 可整体关闭
# 注意：manage.py test 下 settings 已默认将各档位置 None（防跨用例累积），
# 本类用 override_settings 重新开启小额度进行验证。
# ---------------------------------------------------------------------------
from django.core.cache import cache as django_cache  # noqa: E402

THROTTLE_ON = {
    "ADMIN_THROTTLE_RATES": {
        "admin_read": "3/min",
        "admin_write": "2/min",
        "admin_export": "1/min",
        "admin_heavy": "1/min",
    }
}
THROTTLE_OFF = {
    "ADMIN_THROTTLE_RATES": {
        "admin_read": None,
        "admin_write": None,
        "admin_export": None,
        "admin_heavy": None,
    }
}


@override_settings(**THROTTLE_ON)
class AdminThrottleTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_thr", password="pw123456!", role=User.Role.ADMIN
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        django_cache.clear()  # 清掉历史计数，保证用例间独立

    def test_read_scope_throttled_after_limit(self):
        url = "/api/admin-panel/overview/"
        codes = [self.client.get(url).status_code for _ in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])

    def test_429_payload_localized_with_retry_after(self):
        url = "/api/admin-panel/overview/"
        for _ in range(3):
            self.client.get(url)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.data["code"], 429)
        self.assertIn("操作过于频繁", resp.data["message"])
        self.assertIn("Retry-After", resp.headers)

    def test_scopes_are_counted_independently(self):
        # 读档打满后，重操作档仍有自己的额度（不同 scope 独立计数）
        for _ in range(3):
            self.client.get("/api/admin-panel/overview/")
        heavy = self.client.post("/api/admin-panel/users/import-preview/", {}, format="json")
        self.assertNotEqual(heavy.status_code, 429)
        # 重操作档额度=1/min，第二次即被限流
        self.assertEqual(
            self.client.post("/api/admin-panel/users/import-preview/", {}, format="json").status_code,
            429,
        )

    def test_export_scope_separate_from_read(self):
        # 导出档（1/min）与读档独立：导出一次后读仍可用，再次导出被限流
        self.assertEqual(self.client.get("/api/admin-panel/courses/export/").status_code, 200)
        self.assertEqual(self.client.get("/api/admin-panel/courses/export/").status_code, 429)
        self.assertEqual(self.client.get("/api/admin-panel/overview/").status_code, 200)

    def test_permission_denied_does_not_consume_bucket(self):
        # 权限校验先于限流（DRF initial 顺序）：非管理员 403 不消耗 admin 的读档额度
        teacher = User.objects.create_user(
            username="t_thr", password="pw123456!", role=User.Role.TEACHER
        )
        self.client.force_authenticate(user=teacher)
        self.assertEqual(self.client.get("/api/admin-panel/overview/").status_code, 403)
        self.client.force_authenticate(user=self.admin)
        codes = [self.client.get("/api/admin-panel/overview/").status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 200])

    @override_settings(**THROTTLE_OFF)
    def test_rates_none_disables_throttling(self):
        url = "/api/admin-panel/overview/"
        codes = [self.client.get(url).status_code for _ in range(10)]
        self.assertEqual(set(codes), {200})


# ---------------------------------------------------------------------------
# 问答质量看板（qa-quality-stats）指标口径与告警测试（2026-10-22）
# ---------------------------------------------------------------------------
QA_STATS_URL = "/api/admin-panel/qa-quality-stats/"


class _FakeChatProvider:
    """knowledge_qa 测试替身：只实现 chat 签名，避免依赖真实/模拟 Provider。"""

    def chat(self, messages, **kwargs):
        return "测试回答"


@override_settings(**THROTTLE_OFF)
class AdminQAQualityStatsTests(TestCase):
    """问答质量统计端点：窗口 / 指标口径 / 环比基线 / 告警 / 权限。"""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_qa", password="pw123456!", role=User.Role.ADMIN
        )
        self.teacher = User.objects.create_user(
            username="teacher_qa", password="pw123456!",
            role=User.Role.TEACHER, real_name="测试教师",
        )
        self.student = User.objects.create_user(
            username="student_qa", password="pw123456!", role=User.Role.STUDENT
        )
        self.course = Course.objects.create(name="测试课程", teacher=self.teacher)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _qa(self, *, cited=None, skip=False, rewritten="", feedback=0, snapshot=None, course=None):
        return QARecord.objects.create(
            course=course or self.course,
            student=self.student,
            question="测试问题",
            answer="测试回答",
            cited_chunks=[] if cited is None else cited,
            rewritten_question=rewritten,
            context_snapshot=snapshot or {},
            feedback=feedback,
            skip_retrieval=skip,
        )

    def _data(self, **params):
        resp = self.client.get(QA_STATS_URL, params)
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data["data"]

    # ---------- 基础结构 ----------

    def test_empty_database_returns_zero_and_none_rates(self):
        data = self._data()
        self.assertEqual(data["totals"]["questions"], 0)
        self.assertIsNone(data["totals"]["empty_retrieval"]["rate"])
        self.assertIsNone(data["totals"]["rewrite"]["rate"])
        self.assertIsNone(data["totals"]["feedback"]["rate"])
        self.assertIsNone(data["totals"]["feedback"]["coverage"])
        self.assertIsNone(data["totals"]["fallback"]["rate"])
        self.assertEqual(data["degraded"]["L0"], 0)
        self.assertEqual(data["by_course"], [])
        self.assertEqual(data["daily"], [])
        self.assertEqual(data["by_source"], {})
        self.assertEqual(data["alerts"], [])
        self.assertEqual(data["totals"]["cost"]["total_tokens"], 0)

    def test_window_params_in_source(self):
        data = self._data(days=30)
        self.assertEqual(data["window"]["days"], 30)
        self.assertEqual(data["window"]["source"], "days")
        self.assertIn("previous_start", data["window"])
        self.assertIn("previous_end", data["window"])

    # ---------- 指标口径 ----------

    def test_metric_definitions(self):
        """五条记录覆盖全部指标：空检索 / 图片跳过 / 改写 / 反馈 / 兜底 / 降级 / 来源。"""
        self._qa(cited=[], skip=False)                                   # 检索为空
        self._qa(cited=[], skip=True)                                    # 图片默认文案：不进为空分母
        self._qa(                                                         # 全指标记录
            cited=[{"n": 1, "source": "material"}],
            rewritten="改写后的问题", feedback=1,
            snapshot={"degraded_level": 4, "fallback_used": True},
        )
        self._qa(                                                         # 双来源 + 差评 + L1
            cited=[{"n": 1, "source": "script"}, {"n": 2, "source": "ppt"}],
            feedback=-1, snapshot={"degraded_level": 1},
        )
        self._qa(cited=[{"n": 1, "source": "material"}])                 # 正常无反馈
        AICallLog.objects.create(
            capability="chat", provider="tongyi", scene="qa", success=True,
            prompt_tokens=100, completion_tokens=20, total_tokens=120,
        )
        data = self._data()
        totals = data["totals"]
        self.assertEqual(totals["questions"], 5)
        self.assertEqual(totals["skip_retrieval"], 1)
        # 为空率 = 1 / (5-1) = 0.25（图片默认文案记录不进分母）
        self.assertEqual(totals["empty_retrieval"]["count"], 1)
        self.assertEqual(totals["empty_retrieval"]["rate"], 0.25)
        # 改写率 = 1/5 = 0.2；好评率 = 1/2 = 0.5；覆盖率 = 2/5 = 0.4
        self.assertEqual(totals["rewrite"]["rate"], 0.2)
        self.assertEqual(totals["feedback"]["rate"], 0.5)
        self.assertEqual(totals["feedback"]["coverage"], 0.4)
        # 兜底率 = 1/5 = 0.2
        self.assertEqual(totals["fallback"]["rate"], 0.2)
        # 降级：L0=3 / L1=1 / L4=1，降级率 = 2/5 = 0.4
        self.assertEqual(data["degraded"], {
            "L0": 3, "L1": 1, "L2": 0, "L4": 1, "degraded_rate": 0.4,
            "degraded_rate_previous": None,
        })
        # 来源：material×2 / script×1 / ppt×1（一条多引用各计一次）
        self.assertEqual(data["by_source"], {"material": 2, "script": 1, "ppt": 1})
        # 成本：仅 scene=qa 的调用计入
        self.assertEqual(totals["cost"]["calls"], 1)
        self.assertEqual(totals["cost"]["total_tokens"], 120)
        # 课程排行
        row = data["by_course"][0]
        self.assertEqual(row["course_name"], "测试课程")
        self.assertEqual(row["teacher"], "测试教师")
        self.assertEqual(row["questions"], 5)
        self.assertEqual(row["empty_rate"], 0.25)
        self.assertEqual(row["feedback_rate"], 0.5)

    def test_skip_retrieval_excluded_from_empty_denominator(self):
        """纯图片默认文案：cited 为空但不算「检索为空」，且不进分母。"""
        self._qa(cited=[], skip=True)
        self._qa(cited=[], skip=True)
        self._qa(cited=[], skip=False)
        data = self._data()
        self.assertEqual(data["totals"]["empty_retrieval"]["count"], 1)
        self.assertEqual(data["totals"]["empty_retrieval"]["rate"], 1.0)

    def test_non_qa_scene_call_log_not_in_cost(self):
        AICallLog.objects.create(
            capability="chat", provider="tongyi", scene="script_gen", success=True,
            prompt_tokens=999, total_tokens=999,
        )
        self.assertEqual(self._data()["totals"]["cost"]["total_tokens"], 0)

    # ---------- 环比基线 ----------

    def test_previous_period_baseline(self):
        """前一等长周期基线：当前窗记录 + 上周期记录，rate_previous 取上周期同口径。"""
        self._qa(cited=[])  # 当前窗：1 提问 1 为空 → rate 1.0
        prev = self._qa(cited=[{"n": 1, "source": "material"}])
        QARecord.objects.filter(pk=prev.pk).update(
            created_at=timezone.now() - timedelta(days=8)
        )
        data = self._data(days=7)
        self.assertEqual(data["totals"]["empty_retrieval"]["rate"], 1.0)
        self.assertEqual(data["totals"]["empty_retrieval"]["rate_previous"], 0.0)
        self.assertEqual(data["degraded"]["degraded_rate_previous"], 0.0)

    # ---------- 窗口参数 ----------

    def test_invalid_window_params_rejected(self):
        resp = self.client.get(QA_STATS_URL, {"start": "2026/10/01"})
        self.assertEqual(resp.status_code, 400)
        resp = self.client.get(QA_STATS_URL, {"start": "2026-10-10", "end": "2026-10-01"})
        self.assertEqual(resp.status_code, 400)

    # ---------- 告警 ----------

    def _seed_week_questions(self, count, empty_count, l4_count=0, course=None):
        for i in range(count):
            is_empty = i < empty_count
            is_l4 = i >= empty_count and i < empty_count + l4_count
            self._qa(
                cited=[] if is_empty else [{"n": 1, "source": "material"}],
                snapshot={"degraded_level": 4} if is_l4 else {"degraded_level": 0},
                course=course,
            )

    def test_empty_rate_platform_alert(self):
        # 10 条中 4 条为空（40%）：> 30% 触发 warning；再补到 > 50% 触发 error
        self._seed_week_questions(10, 4)
        alerts = [a for a in self._data()["alerts"] if a["type"] == "empty_retrieval_high"]
        platform_alerts = [a for a in alerts if a["course_id"] is None]
        self.assertEqual(len(platform_alerts), 1)
        self.assertEqual(platform_alerts[0]["level"], "warning")
        self.assertIn("40.0%", platform_alerts[0]["detail"])
        # 追加到 6/12 = 50% → 严格大于 50% 才 error，先补到 7/13 ≈ 53.8%
        self._seed_week_questions(3, 3)
        alerts = [a for a in self._data()["alerts"] if a["type"] == "empty_retrieval_high"]
        platform_alerts = [a for a in alerts if a["course_id"] is None]
        self.assertEqual(platform_alerts[0]["level"], "error")

    def test_course_level_empty_alert_needs_min_sample(self):
        # 19 条（低于 20 样本门槛）：无课程级告警
        self._seed_week_questions(19, 10)
        alerts = [a for a in self._data()["alerts"] if a["type"] == "empty_retrieval_high"]
        self.assertEqual([a for a in alerts if a["course_id"] is not None], [])
        # 补足 20 条且为空率 > 30%：出现课程级告警（带 course_id）
        self._seed_week_questions(1, 1)
        alerts = [a for a in self._data()["alerts"] if a["type"] == "empty_retrieval_high"]
        course_alerts = [a for a in alerts if a["course_id"] is not None]
        self.assertEqual(len(course_alerts), 1)
        self.assertEqual(course_alerts[0]["course_id"], self.course.id)
        self.assertIn("测试课程", course_alerts[0]["title"])

    def test_l4_surge_alert(self):
        # 10 条中 2 条 L4（20% > 10% 阈值）→ l4_surge 告警
        self._seed_week_questions(10, 0, l4_count=2)
        alerts = [a for a in self._data()["alerts"] if a["type"] == "l4_surge"]
        self.assertEqual(len(alerts), 1)
        self.assertIn("20.0%", alerts[0]["detail"])

    def test_l4_surge_no_division_by_zero_when_prev_zero(self):
        """上周期有量（≥10）但零 L4：环比无正基数，不误报也不 500。"""
        # 前 7 天：10 条全部 L0（prev_l4_rate=0.0）
        for _ in range(10):
            prev_rec = self._qa(
                cited=[{"n": 1, "source": "material"}], snapshot={"degraded_level": 0}
            )
            QARecord.objects.filter(pk=prev_rec.pk).update(
                created_at=timezone.now() - timedelta(days=10)
            )
        # 当前 7 天：12 条中 1 条 L4（8.3%：低于 10% 绝对阈值）
        self._seed_week_questions(11, 0)
        self._qa(cited=[{"n": 1, "source": "material"}], snapshot={"degraded_level": 4})
        alerts = [a for a in self._data(days=7)["alerts"] if a["type"] == "l4_surge"]
        self.assertEqual(alerts, [])

    def test_no_alerts_below_thresholds(self):
        # 10 条中 2 条为空（20% < 30%）：无告警
        self._seed_week_questions(10, 2)
        alerts = [a for a in self._data()["alerts"] if a["type"] in ("empty_retrieval_high", "l4_surge")]
        self.assertEqual(alerts, [])

    # ---------- 权限 ----------

    def test_non_admin_forbidden(self):
        self.client.force_authenticate(user=self.teacher)
        self.assertEqual(self.client.get(QA_STATS_URL).status_code, 403)

    # ---------- 落库写入路径 ----------

    def test_knowledge_qa_image_only_marks_skip_retrieval(self):
        """纯图片默认文案提问：snapshot 带 skip_retrieval=True（看板排除口径的来源）。"""
        with patch("apps.ai.services.get_provider", return_value=_FakeChatProvider()):
            answer, cited, rewritten, snapshot = knowledge_qa(
                course_id=self.course.id,
                question=IMAGE_ONLY_DEFAULT_QUESTION,
                image_b64="data:image/png;base64,AAAA",
            )
        self.assertEqual(cited, [])
        self.assertIs(snapshot.get("skip_retrieval"), True)

    def test_knowledge_qa_normal_path_has_no_skip_flag(self):
        """正常文字提问：不进 skip 分支，snapshot 不带 skip_retrieval。"""
        fake_snapshot = {"budgets": {}, "chunks": [], "degraded_level": 0}
        with patch("apps.ai.services.get_provider", return_value=_FakeChatProvider()), \
                patch("apps.ai.services._gather_course_context",
                      return_value=("上下文", [{"n": 1, "source": "material"}], fake_snapshot)):
            answer, cited, rewritten, snapshot = knowledge_qa(
                course_id=self.course.id,
                question="什么是进程",
                image_b64=None,
            )
        self.assertNotIn("skip_retrieval", snapshot)
