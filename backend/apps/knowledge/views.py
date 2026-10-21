import json
from pathlib import Path

from django.core.files.storage import default_storage
from django.db.models import Count, Max, Q
from django.http import FileResponse, StreamingHttpResponse
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.ai.providers.factory import chat_supports_vision
from apps.ai.services import (
    build_conversation_context,
    ingest_material,
    knowledge_qa,
    knowledge_qa_stream,
    maybe_update_session_summary,
)
from apps.common.access import classrooms_for_user, courses_for_user, is_platform_admin
from apps.common.permissions import IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet

from .models import KnowledgeChunk, Material, QARecord, QASession
from .preview import (
    MAX_PREVIEW_PAGES,
    PREVIEWABLE_EXTENSIONS,
    convert_office_to_pdf,
    material_media_url,
    material_preview_paths,
    read_material_text,
    render_material_pages,
)
from .serializers import MaterialSerializer, QARecordSerializer, QASessionSerializer
from .services import rebuild_vectors


def _sse(payload: dict) -> str:
    """封装成 SSE data 帧。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# 图片问题允许的最大 base64 长度（约 4MB 原图）
_MAX_IMAGE_B64_LEN = 5_600_000


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
    """Resolve and validate the course/class/catalog named by a QA request.

    返回 (course, classroom, catalog, classroom_ids)。classroom_ids 为学生检索
    资料片段时可见的班级集合：显式传班级时为该班级；未传时自动解析学生在读
    班级（此前学生检索要求资料 classroom 为空，班级定向资料对学生问答永久
    隐形，2026-10-21 修复）。非学生为 None（不过滤）。
    """
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

    classroom_ids = None
    if getattr(request.user, "is_student", False):
        if classroom:
            classroom_ids = [classroom.id]
        else:
            from apps.classroom.models import ClassStudent

            classroom_ids = list(
                ClassStudent.objects.filter(
                    student=request.user,
                    learn_status=ClassStudent.LearnStatus.ACTIVE,
                    classroom__courses=course,
                ).values_list("classroom_id", flat=True)
            )
    return course, classroom, catalog, classroom_ids


def _resolve_qa_session(request, course, catalog):
    """解析（或创建）本次提问所属的问答会话。

    优先级：
    1. 显式 session_id：校验归属本人、本课程，且会话范围与当前提问一致
       （课程级会话不能用于章节提问，反之亦然）；
    2. 旧 session 字符串：按 (course, student, legacy_key) get_or_create——
       旧前端/移动端无感迁移，历史自动接续；
    3. 都不传：新建会话（meta/done 事件把 session_id 带回前端）。
    """
    user = request.user
    catalog_id = catalog.id if catalog else None

    session_id = request.data.get("session_id")
    if session_id:
        sess = QASession.objects.filter(pk=session_id, student=user, course=course).first()
        if not sess:
            raise NotFound("会话不存在或无权访问")
        if (sess.catalog_id or None) != catalog_id:
            raise ValidationError({"session_id": "会话与当前提问范围不一致"})
        return sess

    legacy = str(request.data.get("session") or "")[:64]
    if legacy:
        sess, _created = QASession.objects.get_or_create(
            course=course,
            student=user,
            legacy_key=legacy,
            defaults={"catalog": catalog},
        )
        return sess
    return QASession.objects.create(course=course, catalog=catalog, student=user)


def _next_turn_index(qa_session) -> int:
    last = qa_session.records.order_by("-turn_index").values_list("turn_index", flat=True).first()
    return (last or 0) + 1


def _touch_session(qa_session, question: str):
    """会话元数据维护：首问生成标题；每次提问刷新 updated_at 让列表置顶。"""
    update_fields = ["updated_at"]
    if not qa_session.title:
        qa_session.title = question[:30]
        update_fields.append("title")
    qa_session.save(update_fields=update_fields)


def _prev_snapshot_chunks(qa_session):
    """取会话最近一条带上下文快照的记录的命中片段清单（追问检索兜底用）。

    学生追问时若当前问题经改写仍检索为空，可捞取上一轮引用的片段内容
    作「上一轮参考」注入（见 knowledge_qa(_stream) 的 prev_snapshot 参数）。
    """
    last = (
        qa_session.records.exclude(context_snapshot={})
        .order_by("-turn_index")
        .only("context_snapshot")
        .first()
    )
    if not last:
        return None
    chunks = (last.context_snapshot or {}).get("chunks")
    return chunks or None


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
        from apps.courses.models import PPTResource, TeachingVideo

        course_id = request.data.get("course")
        material_id = request.data.get("material")
        ppt_id = request.data.get("ppt")
        qs = self.get_queryset()  # 行级过滤：只能重建自己课程的资料
        ppt_qs = PPTResource.objects.filter(course__in=courses_for_user(request.user))
        video_qs = TeachingVideo.objects.filter(course__in=courses_for_user(request.user))
        materials = qs.none()
        ppts = ppt_qs.none()
        videos = video_qs.none()
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
            videos = video_qs.filter(course_id=course_id).exclude(scripts=[])
        else:
            raise ValidationError({"course": "请指定要重建向量的课程"})

        report = rebuild_vectors(materials, ppts, videos)
        if report.get("error"):
            return api_response(report, message=report["error"], code=400, status=400)
        message = (
            f"向量重建完成：资料 {report['materials']['success']}/{report['materials']['total']} 份，"
            f"课件 {report['ppts']['success']}/{report['ppts']['total']} 部，"
            f"讲稿 {report['videos']['success']}/{report['videos']['total']} 部，"
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
        响应 data 附带 session_id（本次会话）与 rewritten_question（改写后的
        检索问题，未改写为空串）。
        """
        course, classroom, catalog, classroom_ids = _resolve_qa_scope(request)
        question = request.data.get("question", "").strip()
        if not question:
            return api_response(message="问题不能为空", code=400, status=400)
        image_b64, error = _validate_image(request.data.get("image"))
        if error:
            return api_response(message=error, code=400, status=400)

        qa_session = _resolve_qa_session(request, course, catalog)
        # 多轮对话：基于会话装配历史（滚动摘要 + 预算内最近原文轮）
        history = build_conversation_context(qa_session)
        answer, cited, rewritten, snapshot = knowledge_qa(
            course_id=course.id,
            question=question,
            catalog_id=catalog.id if catalog else None,
            image_b64=image_b64,
            student_access=getattr(request.user, "is_student", False),
            classroom_ids=classroom_ids,
            history=history,
            prev_snapshot=_prev_snapshot_chunks(qa_session),
        )
        record = QARecord.objects.create(
            course=course,
            classroom=classroom,
            catalog=catalog,
            session=qa_session.legacy_key,
            session_ref=qa_session,
            turn_index=_next_turn_index(qa_session),
            student=request.user,
            question=question,
            answer=answer,
            cited_chunks=cited,
            rewritten_question=rewritten[:500],
            context_snapshot=snapshot,
        )
        _touch_session(qa_session, question)
        maybe_update_session_summary(qa_session)
        data = QARecordSerializer(record).data
        data["session_id"] = qa_session.id
        data["rewritten_question"] = rewritten
        return api_response(data, message="回答完成")

    @action(detail=False, methods=["post"], url_path="ask-stream")
    def ask_stream(self, request):
        """流式问答（SSE）：逐 token 返回回答，边生成边显示。

        事件序列：meta(引用片段+编号/改写问题/session_id) -> 若干 delta(文本片段)
        -> (history_dropped，上下文超限分级降级时) -> done(带 record_id)。
        生成结束后落库为一条 QARecord 并维护会话（标题/滚动摘要）。
        """
        course, classroom, catalog, classroom_ids = _resolve_qa_scope(request)
        question = (request.data.get("question") or "").strip()
        if not question:
            return api_response(message="问题不能为空", code=400, status=400)
        image_b64, error = _validate_image(request.data.get("image"))
        if error:
            return api_response(message=error, code=400, status=400)
        user = request.user

        qa_session = _resolve_qa_session(request, course, catalog)
        # 多轮对话：基于会话装配历史（滚动摘要 + 预算内最近原文轮）
        history = build_conversation_context(qa_session)

        def event_stream():
            full, cited = [], []
            snapshot: dict = {}
            rewritten = ""
            record = None
            try:
                for evt in knowledge_qa_stream(
                    course_id=course.id,
                    question=question,
                    catalog_id=catalog.id if catalog else None,
                    image_b64=image_b64,
                    student_access=getattr(user, "is_student", False),
                    classroom_ids=classroom_ids,
                    history=history,
                    prev_snapshot=_prev_snapshot_chunks(qa_session),
                ):
                    if evt["type"] == "meta":
                        cited = evt["cited"]
                        rewritten = evt.get("rewritten_question") or ""
                        # snapshot 仅落库审计，不下发前端；降级级别由 stream
                        # 内部经同一对象引用更新
                        snapshot = evt.get("snapshot") or {}
                        yield _sse(
                            {
                                "type": "meta",
                                "cited": cited,
                                "rewritten_question": rewritten,
                                "session_id": qa_session.id,
                            }
                        )
                    elif evt["type"] == "history_dropped":
                        # 上下文超限分级降级（丢弃部分早期历史重试），level 1/2/4
                        yield _sse({"type": "history_dropped", "level": evt.get("level", 4)})
                    elif evt["type"] == "delta":
                        full.append(evt["text"])
                        yield _sse({"type": "delta", "text": evt["text"]})
            except Exception as exc:  # 生成中出错也要通知前端
                yield _sse({"type": "error", "message": str(exc)})
            answer = "".join(full)
            try:
                record = QARecord.objects.create(
                    course=course,
                    classroom=classroom,
                    catalog=catalog,
                    session=qa_session.legacy_key,
                    session_ref=qa_session,
                    turn_index=_next_turn_index(qa_session),
                    student=user,
                    question=question,
                    answer=answer,
                    cited_chunks=cited,
                    rewritten_question=rewritten[:500],
                    context_snapshot=snapshot,
                )
                _touch_session(qa_session, question)
                # 滚动摘要：阈值触发时在正文产出后执行（不阻塞正文显示），失败静默
                maybe_update_session_summary(qa_session)
            except Exception:
                pass
            yield _sse({"type": "done", "record_id": record.id if record else None})

        resp = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"  # 关闭 nginx/代理缓冲，保证逐段下发
        return resp

    @action(detail=True, methods=["post"], url_path="feedback")
    def feedback(self, request, pk=None):
        """学生对问答记录反馈有用/无用（质量闭环指标来源；幂等覆盖）。"""
        record = self.get_object()
        if record.student_id != request.user.id:
            raise PermissionDenied("只能评价自己的问答记录")
        try:
            value = int(request.data.get("value") or 0)
        except (TypeError, ValueError):
            value = 0
        if value not in (1, -1, 0):
            raise ValidationError({"value": "反馈值只能是 1（有用）/ -1（无用）/ 0（取消）"})
        record.feedback = value
        record.save(update_fields=["feedback", "updated_at"])
        return api_response({"feedback": record.feedback}, message="已记录反馈")


class QASessionViewSet(BaseModelViewSet):
    """问答会话（学生个人资产）：列表/新建/改名/归档/删除/会话内记录。

    行级口径：一律按 student=request.user 过滤——会话是个人资产；
    教师查看学生提问走 QARecord 列表（既有 CourseQA 记录视角），不经由本接口。
    """

    serializer_class = QASessionSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = (
            QASession.objects.filter(student=self.request.user)
            .annotate(
                record_count=Count("records"),
                last_message_at=Max("records__created_at"),
            )
            .select_related("catalog")
        )
        course_id = self.request.query_params.get("course")
        if course_id:
            qs = qs.filter(course_id=course_id)
        params = self.request.query_params
        if "catalog" in params:
            # catalog=<id> 过滤章节会话；catalog=（空值）只看课程级会话
            catalog = params.get("catalog")
            if catalog:
                qs = qs.filter(catalog_id=catalog)
            else:
                qs = qs.filter(catalog__isnull=True)
        status = params.get("status")
        qs = qs.filter(status=status) if status else qs.filter(status=QASession.Status.ACTIVE)
        return qs

    def perform_create(self, serializer):
        course_id = self.request.data.get("course")
        course = courses_for_user(self.request.user).filter(pk=course_id).first()
        if not course:
            raise NotFound("课程不存在或无权访问")
        catalog = None
        catalog_id = self.request.data.get("catalog")
        if catalog_id:
            catalog = course.catalogs.filter(pk=catalog_id).first()
            if not catalog or (self.request.user.is_student and not catalog.is_published):
                raise ValidationError({"catalog": "章节不存在或尚未发布"})
        serializer.save(student=self.request.user, course=course, catalog=catalog)

    def perform_update(self, serializer):
        # 只允许改名与归档（get_queryset 已限定本人会话）
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        # 删除会话连同其问答记录（session_ref 为 SET_NULL，需显式连删）
        sess = self.get_object()
        sess.records.all().delete()
        sess.delete()
        return api_response(message="会话已删除")

    @action(detail=True, methods=["get"])
    def records(self, request, pk=None):
        """会话内问答记录（按轮次升序，含引用片段与反馈状态）。"""
        sess = self.get_object()
        rows = sess.records.select_related("student").order_by("turn_index", "id")
        return api_response(QARecordSerializer(rows, many=True).data)
