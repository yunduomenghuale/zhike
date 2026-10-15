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


def search_chunks(
    course_id: int,
    query_vec: list[float],
    top_k: int = 5,
    *,
    student_access: bool = False,
    classroom_id=None,
):
    """返回按相似度降序的 (chunk, score) 列表。

    片段来源有二：教辅资料（material）与课件 PPT（ppt，每页一片段）。
    旧版本课件（is_active=False）的片段不参与检索——上传新版本时已随之删除，
    这里再兜底一道，防止历史数据残留。
    """
    from django.db.models import Q

    from apps.knowledge.models import KnowledgeChunk

    chunks = (
        KnowledgeChunk.objects.filter(course_id=course_id)
        .exclude(embedding=[])
        # 只保留资料片段与当前启用版本课件的片段
        .filter(Q(ppt__isnull=True) | Q(ppt__is_active=True))
        # 引用展示要取 material.file_name / material.catalog.title /
        # ppt.file_name / ppt.catalog.title，一次带出避免 N+1
        .select_related("material", "material__catalog", "ppt", "ppt__catalog")
    )
    if student_access:
        # 资料片段：qa_open 开启且班级可见；课件片段：已发布章节的当前版本
        material_q = Q(material__isnull=False, material__qa_open=True)
        ppt_q = Q(
            ppt__isnull=False,
            ppt__is_active=True,
            ppt__catalog__is_published=True,
        )
        if classroom_id:
            material_q &= Q(material__classroom__isnull=True) | Q(material__classroom_id=classroom_id)
        else:
            material_q &= Q(material__classroom__isnull=True)
        chunks = chunks.filter(material_q | ppt_q)
    scored = [(c, cosine(query_vec, c.embedding)) for c in chunks]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
