"""JSON 后端：MySQL ``KnowledgeChunk.embedding`` 列 + 内存暴力余弦（现状实现）。

这是默认后端，也是 Qdrant 的**回滚路径**——所以这里的过滤条件、排序、返回值
必须与接入 Qdrant 之前逐字一致（连 ``exclude(embedding=[])`` 与
``select_related`` 的取舍都保持原样）。改动此文件等于改动线上检索结果。
"""
from __future__ import annotations

from django.db.models import Q

from .base import ChunkFilter, VectorBackend, cosine

# 引用展示要取来源名与章节标题，一次带出避免 N+1（两套后端共用此列表）
CHUNK_RELATIONS = (
    "material",
    "material__catalog",
    "ppt",
    "ppt__catalog",
    "video",
    "video__catalog",
)


def filtered_queryset(flt: ChunkFilter, *, with_embedding: bool = True):
    """按 ``ChunkFilter`` 过滤片段（检索语义的唯一实现）。

    Qdrant 后端回填后也用它对命中 id 做**二次校验**：Qdrant payload 是冗余
    副本，MySQL 才是真相——payload 过期（如资料刚关掉 qa_open、课件刚被替换）
    时以库为准，避免学生看到不该看的内容。

    ``with_embedding=False``：调用方只需要片段内容与来源关系（Qdrant 路径已经
    在向量库里算过相似度）时，把 1024 维向量列 defer 掉——单个片段约 10KB
    JSON，15 条命中就是 150KB 的无用传输 + 反序列化（实测占端到端延迟的大头）。
    """
    from apps.knowledge.models import KnowledgeChunk

    chunks = (
        KnowledgeChunk.objects.filter(course_id=flt.course_id)
        .exclude(embedding=[])
        # 只保留资料/讲稿片段与当前启用版本课件的片段
        .filter(Q(ppt__isnull=True) | Q(ppt__is_active=True))
        .select_related(*CHUNK_RELATIONS)
    )
    if not with_embedding:
        chunks = chunks.defer("embedding")
    if not flt.include_script:
        chunks = chunks.exclude(source=KnowledgeChunk.Source.SCRIPT)
    if flt.catalog_id:
        # 挂该章节的片段 + 未挂章节的通用资料片段
        chunks = chunks.filter(
            Q(catalog_id=flt.catalog_id)
            | Q(catalog__isnull=True, source=KnowledgeChunk.Source.MATERIAL)
        )
    if flt.student_access:
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
        if flt.classroom_ids:
            material_q &= Q(material__classroom__isnull=True) | Q(
                material__classroom_id__in=list(flt.classroom_ids)
            )
        else:
            material_q &= Q(material__classroom__isnull=True)
        chunks = chunks.filter(material_q | ppt_q | script_q)
    return chunks


class JsonBackend(VectorBackend):
    """暴力余弦后端：无外部依赖，永远可用（降级终点）。"""

    name = "json"

    def search(self, flt: ChunkFilter, query_vec: list[float], top_k: int = 5):
        chunks = filtered_queryset(flt)
        scored = [(c, cosine(query_vec, c.embedding)) for c in chunks]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def upsert(self, chunks) -> int:
        """JSON 后端的「写」就是 MySQL 的 embedding 列本身，无需同步动作。"""
        return 0

    def delete(self, ids) -> None:
        """同上：删除 MySQL 行即删除了 JSON 后端的数据。"""

    def count(self) -> int | None:
        from apps.knowledge.models import KnowledgeChunk

        return KnowledgeChunk.objects.exclude(embedding=[]).count()
