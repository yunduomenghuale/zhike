"""向量检索抽象（后端可切换：json / qdrant）。

起步实现：知识库片段的 embedding 存 MySQL JSON 字段，做暴力余弦相似度检索。
2026-11 接入 Qdrant：向量同时写入 Qdrant 集合，检索按
``settings.RAG_VECTOR_BACKEND`` 选后端——**调用方代码不变**，切换只改配置，
回滚只需改回 json（数据依赖 MySQL 的 embedding 列，回滚零成本、零重算）。

调用方唯一入口是 ``search_chunks`` / ``search_with_filter``；降级逻辑也收在
这里：Qdrant 不可用（连不上/超时/集合没回填/客户端未装）时自动回落 JSON 后端，
并通过 ``vector_meta()`` 把「本次实际走了哪个后端 + 是否降级」暴露给响应层
（沿用 provider 回退的显性化思路，见 apps/ai/providers/fallback.py）。
"""
from __future__ import annotations

import contextvars
import logging
import threading
import time

from django.conf import settings

from .vector_backends import (
    ChunkFilter,
    VectorBackend,
    cosine,
    get_backend,
    get_json_backend,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ChunkFilter",
    "cosine",
    "search_chunks",
    "search_with_filter",
    "vector_meta",
    "consume_vector_meta",
    "note_vector_fallback",
    "breaker_open",
    "reset_vector_breaker",
]

# 本次请求的向量检索元信息：{"backend": "json"|"qdrant", "fallback": bool, "reason": str}
# 用 contextvar 而非模块全局：worker/线程池里并发请求共享模块，全局会串号。
_vector_meta: contextvars.ContextVar = contextvars.ContextVar(
    "rag_vector_meta", default=None
)


def _set_meta(backend: str, fallback: bool = False, reason: str = "") -> None:
    """记录本次检索实际使用的后端。

    降级标记是「请求级」的粘性标记（对齐 provider 回退语义）：章节内检索降级过，
    随后退回全课程检索成功，也不能把「已降级」抹掉——否则响应体上看不到降级，
    运维就失去唯一线索。
    """
    prev = _vector_meta.get() or {}
    if not fallback and prev.get("fallback"):
        return
    _vector_meta.set({"backend": backend, "fallback": bool(fallback), "reason": reason})


def note_vector_fallback(reason: str) -> None:
    """记录一次降级（只保留首个原因，不覆盖已有标记）。"""
    current = _vector_meta.get() or {}
    if reason and not current.get("fallback"):
        _vector_meta.set(
            {"backend": "json", "fallback": True, "reason": _clean_reason(reason)}
        )


def _clean_reason(reason: str) -> str:
    """压成单行短串：异常原文可能带换行/二进制片段，直接进响应体很难看。"""
    return " ".join(str(reason or "").split())[:200]


def vector_meta() -> dict:
    """读取本次请求的向量检索元信息（不消费，供 snapshot 落库）。"""
    return dict(_vector_meta.get() or {})


def consume_vector_meta() -> dict:
    """读取并清空（响应收口用，避免同一请求多处响应重复携带）。"""
    meta = dict(_vector_meta.get() or {})
    _vector_meta.set(None)
    return meta


def _qdrant_collection_empty_for_course(backend: VectorBackend, flt: ChunkFilter) -> bool:
    """集合里没有该课程的任何向量，但 MySQL 有片段 → 判定为「未回填」。

    这是**部署期最危险的空结果**：Qdrant 正常、查询正常、就是没数据，问答会
    静默变成「资料不足」。识别出来后按降级处理（回落 json 并打标），不让
    切换动作把线上问答能力打回零。
    """
    try:
        from apps.knowledge.models import KnowledgeChunk

        if getattr(backend, "points_for_course", None) is None:
            return False
        if backend.points_for_course(flt.course_id) > 0:
            return False
        return KnowledgeChunk.objects.filter(course_id=flt.course_id).exists()
    except Exception:  # noqa: BLE001 - 探测失败不改变主流程
        return False


# ---------------------------------------------------------------------------
# 熔断：Qdrant 持续不可用时不再逐请求空试
# ---------------------------------------------------------------------------
# 为什么需要：Qdrant 挂掉后每次检索仍会先试一次（DNS/连接失败），实测在降级
# 状态下 p95 被拖到 11.7s（正常 2.2s + 重试与解析器超时）。熔断后连续失败达阈值
# 就一段时间内直接走 json，不再发请求；窗口过后自动放行一次探活，成功即恢复。
# 进程级状态即可：gunicorn 每个 worker 各自熔断，最坏情况是每进程各试几次。
_breaker_lock = threading.Lock()
_breaker_state = {"failures": 0, "open_until": 0.0}


def _breaker_threshold() -> int:
    return max(int(getattr(settings, "RAG_QDRANT_BREAKER_THRESHOLD", 3) or 0), 0)


def _breaker_seconds() -> int:
    return max(int(getattr(settings, "RAG_QDRANT_BREAKER_SECONDS", 30) or 0), 1)


def breaker_open() -> bool:
    """熔断是否处于打开状态（窗口内不再尝试 Qdrant）。"""
    with _breaker_lock:
        return time.monotonic() < _breaker_state["open_until"]


def reset_vector_breaker() -> None:
    """手动复位熔断（运维排查后 / 测试用）。"""
    with _breaker_lock:
        _breaker_state["failures"] = 0
        _breaker_state["open_until"] = 0.0


def _breaker_on_success() -> None:
    with _breaker_lock:
        _breaker_state["failures"] = 0
        _breaker_state["open_until"] = 0.0


def _breaker_on_failure() -> None:
    threshold = _breaker_threshold()
    with _breaker_lock:
        _breaker_state["failures"] += 1
        if threshold and _breaker_state["failures"] >= threshold:
            _breaker_state["open_until"] = time.monotonic() + _breaker_seconds()


def search_with_filter(
    flt: ChunkFilter, query_vec: list[float], top_k: int = 5
):
    """按已组装好的过滤条件检索，返回 [(chunk, score), ...]。

    Qdrant 路径的任何异常都不外抛：记一次降级标记后走 JSON 后端——向量库是
    加速层，不能因为它的抖动让问答整体不可用。连续失败达阈值后进入熔断窗口，
    窗口内直接走 JSON（不再逐请求空试 Qdrant）。
    """
    backend = get_backend()
    if backend.name != "qdrant":
        hits = backend.search(flt, query_vec, top_k)
        _set_meta(backend.name, False, "")
        return hits

    if breaker_open():
        threshold = _breaker_threshold()
        reason = f"Qdrant 连续失败 {threshold} 次已熔断（{_breaker_seconds()}s 后重试），走 MySQL 检索"
        note_vector_fallback(reason)
        return get_json_backend().search(flt, query_vec, top_k)

    try:
        hits = backend.search(flt, query_vec, top_k)
        if not hits and _qdrant_collection_empty_for_course(backend, flt):
            reason = "Qdrant 集合中该课程尚无向量（未回填），已回落 MySQL 检索"
            note_vector_fallback(reason)
            logger.warning("[rag] %s course=%s", reason, flt.course_id)
            return get_json_backend().search(flt, query_vec, top_k)
        _breaker_on_success()
        _set_meta("qdrant", False, "")
        return hits
    except Exception as exc:  # noqa: BLE001 - 降级优先
        _breaker_on_failure()
        reason = f"Qdrant 检索不可用，已回落 MySQL 检索：{str(exc)[:200]}"
        note_vector_fallback(reason)
        logger.warning("[rag] %s", _clean_reason(reason))
        return get_json_backend().search(flt, query_vec, top_k)


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

    后端切换：以上语义由 ``ChunkFilter`` 承载，json / qdrant 两个后端各自翻译
    （qdrant 见 vector_backends/qdrant_backend.py 的 build_qdrant_filter），
    两处必须等价——改动任一实现都要跑 compare_retrieval 比对。
    """
    return search_with_filter(
        ChunkFilter.build(
            course_id,
            catalog_id=catalog_id,
            student_access=student_access,
            classroom_ids=classroom_ids,
        ),
        query_vec,
        top_k,
    )
