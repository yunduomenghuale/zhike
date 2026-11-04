"""片段写入/删除时与 Qdrant 的同步（双写）。

三条原则：

1. **JSON 永远写**：向量就存在 ``KnowledgeChunk.embedding``，MySQL 是唯一真相，
   也是回滚路径；Qdrant 只是它的外置索引，开启时才同步。
2. **提交后再动 Qdrant**：所有同步都挂 ``transaction.on_commit``——事务回滚了
   就不该留下外部副作用（重新解析失败时旧片段仍在库里，Qdrant 也必须保持旧态）。
3. **失败只记日志**：向量库是加速层，任何时候都不能因为 Qdrant 抖动让上传、
   入库、编辑、删除失败。异常一律吞掉并 warning。

写入的两条触发路径（删库里的片段 → 同步删 Qdrant，这一条只有信号）：

- ingest / rebuild 走 ``bulk_create``（不发 post_save 信号）→ 由调用方显式
  调 ``sync_owner`` 回查后 upsert。注意 MySQL 的 ``bulk_create`` **不回填主键**，
  所以必须回查而不能直接用内存对象；
- 单条 ``chunk.save()``（管理端修补等）→ post_save 信号；
- 任何删除（单条 / ``queryset.delete()`` / 级联删课程删课件）→ post_delete
  信号 + id 缓冲批量删，避免一次级联几千条把删除拖死。
"""
from __future__ import annotations

import contextvars
import logging

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

# 待删除的 chunk id 缓冲（同一上下文/事务内累积，提交时一次性批量删）
_pending_deletes: contextvars.ContextVar = contextvars.ContextVar(
    "rag_pending_qdrant_deletes", default=None
)

_OWNER_FILTERS = {
    "material": ("material_id", "material"),
    "ppt": ("ppt_id", "ppt"),
    "video": ("video_id", "video"),
}


def qdrant_enabled() -> bool:
    return (getattr(settings, "RAG_VECTOR_BACKEND", "json") or "json").strip().lower() == "qdrant"


def _backend():
    from .vector_backends import get_qdrant_backend

    return get_qdrant_backend()


def _safe(label: str, fn, *args, **kwargs) -> None:
    """执行同步动作，异常只记日志（绝不影响业务主流程）。"""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - 加速层降级
        logger.warning("[qdrant-sync] %s 失败（已忽略，MySQL 数据不受影响）：%s", label, exc)
        return None


# ---------------------------------------------------------------------------
# 写：新增/更新
# ---------------------------------------------------------------------------
def _chunks_by_owner(owner_kind: str, owner):
    from apps.knowledge.models import KnowledgeChunk

    from .vector_backends.json_backend import CHUNK_RELATIONS

    field = _OWNER_FILTERS[owner_kind][0]
    if owner is None or not getattr(owner, "pk", None):
        return []
    return list(
        KnowledgeChunk.objects.filter(**{field: owner.pk})
        .exclude(embedding=[])
        .select_related(*CHUNK_RELATIONS)
    )


def sync_owner(owner_kind: str, owner) -> None:
    """事务提交后按来源对象回查片段并 upsert（ingest/rebuild 用）。

    owner_kind: material / ppt / video
    """
    if not qdrant_enabled() or owner is None or not getattr(owner, "pk", None):
        return
    owner_pk = owner.pk
    transaction.on_commit(
        lambda: _safe(
            f"sync {owner_kind} {owner_pk}",
            lambda: _backend().upsert(_chunks_by_owner(owner_kind, owner)),
        )
    )


def sync_chunks_now(chunks) -> int:
    """直接 upsert 一批片段（已在内存中且带 select_related 时用）。"""
    if not qdrant_enabled():
        return 0
    chunks = [c for c in chunks if getattr(c, "pk", None)]
    if not chunks:
        return 0
    written = _safe("upsert chunks", lambda: _backend().upsert(chunks))
    return int(written or 0)


def sync_chunk_ids(ids) -> None:
    """事务提交后按 id 回查并 upsert（单条保存/外部写入用）。"""
    if not qdrant_enabled():
        return
    ids = [int(i) for i in ids if i]
    if not ids:
        return
    transaction.on_commit(
        lambda: _safe(
            f"sync chunk ids {ids[:3]}",
            lambda: _backend().upsert(_chunks_by_ids(ids)),
        )
    )


def sync_course(course_id) -> None:
    """事务提交后按课程整批 upsert（课程复用这类「整门课 bulk 复制」场景）。

    课程复用的片段是随行复制（内容与源课程一致、不重算向量），量级可能上千条，
    故按主键 keyset 分页写，不一次性把整门课的向量读进内存。
    """
    if not qdrant_enabled() or not course_id:
        return
    transaction.on_commit(
        lambda: _safe(f"sync course {course_id}", lambda: _sync_course_now(course_id))
    )


def _sync_course_now(course_id, batch_size: int = 1000) -> int:
    from apps.knowledge.models import KnowledgeChunk

    from .vector_backends.json_backend import CHUNK_RELATIONS

    backend = _backend()
    written = 0
    last_id = 0
    while True:
        page = list(
            KnowledgeChunk.objects.filter(course_id=course_id, id__gt=last_id)
            .exclude(embedding=[])
            .order_by("id")
            .select_related(*CHUNK_RELATIONS)[:batch_size]
        )
        if not page:
            return written
        written += backend.upsert(page)
        last_id = page[-1].id


def _chunks_by_ids(ids):
    from apps.knowledge.models import KnowledgeChunk

    from .vector_backends.json_backend import CHUNK_RELATIONS

    return list(
        KnowledgeChunk.objects.filter(id__in=ids)
        .exclude(embedding=[])
        .select_related(*CHUNK_RELATIONS)
    )


# ---------------------------------------------------------------------------
# 删：单条 / queryset / 级联
# ---------------------------------------------------------------------------
def schedule_delete(ids) -> None:
    """把待删 id 收进缓冲，事务提交后批量删除。

    每次都注册一次 on_commit（而不是「只在开缓冲时注册一次」）：上一次注册可能
    随事务回滚被丢弃，而缓冲里还留着那批 id——若这次不补注册，后续删除就再也不
    会触发 flush。重复注册是安全的：flush 只处理当时的缓冲，处理完即清空。
    """
    if not qdrant_enabled():
        return
    ids = [int(i) for i in ids if i]
    if not ids:
        return
    buf = _pending_deletes.get()
    if buf is None:
        buf = []
        _pending_deletes.set(buf)
    buf.extend(ids)
    transaction.on_commit(_flush_deletes)


def _flush_deletes() -> None:
    """批量删除缓冲里的 chunk 点。

    删除前先回查库里是否还有这些 id：**只删库里确实没有了的**。这一步让删除
    同步幂等且事后可证——事务回滚后行还在（不该删）、重复调度（不该报错）、
    跨请求残留的缓冲都不会误删有效片段。
    """
    from apps.knowledge.models import KnowledgeChunk

    buf = _pending_deletes.get() or []
    _pending_deletes.set(None)
    ids = sorted(set(buf))
    if not ids:
        return
    alive = set(
        KnowledgeChunk.objects.filter(id__in=ids).values_list("id", flat=True)
    )
    gone = [i for i in ids if i not in alive]
    if gone:
        _safe(f"delete {len(gone)} chunks", lambda: _backend().delete(gone))


# ---------------------------------------------------------------------------
# 信号
# ---------------------------------------------------------------------------
def _on_chunk_saved(sender, instance, **kwargs) -> None:
    if not qdrant_enabled():
        return
    if not getattr(instance, "pk", None) or not (instance.embedding or []):
        return
    sync_chunk_ids([instance.pk])


def _on_chunk_deleted(sender, instance, **kwargs) -> None:
    """pre_delete 而不是 post_delete：单对象删除的快路径里 Django 会先把主键
    置空再发 post_delete，那样就丢掉 chunk_id、Qdrant 里留下永远删不掉的死点。
    """
    if not qdrant_enabled():
        return
    if getattr(instance, "pk", None):
        schedule_delete([instance.pk])


# ---------------------------------------------------------------------------
# 可见性字段变了 → 刷新受影响的片段 payload
# ---------------------------------------------------------------------------
# 为什么必须做：payload 里的 qa_open / classroom_id / catalog_published /
# video_published 是**父对象状态的快照**。老师发布章节、开关资料的 QA、切换课件
# 版本时，片段本身没变，但 payload 的可见性判定已经过期——Qdrant 会继续把学生
# 挡在新发布的章节外（DB 复验只能删多余命中，补不回漏掉的），表现为「学生问本
# 章内容没有引用」。测试环境实测复现：发布章节后学生池 42 条，Qdrant 侧 0 条。
#
# 触发方式：父对象 post_save + update_fields 交集判断（无关字段的保存不触发）。
# `queryset.update()` 不发信号，这类批量改法（管理端脚本）需用
# `manage.py backfill_qdrant --course <id>` 补，compare_retrieval 可作为探测器。
_PARENT_FIELDS = {
    "catalog": {"is_published"},
    "material": {"qa_open", "classroom_id", "catalog_id"},
    "ppt": {"is_active", "catalog_id"},
    "video": {"is_published", "catalog_id"},
}


def _fields_touched(kwargs, key: str) -> bool:
    fields = kwargs.get("update_fields")
    if fields is None:  # 全量 save：无法判断，按相关处理
        return True
    return bool(_PARENT_FIELDS[key] & set(fields))


def _on_catalog_saved(sender, instance, **kwargs) -> None:
    if not qdrant_enabled() or not getattr(instance, "pk", None):
        return
    if not _fields_touched(kwargs, "catalog"):
        return
    catalog_id = instance.pk
    transaction.on_commit(
        lambda: _safe(
            f"refresh catalog {catalog_id} payload",
            lambda: _sync_owner_chunks("catalog", catalog_id),
        )
    )


def _on_material_saved(sender, instance, **kwargs) -> None:
    if not qdrant_enabled() or not getattr(instance, "pk", None):
        return
    if not _fields_touched(kwargs, "material"):
        return
    material_id = instance.pk
    transaction.on_commit(
        lambda: _safe(
            f"refresh material {material_id} payload",
            lambda: _sync_owner_chunks("material", material_id),
        )
    )


def _on_ppt_saved(sender, instance, **kwargs) -> None:
    if not qdrant_enabled() or not getattr(instance, "pk", None):
        return
    if not _fields_touched(kwargs, "ppt"):
        return
    ppt_id = instance.pk
    transaction.on_commit(
        lambda: _safe(
            f"refresh ppt {ppt_id} payload",
            lambda: _sync_owner_chunks("ppt", ppt_id),
        )
    )


def _on_video_saved(sender, instance, **kwargs) -> None:
    if not qdrant_enabled() or not getattr(instance, "pk", None):
        return
    if not _fields_touched(kwargs, "video"):
        return
    video_id = instance.pk
    transaction.on_commit(
        lambda: _safe(
            f"refresh video {video_id} payload",
            lambda: _sync_owner_chunks("video", video_id),
        )
    )


def _sync_owner_chunks(owner_kind: str, owner_id: int) -> int:
    """按父对象（章节/资料/课件/视频）把其名下片段的 payload 重刷一遍。"""
    from apps.knowledge.models import KnowledgeChunk

    from .vector_backends.json_backend import CHUNK_RELATIONS

    field = {"catalog": "catalog_id", "material": "material_id", "ppt": "ppt_id", "video": "video_id"}[
        owner_kind
    ]
    backend = _backend()
    written = 0
    last_id = 0
    while True:
        page = list(
            KnowledgeChunk.objects.filter(**{field: owner_id}, id__gt=last_id)
            .exclude(embedding=[])
            .order_by("id")
            .select_related(*CHUNK_RELATIONS)[:500]
        )
        if not page:
            return written
        written += backend.upsert(page)
        last_id = page[-1].id


def connect_signals() -> None:
    """在 AppConfig.ready() 里调用（重复调用安全，靠 dispatch_uid 去重）。"""
    from django.db.models.signals import post_save, pre_delete

    from apps.courses.models import Catalog, PPTResource, TeachingVideo
    from apps.knowledge.models import KnowledgeChunk, Material

    post_save.connect(
        _on_chunk_saved,
        sender=KnowledgeChunk,
        dispatch_uid="rag_qdrant_chunk_saved",
        weak=False,
    )
    pre_delete.connect(
        _on_chunk_deleted,
        sender=KnowledgeChunk,
        dispatch_uid="rag_qdrant_chunk_deleted",
        weak=False,
    )
    for func, sender, uid in (
        (_on_catalog_saved, Catalog, "rag_qdrant_catalog_saved"),
        (_on_material_saved, Material, "rag_qdrant_material_saved"),
        (_on_ppt_saved, PPTResource, "rag_qdrant_ppt_saved"),
        (_on_video_saved, TeachingVideo, "rag_qdrant_video_saved"),
    ):
        post_save.connect(func, sender=sender, dispatch_uid=uid, weak=False)
