"""Provider 工厂：按能力（chat / embed / rerank / tts）解析配置。

优先级：管理端按能力配置（AICapabilityConfig）> 环境变量 > Mock。
- 管理端：每项能力一行配置，独立服务商与凭证；
- 环境变量：AI_<CAPABILITY>_* 覆盖 > 旧版 AI_PROVIDER + AI_SETTINGS 派生；
- 未配置 / 无 Key / 解密失败：回退 MockProvider（静默，页面会标出实际运行时）。
"""
from __future__ import annotations

from django.conf import settings
from django.db import DatabaseError

from .base import BaseAIProvider
from .mock import MockProvider

DEFAULT_CAPABILITY = "chat"

# 能力 -> 旧版 AI_SETTINGS 中的模型字段名
_CAPABILITY_MODEL_FIELD = {
    "chat": "chat_model",
    "embed": "embed_model",
    "rerank": "rerank_model",
    "tts": "tts_model",
}

_CAPABILITIES = tuple(_CAPABILITY_MODEL_FIELD)


def mask_api_key(key: str) -> str:
    """API Key 脱敏：保留首尾各 4 位，中间统一以 6 个 * 表示省略。"""
    key = str(key or "")
    if not key:
        return ""
    if len(key) <= 8:
        return f"{key[:2]}{'*' * 6}"
    return f"{key[:4]}{'*' * 6}{key[-4:]}"


def build_provider(provider: str, config: dict, capability: str = DEFAULT_CAPABILITY) -> BaseAIProvider:
    if provider == "mock":
        return MockProvider()
    if provider == "local":
        # 系统内置本地模型：无需 API Key/接口地址，权重在本地推理（见 providers/local.py）
        from .local import LocalModelsProvider

        return LocalModelsProvider(config, capability=capability)
    if not config.get("api_key"):
        return MockProvider()
    if provider in ("deepseek", "openai", "tongyi"):
        from .openai_compat import OpenAICompatProvider

        normalized = dict(config)
        # 按能力把统一的 model 映射到 Provider 期望的字段（同时兼容旧版字典）
        model = config.get("model") or config.get(_CAPABILITY_MODEL_FIELD.get(capability, ""), "")
        normalized[_CAPABILITY_MODEL_FIELD.get(capability, "chat_model")] = model
        return OpenAICompatProvider(normalized, name=provider)
    return MockProvider()


def _env_capability_config(capability: str) -> tuple[str, dict]:
    """环境变量派生：AI_<CAP>_* 覆盖优先，回退旧版 AI_PROVIDER + AI_SETTINGS。"""
    override = getattr(settings, "AI_CAPABILITY_ENV", {}).get(capability, {})
    provider = override.get("provider") or getattr(settings, "AI_PROVIDER", "mock")
    legacy = getattr(settings, "AI_SETTINGS", {}).get(provider, {})
    model_field = _CAPABILITY_MODEL_FIELD.get(capability, "chat_model")
    return provider, {
        "api_key": override.get("api_key") or legacy.get("api_key", ""),
        "base_url": override.get("base_url") or legacy.get("base_url", ""),
        "model": override.get("model") or legacy.get(model_field, ""),
        # 超时/发音人：env 派生不提供，交由 provider 回退 settings 默认值
        "timeout": None,
        "voice": "",
        # 视觉能力：env 无开关位（DB 才有），None=按模型名推断
        "vision": override.get("vision"),
    }


def get_env_config(capability: str = DEFAULT_CAPABILITY) -> tuple[str, dict]:
    """仅按环境变量派生配置（不问数据库）。

    供「保存配置时 API Key 留空」等场景回退已生效 Key 使用——
    此时数据库里可能还没有对应记录，不能走 get_runtime_config 的 DB 优先分支。
    """
    return _env_capability_config(capability)


def get_runtime_config(capability: str = DEFAULT_CAPABILITY) -> tuple[str, dict, str]:
    """返回该能力的 provider、配置和来源（database / environment）。"""
    try:
        from apps.ai.models import AICapabilityConfig

        saved = AICapabilityConfig.objects.filter(capability=capability).first()
    except DatabaseError:
        saved = None

    if saved:
        if not saved.enabled:
            return "mock", {}, "database"
        return saved.provider, {
            "api_key": saved.get_api_key(),
            "base_url": saved.base_url,
            "model": saved.model_name,
            # 管理端可配超时/发音人；为空时 provider 回退 settings 默认值
            "timeout": saved.timeout,
            "voice": saved.voice or "",
            # 图片（多模态）开关：仅 chat 行有意义，供 chat_supports_vision 读取
            "vision": saved.supports_vision,
        }, "database"

    provider, config = _env_capability_config(capability)
    return provider, config, "environment"


def get_provider(capability: str = DEFAULT_CAPABILITY) -> BaseAIProvider:
    provider, config, _source = get_runtime_config(capability)
    return build_provider(provider, config, capability)


# 模型名视觉特征（小写子串匹配）：命中即推断支持图片输入。
# 选取时避开纯文本模型误判：deepseek-v3（"v3"非"vl"）、glm-4-plus、qwen-plus、
# moonshot-v1、gpt-3.5-turbo 等均不含以下特征。
_VISION_MODEL_HINTS = (
    "vl",        # qwen-vl / qwen2.5-vl / internvl / cogvlm / yi-vl
    "vision",    # *-vision-* / gpt-4-vision-preview
    "4v",        # glm-4v 一类命名
    "gpt-4o",    # OpenAI 多模态
    "gpt-4.1",
    "gemini",
    "claude-3",  # claude-3 全系支持图片
    "pixtral",
    "llava",
    "多模态",
)


def model_name_suggests_vision(model_name: str) -> bool:
    """按模型名推断是否视觉（多模态）模型。

    用于 env 派生配置的能力判定与管理端「模型疑似支持视觉但开关关闭」提示，
    DB 显式开关（AICapabilityConfig.supports_vision）始终优先。
    """
    name = str(model_name or "").lower()
    return any(hint in name for hint in _VISION_MODEL_HINTS)


def chat_supports_vision() -> bool:
    """当前对话配置是否支持图片（多模态）输入。

    解析优先级与 build_provider 一致（管理端 DB > 环境变量 > Mock）：
    - DB：chat 行启用时读管理端「支持图片」开关（显式优先，模型名仅用于提示）；
      行不存在 / 未启用即 Mock，Mock 不理解图片，视为不支持；
    - env：AI_CAPABILITY_ENV["chat"]["vision"] 可显式指定，缺省按模型名推断；
    - 一律取不到时返回 False——隐藏上传入口优于用户发送后接口报错。
    """
    provider, config, _source = get_runtime_config("chat")
    vision = config.get("vision")
    if isinstance(vision, bool):
        return vision
    if provider == "mock":
        return False
    return model_name_suggests_vision(config.get("model", ""))
