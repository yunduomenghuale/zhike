"""课程复用（资产整份复制）：把一门课的章节 / 课件 / 讲稿配音 / 资料 / 知识库 /
教学资源 /（可选）题目复制到一门新课程。

设计口径（任务规范 §4 P3）：

1. **真复制，不共享路径**。`ppt_pages/<dirname>` 是按 PPT 资源 id 派生的哈希目录，
   `tts/<uuid>`、`materials/<uuid>` 等也都是每条资产独立命名——共享路径的话，
   删源课程会连带删掉目标课程的资产（规范明确要求「删源课程后新课程资产完好」）。
   因此所有磁盘文件都逐份复制，磁盘增量 ≈ 源课程 media 体积。
2. **向量不重算**。`KnowledgeChunk.embedding` 是 JSON 列，直接随行复制：
   - 复用立刻可用，不必再花一次 embedding 费用（146 片段重嵌入成本不低）；
   - 文本内容完全一致，重算只会得到近似但不同的向量，反而让「片段数一致 + 检索命中」变得不可解释。
3. **失败必须干净回滚**。整份复制在单个事务里；文件不受事务保护，所以逐次登记
   已写文件，异常时统一删除 —— 不留半成品课程，也不留孤儿文件（规范 P3-5）。
4. **产物一律 `status=inactive`**。学生端 `courses_for_user()` 只放行 active 课程，
   所以挂班后学生也看不见；教师确认无误后置 active 才对学学生可见（规范 P3-4）。
5. **班级绑定不复制**。`Material.classroom` 属于「某班专属资料」，复用是课程资产层面的
   动作，带到新课程会让新班的课看到别的班的资料，故置空。
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from django.core.files.storage import default_storage
from django.db import transaction

from apps.knowledge.models import KnowledgeChunk, Material
from apps.questions.models import Question

from .models import Catalog, Course, CourseResource, PPTResource, TeachingVideo
from .ppt_parser import ppt_pages_dirname

MEDIA_URL_PREFIX = "/media/"


# ---------------------------------------------------------------------------
# 统计（复用前预览用）
# ---------------------------------------------------------------------------
@dataclass
class AssetStats:
    catalog_count: int = 0
    catalog_depth: int = 0
    ppt_count: int = 0
    ppt_pages: int = 0
    video_count: int = 0
    script_pages: int = 0
    audio_count: int = 0
    material_count: int = 0
    chunk_count: int = 0
    resource_count: int = 0
    resource_document_count: int = 0
    question_count: int = 0
    media_bytes: int = 0
    question_media_bytes: int = 0
    sections: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "catalog_count": self.catalog_count,
            "catalog_depth": self.catalog_depth,
            "ppt_count": self.ppt_count,
            "ppt_pages": self.ppt_pages,
            "video_count": self.video_count,
            "script_pages": self.script_pages,
            "audio_count": self.audio_count,
            "material_count": self.material_count,
            "chunk_count": self.chunk_count,
            "resource_count": self.resource_count,
            "resource_document_count": self.resource_document_count,
            "question_count": self.question_count,
            "media_bytes": self.media_bytes,
            "question_media_bytes": self.question_media_bytes,
            "media_human": human_size(self.media_bytes),
            "question_media_human": human_size(self.question_media_bytes),
            "sections": self.sections,
        }


def human_size(size: int) -> str:
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _storage_name(url: str) -> str | None:
    """把 /media/xxx 形式的地址转成 storage 相对名；外链/空值返回 None。"""
    text = str(url or "").strip()
    if not text.startswith(MEDIA_URL_PREFIX):
        return None
    return text[len(MEDIA_URL_PREFIX):].lstrip("/")


def _file_size(name: str | None) -> int:
    if not name:
        return 0
    try:
        return default_storage.size(name)
    except Exception:
        return 0


def course_asset_stats(course: Course) -> AssetStats:
    """盘点一门课的资产数量与占用体积（不含题目时也会给出题目数供选择）。"""
    stats = AssetStats()
    # 封面虽是 CharField，但 /media/ 形式时复用会真复制一份，需计入体积
    stats.media_bytes += _file_size(_storage_name(course.cover))
    catalogs = list(Catalog.objects.filter(course=course))
    stats.catalog_count = len(catalogs)
    stats.catalog_depth = _depth_of(catalogs)

    ppts = list(PPTResource.objects.filter(course=course))
    stats.ppt_count = len(ppts)
    for ppt in ppts:
        stats.ppt_pages += len(ppt.parsed_pages or [])
        stats.media_bytes += _file_size(ppt.file.name if ppt.file else "")
        for page in ppt.parsed_pages or []:
            stats.media_bytes += _file_size(_storage_name(page.get("image")))

    videos = list(TeachingVideo.objects.filter(course=course))
    stats.video_count = len(videos)
    seen_audio: set[str] = set()
    for video in videos:
        pages = list(video.scripts or [])
        stats.script_pages += len(pages)
        for item in pages:
            name = _storage_name(item.get("audio_url"))
            if name and name not in seen_audio:
                seen_audio.add(name)
                stats.audio_count += 1
                stats.media_bytes += _file_size(name)
        for url in (video.audio_url, video.subtitle_url, video.video_url):
            name = _storage_name(url)
            if name and name not in seen_audio:
                seen_audio.add(name)
                stats.media_bytes += _file_size(name)

    materials = list(Material.objects.filter(course=course))
    stats.material_count = len(materials)
    for material in materials:
        stats.media_bytes += _file_size(material.file.name if material.file else "")

    resources = list(CourseResource.objects.filter(course=course))
    stats.resource_count = len(resources)
    for resource in resources:
        if resource.kind == CourseResource.Kind.DOCUMENT:
            stats.resource_document_count += 1
            stats.media_bytes += _file_size(resource.file.name if resource.file else "")

    stats.chunk_count = KnowledgeChunk.objects.filter(course=course).count()
    questions = list(Question.objects.filter(course=course))
    stats.question_count = len(questions)
    for question in questions:
        stats.question_media_bytes += _file_size(question.image.name if question.image else "")

    stats.sections = {
        "catalog": stats.catalog_count,
        "ppt": stats.ppt_count,
        "video": stats.video_count,
        "material": stats.material_count,
        "chunk": stats.chunk_count,
        "resource": stats.resource_count,
        "question": stats.question_count,
    }
    return stats


def _depth_of(catalogs: list[Catalog]) -> int:
    """章节层级深度（1 = 只有章；2 = 章下有节）。"""
    return 2 if any(item.parent_id for item in catalogs) else 1


# ---------------------------------------------------------------------------
# 复制
# ---------------------------------------------------------------------------
class _FileLedger:
    """登记本次复制写出的所有文件，异常时统一清理（文件不受事务保护）。"""

    def __init__(self) -> None:
        self.names: list[str] = []
        self.bytes = 0

    def copy(self, name: str | None, folder: str, keep_name: bool = False) -> str:
        """复制 storage 文件到 folder/（默认重命名为 uuid），返回新的相对路径。"""
        if not name:
            return ""
        if not default_storage.exists(name):
            return ""
        suffix = Path(name).suffix.lower()
        target = f"{folder}/{Path(name).name if keep_name else f'{uuid.uuid4().hex}{suffix}'}"
        with default_storage.open(name, "rb") as src:
            saved = default_storage.save(target, src)
        self.names.append(saved)
        self.bytes += _file_size(saved)
        return saved

    def copy_url(self, url: str, folder: str, cache: dict[str, str] | None = None) -> str:
        """复制 /media/xxx 形式的地址，返回新的 /media/ 地址；外链原样返回。"""
        name = _storage_name(url)
        if not name:
            return url or ""
        if cache is not None and name in cache:
            return cache[name]
        saved = self.copy(name, folder)
        new_url = f"{MEDIA_URL_PREFIX}{saved}" if saved else ""
        if cache is not None:
            cache[name] = new_url
        return new_url

    def rollback(self) -> int:
        removed = 0
        for name in self.names:
            try:
                default_storage.delete(name)
                removed += 1
            except Exception:
                continue
        self.names.clear()
        return removed


@dataclass
class ReuseResult:
    course: Course
    stats: AssetStats
    copied: dict
    skipped_questions: int = 0
    media_bytes: int = 0

    def as_dict(self) -> dict:
        return {
            "course_id": self.course.id,
            "course_name": self.course.name,
            "status": self.course.status,
            "copied": self.copied,
            "skipped_questions": self.skipped_questions,
            "media_bytes": self.media_bytes,
            "media_human": human_size(self.media_bytes),
        }


def reuse_course(
    source: Course,
    *,
    teacher,
    name: str | None = None,
    term_id: int | None = None,
    include_questions: bool = False,
    on_progress=None,
) -> ReuseResult:
    """把 source 的资产整份复制成一门新课程（inactive）。失败则整体回滚、删净文件。"""
    ledger = _FileLedger()
    stats = course_asset_stats(source)
    copied: dict = {}

    def report(stage: str, done: int, total: int, message: str = "") -> None:
        if on_progress is None:
            return
        try:
            on_progress(stage, done, total, message)
        except Exception:  # 进度是尽力而为，不能拖垮复制
            pass

    try:
        with transaction.atomic():
            new_course = Course.objects.create(
                name=(name or f"{source.name}（复用）")[:200],
                intro=source.intro,
                cover=_copy_cover(source, ledger),
                term_id=term_id if term_id is not None else source.term_id,
                teacher=teacher,
                # 复用产物一律停用：教师核对后再启用（规范 P3-4）
                status=Course.Status.INACTIVE,
            )

            report("catalog", 0, stats.catalog_count, "复制章节结构")
            catalog_map = _copy_catalogs(source, new_course)
            copied["catalog"] = len(catalog_map)

            report("ppt", 0, stats.ppt_count, "复制课件与页图")
            ppt_map = _copy_ppts(source, new_course, catalog_map, ledger, report)
            copied["ppt"] = len(ppt_map)

            report("video", 0, stats.video_count, "复制讲稿与配音")
            video_map = _copy_videos(source, new_course, catalog_map, ppt_map, ledger, report)
            copied["video"] = len(video_map)

            report("material", 0, stats.material_count, "复制教辅资料")
            material_map = _copy_materials(source, new_course, catalog_map, ledger)
            copied["material"] = len(material_map)

            report("chunk", 0, stats.chunk_count, "复制知识库片段")
            copied["chunk"] = _copy_chunks(
                source, new_course, catalog_map, material_map, ppt_map, video_map
            )

            report("resource", 0, stats.resource_count, "复制教学资源")
            copied["resource"] = _copy_resources(source, new_course, ledger)

            skipped_questions = 0
            if include_questions:
                report("question", 0, stats.question_count, "复制题目")
                copied["question"], skipped_questions = _copy_questions(
                    source, new_course, catalog_map, ledger, teacher
                )
            else:
                copied["question"] = 0

            report("done", 1, 1, "完成")
            return ReuseResult(
                course=new_course,
                stats=stats,
                copied=copied,
                skipped_questions=skipped_questions,
                media_bytes=ledger.bytes,
            )
    except Exception:
        ledger.rollback()
        raise


def _copy_cover(source: Course, ledger: _FileLedger) -> str:
    """封面是 CharField：只有 /media/ 形式才需要真复制，外链原样带走。"""
    cover = source.cover or ""
    if not cover:
        return ""
    if _storage_name(cover):
        return ledger.copy_url(cover, "covers")
    return cover


def _copy_catalogs(source: Course, new_course: Course) -> dict[int, Catalog]:
    """先建全部（parent 置空）再回填父子关系，避免依赖遍历顺序。"""
    rows = list(Catalog.objects.filter(course=source).order_by("order", "id"))
    mapping: dict[int, Catalog] = {}
    for row in rows:
        mapping[row.id] = Catalog.objects.create(
            course=new_course,
            parent=None,
            title=row.title,
            order=row.order,
            intro=row.intro,
            is_published=row.is_published,
        )
    for row in rows:
        if row.parent_id and row.parent_id in mapping:
            mapping[row.id].parent = mapping[row.parent_id]
            mapping[row.id].save(update_fields=["parent", "updated_at"])
    return mapping


def _copy_ppts(source, new_course, catalog_map, ledger, report) -> dict[int, PPTResource]:
    """课件本体文件 + 页图目录都要复制；页图目录名由新资源 id 派生，故先建行再落图。"""
    mapping: dict[int, PPTResource] = {}
    rows = list(PPTResource.objects.filter(course=source).order_by("id"))
    for index, row in enumerate(rows, start=1):
        catalog = catalog_map.get(row.catalog_id)
        if catalog is None:
            # 章节已被删（理论不该发生，catalog 是 CASCADE）——跳过而不是留脏数据
            continue
        new_file = ""
        if row.file:
            new_file = ledger.copy(row.file.name, "ppt")
        new_ppt = PPTResource.objects.create(
            course=new_course,
            catalog=catalog,
            file_name=row.file_name,
            file=new_file or None,
            parse_status=row.parse_status,
            version=1,
            is_active=row.is_active,
            parsed_pages=[],
            parse_progress={},
        )
        pages = []
        dirname = ppt_pages_dirname(new_ppt.id)
        for page in row.parsed_pages or []:
            item = dict(page)
            image_url = item.get("image") or ""
            if _storage_name(image_url):
                saved = ledger.copy(_storage_name(image_url), f"ppt_pages/{dirname}", keep_name=True)
                if saved:
                    item["image"] = f"{MEDIA_URL_PREFIX}{saved}"
            pages.append(item)
        new_ppt.parsed_pages = pages
        new_ppt.save(update_fields=["parsed_pages", "updated_at"])
        mapping[row.id] = new_ppt
        report("ppt", index, len(rows), f"复制课件 {index}/{len(rows)}")
    return mapping


def _copy_videos(source, new_course, catalog_map, ppt_map, ledger, report) -> dict[int, TeachingVideo]:
    mapping: dict[int, TeachingVideo] = {}
    rows = list(TeachingVideo.objects.filter(course=source).order_by("id"))
    url_cache: dict[str, str] = {}  # 同一音频被多页引用时只复制一次
    for index, row in enumerate(rows, start=1):
        catalog = catalog_map.get(row.catalog_id)
        if catalog is None:
            continue
        scripts = []
        for item in copy.deepcopy(row.scripts or []):
            if isinstance(item, dict):
                item["audio_url"] = ledger.copy_url(
                    item.get("audio_url", ""), "tts", url_cache
                )
            scripts.append(item)
        new_video = TeachingVideo.objects.create(
            course=new_course,
            catalog=catalog,
            ppt=ppt_map.get(row.ppt_id) if row.ppt_id else None,
            scripts=scripts,
            audio_url=ledger.copy_url(row.audio_url, "tts", url_cache),
            subtitle_url=ledger.copy_url(row.subtitle_url, "tts", url_cache),
            video_url=ledger.copy_url(row.video_url, "videos", url_cache),
            gen_status=row.gen_status,
            is_published=row.is_published,
            published_at=row.published_at,
        )
        mapping[row.id] = new_video
        report("video", index, len(rows), f"复制讲稿 {index}/{len(rows)}")
    return mapping


def _copy_materials(source, new_course, catalog_map, ledger) -> dict[int, Material]:
    mapping: dict[int, Material] = {}
    for row in Material.objects.filter(course=source).order_by("id"):
        new_file = ledger.copy(row.file.name, "materials") if row.file else ""
        mapping[row.id] = Material.objects.create(
            course=new_course,
            # 班级专属资料不跟着复用（见模块头说明 5）
            classroom=None,
            catalog=catalog_map.get(row.catalog_id),
            file_name=row.file_name,
            file_type=row.file_type,
            file=new_file or None,
            parse_status=row.parse_status,
            qa_open=row.qa_open,
        )
    return mapping


def _copy_chunks(source, new_course, catalog_map, material_map, ppt_map, video_map) -> int:
    """向量随行复制（不重算）：内容与源课程完全一致，检索行为可直接比对。"""
    rows = list(KnowledgeChunk.objects.filter(course=source).order_by("id"))
    if not rows:
        return 0
    batch = [
        KnowledgeChunk(
            source=row.source,
            material=material_map.get(row.material_id) if row.material_id else None,
            ppt=ppt_map.get(row.ppt_id) if row.ppt_id else None,
            video=video_map.get(row.video_id) if row.video_id else None,
            course=new_course,
            catalog=catalog_map.get(row.catalog_id),
            content=row.content,
            page=row.page,
            embedding=row.embedding,
        )
        for row in rows
    ]
    KnowledgeChunk.objects.bulk_create(batch, batch_size=200)
    return len(batch)


def _copy_resources(source, new_course, ledger) -> int:
    """思维导图/交互演示是平台预置静态页（path 指向 /resources/，共享只读），
    只复制行并拿到新的 access_token；文档类必须复制文件本体。"""
    rows = list(CourseResource.objects.filter(course=source).order_by("order", "id"))
    for row in rows:
        new_file = ledger.copy(row.file.name, "course_resources") if row.file else ""
        CourseResource.objects.create(
            course=new_course,
            kind=row.kind,
            title=row.title,
            path=row.path,
            file=new_file or None,
            file_name=row.file_name,
            file_size=row.file_size,
            intro=row.intro,
            is_published=row.is_published,
            order=row.order,
        )
    return len(rows)


def _copy_questions(source, new_course, catalog_map, ledger, teacher) -> tuple[int, int]:
    """题目复制：章节是 PROTECT 外键，章节映射不到的题跳过（计数返回给结果页）。"""
    rows = list(Question.objects.filter(course=source).order_by("id"))
    copied, skipped = 0, 0
    for row in rows:
        catalog = catalog_map.get(row.catalog_id)
        if catalog is None:
            skipped += 1
            continue
        image = ledger.copy(row.image.name, "question_images") if row.image else ""
        new_question = Question.objects.create(
            course=new_course,
            catalog=catalog,
            qtype=row.qtype,
            stem=row.stem,
            image=image or None,
            options=copy.deepcopy(row.options or []),
            answer=copy.deepcopy(row.answer or {}),
            analysis=row.analysis,
            score=row.score,
            difficulty=row.difficulty,
            knowledge_tags=copy.deepcopy(row.knowledge_tags or []),
            source=row.source,
            status=row.status,
            creator=teacher,
        )
        # 用途分类（练习/作业/考试）必须跟着走，否则新课程题目在对应场景里消失
        new_question.scenes.set(row.scenes.all())
        copied += 1
    return copied, skipped


# ---------------------------------------------------------------------------
# 任务入口（由 apps/ai/tasks.py 分发）
# ---------------------------------------------------------------------------
def run_course_reuse(task) -> None:
    """AITask 执行体：进度写 task.progress，结果写 task.result。"""
    from django.utils import timezone

    from apps.ai.models import AITask

    options = dict(task.progress or {}).get("options") or {}
    source = task.course
    if source is None:
        raise ValueError("源课程不存在")
    if task.triggered_by_id is None:
        raise ValueError("缺少操作人，无法创建新课程")

    def on_progress(stage, done, total, message=""):
        AITask.objects.filter(id=task.id).update(
            progress={
                "options": options,
                "stage": stage,
                "done": done,
                "total": total,
                "message": message or stage,
            }
        )

    result = reuse_course(
        source,
        teacher=task.triggered_by,
        name=options.get("name") or None,
        term_id=options.get("term_id"),
        include_questions=bool(options.get("include_questions")),
        on_progress=on_progress,
    )
    payload = result.as_dict()
    payload["source_course_id"] = source.id
    payload["source_course_name"] = source.name
    AITask.objects.filter(id=task.id).update(
        result=payload,
        status=AITask.Status.SUCCESS,
        finished_at=timezone.now(),
        progress={
            "options": options,
            "stage": "done",
            "done": 1,
            "total": 1,
            "message": "复用完成",
        },
    )
