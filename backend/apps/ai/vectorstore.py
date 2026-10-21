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
    classroom_ids=None,
    catalog_id=None,
):
    """返回按相似度降序的 (chunk, score) 列表。

    片段来源有三：教辅资料（material）、课件 PPT（ppt，每页一片段）、
    逐页讲解稿（script，每页一片段）。旧版本课件（is_active=False）的片段
    不参与检索——上传新版本时已随之删除，这里再兜底一道。

    章节候选池（传 catalog_id 时）= 挂该章节的片段 + 未挂章节的通用资料
    片段（catalog 为空的 material 片段，如教材电子版/考纲——这类资料本就
    不该强制挂章节，2026-10-21 起纳入章节候选池；过滤走 chunk 冗余的
    catalog 字段，不再 join 来源表）。调用方在章节无片段时可自行退回全课程。

    classroom_ids：学生可见的班级集合（在读班级，由调用方解析）。学生检索
    资料片段时，「面向全课程的资料（classroom 为空）+ 定向到其在读班级的
    资料」均可见。

    学生可见性按来源分别判定：资料要求 qa_open + 班级可见；课件要求当前
    版本 + 章节已发布；讲稿要求视频已发布 + 章节已发布。

    回滚开关：settings.AI_QA_DISABLE_SCRIPT_SOURCE 为真时讲稿片段不参与
    检索（讲稿入检索体系的一键退回，退回后 QA 侧走原文限量兜底）。
    """
    from django.conf import settings
    from django.db.models import Q

    from apps.knowledge.models import KnowledgeChunk

    chunks = (
        KnowledgeChunk.objects.filter(course_id=course_id)
        .exclude(embedding=[])
        # 只保留资料/讲稿片段与当前启用版本课件的片段
        .filter(Q(ppt__isnull=True) | Q(ppt__is_active=True))
        # 引用展示要取来源名与章节标题，一次带出避免 N+1
        .select_related(
            "material", "material__catalog",
            "ppt", "ppt__catalog",
            "video", "video__catalog",
        )
    )
    if getattr(settings, "AI_QA_DISABLE_SCRIPT_SOURCE", False):
        chunks = chunks.exclude(source=KnowledgeChunk.Source.SCRIPT)
    if catalog_id:
        # 挂该章节的片段 + 未挂章节的通用资料片段
        chunks = chunks.filter(
            Q(catalog_id=catalog_id)
            | Q(catalog__isnull=True, source=KnowledgeChunk.Source.MATERIAL)
        )
    if student_access:
        material_q = Q(source=KnowledgeChunk.Source.MATERIAL, material__qa_open=True)
        ppt_q = Q(
            source=KnowledgeChunk.Source.PPT,
            ppt__is_active=True,
            ppt__catalog__is_published=True,
        )
        script_q = Q(
            source=KnowledgeChunk.Source.SCRIPT,
            video__is_published=True,
            video__catalog__is_published=True,
        )
        if classroom_ids:
            material_q &= Q(material__classroom__isnull=True) | Q(
                material__classroom_id__in=list(classroom_ids)
            )
        else:
            material_q &= Q(material__classroom__isnull=True)
        chunks = chunks.filter(material_q | ppt_q | script_q)
    scored = [(c, cosine(query_vec, c.embedding)) for c in chunks]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
