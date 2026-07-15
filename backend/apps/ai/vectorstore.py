"""向量检索抽象。

起步实现：知识库片段的 embedding 存 JSON 字段，做暴力余弦相似度检索。
数据量增大后，把 search 换成 pgvector / Milvus / Qdrant 即可，调用方不变。
"""
from __future__ import annotations

import math


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def search_chunks(course_id: int, query_vec: list[float], top_k: int = 5):
    """返回按相似度降序的 (chunk, score) 列表。"""
    from apps.knowledge.models import KnowledgeChunk

    chunks = KnowledgeChunk.objects.filter(course_id=course_id).exclude(embedding=[])
    scored = [(c, cosine(query_vec, c.embedding)) for c in chunks]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
