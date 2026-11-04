"""向量检索后端注册表（json / qdrant 可切换）。

调用方只认 ``apps.ai.vectorstore.search_chunks``；本包负责按
``settings.RAG_VECTOR_BACKEND`` 选后端，并把「Qdrant 不可用 → 回落 json」
的降级逻辑收在一处（见 vectorstore.search_chunks）。
"""
from __future__ import annotations

from .base import ChunkFilter, VectorBackend, cosine

__all__ = [
    "ChunkFilter",
    "VectorBackend",
    "cosine",
    "get_backend",
    "get_json_backend",
    "get_qdrant_backend",
    "reset_backend_cache",
]


def get_json_backend() -> VectorBackend:
    from .json_backend import JsonBackend

    return JsonBackend()


def get_qdrant_backend() -> VectorBackend:
    from .qdrant_backend import QdrantBackend

    return QdrantBackend()


def get_backend(name: str | None = None) -> VectorBackend:
    """按名字取后端实例（None=读 settings.RAG_VECTOR_BACKEND）。

    未知取值回落到 json：配置写错不该让问答直接挂掉（json 是回滚路径，
    行为与接入 Qdrant 前逐字一致）。
    """
    if name is None:
        from django.conf import settings

        name = getattr(settings, "RAG_VECTOR_BACKEND", "json")
    name = (name or "json").strip().lower()
    if name == "qdrant":
        return get_qdrant_backend()
    return get_json_backend()


def reset_backend_cache() -> None:
    """清空 Qdrant 客户端/集合就绪缓存（测试与切换配置后调用）。"""
    from .qdrant_backend import reset_client_cache

    reset_client_cache()
