"""对话模型视觉（图片）能力判定测试。

覆盖 chat_supports_vision 的三级解析（管理端 DB > 环境变量 > Mock）：
- DB 行启用时读「支持图片」开关，显式开关优先于模型名推断；
- DB 行不存在 / 未启用（回落 Mock）一律 False——Mock 不理解图片；
- 环境变量派生：AI_CAPABILITY_ENV["chat"]["vision"] 显式指定优先，
  缺省按模型名推断（vl / vision / gpt-4o 等命中，deepseek-v3 / glm-4-plus 不误判）。
"""
from django.test import TestCase, override_settings

from apps.ai.models import AICapabilityConfig
from apps.ai.providers.factory import chat_supports_vision, model_name_suggests_vision


class ModelNameSuggestsVisionTests(TestCase):
    def test_vision_models_matched(self):
        for name in [
            "qwen-vl-max", "qwen2.5-vl-72b-instruct", "glm-4v-plus",
            "gpt-4o-mini", "gemini-1.5-pro", "claude-3-5-sonnet",
            "Qwen-VL-Max",  # 大小写不敏感
        ]:
            self.assertTrue(model_name_suggests_vision(name), name)

    def test_text_models_not_matched(self):
        # 纯文本模型不能误判：deepseek-v3 是「v3」不是「vl」；glm-4-plus / qwen-plus 同理
        for name in [
            "qwen3.7-plus", "qwen-plus", "deepseek-v3", "deepseek-chat",
            "glm-4-plus", "glm-4-flash", "gpt-3.5-turbo", "moonshot-v1-8k",
            "text-embedding-v3", "gte-rerank-v2", "",
        ]:
            self.assertFalse(model_name_suggests_vision(name), name)


@override_settings(AI_PROVIDER="mock", AI_SETTINGS={}, AI_CAPABILITY_ENV={})
class ChatSupportsVisionDatabaseTests(TestCase):
    """DB 配置优先：开关显式优先于模型名。"""

    def _row(self, **kwargs):
        defaults = dict(
            capability="chat", provider="tongyi", enabled=True,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_name="qwen3.7-plus",
        )
        defaults.update(kwargs)
        return AICapabilityConfig.objects.create(**defaults)

    def test_db_flag_on_returns_true_even_when_model_name_is_text(self):
        """qwen3.7-plus 名称不带 vl/vision 但实测支持视觉：以管理端开关为准。"""
        self._row(supports_vision=True)
        self.assertTrue(chat_supports_vision())

    def test_db_flag_off_returns_false_even_when_model_looks_vision(self):
        """模型名疑似视觉但开关关闭：显式开关优先（管理端会给出错配提示）。"""
        self._row(model_name="qwen-vl-max", supports_vision=False)
        self.assertFalse(chat_supports_vision())

    def test_disabled_row_falls_back_to_mock_and_false(self):
        """行未启用 → 回落 Mock，Mock 不理解图片，一律 False。"""
        self._row(enabled=False, supports_vision=True)
        self.assertFalse(chat_supports_vision())

    def test_no_row_with_mock_provider_returns_false(self):
        self.assertFalse(chat_supports_vision())


@override_settings(
    AI_PROVIDER="tongyi",
    AI_SETTINGS={"tongyi": {"api_key": "k", "base_url": "u", "chat_model": "qwen-vl-max"}},
    AI_CAPABILITY_ENV={},
)
class ChatSupportsVisionEnvTests(TestCase):
    """无 DB 行时按环境变量：模型名推断 / 显式 vision 覆盖。"""

    def test_env_model_name_heuristic(self):
        self.assertTrue(chat_supports_vision())

    def test_env_explicit_vision_false_overrides_heuristic(self):
        with override_settings(AI_CAPABILITY_ENV={"chat": {"provider": "tongyi", "vision": False}}):
            self.assertFalse(chat_supports_vision())

    def test_env_explicit_vision_true_overrides_text_model(self):
        with override_settings(
            AI_PROVIDER="tongyi",
            AI_SETTINGS={"tongyi": {"api_key": "k", "base_url": "u", "chat_model": "deepseek-chat"}},
            AI_CAPABILITY_ENV={"chat": {"provider": "tongyi", "vision": True}},
        ):
            self.assertTrue(chat_supports_vision())
