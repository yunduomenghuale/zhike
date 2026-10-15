import json
from pathlib import Path

from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import FileResponse, StreamingHttpResponse
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.ai.providers.factory import chat_supports_vision
from apps.ai.services import (
    build_qa_history,
    ingest_material,
    knowledge_qa,
    knowledge_qa_stream,
)
from apps.common.permissions import IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet

from .models import KnowledgeChunk, Material, QARecord
from .preview import (
    MAX_PREVIEW_PAGES,
    PREVIEWABLE_EXTENSIONS,
    convert_office_to_pdf,
    material_media_url,
    material_preview_paths,
    read_material_text,
    render_material_pages,
)
from .serializers import MaterialSerializer, QARecordSerializer
from .services import rebuild_vectors


def _sse(payload: dict) -> str:
    """封装成 SSE data 帧。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# 图片问题允许的最大 base64 长度（约 4MB 原图）
_MAX_IMAGE_B64_LEN = 5_600_000

# 多轮对话：最多携带的历史轮数（一问一答为一轮）
QA_MAX_HISTORY_TURNS = 10


def _validate_image(value):
    """校验可选的 base64 图片（data URL）。返回 (image_b64 或 None, 错误信息或 None)。"""
    if not value:
        return None, None
    if not isinstance(value, str) or not value.startswith("data:image/"):
        return None, "图片格式不正确"
    if len(value) > _MAX_IMAGE_B64_LEN:
        return None, "图片过大，请压缩后再试"
    return value, None


def _resolve_qa_scope(request):
    """Resolve and validate the course/class/catalog named by a QA request."""
    course_id = request.data.get("course")
    course = courses_for_user(request.user).filter(pk=course_id).first()
    if not course:
        raise NotFound("课程不存在或无权访问")

    classroom_id = request.data.get("classroom")
    classroom = None
    if classroom_id:
        classroom = classrooms_for_user(request.user).filter(pk=classroom_id).first()
        if not classroom or not classroom.courses.filter(pk=course.pk).exists():
            raise ValidationError({"classroom": "班级不存在、无权访问或未关联当前课程"})

    catalog_id = request.data.get("catalog")
    catalog = None
    if catalog_id:
        catalog = course.catalogs.filter(pk=catalog_id).first()
        if not catalog or (request.user.is_student and not catalog.is_published):
            raise ValidationError({"catalog": "章节不存在或尚未发布"})
    return course, classroom, catalog


class MaterialViewSet(BaseModelViewSet):
    serializer_class = MaterialSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "classroom", "parse_status", "qa_open"]

    def get_queryset(self):
        user = self.request.user
        qs = Material.objects.filter(course__in=courses_for_user(user))
        if getattr(user, "is_student", False):
            qs = qs.filter(
                Q(classroom__isnull=True)
                | Q(classroom__students__student=user, classroom__students__learn_status="active")
            )
        return qs.distinct().order_by("id")

    def perform_create(self, serializer):
        """上传即自动识别类型并解析入库（需求 T-K-01/02）。"""
        from .extractor import detect_file_type

        material = serializer.save()
        if material.file and not material.file_type:
            material.file_type = detect_file_type(material.file_name or material.file.name)
            material.save(update_fields=["file_type", "updated_at"])
        ingest_material(material)

    @action(detail=True, methods=["post"], url_path="reparse")
    def reparse(self, request, pk=None):
        """重新解析入库：抽取→切分→向量化→写入知识库片段（需求 T-K-03）。"""
        material = self.get_object()
        count = ingest_material(material)
        return api_response({"chunk_count": count}, message="资料已重新入库")

    @action(detail=False, methods=["post"], url_path="rebuild-vectors")
    def rebuild_vectors_action(self, request):
        """用当前向量模型重建知识库向量（换向量模型/修复 mock 向量后必须执行）。

        覆盖教辅资料与课件 PPT（课件是向量库的主要内容，每页一个片段）。
        body: {"course": 课程ID（必填，除非传 material/ppt）,
               "material": 资料ID（可选，只重建一份）,
               "ppt": 课件ID（可选，只重建一部）}
        出错处理：事前校验失败（模型不可用）返回 400 且不动数据；单项失败
        不影响其他项，失败清单随响应返回，修复后可再次调用续跑。
        """
        from apps.courses.models import PPTResource

        course_id = request.data.get("course")
        material_id = request.data.get("material")
        ppt_id = request.data.get("ppt")
        qs = self.get_queryset()  # 行级过滤：只能重建自己课程的资料
        ppt_qs = PPTResource.objects.filter(course__in=courses_for_user(request.user))
        materials = qs.none()
        ppts = ppt_qs.none()
        if material_id:
            materials = qs.filter(pk=material_id)
            if not materials.exists():
                raise NotFound("资料不存在或无权访问")
        elif ppt_id:
            ppts = ppt_qs.filter(pk=ppt_id)
            if not ppts.exists():
                raise NotFound("课件不存在或无权访问")
        elif course_id:
            materials = qs.filter(course_id=course_id)
            ppts = ppt_qs.filter(course_id=course_id, is_active=True)
        else:
            raise ValidationError({"course": "请指定要重建向量的课程"})

        report = rebuild_vectors(materials, ppts)
        if report.get("error"):
            return api_response(report, message=report["error"], code=400, status=400)
        message = (
            f"向量重建完成：资料 {report['materials']['success']}/{report['materials']['total']} 份，"
            f"课件 {report['ppts']['success']}/{report['ppts']['total']} 部，"
            f"共 {report['chunks']} 个片段"
        )
        if report["failed"]:
            message += f"，失败 {len(report['failed'])} 项（详见返回清单，可修复后重试）"
        return api_response(report, message=message)

    @action(detail=True, methods=["post"], url_path="toggle-qa")
    def toggle_qa(self, request, pk=None):
        """开启/关闭该资料对学生的自由提问（需求 T-K-04）。"""
        material = self.get_object()
        material.qa_open = not material.qa_open
        material.save(update_fields=["qa_open", "updated_at"])
        return api_response({"qa_open": material.qa_open}, message="已更新开放状态")

    @action(detail=True, methods=["get"], url_path="preview")
    def preview(self, request, pk=None):
        """资料在线预览：PDF 直接逐页出图；Word/PPT 经 LibreOffice 转 PDF 后出图；txt 回文本。

        页图按存储文件名哈希缓存（uuid 文件名内容不可变，可安全复用）；
        Word/PPT 首次预览需转换，耗时较长。权限继承 ViewSet：get_object()
        走 get_queryset() 行级过滤，无权访问即 404。
        """
        material = self.get_object()
        if not material.file:
            raise ValidationError({"file": "资料文件缺失，请联系老师重新上传"})
        name = material.file.name
        ext = Path(name).suffix.lower()

        if ext == ".txt":
            if not default_storage.exists(name):
                raise ValidationError({"file": "资料文件缺失，请联系老师重新上传"})
            return api_response(
                {"kind": "text", "text": read_material_text(name), "name": material.file_name},
                message="预览已就绪",
            )

        if ext not in PREVIEWABLE_EXTENSIONS:
            raise ValidationError({"file": "该类型暂不支持在线预览，请下载后查看"})
        if not default_storage.exists(name):
            raise ValidationError({"file": "资料文件缺失，请联系老师重新上传"})

        rel_root, cache_root = material_preview_paths(name)
        rel_pages = rel_root / "pages"
        pages_dir = cache_root / "pages"
        cached = sorted(pages_dir.glob("slide-*.png")) if pages_dir.exists() else []
        if cached:
            page_urls = [material_media_url(rel_pages / page.name) for page in cached]
            return api_response(
                {"kind": "pages", "pages": page_urls, "name": material.file_name},
                message="预览已就绪",
            )

        try:
            file_path = default_storage.path(name)
        except NotImplementedError:
            raise ValidationError({"file": "当前存储不支持在线预览"})

        pdf_path = file_path if ext == ".pdf" else convert_office_to_pdf(file_path, cache_root)
        if not pdf_path:
            raise ValidationError({"file": "文档转换失败，请下载后查看"})

        import pypdfium2 as pdfium

        try:
            pdf = pdfium.PdfDocument(str(pdf_path))
            page_count = len(pdf)
            pdf.close()
        except Exception:
            raise ValidationError({"file": "文档解析失败，请下载后查看"})
        if page_count > MAX_PREVIEW_PAGES:
            raise ValidationError({"file": f"文档超过 {MAX_PREVIEW_PAGES} 页，请下载后查看"})

        page_urls = render_material_pages(pdf_path, rel_root, cache_root)
        if not page_urls:
            raise ValidationError({"file": "文档渲染失败，请下载后查看"})
        return api_response(
            {"kind": "pages", "pages": page_urls, "name": material.file_name},
            message="预览已就绪",
        )

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        """资料下载：强制 attachment 并把文件名还原为原始文件名（存储名是 uuid）。

        FileResponse 流式返回，不走统一响应包装；权限同样由 get_object() 行级过滤。
        """
        material = self.get_object()
        if not material.file or not default_storage.exists(material.file.name):
            raise NotFound("资料文件不存在或已被移除")
        fh = default_storage.open(material.file.name, "rb")
        return FileResponse(fh, as_attachment=True, filename=material.file_name)


class QARecordViewSet(BaseModelViewSet):
    serializer_class = QARecordSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["course", "classroom", "student"]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs = QARecord.objects.select_related("student", "course", "classroom")
        if getattr(user, "is_student", False):
            qs = qs.filter(student=user)
        elif getattr(user, "is_teacher", False):
            qs = qs.filter(course__teacher=user)
        elif not is_platform_admin(user):
            qs = qs.none()
        return qs

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed("POST", detail="请使用 ask 或 ask-stream 接口提问")

    @action(detail=False, methods=["get"], url_path="vision-capability")
    def vision_capability(self, request):
        """当前对话模型是否支持图片输入。

        学生/教师端问答据此决定是否显示图片上传入口：不支持时隐藏入口，
        避免用户发送图片后被接口拒绝。不泄露任何配置与密钥。
        """
        return api_response({"supports_vision": chat_supports_vision()})

    @action(detail=False, methods=["post"], url_path="ask")
    def ask(self, request):
        """学生向课程知识库自由提问（需求 S-K-01/02/04）。

        基于课程资料检索 + 大模型回答；无相关资料时提示资料不足，不编造。
        """
        course, classroom, catalog = _resolve_qa_scope(request)
        question = request.data.get("question", "").strip()
        if not question:
            return api_response(message="问题不能为空", code=400, status=400)
        image_b64, error = _validate_image(request.data.get("image"))
        if error:
            return api_response(message=error, code=400, status=400)

        session = str(request.data.get("session") or "")[:64]
        history = build_qa_history(
            course.id,
            request.user.id,
            session,
            max_turns=QA_MAX_HISTORY_TURNS,
        )
        answer, cited = knowledge_qa(
            course_id=course.id,
            question=question,
            catalog_id=catalog.id if catalog else None,
            image_b64=image_b64,
            student_access=getattr(request.user, "is_student", False),
            classroom_id=classroom.id if classroom else None,
            history=history,
        )
        record = QARecord.objects.create(
            course=course,
            classroom=classroom,
            catalog=catalog,
            session=str(request.data.get("session") or "")[:64],
            student=request.user,
            question=question,
            answer=answer,
            cited_chunks=cited,
        )
        return api_response(QARecordSerializer(record).data, message="回答完成")

    @action(detail=False, methods=["post"], url_path="ask-stream")
    def ask_stream(self, request):
        """流式问答（SSE）：逐 token 返回回答，边生成边显示。

        事件序列：meta(引用片段) -> 若干 delta(文本片段) -> done。
        生成结束后落库为一条 QARecord。
        """
        course, classroom, catalog = _resolve_qa_scope(request)
        session = str(request.data.get("session") or "")[:64]
        question = (request.data.get("question") or "").strip()
        if not question:
            return api_response(message="问题不能为空", code=400, status=400)
        image_b64, error = _validate_image(request.data.get("image"))
        if error:
            return api_response(message=error, code=400, status=400)
        user = request.user

        # 多轮对话：取同会话最近几轮历史拼进模型上下文
        history = build_qa_history(
            course.id,
            user.id,
            session,
            max_turns=QA_MAX_HISTORY_TURNS,
        )

        def event_stream():
            full, cited = [], []
            try:
                for evt in knowledge_qa_stream(
                    course_id=course.id,
                    question=question,
                    catalog_id=catalog.id if catalog else None,
                    image_b64=image_b64,
                    student_access=getattr(user, "is_student", False),
                    classroom_id=classroom.id if classroom else None,
                    history=history,
                ):
                    if evt["type"] == "meta":
                        cited = evt["cited"]
                        yield _sse({"type": "meta", "cited": cited})
                    elif evt["type"] == "history_dropped":
                        # 上下文超限已降级（丢弃多轮历史重试成功）
                        yield _sse({"type": "history_dropped"})
                    elif evt["type"] == "delta":
                        full.append(evt["text"])
                        yield _sse({"type": "delta", "text": evt["text"]})
            except Exception as exc:  # 生成中出错也要通知前端
                yield _sse({"type": "error", "message": str(exc)})
            answer = "".join(full)
            try:
                QARecord.objects.create(
                    course=course,
                    classroom=classroom,
                    catalog=catalog,
                    session=session,
                    student=user,
                    question=question,
                    answer=answer,
                    cited_chunks=cited,
                )
            except Exception:
                pass
            yield _sse({"type": "done"})

        resp = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"  # 关闭 nginx/代理缓冲，保证逐段下发
        return resp
from apps.common.access import classrooms_for_user, courses_for_user, is_platform_admin
