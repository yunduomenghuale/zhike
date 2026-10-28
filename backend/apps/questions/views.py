import os
import tempfile
import time
from uuid import uuid4

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.ai.models import AITask
from apps.ai.tasks import submit_ai_task
from apps.common.access import courses_for_user, is_platform_admin
from apps.common.permissions import IsStudent, IsTeacher, IsTeacherOrAdmin, IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet
from apps.courses.models import Catalog, Course
from django.db.models import Q
from apps.knowledge.extractor import extract_text_with_images, extract_text_with_tables

from .draft_pipeline import save_batch_drafts
from .grading import grade_objective
from .import_parser import parse_questions
from .models import AnswerRecord, Question, QuestionDraftBatch, WrongMastery, WrongNote
from .serializers import (
    AnswerRecordSerializer,
    QuestionDraftBatchSerializer,
    QuestionSerializer,
    StudentQuestionSerializer,
)
from .throttles import TeacherAiScopedThrottle

# 文档导入约束（设计方案 §2.4 / 附录 B-5~B-7）
IMPORT_SUPPORTED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md"}
IMPORT_MAX_SIZE = 10 * 1024 * 1024  # 10MB
RAW_TEXT_LIMIT = 100_000  # raw_text 截断字符数（防撑爆行）

# 题目配图上传约束（与 nginx media 危险扩展强制下载双保险：仅图片类型）
QUESTION_IMAGE_MAX_SIZE = 5 * 1024 * 1024  # 5MB
QUESTION_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


class QuestionImageUploadView(APIView):
    """题目配图上传（教师）：uuid 化存储、扩展名/大小/PIL 三层校验。

    「先上传后提交」：返回的 path 由前端在保存题目/草稿时随表单回传，
    入库管道与 QuestionSerializer 仅接受 question_images/ 前缀路径。
    """

    permission_classes = [IsTeacherOrAdmin]
    parser_classes = [MultiPartParser]

    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            return api_response(message="请选择图片文件", code=400, status=400)
        ext = os.path.splitext(upload.name or "")[1].lower()
        if ext not in QUESTION_IMAGE_EXTS:
            return api_response(message="仅支持 PNG/JPG/GIF/WebP/BMP 图片", code=400, status=400)
        if upload.size > QUESTION_IMAGE_MAX_SIZE:
            return api_response(message="图片超过 5MB 上限，请压缩后重试", code=400, status=400)
        try:
            from PIL import Image

            img = Image.open(upload)
            img.verify()
        except Exception:
            return api_response(message="文件不是有效的图片", code=400, status=400)
        upload.seek(0)
        name = f"question_images/{uuid4().hex}{ext}"
        path = default_storage.save(name, upload)
        return api_response({"path": path, "url": f"/media/{path}"}, message="上传成功", status=201)
# 扩展名 → 文件头魔数（txt/md 纯文本不复检）
_IMPORT_MAGIC = {
    ".pdf": b"%PDF",
    ".doc": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",  # OLE2 复合文档
    ".docx": b"PK\x03\x04",  # ZIP/OOXML
}
# AI 多类型生题约束（阶段 4）：一次提交的题型数/单组数量/总数/分值上限
AI_GEN_MAX_GROUPS = 5
AI_GEN_MAX_COUNT = 20
AI_GEN_MAX_TOTAL = 50
AI_GEN_MAX_SCORE = 100


class QuestionViewSet(BaseModelViewSet):
    serializer_class = QuestionSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "catalog", "qtype", "difficulty", "status", "source"]
    search_fields = ["stem"]
    # 教师端 AI 重操作限流（throttles.py 按 action_scopes 分档，未声明的动作放行）
    throttle_classes = [TeacherAiScopedThrottle]
    action_scopes = {"generate": "teacher_ai_generate", "import": "teacher_ai_import"}

    def get_queryset(self):
        user = self.request.user
        qs = Question.objects.filter(course__in=courses_for_user(user))
        # 学生只见已发布题目（用于章节练习）
        if getattr(user, "is_student", False):
            qs = qs.filter(
                status=Question.Status.PUBLISHED,
                catalog__is_published=True,
            )
        return qs.order_by("id")

    def get_serializer_class(self):
        # 学生列表/详情用不含答案解析的序列化器（练习时不泄题）
        user = self.request.user
        if user.is_authenticated and user.is_student and self.action in ("list", "retrieve"):
            return StudentQuestionSerializer
        return QuestionSerializer

    def perform_create(self, serializer):
        serializer.save(creator=self.request.user)

    @action(detail=False, methods=["post"], url_path="practice-submit", permission_classes=[IsStudent])
    def practice_submit(self, request):
        """章节练习提交：逐题自动评分并返回正确答案与解析（需求 S-Q-01/02/03）。

        请求：{"answers": {"<question_id>": <answer_obj>, ...}}
        """
        answers = request.data.get("answers", {}) or {}
        if not isinstance(answers, dict):
            raise ValidationError({"answers": "答案格式不正确"})
        try:
            question_ids = [int(key) for key in answers]
        except (TypeError, ValueError):
            raise ValidationError({"answers": "题目编号格式不正确"})
        results, total, correct = [], 0, 0
        q_map = {q.id: q for q in self.get_queryset().filter(id__in=question_ids)}
        for qid, stu_ans in answers.items():
            q = q_map.get(int(qid))
            if not q:
                continue
            is_correct, score = grade_objective(q, stu_ans or {})
            AnswerRecord.objects.create(
                student=request.user, question=q, scene=AnswerRecord.Scene.PRACTICE,
                student_answer=stu_ans or {}, is_correct=is_correct, score=score,
            )
            total += 1
            if is_correct:
                correct += 1
            results.append({
                "question_id": q.id,
                "is_correct": is_correct,
                "score": float(score) if score is not None else None,
                "correct_answer": q.answer,
                "analysis": q.analysis,
            })
        return api_response(
            {"total": total, "correct": correct, "results": results},
            message="练习提交完成",
        )

    @action(detail=False, methods=["post"], url_path="generate", permission_classes=[IsTeacher])
    def generate(self, request):
        """AI 多类型生题（异步，需求 T-Q-01 阶段 4）：提交即返回 task_id。

        请求：{"course":1,"catalog":2,"objective":"...","groups":[
            {"qtype":"single","count":5,"score":2}, {"qtype":"blank","count":3,"score":4}]}
        生成配置（groups/objective）随任务落 AITask.progress，后台线程逐组
        生成（question_gen_ai.run_question_gen），全部草稿落 QuestionDraftBatch
        （origin=AI_GEN），教师预览编辑后走 save 管道入库（与文档导入共用）。
        前端轮询 /api/ai-tasks/<id>/；完成后 result.batch_id 即草稿批次 id。
        防重复提交：同教师同课程同时只允许一条进行中任务（模型层唯一索引）。
        """
        course_id = request.data.get("course")
        catalog_id = request.data.get("catalog")
        if not catalog_id:
            return api_response(message="请先选择题目所属章节", code=400, status=400)
        catalog = Catalog.objects.filter(
            id=catalog_id,
            course_id=course_id,
            course__teacher=request.user,
        ).first()
        if not catalog:
            return api_response(message="所选章节不属于当前课程", code=400, status=400)

        groups, err = self._validate_groups(request.data.get("groups"))
        if err:
            return api_response(message=err, code=400, status=400)
        objective = str(request.data.get("objective") or "")[:500]

        try:
            task = submit_ai_task(
                AITask.TaskType.QUESTION_GEN,
                user=request.user,
                course=catalog.course,
                catalog=catalog,
                progress={
                    "stage": "queued",
                    "done": 0,
                    # 进度按题计数（与 run_question_gen 的逐块推进同口径）
                    "total": sum(g["count"] for g in groups),
                    "groups": groups,
                    "objective": objective,
                    "message": "排队中…",
                },
            )
        except IntegrityError:
            # uniq_active_question_gen：同教师同课程已有 pending/running 任务
            return api_response(message="已有进行中的生题任务，请等待完成后再试", code=400, status=400)
        return api_response(
            {"task_id": task.id, "groups": groups},
            message="生题任务已提交，生成过程中离开页面也不会丢失",
        )

    @staticmethod
    def _validate_groups(raw):
        """groups 校验：题型合法、数量/分值有界、总数受控。

        返回 (groups, None) 或 (None, 中文错误文案)。
        """
        qtypes = {q for q, _ in Question.QType.choices}
        if not isinstance(raw, list) or not raw:
            return None, "请至少选择一个题型并设置数量"
        if len(raw) > AI_GEN_MAX_GROUPS:
            return None, f"一次最多同时生成 {AI_GEN_MAX_GROUPS} 种题型"
        groups, total = [], 0
        for g in raw:
            if not isinstance(g, dict):
                return None, "题型配置格式不正确"
            qtype = str(g.get("qtype") or "").strip()
            if qtype not in qtypes:
                return None, f"不支持的题型：{qtype or '空'}"
            try:
                count = int(g.get("count"))
                score = float(g.get("score"))
            except (TypeError, ValueError):
                return None, "题型数量与分值必须是数字"
            if count < 1 or count > AI_GEN_MAX_COUNT:
                return None, f"每种题型数量需在 1-{AI_GEN_MAX_COUNT} 之间"
            if score < 0.5 or score > AI_GEN_MAX_SCORE:
                return None, f"每题分值需在 0.5-{AI_GEN_MAX_SCORE} 之间"
            total += count
            groups.append({"qtype": qtype, "count": count, "score": score})
        if total > AI_GEN_MAX_TOTAL:
            return None, f"一次生成题目总数不可超过 {AI_GEN_MAX_TOTAL}"
        return groups, None

    @action(detail=False, methods=["post"], url_path="import", permission_classes=[IsTeacherOrAdmin])
    def import_questions(self, request):
        """上传题目文档 → 规则解析 → 建草稿批次（需求 T-Q-01 导入链路）。

        multipart：file + course（+ catalog 可选，后续可 PATCH 改目标章节）。
        权限：教师且课程归属本人，平台管理员除外（附录 B-2）；批次含答案解析，
        学生绝不可见。解析出 0 题 / 无文本 → 400 明确文案。
        """
        upload = request.FILES.get("file")
        if not upload:
            return api_response(message="请上传题目文件", code=400, status=400)
        ext = os.path.splitext(upload.name)[1].lower()
        if ext not in IMPORT_SUPPORTED_EXTENSIONS:
            supported = "、".join(sorted(IMPORT_SUPPORTED_EXTENSIONS))
            return api_response(message=f"暂不支持该文件格式，支持：{supported}", code=400, status=400)
        if upload.size > IMPORT_MAX_SIZE:
            return api_response(message="文件超过 10MB 上限，请压缩或拆分后重试", code=400, status=400)

        course = Course.objects.filter(id=request.data.get("course")).first()
        if not course:
            return api_response(message="请选择目标课程", code=400, status=400)
        if not is_platform_admin(request.user) and course.teacher_id != request.user.id:
            return api_response(message="只能导入到自己负责课程的题目", code=400, status=400)

        catalog = None
        catalog_id = request.data.get("catalog") or None
        if catalog_id:
            catalog = Catalog.objects.filter(id=catalog_id, course_id=course.id).first()
            if not catalog:
                return api_response(message="所选章节不属于当前课程", code=400, status=400)

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            for chunk in upload.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            magic = _IMPORT_MAGIC.get(ext)
            if magic:
                with open(tmp_path, "rb") as f:
                    if not f.read(len(magic)).startswith(magic):
                        return api_response(
                            message="文件内容与扩展名不符，请确认文件未损坏且格式正确",
                            code=400, status=400,
                        )
            started = time.monotonic()
            # 题图感知抽取：docx/pdf 在图片原文位置插入 [[QUESTION_IMAGE:n]] 占位行
            text, extracted_images = extract_text_with_images(tmp_path)
            parse_ms = int((time.monotonic() - started) * 1000)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        if not text.strip():
            return api_response(
                message="未能提取到文本内容（扫描件/图片型文档暂不支持，或文件已损坏），请转换后可重试",
                code=400, status=400,
            )
        drafts = parse_questions(text)
        if not drafts:
            return api_response(
                message="未能识别出题目，请确认文档包含题号、选项、答案等结构（可下载导入模板参考格式）",
                code=400, status=400,
            )

        # 题图落盘：草稿的占位序号 → 媒体库路径（入库管道按 question_images/ 前缀透传）
        for draft in drafts:
            idx = draft.pop("image_index", None)
            if idx is None:
                continue
            img = next((i for i in extracted_images if i["index"] == idx), None)
            if not img or not img.get("data"):
                draft.setdefault("_warnings", []).append("题图提取失败，请手动上传")
                continue
            name = f"question_images/{uuid4().hex}{img['ext']}"
            draft["image"] = default_storage.save(name, ContentFile(img["data"]))

        batch = QuestionDraftBatch(
            origin=QuestionDraftBatch.Origin.IMPORT,
            course=course,
            catalog=catalog,
            creator=request.user,
            file_name=upload.name[:255],
            drafts=drafts,
            raw_text=text[:RAW_TEXT_LIMIT],
            stats={
                "total": len(drafts),
                "warned": sum(1 for d in drafts if d.get("_warnings")),
                "with_image": sum(1 for d in drafts if d.get("image")),
                "truncated": len(text) > RAW_TEXT_LIMIT,
                "parse_ms": parse_ms,
            },
        )
        batch.save()
        # 上传文件转入 FileField 存储（upload_to 自动 uuid 化命名，入库即删时清理）
        batch.file.save(upload.name, upload, save=True)

        return api_response(
            QuestionDraftBatchSerializer(batch).data,
            message=f"已识别 {len(drafts)} 道题目，请预览编辑后入库",
        )


class QuestionDraftBatchViewSet(BaseModelViewSet):
    """题目草稿批次：导入/AI 生成共用的待入库池（恢复入口 + 防抖回传 + 批量入库）。

    权限：IsTeacherOrAdmin；行级过滤 course__teacher=user（平台管理员全量），
    不用 courses_for_user（其包含学生 enrolled 课程，会泄露答案解析，附录 B-2）。
    """

    serializer_class = QuestionDraftBatchSerializer
    permission_classes = [IsTeacherOrAdmin]
    filterset_fields = ["course", "status", "origin"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs = QuestionDraftBatch.objects.select_related("course", "catalog")
        if is_platform_admin(user):
            return qs.order_by("-id")
        return qs.filter(course__teacher=user).order_by("-id")

    def perform_update(self, serializer):
        drafts = serializer.validated_data.get("drafts")
        if drafts is not None and not all(isinstance(d, dict) for d in drafts):
            raise ValidationError({"drafts": "草稿数据格式不正确"})
        serializer.save()

    def perform_destroy(self, instance):
        # 放弃批次：先删文件再删行（入库即删的同款清理）
        if instance.file:
            instance.file.delete(save=False)
        instance.delete()

    @action(detail=True, methods=["post"], url_path="save")
    def save_drafts(self, request, pk=None):
        """批量入库：body {items:[草稿...], publish:bool}（教师勾选/编辑后的子集）。

        流水线见 draft_pipeline.save_batch_drafts；部分失败不整批回滚，
        失败项留批次内可修正重试；精确查重防重复入库（附录 B-3）。
        publish=True 时入库题目直接置「已发布」，省去逐题点发布（导入/AI 生题共用）。
        """
        batch = self.get_object()
        publish = request.data.get("publish") in (True, "true", "1", 1)
        try:
            result = save_batch_drafts(batch, request.data.get("items"), request.user, publish=publish)
        except ValidationError as exc:
            detail = exc.detail[0] if isinstance(exc.detail, list) and exc.detail else exc.detail
            return api_response(message=str(detail), code=400, status=400)
        saved_n = len(result["saved"])
        message = f"已入库并发布 {saved_n} 题" if publish else f"已入库 {saved_n} 题"
        if result["skipped"]:
            message += f"，跳过 {result['skipped']} 题（题库已存在相同题干）"
        if result["failed"]:
            message += f"，{len(result['failed'])} 题待修正"
        return api_response(result, message=message)


class AnswerRecordViewSet(BaseModelViewSet):
    serializer_class = AnswerRecordSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["scene", "question", "student"]

    def get_queryset(self):
        user = self.request.user
        qs = AnswerRecord.objects.select_related("question")
        if user.is_authenticated and user.is_student:
            qs = qs.filter(student=user)
        elif user.is_authenticated and user.is_teacher:
            qs = qs.filter(question__course__teacher=user)
        elif not is_platform_admin(user):
            qs = qs.none()
        return qs.order_by("id")

    def create(self, request, *args, **kwargs):
        """学生提交章节练习答案，客观题即时自动评分（需求 S-Q-01/02）。"""
        if not request.user.is_student:
            raise PermissionDenied("仅学生可提交练习答案")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data["question"]
        if not Question.objects.filter(
            pk=question.pk,
            course__in=courses_for_user(request.user),
            catalog__is_published=True,
            status=Question.Status.PUBLISHED,
        ).exists():
            raise PermissionDenied("题目不存在、尚未发布或无权访问")
        student_answer = serializer.validated_data.get("student_answer", {})
        is_correct, score = grade_objective(question, student_answer)
        record = serializer.save(student=request.user, is_correct=is_correct, score=score)
        return api_response(
            AnswerRecordSerializer(record).data, message="提交成功", status=201
        )


class WrongNoteViewSet(BaseModelViewSet):
    """学生手动错题：学生只能增删查自己的记录。"""

    permission_classes = [IsStudent]
    filterset_fields = ["course"]

    def get_queryset(self):
        return WrongNote.objects.filter(student=self.request.user)

    def get_serializer_class(self):
        from .serializers import WrongNoteSerializer

        return WrongNoteSerializer

    def perform_create(self, serializer):
        serializer.save(student=self.request.user)


class WrongMasteryView(APIView):
    """错题巩固/移除状态：查询我的标记集合 + 切换标记。

    POST 参数：question 或 note（二选一），action=master(默认)|remove。
    同一记录两个标记都被取消时自动删除记录。
    """

    permission_classes = [IsStudent]

    def get(self, request):
        qs = WrongMastery.objects.filter(student=request.user)
        course_id = request.query_params.get("course")
        if course_id:
            qs = qs.filter(Q(question__course_id=course_id) | Q(note__course_id=course_id))
        return api_response({
            "questions": [m.question_id for m in qs if m.question_id and not m.removed],
            "notes": [m.note_id for m in qs if m.note_id and not m.removed],
            "removed_questions": [m.question_id for m in qs if m.question_id and m.removed],
            "removed_notes": [m.note_id for m in qs if m.note_id and m.removed],
        })

    def post(self, request):
        question_id = request.data.get("question")
        note_id = request.data.get("note")
        action = request.data.get("action", "master")
        if not question_id and not note_id:
            return api_response(message="缺少 question 或 note 参数", code=400, status=400)

        lookup = {"student": request.user}
        if question_id:
            lookup["question_id"] = question_id
        else:
            lookup["note_id"] = note_id

        obj, created = WrongMastery.objects.get_or_create(**lookup)

        if action == "remove":
            obj.removed = not obj.removed
            obj.save()
            if not obj.removed:
                # 取消移除且未巩固：记录无意义，直接删除
                obj.delete()
                return api_response({"removed": False}, message="已恢复到错题本")
            return api_response({"removed": True}, message="已从错题本移除")

        # 巩固标记切换；若同时处于已移除状态则一并取消移除
        if not created and not obj.removed:
            obj.delete()
            return api_response({"mastered": False}, message="已取消巩固标记")
        obj.removed = False
        obj.save()
        return api_response({"mastered": True}, message="已标记为已巩固")
