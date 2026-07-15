import os
import tempfile

from rest_framework.decorators import action
from django.db.models.deletion import ProtectedError
from django.db.models import Max

from apps.ai.services import generate_catalog_from_plan, generate_scripts_for_video
from apps.common.permissions import IsTeacher, IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet

from .models import Catalog, Course, PPTResource, TeachingVideo
from .serializers import (
    CatalogSerializer,
    CourseSerializer,
    PPTResourceSerializer,
    TeachingVideoSerializer,
)


class CourseViewSet(BaseModelViewSet):
    serializer_class = CourseSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["status", "term"]
    search_fields = ["name", "intro"]

    def get_queryset(self):
        qs = Course.objects.all()
        user = self.request.user
        # 教师只看自己的课程；学生可见的课程由班级关系约束（此处返回全部，交由班级过滤）
        if user.is_authenticated and user.is_teacher:
            qs = qs.filter(teacher=user)
        return qs

    def perform_create(self, serializer):
        serializer.save(teacher=self.request.user)


class CatalogViewSet(BaseModelViewSet):
    serializer_class = CatalogSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "parent", "is_published"]

    def get_queryset(self):
        qs = Catalog.objects.all()
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
        return qs

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
        """基于该章节 PPT 逐页生成讲解稿并保存到教学视频（需求 T-V-01）。"""
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
        video = TeachingVideo.objects.filter(catalog=catalog).first()
        force = str(request.data.get("force", "")).lower() in ("1", "true", "yes", "on")
        if (
            video
            and not force
            and video.ppt_id == ppt.id
            and video.scripts
            and len(video.scripts) == len(ppt.parsed_pages)
        ):
            return api_response(
                {"pages": len(video.scripts), "cached": True},
                message="已存在讲解稿",
            )
        try:
            scripts = generate_scripts_for_video(ppt.parsed_pages)
        except Exception:
            return api_response(message="AI 讲解稿生成失败，请稍后重试", code=502, status=502)
        video, _ = TeachingVideo.objects.get_or_create(
            catalog=catalog, defaults={"course": catalog.course, "ppt": ppt}
        )
        video.course = catalog.course
        video.ppt = ppt
        video.scripts = scripts
        video.audio_url = ""
        video.subtitle_url = ""
        video.video_url = ""
        video.gen_status = TeachingVideo.GenStatus.SCRIPT_READY
        video.save()
        return api_response({"pages": len(scripts)}, message="讲解稿生成完成")

    @action(detail=True, methods=["post"], url_path="generate-audio", permission_classes=[IsTeacher])
    def generate_audio(self, request, pk=None):
        """基于讲解稿逐页 AI 配音（需求 T-V-03）。"""
        from apps.ai.services import synthesize_audio_for_video

        catalog = self.get_object()
        video = TeachingVideo.objects.filter(catalog=catalog).first()
        if not video or not video.scripts:
            return api_response(message="请先生成讲解稿", code=400, status=400)
        ok = synthesize_audio_for_video(video)
        video.refresh_from_db()
        scripts = video.scripts or []
        total = len([item for item in scripts if item.get("script")])
        audio_pages = sum(1 for item in scripts if item.get("audio_url"))
        failed_pages = [
            item.get("page")
            for item in scripts
            if item.get("script") and not item.get("audio_url")
        ]
        return api_response(
            {
                "created_pages": ok,
                "audio_pages": audio_pages,
                "total_pages": total,
                "failed_pages": failed_pages,
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


class PPTResourceViewSet(BaseModelViewSet):
    serializer_class = PPTResourceSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "catalog", "parse_status"]

    def get_queryset(self):
        return PPTResource.objects.order_by("-version", "-id")

    def perform_create(self, serializer):
        """上传 PPT 后自动逐页解析文本（需求 T-P-02）。"""
        from .ppt_parser import attach_slide_images, parse_teaching_file_pages, render_presentation_slide_images

        course = serializer.validated_data["course"]
        catalog = serializer.validated_data["catalog"]
        existing = PPTResource.objects.filter(course=course, catalog=catalog)
        next_version = (existing.aggregate(max_version=Max("version"))["max_version"] or 0) + 1
        existing.update(is_active=False)

        ppt = serializer.save(
            version=next_version,
            is_active=True,
            parse_status=PPTResource.ParseStatus.PARSING,
        )
        if ppt.file:
            pages = parse_teaching_file_pages(ppt.file.path)
            images = render_presentation_slide_images(ppt.file.path, resource_id=ppt.id)
            pages = attach_slide_images(pages, images)
            ppt.parsed_pages = pages
            ppt.parse_status = ppt.ParseStatus.DONE if pages else ppt.ParseStatus.FAILED
            ppt.save(update_fields=["parsed_pages", "parse_status", "updated_at"])

    @action(detail=True, methods=["post"], url_path="reparse")
    def reparse(self, request, pk=None):
        from .ppt_parser import attach_slide_images, parse_teaching_file_pages, render_presentation_slide_images

        ppt = self.get_object()
        pages = parse_teaching_file_pages(ppt.file.path) if ppt.file else []
        if ppt.file:
            images = render_presentation_slide_images(ppt.file.path, resource_id=ppt.id)
            pages = attach_slide_images(pages, images)
        ppt.parsed_pages = pages
        ppt.parse_status = ppt.ParseStatus.DONE if pages else ppt.ParseStatus.FAILED
        ppt.save(update_fields=["parsed_pages", "parse_status", "updated_at"])
        return api_response({"page_count": len(pages)}, message="重新解析完成")


class TeachingVideoViewSet(BaseModelViewSet):
    serializer_class = TeachingVideoSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "catalog", "gen_status", "is_published"]

    def get_queryset(self):
        return TeachingVideo.objects.select_related("catalog")

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
        video.save(update_fields=["scripts", "audio_url", "subtitle_url", "video_url", "gen_status", "updated_at"])
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
        video.save(update_fields=["scripts", "audio_url", "subtitle_url", "video_url", "gen_status", "updated_at"])
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
        video.save(update_fields=["scripts", "audio_url", "subtitle_url", "video_url", "gen_status", "updated_at"])
        return api_response(self.get_serializer(video).data, message="该页讲稿已重新生成，需要重新配音")
