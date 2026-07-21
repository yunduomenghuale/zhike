"""Provider 工厂：优先读取管理端配置，未配置时兼容环境变量。"""
from __future__ import annotations

from django.conf import settings
from django.db import DatabaseError

from .base import BaseAIProvider
from .mock import MockProvider


def build_provider(provider: str, config: dict) -> BaseAIProvider:
    if provider == "mock":
        return MockProvider()
    if not config.get("api_key"):
        return MockProvider()
    if provider in ("deepseek", "openai", "tongyi"):
        from .openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(config, name=provider)
    if provider == "zhipu":
        from .zhipu import ZhipuProvider

        return ZhipuProvider(config)
    return MockProvider()


def get_runtime_config() -> tuple[str, dict, str]:
    """返回 provider、配置和来源（database/environment）。"""
    try:
        from apps.ai.models import AIConfiguration

        saved = AIConfiguration.objects.order_by("id").first()
    except DatabaseError:
        saved = None

    if saved:
        if not saved.enabled:
            return "mock", {}, "database"
        return saved.provider, {
            "api_key": saved.get_api_key(),
            "base_url": saved.base_url,
            "chat_model": saved.chat_model,
            "embed_model": saved.embed_model,
            "tts_model": saved.tts_model,
        }, "database"

    provider = getattr(settings, "AI_PROVIDER", "mock")
    config = getattr(settings, "AI_SETTINGS", {}).get(provider, {})
    return provider, config, "environment"


def get_provider() -> BaseAIProvider:
    provider, config, _source = get_runtime_config()
    return build_provider(provider, config)
