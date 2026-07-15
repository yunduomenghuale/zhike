"""Provider 工厂：按 settings.AI_PROVIDER 返回单例实现。"""
from __future__ import annotations

from functools import lru_cache

from django.conf import settings

from .base import BaseAIProvider
from .mock import MockProvider


@lru_cache(maxsize=1)
def get_provider() -> BaseAIProvider:
    provider = getattr(settings, "AI_PROVIDER", "mock")
    conf = getattr(settings, "AI_SETTINGS", {})

    # DeepSeek / 任意 OpenAI 兼容端点（含阿里 MaaS、本地 vLLM）
    if provider in ("deepseek", "openai") and conf.get(provider, {}).get("api_key"):
        from .openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(conf[provider], name=provider)

    if provider == "zhipu" and conf.get("zhipu", {}).get("api_key"):
        from .zhipu import ZhipuProvider

        return ZhipuProvider(conf["zhipu"])
    if provider == "tongyi" and conf.get("tongyi", {}).get("api_key"):
        from .openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(conf["tongyi"], name="tongyi")

    # 默认 / 未配置 Key -> Mock，保证业务流程可跑通
    return MockProvider()
