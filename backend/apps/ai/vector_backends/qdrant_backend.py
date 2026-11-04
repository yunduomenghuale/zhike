"""Qdrant 后端：同一批向量（1024 维，Cosine）的外置索引。

**存量向量直接搬运**：本后端不做任何 embedding 计算，只把
``KnowledgeChunk.embedding`` 原样 upsert 进集合（回填走 ``backfill_qdrant``，
增量走 ingest 双写）。这样切后端不产生 API 成本，也不会出现「同一文本两个
向量」导致的双读不一致。

payload 是冗余副本（Qdrant 不放正文，避免两处存储漂移），字段与
``ChunkFilter`` 严格对应：``course_id`` / ``catalog_id``（0 表示未挂章节，
不用 null 是为了跨 qdrant-client 版本的过滤兼容）/ ``source`` / ``page``
（0 表示无页码）/ ``is_active`` / ``qa_open`` / ``classroom_id``（0 表示面向
全课程）/ ``catalog_published`` / ``video_published``。

命中后仍会用 MySQL 侧 ``filtered_queryset`` 复验一遍：payload 过期（资料刚关闭
qa_open、课件刚被替换）时以库为准——学生可见性不能只靠一份副本。
"""
from __future__ import annotations

import logging
import threading

from .base import ChunkFilter, VectorBackend

logger = logging.getLogger(__name__)

# 单次 upsert 请求的点数上限：回填按 1000 条分页读库，但请求侧再切小一些，
# 避免单请求体过大（1024 维 × 500 点 ≈ 2MB JSON）
UPSERT_BATCH = 256
# 单次 delete 请求的 id 数（级联删除可能一次上万条，必须分批）
DELETE_BATCH = 500

_client_lock = threading.Lock()
_clients: dict[tuple[str, str], object] = {}
_ready_lock = threading.Lock()
_ready: set[str] = set()


def reset_client_cache() -> None:
    """关闭并清空客户端与「集合已就绪」缓存（配置变更/测试用）。

    必须显式 close：本地文件模式（QDRANT_URL=local:）靠文件锁独占目录，
    不关掉的话同一个目录第二次打开会失败，临时目录也删不掉。
    """
    with _client_lock:
        for client in _clients.values():
            try:
                client.close()
            except Exception:  # noqa: BLE001 - 关闭失败不影响后续
                pass
        _clients.clear()
    with _ready_lock:
        _ready.clear()


def _connection():
    from django.conf import settings

    url = (getattr(settings, "QDRANT_URL", "") or "").strip()
    api_key = (getattr(settings, "QDRANT_API_KEY", "") or "").strip()
    timeout = getattr(settings, "QDRANT_TIMEOUT", 3)
    return url, api_key, timeout


def get_client():
    """取（进程内复用的）Qdrant 客户端。

    支持三种 QDRANT_URL 形态：
    - ``http(s)://host:6333``：连真实服务（生产走 compose 里的 qdrant）；
    - ``local:<path>``：qdrant-client 本地文件模式，无需起容器（开发/单测）；
    - 空：视为不可用，抛异常由上层回落 json。
    """
    import qdrant_client

    url, api_key, timeout = _connection()
    if not url:
        raise RuntimeError("QDRANT_URL 未配置")
    key = (url, api_key)
    with _client_lock:
        client = _clients.get(key)
        if client is not None:
            return client
        if url.startswith("local:"):
            path = url[len("local:") :].strip()
            if not path:
                raise RuntimeError("QDRANT_URL=local: 后需要给目录路径")
            client = qdrant_client.QdrantClient(path=path)
        elif url.startswith("file://"):
            client = qdrant_client.QdrantClient(path=url[len("file://") :])
        else:
            client = qdrant_client.QdrantClient(
                url=url,
                api_key=api_key or None,
                timeout=timeout,
                prefer_grpc=False,
                # 不做客户端/服务端版本握手：省一次往返，且服务不可用时少一条告警；
                # API 兼容在调用侧用 hasattr 兜底（query_points / search 两套）
                check_compatibility=False,
            )
        _clients[key] = client
        return client


def _collection() -> str:
    from django.conf import settings

    name = (getattr(settings, "QDRANT_COLLECTION", "") or "").strip()
    return name or "zhike_chunks"


def _vector_size() -> int:
    from django.conf import settings

    try:
        return int(getattr(settings, "RAG_QDRANT_VECTOR_SIZE", 1024) or 1024)
    except (TypeError, ValueError):
        return 1024


# ---------------------------------------------------------------------------
# payload 构造（写入侧唯一实现）
# ---------------------------------------------------------------------------
def _pid(obj) -> int:
    return int(getattr(obj, "id", 0) or 0)


def chunk_payload(chunk) -> dict:
    """把片段摊平成 Qdrant payload（过滤所需字段全部就位，检索时不再 join）。"""
    material = chunk.material
    ppt = chunk.ppt
    video = chunk.video
    catalog = None
    is_active = True
    qa_open = False
    classroom_id = 0
    catalog_published = False
    video_published = False
    if material is not None:
        catalog = material.catalog
        qa_open = bool(material.qa_open)
        classroom_id = _pid(material.classroom)
    elif ppt is not None:
        catalog = ppt.catalog
        is_active = bool(ppt.is_active)
        catalog_published = bool(ppt.catalog is not None and ppt.catalog.is_published)
    elif video is not None:
        catalog = video.catalog
        video_published = bool(video.is_published)
        catalog_published = bool(video.catalog is not None and video.catalog.is_published)
    return {
        "chunk_id": _pid(chunk),
        "course_id": _pid(chunk.course),
        "catalog_id": _pid(catalog),  # 0 = 未挂章节（= MySQL 的 NULL）
        "source": chunk.source,
        "page": int(chunk.page or 0),  # 0 = 无页码
        "is_active": is_active,
        "material_id": _pid(material),
        "ppt_id": _pid(ppt),
        "video_id": _pid(video),
        "qa_open": qa_open,
        "classroom_id": classroom_id,  # 0 = 面向全课程
        "catalog_published": catalog_published,
        "video_published": video_published,
    }


# ---------------------------------------------------------------------------
# 过滤条件翻译（与 json_backend.filtered_queryset 等价，改动需两边同步）
# ---------------------------------------------------------------------------
def build_qdrant_filter(flt: ChunkFilter):
    from qdrant_client import models

    def cond(key: str, value):
        return models.FieldCondition(key=key, match=models.MatchValue(value=value))

    # 课程边界 + 「只保留资料/讲稿片段与当前启用版本课件的片段」
    must: list = [cond("course_id", flt.course_id), cond("is_active", True)]
    must_not: list = []
    if not flt.include_script:
        must_not.append(cond("source", "script"))
    if flt.catalog_id:
        # 挂该章节的片段 + 未挂章节的通用资料片段
        must.append(
            models.Filter(
                should=[
                    cond("catalog_id", int(flt.catalog_id)),
                    models.Filter(
                        must=[cond("catalog_id", 0), cond("source", "material")]
                    ),
                ]
            )
        )
    if flt.student_access:
        material_must: list = [
            cond("source", "material"),
            cond("qa_open", True),
        ]
        if flt.classroom_ids:
            material_must.append(
                models.Filter(
                    should=[
                        cond("classroom_id", 0),
                        models.FieldCondition(
                            key="classroom_id",
                            match=models.MatchAny(any=list(flt.classroom_ids)),
                        ),
                    ]
                )
            )
        else:
            material_must.append(cond("classroom_id", 0))
        must.append(
            models.Filter(
                should=[
                    models.Filter(must=material_must),
                    # 课件：is_active 已在上方全局条件里
                    models.Filter(
                        must=[cond("source", "ppt"), cond("catalog_published", True)]
                    ),
                    models.Filter(
                        must=[
                            cond("source", "script"),
                            cond("video_published", True),
                            cond("catalog_published", True),
                        ]
                    ),
                ]
            )
        )
    return models.Filter(must=must, must_not=must_not or None)


class QdrantBackend(VectorBackend):
    """Qdrant 集合检索（ID = chunk_id，幂等 upsert）。"""

    name = "qdrant"

    def __init__(self):
        self.collection = _collection()
        self.vector_size = _vector_size()

    # ---------------------------------------------------------------- 运维
    def ensure_ready(self) -> None:
        """集合不存在则按 size=1024/distance=Cosine 建；size 不符则明确报错。"""
        from qdrant_client import models

        client = get_client()
        key = f"{_connection()[0]}::{self.collection}::{self.vector_size}"
        with _ready_lock:
            if key in _ready:
                return
        exists = False
        try:
            exists = bool(client.collection_exists(self.collection))
        except AttributeError:  # 老版本客户端
            exists = self.collection in {
                c.name for c in client.get_collections().collections
            }
        if not exists:
            try:
                client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(
                        size=self.vector_size, distance=models.Distance.COSINE
                    ),
                )
                logger.info(
                    "[qdrant] 创建集合 %s（size=%s, distance=Cosine）",
                    self.collection,
                    self.vector_size,
                )
            except Exception:
                # 首检并发：backend 多线程 / backend 与 worker 同时建集合，
                # 抢输的一方会拿到「already exists」——已存在即视为就绪，不报错
                if not client.collection_exists(self.collection):
                    raise
        else:
            info = client.get_collection(self.collection)
            params = getattr(getattr(info, "config", None), "params", None)
            size = None
            vectors = getattr(params, "vectors", None)
            if vectors is not None:
                size = getattr(vectors, "size", None)
            if size and int(size) != int(self.vector_size):
                raise RuntimeError(
                    f"集合 {self.collection} 向量维度为 {size}，配置为 {self.vector_size}："
                    "换向量模型后必须重建集合（backfill_qdrant --reset）"
                )
        with _ready_lock:
            _ready.add(key)

    def health(self) -> tuple[bool, str]:
        try:
            self.ensure_ready()
            info = get_client().get_collection(self.collection)
            return True, f"{self.collection} points={getattr(info, 'points_count', '?')}"
        except Exception as exc:  # noqa: BLE001 - 健康探查不该抛
            return False, str(exc)[:300]

    def count(self) -> int | None:
        self.ensure_ready()
        return int(get_client().count(self.collection, exact=True).count)

    def drop_collection(self) -> None:
        """删集合（换向量模型后重建 / 回填 --reset）。"""
        client = get_client()
        try:
            exists = bool(client.collection_exists(self.collection))
        except AttributeError:
            exists = self.collection in {c.name for c in client.get_collections().collections}
        if exists:
            client.delete_collection(self.collection)
        with _ready_lock:
            _ready.discard(f"{_connection()[0]}::{self.collection}::{self.vector_size}")

    def points_for_course(self, course_id: int) -> int:
        """该课程在集合里的点数（近似，用于识别「集合没回填」的错误空结果）。"""
        from qdrant_client import models

        self.ensure_ready()
        result = get_client().count(
            self.collection,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="course_id", match=models.MatchValue(value=int(course_id))
                    )
                ]
            ),
            exact=False,
        )
        return int(getattr(result, "count", 0) or 0)

    # ---------------------------------------------------------------- 读
    def _query(self, query_vec, qfilter, top_k: int):
        client = get_client()
        timeout = None
        try:
            from django.conf import settings

            timeout = int(getattr(settings, "QDRANT_TIMEOUT", 3) or 3)
        except Exception:  # noqa: BLE001
            timeout = None
        if hasattr(client, "query_points"):
            resp = client.query_points(
                collection_name=self.collection,
                query=list(query_vec),
                query_filter=qfilter,
                limit=top_k,
                with_payload=False,
                with_vectors=False,
                timeout=timeout,
            )
            return list(getattr(resp, "points", []) or [])
        # 1.7 以前的老客户端
        return list(
            client.search(
                collection_name=self.collection,
                query_vector=list(query_vec),
                query_filter=qfilter,
                limit=top_k,
                with_payload=False,
                with_vectors=False,
            )
        )

    def search(self, flt: ChunkFilter, query_vec: list[float], top_k: int = 5):
        from .json_backend import filtered_queryset

        if not query_vec:
            return []
        self.ensure_ready()
        points = self._query(query_vec, build_qdrant_filter(flt), top_k)
        if not points:
            return []
        order = [int(p.id) for p in points]
        scores = {int(p.id): float(p.score) for p in points}
        # 复验：payload 是副本，MySQL 才是可见性的真相（顺带过滤掉已删除的 id）。
        # defer embedding：向量已在库里算完，回表只为取内容与来源关系。
        rows = filtered_queryset(flt, with_embedding=False).filter(id__in=order)
        by_id = {c.id: c for c in rows}
        return [(by_id[cid], scores[cid]) for cid in order if cid in by_id]

    # ---------------------------------------------------------------- 写
    def upsert(self, chunks) -> int:
        """幂等 upsert（ID=chunk_id）。向量维度不符的片段跳过并记日志。"""
        from qdrant_client import models

        chunks = [c for c in chunks if getattr(c, "pk", None)]
        if not chunks:
            return 0
        self.ensure_ready()
        points = []
        skipped = 0
        for chunk in chunks:
            vec = chunk.embedding or []
            if len(vec) != self.vector_size:
                skipped += 1
                continue
            points.append(
                models.PointStruct(
                    id=int(chunk.pk), vector=list(vec), payload=chunk_payload(chunk)
                )
            )
        if skipped:
            logger.warning(
                "[qdrant] %s 个片段向量维度不是 %s，已跳过（回填会单独报告）",
                skipped,
                self.vector_size,
            )
        client = get_client()
        for start in range(0, len(points), UPSERT_BATCH):
            client.upsert(
                collection_name=self.collection,
                points=points[start : start + UPSERT_BATCH],
                wait=True,
            )
        return len(points)

    def delete(self, ids) -> None:
        from qdrant_client import models

        ids = [int(i) for i in ids if i]
        if not ids:
            return
        self.ensure_ready()
        client = get_client()
        for start in range(0, len(ids), DELETE_BATCH):
            client.delete(
                collection_name=self.collection,
                points_selector=models.PointIdsList(
                    points=ids[start : start + DELETE_BATCH]
                ),
                wait=True,
            )
