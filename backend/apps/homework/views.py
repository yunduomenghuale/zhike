from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import hashlib
import json

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.classroom.models import ClassStudent
from apps.common.access import student_study_block_detail, student_submit_block_detail
from apps.common.permissions import IsStudent, IsTeacher, IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet
from apps.courses.ppt_parser import render_pdf_to_images
from apps.questions.grading import grade_objective
from apps.questions.models import AnswerRecord, Question

from .models import Homework, HomeworkAnswer, HomeworkSubmission
from .serializers import (
    HOMEWORK_ATTACHMENT_ALLOWED_EXTENSIONS,
    MAX_HOMEWORK_ATTACHMENT_COUNT,
    MAX_HOMEWORK_ATTACHMENT_SIZE,
    MAX_PREVIEW_PAGES,
    MAX_SUBMISSION_FILE_COUNT,
    MAX_SUBMISSION_FILE_SIZE,
    SUBMISSION_ALLOWED_EXTENSIONS,
    HomeworkSerializer,
    HomeworkSubmissionSerializer,
)
from .stats import build_homework_stats


def _media_url(rel_path: Path) -> str:
    """相对 media 的路径 → URL（as_posix 保证 Windows 下也是正斜杠）。"""
    return settings.MEDIA_URL + rel_path.as_posix()


def _delete_media_file(url: str) -> None:
    """按 media URL 删除存储文件（失败仅忽略，不阻断业务）。"""
    if not url or not url.startswith(settings.MEDIA_URL):
        return
    name = url[len(settings.MEDIA_URL):]
    try:
        if default_storage.exists(name):
            default_storage.delete(name)
    except OSError:
        pass


def _save_submission_files(files) -> list[dict]:
    """保存学生提交的附件（支持多文件与图片），返回 [{name, size, type, url}]。"""
    if len(files) > MAX_SUBMISSION_FILE_COUNT:
        raise ValidationError({"attachments": f"一次最多上传 {MAX_SUBMISSION_FILE_COUNT} 个附件"})
    saved = []
    for uploaded in files:
        name = uploaded.name or ""
        suffix = Path(name).suffix.lower()
        if suffix not in SUBMISSION_ALLOWED_EXTENSIONS:
            raise ValidationError({"attachments": f"不支持的附件格式：{name}"})
        if uploaded.size > MAX_SUBMISSION_FILE_SIZE:
            raise ValidationError({"attachments": "单个附件大小不能超过 20MB"})
        stored = default_storage.save(f"homework_submit/{uuid4().hex}{suffix}", uploaded)
        saved.append({
            "name": name,
            "size": uploaded.size,
            "type": uploaded.content_type or "",
            "url": default_storage.url(stored),
        })
    return saved


def _resolve_staged_files(items) -> list[dict]:
    """采纳学生端即时上传的暂存附件：仅允许 homework_submit/ 前缀且文件真实存在。

    大小以存储中的实际文件为准，防止客户端谎报；孤儿暂存文件由
    cleanup_submission_staging 管理命令清理。
    """
    prefix = f"{settings.MEDIA_URL}homework_submit/"
    resolved = []
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError({"uploaded": "附件信息不合法"})
        url = str(item.get("url") or "")
        if not url.startswith(prefix):
            raise ValidationError({"uploaded": "附件地址不合法"})
        name = url[len(settings.MEDIA_URL):]
        if not default_storage.exists(name):
            raise ValidationError({"uploaded": "附件不存在或已过期，请重新选择"})
        try:
            size = default_storage.size(name)
        except OSError:
            raise ValidationError({"uploaded": "附件读取失败，请重新选择"})
        if size > MAX_SUBMISSION_FILE_SIZE:
            raise ValidationError({"uploaded": "单个附件大小不能超过 20MB"})
        resolved.append({
            "name": Path(str(item.get("name") or name)).name,
            "size": size,
            "type": str(item.get("type") or ""),
            "url": url,
        })
    return resolved


class HomeworkViewSet(BaseModelViewSet):
    serializer_class = HomeworkSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "classroom", "status", "mode"]

    def get_queryset(self):
        user = self.request.user
        qs = Homework.objects.select_related("course", "classroom").prefetch_related("questions")
        if user.is_authenticated and user.is_student:
            # 学籍门控（方案 §5.4）：休学即停学，不给作业清单；毕业生仍看历史作业
            # （提交入口另拦，见 HomeworkSubmissionViewSet.create）。
            blocked = student_study_block_detail(user)
            if blocked:
                return qs.none()
            # 只看当前占用班级的作业：转班后旧班作业从待办消失（与课程列表一致），
            # 已交记录仍在「提交记录」可见（submission 侧按学生本人过滤，不按班）。
            qs = qs.filter(
                classroom__students__student=user,
                classroom__students__learn_status__in=ClassStudent.OCCUPYING_STATUSES,
                status=Homework.Status.PUBLISHED,
            )
        elif user.is_authenticated and user.is_teacher:
            # 锚点是课程负责人（作业属于某门课在某班的投放）
            qs = qs.filter(course__teacher=user)
        return qs.distinct()

    def _notify_if_published(self, instance, previous_status):
        """作业首次进入「已发布」状态时通知班级学生。"""
        if instance.status != Homework.Status.PUBLISHED or previous_status == Homework.Status.PUBLISHED:
            return
        from apps.users.models import notify_class_students

        notify_class_students(
            instance.classroom,
            ntype="homework",
            title=f"新作业发布：{instance.title}",
            content=f"《{instance.course.name}》发布了新作业「{instance.title}」，请及时完成。",
            link=f"/student/courses/{instance.course_id}/homework",
        )

    def perform_create(self, serializer):
        instance = serializer.save()
        self._notify_if_published(instance, None)

    def perform_update(self, serializer):
        previous = serializer.instance.status
        instance = serializer.save()
        self._notify_if_published(instance, previous)

    def perform_destroy(self, instance):
        # HomeworkAnswer 对题目为 PROTECT 外键，先清理各题作答记录再删除作业
        HomeworkAnswer.objects.filter(homework_question__homework=instance).delete()
        super().perform_destroy(instance)

    @action(detail=True, methods=["post", "delete"], url_path="attachments")
    def attachments(self, request, pk=None):
        """作业附件管理：POST 上传（追加，支持多文件，不替换原有附件）/ DELETE 按 url 移除单个。

        注意：DRF 每个 action 生成一条独立路由，同 url_path 的多个动作会因
        Django 首条匹配而 405，故上传与移除必须合并为同一 action。
        权限继承 ViewSet（IsTeacherOrReadOnly + get_queryset 行级过滤）。
        """
        homework = self.get_object()
        if request.method == "DELETE":
            url = str(request.data.get("url") or "").strip()
            if not url:
                raise ValidationError({"url": "缺少要移除的附件地址"})
            remaining, removed = [], None
            for item in homework.attachments:
                if removed is None and item.get("url") == url:
                    removed = item
                else:
                    remaining.append(item)
            if removed is None:
                return api_response(message="附件不存在或已被移除", code=400, status=400)
            homework.attachments = remaining
            homework.save(update_fields=["attachments", "updated_at"])
            _delete_media_file(removed.get("url"))
            return api_response(message="附件已移除")

        files = request.FILES.getlist("attachments") or request.FILES.getlist("attachment")
        if not files:
            raise ValidationError({"attachments": "请选择要上传的附件"})
        if len(homework.attachments) + len(files) > MAX_HOMEWORK_ATTACHMENT_COUNT:
            raise ValidationError({"attachments": f"作业附件最多 {MAX_HOMEWORK_ATTACHMENT_COUNT} 个"})
        # 先全部校验再落盘，避免部分失败留下孤儿文件
        for uploaded in files:
            if Path(uploaded.name).suffix.lower() not in HOMEWORK_ATTACHMENT_ALLOWED_EXTENSIONS:
                raise ValidationError({"attachments": f"不支持的附件格式：{uploaded.name}"})
            if uploaded.size > MAX_HOMEWORK_ATTACHMENT_SIZE:
                raise ValidationError({"attachments": "单个附件大小不能超过 20MB"})
        added = []
        for uploaded in files:
            suffix = Path(uploaded.name).suffix.lower()
            stored = default_storage.save(f"homework/{uuid4().hex}{suffix}", uploaded)
            added.append({
                "name": Path(uploaded.name).name,
                "size": uploaded.size,
                "type": uploaded.content_type or "",
                "url": default_storage.url(stored),
            })
        homework.attachments = [*homework.attachments, *added]
        homework.save(update_fields=["attachments", "updated_at"])
        return api_response(
            {"added": added, "attachments": homework.attachments},
            message=f"已上传 {len(added)} 个附件",
        )

    @action(detail=True, methods=["get"], url_path="attachments/preview")
    def preview_attachment(self, request, pk=None):
        """把作业附件中的 PDF 逐页渲染为图片，供前端无工具栏连续滚动预览。

        页图目录按存储文件名哈希派生：文件名 uuid 化后内容不可变，可安全缓存复用。
        """
        homework = self.get_object()
        url = str(request.query_params.get("url") or "").strip()
        item = next((a for a in homework.attachments if a.get("url") == url), None)
        if item is None:
            raise ValidationError({"url": "附件不存在或已被移除，请刷新后重试"})
        if Path(url).suffix.lower() != ".pdf":
            raise ValidationError({"url": "仅 PDF 附件支持在线预览"})
        if not url.startswith(settings.MEDIA_URL):
            raise ValidationError({"url": "附件地址不合法"})
        name = url[len(settings.MEDIA_URL):]
        if not default_storage.exists(name):
            raise ValidationError({"url": "附件文件缺失，请重新上传"})

        digest = hashlib.sha256(name.encode()).hexdigest()[:16]
        rel_dir = Path("homework_preview") / digest
        out_dir = Path(settings.MEDIA_ROOT) / rel_dir
        cached = sorted(out_dir.glob("slide-*.png")) if out_dir.exists() else []
        if cached:
            page_urls = [_media_url(rel_dir / page.name) for page in cached]
        else:
            try:
                file_path = default_storage.path(name)
            except NotImplementedError:
                raise ValidationError({"url": "当前存储不支持在线预览"})
            import pypdfium2 as pdfium

            try:
                pdf = pdfium.PdfDocument(file_path)
            except Exception:
                raise ValidationError({"url": "PDF 解析失败，无法预览"})
            try:
                if len(pdf) > MAX_PREVIEW_PAGES:
                    raise ValidationError({"url": f"PDF 超过 {MAX_PREVIEW_PAGES} 页，请下载后查看"})
            finally:
                pdf.close()
            out_dir.mkdir(parents=True, exist_ok=True)
            rendered = render_pdf_to_images(file_path, out_dir, rel_dir)
            if not rendered:
                raise ValidationError({"url": "PDF 渲染失败，请下载后查看"})
            page_urls = [rendered[key] for key in sorted(rendered)]
        return api_response({"pages": page_urls, "name": item.get("name", "")}, message="预览已就绪")

    @action(detail=True, methods=["get"], url_path="stats", permission_classes=[IsTeacher])
    def stats(self, request, pk=None):
        """作业统计（对齐考试统计 T-E-07）：发布后全员提交/完成情况分析。

        总览（应交/已交/未交、逾期、待批改、均分、及格率、优秀率）、
        总分分段分布、逐题得分与选项分布（题库作业）、全班提交与成绩排名。
        权限同作业管理（本班教师）。
        """
        homework = self.get_object()
        return api_response(build_homework_stats(homework))


class HomeworkSubmissionViewSet(BaseModelViewSet):
    serializer_class = HomeworkSubmissionSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["homework", "student", "correct_status"]

    def get_queryset(self):
        user = self.request.user
        qs = HomeworkSubmission.objects.select_related("student", "homework").prefetch_related(
            "answer_items__homework_question"
        )
        if user.is_authenticated and user.is_student:
            qs = qs.filter(student=user)
        elif user.is_authenticated and user.is_teacher:
            qs = qs.filter(homework__course__teacher=user)
        return qs

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """学生交作业；题库作业逐题留痕并自动批改客观题。"""
        if not request.user.is_student:
            raise PermissionDenied("仅学生可提交作业")
        # 学籍门控（方案 §5.4）：毕业/休学/退学不能提交。毕业生看得到历史作业，
        # 但提交入口关闭——统计窗口随学期关闭，补交只会污染完成率。
        blocked = student_submit_block_detail(request.user, "提交作业")
        if blocked:
            raise PermissionDenied(blocked)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        homework = serializer.validated_data["homework"]
        if homework.status != Homework.Status.PUBLISHED:
            raise ValidationError({"homework": "作业尚未发布"})
        if homework.start_time and timezone.now() < homework.start_time:
            raise ValidationError({"homework": "作业尚未开始"})
        # 成员校验收紧到占用关系：转班学生旧班作业不能再交（与作业列表口径一致）
        if not homework.classroom.students.filter(
            student=request.user, learn_status__in=ClassStudent.OCCUPYING_STATUSES
        ).exists():
            raise PermissionDenied("你不在该作业所属班级中")

        answers = serializer.validated_data.pop("answers", {}) or {}
        # 学生端即时上传的暂存附件引用（提交时采纳，不再随表单重复传文件）
        staged = serializer.validated_data.pop("uploaded", []) or []
        # 兼容 answers/uploaded 以 JSON 字符串提交（FormData 场景），避免 500
        if isinstance(answers, str):
            try:
                answers = json.loads(answers)
            except (TypeError, ValueError):
                answers = {}
        if not isinstance(answers, dict):
            answers = {}
        if isinstance(staged, str):
            try:
                staged = json.loads(staged)
            except (TypeError, ValueError):
                raise ValidationError({"uploaded": "附件信息不合法"})
        if not isinstance(staged, list):
            raise ValidationError({"uploaded": "附件信息不合法"})
        content = serializer.validated_data.get("content", "")
        attachment = serializer.validated_data.get("attachment")
        attachments = _save_submission_files(request.FILES.getlist("attachments"))
        attachments.extend(_resolve_staged_files(staged))
        if len(attachments) > MAX_SUBMISSION_FILE_COUNT:
            raise ValidationError({"attachments": f"一次最多上传 {MAX_SUBMISSION_FILE_COUNT} 个附件"})
        if homework.mode == Homework.Mode.ATTACHMENT and not str(content).strip() and not attachment and not attachments:
            raise ValidationError("请填写作业内容或上传附件")

        is_late = bool(homework.deadline and timezone.now() > homework.deadline)
        submission = serializer.save(
            student=request.user,
            is_late=is_late,
            objective_score=Decimal("0"),
            attachments=attachments,
        )

        if homework.mode == Homework.Mode.QUESTIONS:
            objective_total = Decimal("0")
            has_subjective = False
            for item in homework.questions.order_by("order", "id"):
                snapshot = item.snapshot or {}
                student_answer = answers.get(str(item.id), answers.get(item.id, {})) or {}
                qtype = snapshot.get("qtype")
                if qtype == Question.QType.SHORT:
                    is_correct, score = None, None
                    has_subjective = True
                else:
                    frozen_question = SimpleNamespace(
                        qtype=qtype,
                        answer=snapshot.get("answer") or {},
                        score=item.score,
                    )
                    is_correct, score = grade_objective(frozen_question, student_answer)
                    if score is None:
                        has_subjective = True
                    else:
                        objective_total += score

                HomeworkAnswer.objects.create(
                    submission=submission,
                    homework_question=item,
                    student_answer=student_answer,
                    is_correct=is_correct,
                    score=score,
                    graded_at=timezone.now() if score is not None else None,
                )
                if item.question_id:
                    AnswerRecord.objects.create(
                        student=request.user,
                        question_id=item.question_id,
                        scene=AnswerRecord.Scene.HOMEWORK,
                        scene_ref_id=homework.id,
                        student_answer=student_answer,
                        is_correct=is_correct,
                        score=score,
                    )

            submission.objective_score = objective_total
            submission.score = objective_total
            # 纯客观题作业无人工批改环节，提交即自动出分并发布成绩（学生可直接查看答案/解析/结果）
            submission.correct_status = (
                HomeworkSubmission.CorrectStatus.SUBMITTED
                if has_subjective
                else HomeworkSubmission.CorrectStatus.RETURNED
            )
            submission.save(update_fields=["objective_score", "score", "correct_status", "updated_at"])

        return api_response(
            self.get_serializer(submission).data,
            message=(
                "提交成功，客观题已自动批改，成绩已发布"
                if homework.mode == Homework.Mode.QUESTIONS
                and submission.correct_status == HomeworkSubmission.CorrectStatus.RETURNED
                else "提交成功，客观题已自动批改"
                if homework.mode == Homework.Mode.QUESTIONS
                else "提交成功"
            ),
            status=201,
        )

    @action(detail=False, methods=["post"], url_path="attachments", permission_classes=[IsStudent])
    def stage_attachments(self, request):
        """学生提交前即时上传附件到暂存目录（前端带进度展示）；提交时以 uploaded 字段引用。

        暂存文件未被提交引用时成为孤儿，由 cleanup_submission_staging 管理命令清理。
        """
        # 学籍门控：暂存是提交的前置动作，毕业生/休学生传了附件也提交不了，
        # 不如在入口就拦掉（方案 §5.4 精确拦截点明确包含 stage_attachments）。
        blocked = student_submit_block_detail(request.user, "上传作业附件")
        if blocked:
            raise PermissionDenied(blocked)
        files = request.FILES.getlist("attachments")
        if not files:
            raise ValidationError({"attachments": "请选择要上传的附件"})
        if len(files) > MAX_SUBMISSION_FILE_COUNT:
            raise ValidationError({"attachments": f"一次最多上传 {MAX_SUBMISSION_FILE_COUNT} 个附件"})
        # 先全部校验再落盘，避免部分失败留下孤儿文件
        for uploaded in files:
            name = uploaded.name or ""
            if Path(name).suffix.lower() not in SUBMISSION_ALLOWED_EXTENSIONS:
                raise ValidationError({"attachments": f"不支持的附件格式：{name}"})
            if uploaded.size > MAX_SUBMISSION_FILE_SIZE:
                raise ValidationError({"attachments": "单个附件大小不能超过 20MB"})
        saved = []
        for uploaded in files:
            name = uploaded.name or ""
            suffix = Path(name).suffix.lower()
            stored = default_storage.save(f"homework_submit/{uuid4().hex}{suffix}", uploaded)
            saved.append({
                "name": Path(name).name,
                "size": uploaded.size,
                "type": uploaded.content_type or "",
                "url": default_storage.url(stored),
            })
        return api_response({"added": saved}, message=f"已上传 {len(saved)} 个附件")

    @action(detail=True, methods=["post"], url_path="grade", permission_classes=[IsTeacher])
    @transaction.atomic
    def grade(self, request, pk=None):
        """教师批改附件作业或题库作业中的主观题。

        批改即发布（用户要求取消「已批改未发布」中间状态）：
        correct_status 直接置 RETURNED，学生即时可见成绩与答案/解析。
        """
        submission = self.get_object()
        homework = submission.homework

        if homework.mode == Homework.Mode.QUESTIONS:
            answer_scores = request.data.get("answer_scores", {}) or {}
            manual_items = submission.answer_items.select_related("homework_question").filter(
                homework_question__snapshot__qtype=Question.QType.SHORT
            )
            for answer_item in manual_items:
                data = answer_scores.get(str(answer_item.id), answer_scores.get(answer_item.id))
                if data is None:
                    if answer_item.score is None:
                        raise ValidationError({"answer_scores": "请完成所有主观题评分"})
                    continue
                raw_score = data.get("score") if isinstance(data, dict) else data
                try:
                    score = Decimal(str(raw_score))
                except (InvalidOperation, TypeError):
                    raise ValidationError({"answer_scores": "主观题分值格式不正确"})
                if score < 0 or score > answer_item.homework_question.score:
                    raise ValidationError({"answer_scores": "主观题得分不能超过题目分值"})
                answer_item.score = score
                answer_item.comment = data.get("comment", "") if isinstance(data, dict) else ""
                answer_item.graded_at = timezone.now()
                answer_item.save(update_fields=["score", "comment", "graded_at", "updated_at"])
                if answer_item.homework_question.question_id:
                    AnswerRecord.objects.filter(
                        student=submission.student,
                        question_id=answer_item.homework_question.question_id,
                        scene=AnswerRecord.Scene.HOMEWORK,
                        scene_ref_id=homework.id,
                    ).order_by("-id").update(score=score)

            if manual_items.filter(score__isnull=True).exists():
                raise ValidationError({"answer_scores": "请完成所有主观题评分"})
            total = submission.answer_items.aggregate(total=Sum("score"))["total"] or Decimal("0")
            submission.score = total
        else:
            try:
                score = Decimal(str(request.data.get("score")))
            except (InvalidOperation, TypeError):
                raise ValidationError({"score": "请输入有效分数"})
            if score < 0 or score > homework.total_score:
                raise ValidationError({"score": "得分不能超过作业总分"})
            submission.score = score

        submission.comment = request.data.get("comment", submission.comment)
        # 批改即发布：不再有「已批改未发布」中间状态
        submission.correct_status = HomeworkSubmission.CorrectStatus.RETURNED
        submission.save(update_fields=["score", "comment", "correct_status", "updated_at"])
        # get_object 带过 prefetch_related，上面逐题 save 后缓存里还是批改前的旧对象，
        # 直接序列化会把旧分值/旧评语返回给前端；清掉缓存让响应反映最新批改结果
        if hasattr(submission, "_prefetched_objects_cache"):
            submission._prefetched_objects_cache.pop("answer_items", None)
        return api_response(self.get_serializer(submission).data, message="批改完成")

    @action(detail=True, methods=["post"], url_path="release", permission_classes=[IsTeacher])
    def release(self, request, pk=None):
        """发布单个学生的批改结果（需求 T-H-05）。仅已批改的可发布。"""
        submission = self.get_object()
        if submission.correct_status == HomeworkSubmission.CorrectStatus.RETURNED:
            return api_response(self.get_serializer(submission).data, message="成绩已发布")
        if submission.correct_status != HomeworkSubmission.CorrectStatus.GRADED:
            return api_response(message="请先完成批改再发布成绩", code=400, status=400)
        submission.correct_status = HomeworkSubmission.CorrectStatus.RETURNED
        submission.save(update_fields=["correct_status", "updated_at"])
        return api_response(self.get_serializer(submission).data, message="成绩已发布")

    @action(detail=False, methods=["post"], url_path="release-all", permission_classes=[IsTeacher])
    def release_all(self, request):
        """按作业批量发布所有已批改提交的成绩（需求 T-H-05）。"""
        homework_id = request.data.get("homework")
        if not homework_id:
            return api_response(message="缺少 homework 参数", code=400, status=400)
        qs = HomeworkSubmission.objects.filter(
            homework_id=homework_id,
            homework__course__teacher=request.user,
            correct_status=HomeworkSubmission.CorrectStatus.GRADED,
        )
        count = qs.update(correct_status=HomeworkSubmission.CorrectStatus.RETURNED)
        return api_response({"released": count}, message=f"已发布 {count} 份成绩")
