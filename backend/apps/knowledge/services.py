"""知识库维护服务（向量重建，覆盖教辅资料与课件 PPT）。

为什么需要重建向量：
1. 更换向量模型后，新旧向量处于不同的向量空间，cosine 维度不符时
   ``vectorstore.cosine`` 静默返回 0.0——不报错，但所有旧片段永久沉底，
   知识库检索实际已失效；
2. 曾用模拟模式（Mock 64 维假向量）入过库的资料，需要换成真实模型的向量；
3. 全量刷新：切分策略/模型版本升级后统一重算。

课件 PPT 是向量库的主要内容（每页一个片段），与教辅资料同等对待。

出错处理是重点，本模块的四条防线：
1. **事前校验、失败即止**：先用固定样本试嵌一次（allow_fallback=False），
   确认向量模型真实可用并拿到维度。模型不可用时直接返回错误、
   不动任何数据——避免跑到一半才发现不可用，留下半新半旧的混合状态。
2. **先算后删、事务内替换**：每份资料/课件先算出全部新向量并校验数量/维度，
   通过后才在事务里 delete + bulk_create；写入异常时删除回滚，旧片段原样保留。
3. **单项失败可续跑**：某份资料/课件失败只记录原因并继续下一项，返回失败清单；
   修复后按 material_id / ppt_id 再次调用即可只补失败的，不会重复劳动。
4. **全链路禁用 mock 兜底**：嵌入一律 allow_fallback=False，杜绝 64 维假向量
   混进真实向量空间。
"""
from __future__ import annotations

# 事前校验用的固定样本：与业务文本无关，只为确认「模型可用 + 拿到维度」
_DIMENSION_PROBE = "向量重建维度校验样本"

# 与 ingest_material 保持一致：重建后的切分方式必须和入库时相同，
# 否则重新解析（reparse）又会生成另一套片段
_CHUNK_SIZE = 500


from apps.ai.calllog import scene_decorator
from apps.ai.models import AICallLog
from apps.ai.services import split_text_semantic


class RebuildError(RuntimeError):
    """单份资料/课件重建失败（携带可向用户展示的原因）。"""


@scene_decorator(AICallLog.Scene.VECTOR_REBUILD)
def rebuild_vectors(materials=None, ppts=None, videos=None) -> dict:
    """用当前生效的向量模型重建给定资料、课件与讲稿的向量。

    materials：Material 可迭代对象（调用方需先完成权限/范围过滤）。
    ppts：PPTResource 可迭代对象（只重建当前启用版本 is_active=True）。
    videos：TeachingVideo 可迭代对象（讲稿片段，每页一片段）。
    返回报告::

        {
            "materials": {"total", "success", "failed": [...]},
            "ppts": {"total", "success", "chunks", "failed": [...]},
            "videos": {"total", "success", "chunks", "failed": [...]},
            "total": 资料+课件+讲稿总数, "success": 成功总数,
            "failed": 合并失败清单（条目带 kind，可续跑）,
            "chunks": 重建片段总数（资料+课件+讲稿）,
            "provider": 实际 provider 名, "model": 向量模型名, "dimension": 向量维度,
            "error": "",  # 非空表示事前校验失败，整体未执行
        }
    """
    from apps.ai.providers.factory import get_provider
    from apps.ai.providers.mock import MockProvider

    report = {
        "materials": {"total": 0, "success": 0, "failed": []},
        "ppts": {"total": 0, "success": 0, "chunks": 0, "failed": []},
        "videos": {"total": 0, "success": 0, "chunks": 0, "failed": []},
        "total": 0,
        "success": 0,
        "failed": [],
        "chunks": 0,
        "provider": "",
        "model": "",
        "dimension": 0,
        "error": "",
    }
    materials = list(materials or [])
    ppts = list(ppts or [])
    videos = list(videos or [])
    report["materials"]["total"] = len(materials)
    report["ppts"]["total"] = len(ppts)
    report["videos"]["total"] = len(videos)
    report["total"] = len(materials) + len(ppts) + len(videos)
    if not materials and not ppts and not videos:
        report["error"] = "没有需要重建的资料、课件或讲稿"
        return report

    provider = get_provider("embed")
    report["provider"] = provider.name
    report["model"] = getattr(provider, "embed_model", "") or ""
    # 模拟模式（含未配置 embed 模型的真实服务商回落）不接受重建：
    # 用 64 维假向量覆盖真实向量空间比不重建更糟
    if isinstance(provider, MockProvider) or provider.name == "mock":
        report["error"] = (
            "向量模型未配置或已回退模拟模式：请先在管理端「大模型配置 · 向量化」"
            "中启用真实向量模型（通义千问或本地模型服务），并测试连接通过后再重建"
        )
        return report

    # 防线 1：试嵌样本，确认真实可用并记录维度（失败即止，不动数据）
    try:
        probe = provider.embed([_DIMENSION_PROBE], allow_fallback=False)
    except Exception as exc:
        report["error"] = f"向量模型调用失败：{str(exc)[:300]}"
        return report
    dimension = len(probe[0]) if probe and probe[0] else 0
    if not dimension:
        report["error"] = "向量模型返回了空向量，请检查模型配置后重试"
        return report
    report["dimension"] = dimension

    # 防线 3：逐项重建，单项失败记录原因继续（可续跑）
    for material in materials:
        try:
            report["chunks"] += _rebuild_one(material, provider, dimension)
            report["materials"]["success"] += 1
            report["success"] += 1
        except Exception as exc:
            _record_failure(report, "material", material.id, material.file_name, str(exc))
    for ppt in ppts:
        try:
            count = _rebuild_ppt_one(ppt, provider, dimension)
            report["ppts"]["chunks"] += count
            report["chunks"] += count
            report["ppts"]["success"] += 1
            report["success"] += 1
        except Exception as exc:
            _record_failure(report, "ppt", ppt.id, ppt.file_name, str(exc))
    for video in videos:
        try:
            count = _rebuild_script_one(video, provider, dimension)
            report["videos"]["chunks"] += count
            report["chunks"] += count
            report["videos"]["success"] += 1
            report["success"] += 1
        except Exception as exc:
            _record_failure(report, "video", video.id, f"{video.catalog_id} 章节讲稿", str(exc))
    return report


def _record_failure(report: dict, kind: str, obj_id, file_name: str, reason: str) -> None:
    """记录失败项：同时进分项清单与合并清单（带 kind 便于前端续跑）。"""
    id_key = {"material": "material_id", "ppt": "ppt_id", "video": "video_id"}[kind]
    item = {
        "kind": kind,
        id_key: obj_id,
        "file_name": file_name,
        "reason": reason[:300],
    }
    section = {"material": "materials", "ppt": "ppts", "video": "videos"}[kind]
    report[section]["failed"].append(item)
    report["failed"].append(item)


def _rebuild_one(material, provider, dimension: int) -> int:
    """重建单份资料的向量，返回片段数。任何失败都抛 RebuildError，旧数据不动。"""
    from django.db import transaction

    from .extractor import extract_text
    from .models import KnowledgeChunk

    if not material.file:
        raise RebuildError("资料文件缺失，请重新上传")

    file_path = material.file.path
    # extract_text 对缺失/不可解析文件返回空串（内部已 try），不抛异常
    raw_text = (getattr(material, "_extracted_text", "") or extract_text(file_path)).strip()
    if not raw_text:
        material.parse_status = material.ParseStatus.FAILED
        material.save(update_fields=["parse_status", "updated_at"])
        raise RebuildError("未能抽取到文本内容（文件可能为扫描件、空文件或已损坏）")

    pieces = split_text_semantic(raw_text, size=_CHUNK_SIZE) or [raw_text]

    # 防线 4：禁用 mock 兜底；防线 2：先算后删——全部校验通过才替换旧片段
    try:
        embeddings = provider.embed(pieces, allow_fallback=False)
    except Exception as exc:
        raise RebuildError(f"向量生成失败：{str(exc)[:200]}")
    if len(embeddings) != len(pieces):
        raise RebuildError(
            f"向量数量与文本片段不一致（返回 {len(embeddings)} 条 / 应有 {len(pieces)} 条），已保留旧向量"
        )
    for emb in embeddings:
        if not emb or len(emb) != dimension:
            raise RebuildError(
                f"向量维度不一致（期望 {dimension} 维，实际 {len(emb) if emb else 0} 维），已保留旧向量"
            )

    objs = [
        KnowledgeChunk(
            source=KnowledgeChunk.Source.MATERIAL,
            material=material,
            course_id=material.course_id,
            catalog_id=material.catalog_id,
            content=piece,
            embedding=emb,
        )
        for piece, emb in zip(pieces, embeddings)
    ]
    with transaction.atomic():
        material.chunks.all().delete()
        KnowledgeChunk.objects.bulk_create(objs)

    material.parse_status = material.ParseStatus.DONE
    material.save(update_fields=["parse_status", "updated_at"])
    return len(objs)


def _rebuild_ppt_one(ppt, provider, dimension: int) -> int:
    """重建单部课件的向量（每页一个片段），返回片段数。失败抛 RebuildError，旧数据不动。

    与 _rebuild_one 的差别：页面文本直接取自 ppt.parsed_pages（已解析的
    结构化数据，无需再读文件），也不修改 parse_status——解析状态与向量
    入库是否成功无关。
    """
    from django.db import transaction

    from .models import KnowledgeChunk

    pieces: list[str] = []
    page_nos: list = []
    for pg in ppt.parsed_pages or []:
        if not isinstance(pg, dict):
            continue
        text = f"{pg.get('title', '') or ''}\n{pg.get('body', '') or ''}".strip()
        if not text:
            continue
        pieces.append(text)
        page_nos.append(pg.get("page") or len(pieces))
    if not pieces:
        raise RebuildError("课件没有可入库的页面文本（可能为扫描件或空文件）")

    try:
        embeddings = provider.embed(pieces, allow_fallback=False)
    except Exception as exc:
        raise RebuildError(f"向量生成失败：{str(exc)[:200]}")
    if len(embeddings) != len(pieces):
        raise RebuildError(
            f"向量数量与课件页面不一致（返回 {len(embeddings)} 条 / 应有 {len(pieces)} 条），已保留旧向量"
        )
    for emb in embeddings:
        if not emb or len(emb) != dimension:
            raise RebuildError(
                f"向量维度不一致（期望 {dimension} 维，实际 {len(emb) if emb else 0} 维），已保留旧向量"
            )

    objs = [
        KnowledgeChunk(
            source=KnowledgeChunk.Source.PPT,
            ppt=ppt,
            course_id=ppt.course_id,
            catalog_id=ppt.catalog_id,
            content=piece,
            page=page_no,
            embedding=emb,
        )
        for piece, page_no, emb in zip(pieces, page_nos, embeddings)
    ]
    with transaction.atomic():
        ppt.chunks.all().delete()
        KnowledgeChunk.objects.bulk_create(objs)
    return len(objs)


def _rebuild_script_one(video, provider, dimension: int) -> int:
    """重建单部教学视频的讲稿向量（每页一个片段），返回片段数。失败抛 RebuildError。

    与 _rebuild_ppt_one 的差别：片段文本带 PPT 页标题（与 ingest_video_scripts
    口径一致——重建切分方式必须和入库时相同，否则讲稿更新又会生成另一套片段）。
    """
    from django.db import transaction

    from .models import KnowledgeChunk

    page_titles: dict = {}
    for pg in (video.ppt.parsed_pages or []) if video.ppt else []:
        if isinstance(pg, dict) and pg.get("page"):
            page_titles[int(pg["page"])] = (pg.get("title") or "").strip()

    pieces: list[str] = []
    page_nos: list = []
    for s in video.scripts or []:
        if not isinstance(s, dict):
            continue
        text = (s.get("script") or "").strip()
        if not text:
            continue
        page_no = s.get("page") or len(pieces) + 1
        title = page_titles.get(int(page_no) if page_no else 0, "")
        pieces.append(f"{title}\n{text}" if title else text)
        page_nos.append(page_no)
    if not pieces:
        raise RebuildError("讲稿没有可入库的页面内容")

    try:
        embeddings = provider.embed(pieces, allow_fallback=False)
    except Exception as exc:
        raise RebuildError(f"向量生成失败：{str(exc)[:200]}")
    if len(embeddings) != len(pieces):
        raise RebuildError(
            f"向量数量与讲稿页面不一致（返回 {len(embeddings)} 条 / 应有 {len(pieces)} 条），已保留旧向量"
        )
    for emb in embeddings:
        if not emb or len(emb) != dimension:
            raise RebuildError(
                f"向量维度不一致（期望 {dimension} 维，实际 {len(emb) if emb else 0} 维），已保留旧向量"
            )

    objs = [
        KnowledgeChunk(
            source=KnowledgeChunk.Source.SCRIPT,
            video=video,
            course_id=video.course_id,
            catalog_id=video.catalog_id,
            content=piece,
            page=page_no,
            embedding=emb,
        )
        for piece, page_no, emb in zip(pieces, page_nos, embeddings)
    ]
    with transaction.atomic():
        video.chunks.all().delete()
        KnowledgeChunk.objects.bulk_create(objs)
    return len(objs)
