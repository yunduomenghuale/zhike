import os
import tempfile
import time

import django_filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from django.conf import settings
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Max
from django.http import HttpResponse
from django.utils import timezone

from apps.ai.services import generate_catalog_from_plan, generate_scripts_for_video
from apps.common.access import courses_for_user
from apps.common.error_pages import render_block_page
from apps.common.permissions import IsStudent, IsTeacher, IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet
from apps.knowledge.models import KnowledgeChunk

from . import resource_gate
from .models import Catalog, Course, CourseResource, PPTResource, TeachingVideo, VideoWatchProgress
from .serializers import (
    CatalogSerializer,
    CourseResourceSerializer,
    CourseSerializer,
    PPTResourceSerializer,
    TeachingVideoSerializer,
    VideoWatchProgressSerializer,
)


def _invalidate_teaching_video_for_new_ppt(catalog, ppt):
    """课件换版后清除旧衍生内容，防止学生继续访问旧讲稿或配音。"""
    video = TeachingVideo.objects.select_for_update().filter(catalog=catalog).first()
    if not video:
        return

    # 讲稿片段随讲稿一并清除（换版后旧讲稿不再参与检索）
    video.chunks.all().delete()

    video.ppt = ppt
    video.scripts = []
    video.audio_url = ""
    video.subtitle_url = ""
    video.video_url = ""
    video.gen_status = TeachingVideo.GenStatus.DRAFT
    video.is_published = False
    video.published_at = None
    video.save(
        update_fields=[
            "ppt",
            "scripts",
            "audio_url",
            "subtitle_url",
            "video_url",
            "gen_status",
            "is_published",
            "published_at",
            "updated_at",
        ]
    )
    video.watch_progress.update(
        last_page=0,
        last_position=0,
        watch_seconds=0,
        total_seconds=0,
        page_durations={},
        page_watched={},
        page_count=0,
        status=VideoWatchProgress.Status.NOT_STARTED,
        updated_at=timezone.now(),
    )


class CourseFilter(django_filters.FilterSet):
    """学期筛选兼容两种传参：`?term=2026秋`（文本模糊）与 `?term_id=3`（精确）。"""

    term = django_filters.CharFilter(field_name="term__name", lookup_expr="icontains")
    term_id = django_filters.NumberFilter(field_name="term_id")

    class Meta:
        model = Course
        fields = ["status"]


class CourseViewSet(BaseModelViewSet):
    serializer_class = CourseSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_class = CourseFilter
    search_fields = ["name", "intro"]

    def get_queryset(self):
        return courses_for_user(self.request.user)

    def perform_create(self, serializer):
        serializer.save(teacher=self.request.user)


class CatalogViewSet(BaseModelViewSet):
    serializer_class = CatalogSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "parent", "is_published"]

    def get_queryset(self):
        qs = Catalog.objects.filter(course__in=courses_for_user(self.request.user))
        user = self.request.user
        # 学生只见已发布章节（需求 T-D-04 / S-V-01）
        if user.is_authenticated and user.is_student:
            qs = qs.filter(is_published=True)
        course_id = self.request.query_params.get("course")
        # 顶层目录（章）默认只返回 parent 为空的，children 由序列化器递归带出
        if self.action == "list" and self.request.query_params.get("tree") == "1":
            qs = qs.filter(parent__isnull=True)
        if course_id:
            qs = qs.filter(course_id=course_id)
        # 按排序号排列（模型 Meta 口径 order,id）：视图曾硬编码 order_by("id") 导致
        # 章节的「排序号」字段保存后从不影响列表顺序
        return qs.order_by("order", "id")

    def destroy(self, request, *args, **kwargs):
        catalog = self.get_object()
        try:
            self.perform_destroy(catalog)
        except ProtectedError:
            return api_response(
                message="该章节下仍有题目，请先将题目移动到其他章节",
                code=400,
                status=400,
            )
        return api_response(message="删除成功")

    @action(detail=True, methods=["post"], url_path="generate-script", permission_classes=[IsTeacher])
    def generate_script(self, request, pk=None):
        """基于该章节 PPT 分批生成讲解稿并保存到教学视频（需求 T-V-01）。

        分批生成：limit 指定本批最多生成页数（默认 6，上限 12），前端循环调用直至
        done=true，避免一次生成几十页讲解稿超过网关 180s 超时（499）。
        """
        from apps.ai.services import generate_script_pages_batched

        catalog = self.get_object()
        ppt = (
            PPTResource.objects.filter(
                catalog=catalog,
                parse_status=PPTResource.ParseStatus.DONE,
            )
            .order_by("-is_active", "-version", "-id")
            .first()
        )
        if not ppt or not ppt.parsed_pages:
            return api_response(message="该章节还没有已解析的 PPT", code=400, status=400)
        try:
            limit = int(request.data.get("limit") or 6)
        except (TypeError, ValueError):
            limit = 6
        limit = max(1, min(limit, 12))
        force = str(request.data.get("force", "")).lower() in ("1", "true", "yes", "on")

        video, _ = TeachingVideo.objects.get_or_create(
            catalog=catalog, defaults={"course": catalog.course, "ppt": ppt}
        )
        # 换了新版本 PPT 或明确 force 时重置衍生内容（含学生观看进度，沿用主线换版逻辑）
        if force or video.ppt_id != ppt.id:
            _invalidate_teaching_video_for_new_ppt(catalog, ppt)
        video.course = catalog.course
        video.ppt = ppt
        video.save()

        result = generate_script_pages_batched(video, ppt.parsed_pages, batch_size=limit)
        if result.get("done"):
            # 整章讲稿生成完成：入库向量库参与检索（失败静默，QA 侧有兜底）
            from apps.ai.services import ingest_video_scripts

            ingest_video_scripts(video)
        return api_response(
            result,
            message=f"已生成 {result['script_pages']}/{result['pages']} 页讲解稿",
        )

    @action(detail=True, methods=["post"], url_path="generate-audio", permission_classes=[IsTeacher])
    def generate_audio(self, request, pk=None):
        """基于讲解稿逐页 AI 配音（需求 T-V-03）。

        分段生成：limit 指定本批最多合成页数（默认 3，上限 10），前端循环调用直至
        done=true，避免多页同步合成超过网关 180s 超时导致前端无反馈。
        """
        from apps.ai.services import synthesize_audio_for_video

        catalog = self.get_object()
        video = TeachingVideo.objects.filter(catalog=catalog).first()
        if not video or not video.scripts:
            return api_response(message="请先生成讲解稿", code=400, status=400)
        try:
            limit = int(request.data.get("limit") or 3)
        except (TypeError, ValueError):
            limit = 3
        limit = max(1, min(limit, 10))
        created = synthesize_audio_for_video(video, limit=limit)
        video.refresh_from_db()
        scripts = video.scripts or []
        total = len([item for item in scripts if item.get("script")])
        audio_pages = sum(1 for item in scripts if item.get("audio_url"))
        # 仅把明确合成失败（有 audio_error）的页计为失败；尚未轮到的页不算失败。
        # failed_details 带上失败原因（provider 报错截断 300 字），供前端在配音
        # 服务不可用（模型下线/Key 失效等）时展示具体错误并终止循环，而非无限重试。
        failed_details = [
            {"page": item.get("page"), "error": item.get("audio_error")}
            for item in scripts
            if item.get("script") and not item.get("audio_url") and item.get("audio_error")
        ]
        failed_pages = [item["page"] for item in failed_details]
        remaining = total - audio_pages
        return api_response(
            {
                "created_pages": created,
                "audio_pages": audio_pages,
                "total_pages": total,
                "failed_pages": failed_pages,
                "failed_details": failed_details,
                "remaining": remaining,
                "done": remaining == 0,
            },
            message=f"已完成 {audio_pages}/{total} 页配音",
        )

    @action(detail=False, methods=["post"], url_path="generate-from-plan")
    def generate_from_plan(self, request):
        """上传授课计划文本，调用大模型识别章节结构生成初始目录（需求 T-D-02）。

        教师确认后才落库：这里返回识别结果，前端确认后逐条创建。
        """
        course_id = request.data.get("course")
        plan_text = request.data.get("plan_text", "")
        result = generate_catalog_from_plan(plan_text)
        return api_response(
            {"course": course_id, "catalog_tree": result},
            message="目录识别完成，请教师确认后保存",
        )


    @action(detail=False, methods=["post"], url_path="preview-from-file", permission_classes=[IsTeacher])
    def preview_from_file(self, request):
        upload = request.FILES.get("file")
        if not upload:
            return api_response(message="请上传授课文件", code=400, status=400)

        from .ppt_parser import SUPPORTED_EXTENSIONS, pages_to_chapter_tree, parse_teaching_file_pages

        ext = os.path.splitext(upload.name)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            supported = "、".join(sorted(SUPPORTED_EXTENSIONS))
            return api_response(message=f"暂不支持该文件格式，支持：{supported}", code=400, status=400)

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            for chunk in upload.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            pages = parse_teaching_file_pages(tmp_path)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        if not pages:
            return api_response(message="未能从文件中解析出目录内容", code=400, status=400)

        return api_response(
            {
                "file_name": upload.name,
                "page_count": len(pages),
                "catalog_tree": pages_to_chapter_tree(pages),
                "pages": pages[:80],
            },
            message="目录预览已生成",
        )


def _parse_progress_payload(stage: str, done: int = 0, total: int = 0, error: str = "") -> dict:
    """解析进度统一结构：stage ∈ text/render/embed/done/failed。"""
    return {"stage": stage, "done": int(done or 0), "total": int(total or 0), "error": error or ""}


def _make_parse_progress_writer(ppt):
    """构造带节流的解析进度写入器。

    逐页回调频率很高（文本解析/图片渲染每页各一次），统一限速约 0.5s 落库一次；
    done>=total 或 force=True 时立即写，保证阶段切换与终态不丢。
    进度是尽力而为的展示数据，写库失败不影响解析主流程。
    """
    state = {"last": 0.0}

    def write(stage: str, done: int = 0, total: int = 0, error: str = "", force: bool = False):
        now = time.monotonic()
        if not force and done < total and now - state["last"] < 0.5:
            return
        state["last"] = now
        try:
            ppt.parse_progress = _parse_progress_payload(stage, done, total, error)
            ppt.save(update_fields=["parse_progress", "updated_at"])
        except Exception:
            pass

    return write


class PPTResourceViewSet(BaseModelViewSet):
    serializer_class = PPTResourceSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "catalog", "parse_status"]

    def get_queryset(self):
        qs = PPTResource.objects.filter(course__in=courses_for_user(self.request.user))
        if getattr(self.request.user, "is_student", False):
            qs = qs.filter(catalog__is_published=True, is_active=True)
        return qs.order_by("-version", "-id")

    def perform_create(self, serializer):
        """上传 PPT 后自动逐页解析文本（需求 T-P-02）。

        解析仍在请求内同步完成（响应契约不变），但各阶段进度实时写入
        ppt.parse_progress，前端轮询列表即可展示「上传 → 解析文本 x/y 页 →
        渲染图片 x/y 页 → 建立索引」的细粒度进度。
        """
        from .ppt_parser import attach_slide_images, parse_teaching_file_pages, render_presentation_slide_images

        course = serializer.validated_data["course"]
        catalog = serializer.validated_data["catalog"]
        existing = PPTResource.objects.filter(course=course, catalog=catalog)
        next_version = (existing.aggregate(max_version=Max("version"))["max_version"] or 0) + 1

        ppt = serializer.save(
            version=next_version,
            is_active=False,
            parse_status=PPTResource.ParseStatus.PARSING,
        )
        write_progress = _make_parse_progress_writer(ppt)
        pages = []
        parse_error = ""
        if ppt.file:
            try:
                write_progress("text", force=True)
                pages = parse_teaching_file_pages(
                    ppt.file.path,
                    on_page=lambda done, total: write_progress("text", done, total),
                )
                # 页数在文本解析后已知：渲染阶段直接带总数，全局锁排队期间也显示 0/N
                write_progress("render", 0, len(pages), force=True)
                images = render_presentation_slide_images(
                    ppt.file.path,
                    resource_id=ppt.id,
                    on_progress=lambda done, total: write_progress("render", done, total),
                )
                pages = attach_slide_images(pages, images)
            except Exception as exc:
                # 解析异常不再让请求 500：落失败状态与原因，前端轮询能看到
                parse_error = str(exc)[:200]
                pages = []

        with transaction.atomic():
            ppt.parsed_pages = pages
            ppt.parse_status = ppt.ParseStatus.DONE if pages else ppt.ParseStatus.FAILED
            ppt.is_active = bool(pages)
            ppt.parse_progress = _parse_progress_payload(
                "done" if pages else "failed", len(pages), len(pages), parse_error
            )
            ppt.save(update_fields=["parsed_pages", "parse_status", "is_active", "parse_progress", "updated_at"])
            if pages:
                existing.exclude(pk=ppt.pk).update(is_active=False)
                _invalidate_teaching_video_for_new_ppt(catalog, ppt)
                # 旧版本课件的向量片段随之失效（可能还是另一套向量空间），先删后建
                KnowledgeChunk.objects.filter(ppt__in=existing.exclude(pk=ppt.pk)).delete()

        # 课件是向量库的主要内容：解析成功即逐页入库（失败静默，QA 有原文兜底）
        if pages:
            from apps.ai.services import ingest_ppt_pages

            write_progress("embed", 0, len(pages), force=True)
            ingest_ppt_pages(ppt, on_progress=lambda d, t: write_progress("embed", d, t))
            write_progress("done", len(pages), len(pages), force=True)

    @action(detail=True, methods=["post"], url_path="reparse")
    def reparse(self, request, pk=None):
        from .ppt_parser import attach_slide_images, parse_teaching_file_pages, render_presentation_slide_images

        ppt = self.get_object()
        write_progress = _make_parse_progress_writer(ppt)
        pages = []
        parse_error = ""
        ppt.parse_status = ppt.ParseStatus.PARSING
        ppt.save(update_fields=["parse_status", "updated_at"])
        if ppt.file:
            try:
                write_progress("text", force=True)
                pages = parse_teaching_file_pages(
                    ppt.file.path,
                    on_page=lambda done, total: write_progress("text", done, total),
                )
                # 页数在文本解析后已知：渲染阶段直接带总数，全局锁排队期间也显示 0/N
                write_progress("render", 0, len(pages), force=True)
                images = render_presentation_slide_images(
                    ppt.file.path,
                    resource_id=ppt.id,
                    on_progress=lambda done, total: write_progress("render", done, total),
                )
                pages = attach_slide_images(pages, images)
            except Exception as exc:
                parse_error = str(exc)[:200]
                pages = []
        ppt.parsed_pages = pages
        ppt.parse_status = ppt.ParseStatus.DONE if pages else ppt.ParseStatus.FAILED
        ppt.parse_progress = _parse_progress_payload(
            "done" if pages else "failed", len(pages), len(pages), parse_error
        )
        ppt.save(update_fields=["parsed_pages", "parse_status", "parse_progress", "updated_at"])
        chunk_count = 0
        if pages:
            from apps.ai.services import ingest_ppt_pages

            write_progress("embed", 0, len(pages), force=True)
            chunk_count = ingest_ppt_pages(ppt, on_progress=lambda d, t: write_progress("embed", d, t))
            write_progress("done", len(pages), len(pages), force=True)
        return api_response(
            {"page_count": len(pages), "chunk_count": chunk_count}, message="重新解析完成"
        )


class TeachingVideoViewSet(BaseModelViewSet):
    serializer_class = TeachingVideoSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "catalog", "gen_status", "is_published"]

    def get_queryset(self):
        qs = TeachingVideo.objects.filter(
            course__in=courses_for_user(self.request.user)
        ).select_related("catalog")
        if getattr(self.request.user, "is_student", False):
            qs = qs.filter(catalog__is_published=True, is_published=True)
        return qs.order_by("id")

    @action(detail=True, methods=["post"], url_path="generate-scripts")
    def generate_scripts(self, request, pk=None):
        """基于章节 PPT 逐页生成讲解稿（需求 T-V-01）。"""
        video = self.get_object()
        pages = video.ppt.parsed_pages if video.ppt else []
        video.scripts = generate_scripts_for_video(pages)
        video.audio_url = ""
        video.subtitle_url = ""
        video.video_url = ""
        video.gen_status = TeachingVideo.GenStatus.SCRIPT_READY
        video.is_published = True
        video.save(update_fields=["scripts", "audio_url", "subtitle_url", "video_url", "gen_status", "is_published", "updated_at"])
        # 讲稿整体就绪：入库向量库参与检索（失败静默，QA 侧有兜底）
        from apps.ai.services import ingest_video_scripts

        ingest_video_scripts(video)
        return api_response(self.get_serializer(video).data, message="讲解稿生成完成")

    @action(detail=True, methods=["post"], url_path="update-script", permission_classes=[IsTeacher])
    def update_script(self, request, pk=None):
        """手动修改某一页讲解稿；内容变化后该页配音失效，需要重新配音。"""
        video = self.get_object()
        page = request.data.get("page")
        script = str(request.data.get("script") or "").strip()
        if page in (None, ""):
            return api_response(message="缺少页码", code=400, status=400)
        if not script:
            return api_response(message="讲稿内容不能为空", code=400, status=400)
        try:
            page = int(page)
        except (TypeError, ValueError):
            return api_response(message="页码格式不正确", code=400, status=400)

        scripts = list(video.scripts or [])
        target = None
        for item in scripts:
            if int(item.get("page") or 0) == page:
                target = item
                break
        if target is None:
            target = {"page": page}
            scripts.append(target)
            scripts.sort(key=lambda item: int(item.get("page") or 0))

        changed = (target.get("script") or "").strip() != script
        target["script"] = script
        if changed:
            target.pop("audio_url", None)
            target.pop("audio_error", None)
            video.audio_url = ""
            video.subtitle_url = ""
            video.video_url = ""
            video.gen_status = TeachingVideo.GenStatus.SCRIPT_READY

        video.scripts = scripts
        video.save(update_fields=["scripts", "audio_url", "subtitle_url", "video_url", "gen_status", "is_published", "updated_at"])
        if changed:
            # 讲稿内容变化：重建该视频讲稿片段（幂等全量替换，失败静默）
            from apps.ai.services import ingest_video_scripts

            ingest_video_scripts(video)
        return api_response(self.get_serializer(video).data, message="讲稿已保存，修改页需要重新配音")

    @action(detail=True, methods=["post"], url_path="regenerate-script-page", permission_classes=[IsTeacher])
    def regenerate_script_page(self, request, pk=None):
        """只重新生成单页讲解稿；不影响其它页，当前页旧配音失效。"""
        video = self.get_object()
        page = request.data.get("page")
        if page in (None, ""):
            return api_response(message="缺少页码", code=400, status=400)
        try:
            page = int(page)
        except (TypeError, ValueError):
            return api_response(message="页码格式不正确", code=400, status=400)

        ppt_pages = video.ppt.parsed_pages if video.ppt else []
        source_page = None
        for item in ppt_pages:
            if int(item.get("page") or 0) == page:
                source_page = item
                break
        if not source_page:
            return api_response(message="未找到该页 PPT 内容", code=404, status=404)

        try:
            generated = generate_scripts_for_video([source_page])
        except Exception:
            return api_response(message="AI 讲稿生成失败，请稍后重试", code=502, status=502)
        if not generated:
            return api_response(message="未能生成该页讲稿", code=502, status=502)

        scripts = list(video.scripts or [])
        target = None
        for item in scripts:
            if int(item.get("page") or 0) == page:
                target = item
                break
        if target is None:
            target = {"page": page}
            scripts.append(target)
            scripts.sort(key=lambda item: int(item.get("page") or 0))

        target["script"] = generated[0].get("script") or ""
        target.pop("audio_url", None)
        target.pop("audio_error", None)
        video.scripts = scripts
        video.audio_url = ""
        video.subtitle_url = ""
        video.video_url = ""
        video.gen_status = TeachingVideo.GenStatus.SCRIPT_READY
        video.save(update_fields=["scripts", "audio_url", "subtitle_url", "video_url", "gen_status", "is_published", "updated_at"])
        # 单页讲稿重生成：重建该视频讲稿片段（幂等全量替换，失败静默）
        from apps.ai.services import ingest_video_scripts

        ingest_video_scripts(video)
        return api_response(self.get_serializer(video).data, message="该页讲稿已重新生成，需要重新配音")

    @action(detail=True, methods=["post"], url_path="regenerate-audio-page", permission_classes=[IsTeacher])
    def regenerate_audio_page(self, request, pk=None):
        """只重新合成指定页的配音（讲稿不变），覆盖该页音频地址。"""
        video = self.get_object()
        page = request.data.get("page")
        if page in (None, ""):
            return api_response(message="缺少页码", code=400, status=400)
        try:
            page = int(page)
        except (TypeError, ValueError):
            return api_response(message="页码格式不正确", code=400, status=400)

        scripts = list(video.scripts or [])
        target = None
        for item in scripts:
            if int(item.get("page") or 0) == page:
                target = item
                break
        if target is None or not str(target.get("script") or "").strip():
            return api_response(message="该页还没有讲解稿，请先生成讲稿", code=400, status=400)

        from apps.ai.providers.factory import get_provider

        provider = get_provider("tts")
        if getattr(provider, "name", "") == "mock":
            return api_response(message="当前为模拟模式，无法合成真实配音", code=400, status=400)
        try:
            # 发音人优先级：管理端配置 > AI_TTS_VOICE 环境变量 > Cherry（DashScope 音色名/本地说话人ID）
            voice = getattr(provider, "voice", "") or getattr(settings, "AI_TTS_VOICE", "Cherry")
            from apps.ai.calllog import ai_scene
            from apps.ai.models import AICallLog

            with ai_scene(AICallLog.Scene.TTS, course_id=video.course_id):
                audio_url = provider.tts(target["script"].strip(), voice=voice)
        except Exception as exc:
            target["audio_error"] = str(exc)[:300]
            video.scripts = scripts
            video.save(update_fields=["scripts", "updated_at"])
            return api_response(message=f"配音合成失败：{str(exc)[:200]}", code=502, status=502)

        target["audio_url"] = audio_url
        target.pop("audio_error", None)
        video.scripts = scripts
        # 该页补齐后若全部页均有配音，回到配音就绪态
        script_count = len([item for item in scripts if (item.get("script") or "").strip()])
        audio_count = len([item for item in scripts if item.get("audio_url")])
        if script_count > 0 and audio_count == script_count:
            video.gen_status = TeachingVideo.GenStatus.AUDIO_READY
        video.save(update_fields=["scripts", "gen_status", "updated_at"])
        return api_response(self.get_serializer(video).data, message=f"第 {page} 页配音已重新生成")

    @action(detail=True, methods=["post"], url_path="report-progress", permission_classes=[IsStudent])
    def report_progress(self, request, pk=None):
        """学生上报连播学习进度（需求 S-V-03）。

        参数：last_page 当前页索引、last_position 页内秒数、
        duration_delta 本次新增学习秒数、completed 是否学完整章。
        """
        video = self.get_object()

        def _int(value, default=0):
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                return default

        def _float(value, default=0.0):
            try:
                return max(0.0, float(value))
            except (TypeError, ValueError):
                return default

        last_page = _int(request.data.get("last_page"))
        last_position = _float(request.data.get("last_position"))
        duration_delta = _int(request.data.get("duration_delta"))
        completed = str(request.data.get("completed", "")).lower() in ("1", "true", "yes")
        page_durations = request.data.get("page_durations")
        page_watched = request.data.get("page_watched")
        page_count = _int(request.data.get("page_count"))

        progress, _ = VideoWatchProgress.objects.get_or_create(
            student=request.user, video=video
        )
        progress.last_page = last_page
        progress.last_position = last_position
        # 每页时长 / 已看时长按页取最大值合并，未播放的页不计入
        if isinstance(page_durations, dict) and page_durations:
            merged = dict(progress.page_durations or {})
            for k, v in page_durations.items():
                try:
                    merged[str(k)] = max(float(v), float(merged.get(str(k)) or 0))
                except (TypeError, ValueError):
                    continue
            progress.page_durations = merged
            progress.total_seconds = sum(merged.values())
        if isinstance(page_watched, dict) and page_watched:
            merged = dict(progress.page_watched or {})
            for k, v in page_watched.items():
                try:
                    merged[str(k)] = max(float(v), float(merged.get(str(k)) or 0))
                except (TypeError, ValueError):
                    continue
            progress.page_watched = merged
        if page_count:
            progress.page_count = max(progress.page_count, page_count)
        # 单次上报时长做上限保护，避免前端异常刷量
        progress.watch_seconds += min(duration_delta, 300)
        if completed:
            progress.status = VideoWatchProgress.Status.COMPLETED
        elif progress.status != VideoWatchProgress.Status.COMPLETED:
            progress.status = VideoWatchProgress.Status.IN_PROGRESS
        progress.save()

        # 章节完成即自动提交 AI 学习总结（设计 §4.1：异步不阻塞进度上报；
        # 幂等——已有 pending/running/success 任务则跳过，重看重复触发不刷量）。
        # F13：summary_task_id 为加性字段，旧版移动端忽略即可。
        summary_task_id = None
        if completed:
            import logging

            from apps.analytics.views import _submit_chapter_summary

            try:
                task, cached, _error = _submit_chapter_summary(request.user, video.catalog)
                if not cached:
                    summary_task_id = task.id
            except Exception:
                logging.getLogger(__name__).exception(
                    "章节总结自动提交失败（video_id=%s）", video.id
                )
        data = VideoWatchProgressSerializer(progress).data
        data["summary_task_id"] = summary_task_id
        return api_response(data, message="进度已记录")


class WatchProgressViewSet(BaseModelViewSet):
    """视频学习进度查询（学生看自己的，教师看自己课程的）。"""

    serializer_class = VideoWatchProgressSerializer
    http_method_names = ["get", "head", "options"]
    filterset_fields = ["video", "student", "status"]

    def get_queryset(self):
        user = self.request.user
        qs = VideoWatchProgress.objects.select_related("student", "video__catalog")
        if user.is_authenticated and user.is_student:
            qs = qs.filter(student=user)
        elif user.is_authenticated and user.is_teacher:
            qs = qs.filter(video__course__teacher=user)
        course_id = self.request.query_params.get("course")
        if course_id:
            qs = qs.filter(video__course_id=course_id)
        return qs.order_by("id")


class CourseResourceViewSet(BaseModelViewSet):
    """课程教学资源（思维导图/交互演示/文档）：直接归属课程，不再挂章节。

    预置类（mindmap/demo）教师引用平台静态页；文档类（document）教师上传
    pdf/doc/docx（≤100MB，multipart）。学生看已发布的，访问走签名门控。
    """

    serializer_class = CourseResourceSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "kind", "is_published"]

    def get_queryset(self):
        qs = CourseResource.objects.select_related("course")
        user = self.request.user
        if user.is_authenticated and user.is_student:
            qs = qs.filter(is_published=True, course__classes__students__student=user,
                           course__classes__students__learn_status="active")
        elif user.is_authenticated and user.is_teacher:
            qs = qs.filter(course__teacher=user)
        elif not user.is_authenticated or not user.is_staff:
            qs = qs.none()
        return qs.distinct()

    def perform_create(self, serializer):
        serializer.save()

    def create(self, request, *args, **kwargs):
        # 文档类走 multipart 上传（file 字段），大小/格式校验在序列化器；
        # 预置类保持 JSON 提交。统一以真实文件 size 落库。
        upload = request.FILES.get("file")
        if upload and upload.size == 0:
            return api_response(message="文档文件为空", code=400, status=400)
        response = super().create(request, *args, **kwargs)
        if upload and response.status_code < 400:
            instance = CourseResource.objects.get(pk=response.data["data"]["id"])
            instance.file_name = upload.name
            instance.file_size = upload.size
            instance.save(update_fields=["file_name", "file_size", "updated_at"])
            response.data["data"] = CourseResourceSerializer(
                instance, context={"request": request}
            ).data
        return response

    def perform_destroy(self, instance):
        # 删除文档类资源时清理上传文件（预置类 file 为空，delete 为 no-op）
        if instance.file:
            instance.file.delete(save=False)
        instance.delete()

    @action(detail=True, methods=["post"], url_path="sign", permission_classes=[IsAuthenticated])
    def sign(self, request, pk=None):
        """签发资源访问 URL（2 小时有效）。queryset 已按身份+发布状态过滤：
        学生仅能签发本人已发布资源，教师可预览本人未发布资源。"""
        resource = self.get_object()
        return api_response(resource_gate.sign_resource(resource))

    @action(detail=True, methods=["post"], url_path="publish", permission_classes=[IsTeacher])
    def publish(self, request, pk=None):
        resource = self.get_object()
        resource.is_published = True
        resource.save(update_fields=["is_published", "updated_at"])
        return api_response(
            CourseResourceSerializer(resource, context={"request": request}).data, message="资源已发布"
        )

    @action(detail=True, methods=["post"], url_path="unpublish", permission_classes=[IsTeacher])
    def unpublish(self, request, pk=None):
        resource = self.get_object()
        resource.is_published = False
        resource.save(update_fields=["is_published", "updated_at"])
        return api_response(
            CourseResourceSerializer(resource, context={"request": request}).data, message="资源已下架"
        )

    @action(detail=False, methods=["post"], url_path="preset-sign", permission_classes=[IsAuthenticated, IsTeacher])
    def preset_sign(self, request):
        """教师添加资源前预览平台预置页：按路径签发预览 URL（无需资源行）。"""
        path = (request.data.get("path") or "").strip().strip("/")
        if not resource_gate.PRESET_PATH_RE.fullmatch(path):
            return api_response(message="仅支持预览 mindmap/*.html 或 demos/*.html 预置页", code=400, status=400)
        return api_response(resource_gate.sign_preset(path))


def _resource_error_page(status: int, title: str, hint: str):
    """门控失败的友好提示页（统一实现见 apps/common/error_pages.py，实验门控同款）。"""
    return render_block_page(status, title, hint)


def course_resource_page(request, token):
    """资源入口页：验签 → 读 HTML（预置页/自定义上传） → 注入 <base> 指向签名资产路由。

    自定义 HTML 为教师上传内容，响应加 CSP：默认仅同源 + data/blob，
    脚本/样式允许同源与内联（自包含单文件可运行），挡外部脚本引用与数据外发。
    """
    resource = CourseResource.objects.filter(access_token=token).first()
    if resource is None or not resource_gate.verify_resource(
        resource, request.GET.get("sig", ""), request.GET.get("exp", "")
    ):
        return _resource_error_page(403, "资源链接无效或已过期", "请返回课程页面重新打开该资源。")
    html = resource_gate.read_page(resource)
    if html is None:
        return _resource_error_page(404, "资源页面不存在", "资源文件已丢失，请联系教师重新上传。")
    base = resource_gate.asset_base(resource, request.GET.get("sig", ""), request.GET.get("exp", ""))
    response = HttpResponse(
        resource_gate.inject_base(html, base), content_type="text/html; charset=utf-8"
    )
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = (
        "default-src 'self' data: blob:; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self' data:; "
        "connect-src 'self' blob:; "
        "frame-ancestors 'self'"
    )
    # 查看器以同源 iframe 嵌入本页（clickjacking 中间件不覆盖已设置的响应头）
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response


def course_resource_asset(request, token, sig, exp, rest):
    """资源资产（JS/CSS/图片等）：同一 token 签名校验后从 RESOURCES_ROOT 读出。"""
    resource = CourseResource.objects.filter(access_token=token).first()
    if resource is None or not resource_gate.verify_resource(resource, sig, exp):
        return _resource_error_page(403, "资源链接无效或已过期", "请返回课程页面重新打开该资源。")
    path = resource_gate.read_asset(rest)
    if path is None:
        return _resource_error_page(404, "资源文件不存在", "请返回课程页面重新打开该资源。")
    response = HttpResponse(path.read_bytes(), content_type=resource_gate.guess_content_type(path))
    response["Cache-Control"] = "private, max-age=7200"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def course_resource_preset_page(request, sig, exp, rest):
    """预置页预览入口（教师）：验签 → 读 HTML → 注入 <base>。"""
    if not resource_gate.verify_preset(sig, exp):
        return _resource_error_page(403, "预览链接无效或已过期", "请重新选择平台页面生成预览。")
    if not rest.endswith(".html"):
        return _resource_error_page(404, "页面不存在", "仅支持预览 HTML 预置页。")
    path = resource_gate.read_asset(rest)
    if path is None:
        return _resource_error_page(404, "页面不存在", "平台尚未部署该预置页面，请联系管理员。")
    parent = rest.rsplit("/", 1)[0] if "/" in rest else ""
    base = resource_gate.preset_asset_base(sig, exp, parent)
    response = HttpResponse(
        resource_gate.inject_base(path.read_text(encoding="utf-8", errors="replace"), base),
        content_type="text/html; charset=utf-8",
    )
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response


def course_resource_file(request, token):
    """文档类资源文件：验签（含发布状态）→ 流式输出上传文件。

    与预置页共用 token 级签名（sign 动作签发，2h 时效，下架即失效）；
    PDF 内联预览（浏览器原生），doc/docx 以附件下载。
    """
    resource = CourseResource.objects.filter(access_token=token).first()
    if resource is None or not resource_gate.verify_resource(
        resource, request.GET.get("sig", ""), request.GET.get("exp", "")
    ):
        return _resource_error_page(403, "资源链接无效或已过期", "请返回课程页面重新打开该资源。")
    if resource.kind != CourseResource.Kind.DOCUMENT or not resource.file:
        return _resource_error_page(404, "资源文件不存在", "该资源不是文档类型，请返回课程页面重试。")
    from django.http import FileResponse

    inline = resource.file.name.lower().endswith(".pdf")
    response = FileResponse(
        resource.file.open("rb"),
        as_attachment=not inline,
        filename=resource.file_name or resource.title,
        content_type=resource_gate.guess_content_type_name(resource.file.name),
    )
    response["Cache-Control"] = "private, max-age=7200"
    response["X-Content-Type-Options"] = "nosniff"
    if inline:
        # 允许同源 iframe 嵌入（PDF 查看器），clickjacking 中间件不覆盖已设置的头
        response["X-Frame-Options"] = "SAMEORIGIN"
    return response


def course_resource_preset_asset(request, sig, exp, rest):
    """预置页预览资产（教师签名，2 小时有效）。"""
    if not resource_gate.verify_preset(sig, exp):
        return _resource_error_page(403, "预览链接无效或已过期", "请重新选择平台页面生成预览。")
    path = resource_gate.read_asset(rest)
    if path is None:
        return _resource_error_page(404, "资源文件不存在", "请重新选择平台页面生成预览。")
    response = HttpResponse(path.read_bytes(), content_type=resource_gate.guess_content_type(path))
    response["Cache-Control"] = "private, max-age=7200"
    response["X-Content-Type-Options"] = "nosniff"
    return response
