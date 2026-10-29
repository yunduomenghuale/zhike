from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated

from apps.common.access import is_platform_admin
from apps.common.permissions import IsTeacher, IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet
from apps.questions.models import Question

from .composer import compose_manual, compose_random
from .models import Exam, ExamLog, ExamSubmission, Paper
from .stats import build_exam_stats
from .resolver import (
    build_for_review,
    build_for_taking,
    build_layout,
    layout_matches,
    score_for_item,
    unmap_student_answer,
)
from .serializers import (
    ExamLogSerializer,
    ExamSerializer,
    ExamSubmissionSerializer,
    PaperSerializer,
)


class ExamViewSet(BaseModelViewSet):
    serializer_class = ExamSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "classroom", "status"]

    def get_queryset(self):
        user = self.request.user
        qs = Exam.objects.select_related("classroom").prefetch_related("papers")
        if getattr(user, "is_student", False):
            # 学生可见：已发布且在读班级的考试 + 本人有答卷的考试。
            # 教师结束考试（finished）或过期后，已交卷学生仍能回看自己的考试记录与成绩。
            qs = qs.filter(
                Q(
                    status=Exam.Status.PUBLISHED,
                    classroom__students__student=user,
                    classroom__students__learn_status="active",
                )
                | Q(submissions__student=user)
            ).distinct()
        elif getattr(user, "is_teacher", False):
            # 锚点是课程负责人；班级维度只看「该课是否挂在这个班」，不看建班人
            qs = qs.filter(course__teacher=user)
        elif not is_platform_admin(user):
            qs = qs.none()
        return qs.distinct()

    def _notify_if_published(self, instance, previous_status):
        """考试首次进入「已发布」状态时通知班级学生。"""
        if instance.status != Exam.Status.PUBLISHED or previous_status == Exam.Status.PUBLISHED:
            return
        from apps.users.models import notify_class_students

        notify_class_students(
            instance.classroom,
            ntype="exam",
            title=f"新考试发布：{instance.name}",
            content=f"《{instance.course.name}》发布了新考试「{instance.name}」，请按时参加。",
            link=f"/student/courses/{instance.course_id}/exams",
        )

    def _ensure_composed(self, exam):
        """发布前必须完成组卷：至少一套含题目的试卷（需求：发布前必须组卷）。"""
        if not any(p.question_items for p in exam.papers.all()):
            raise ValidationError("发布前必须先完成组卷")

    def perform_create(self, serializer):
        # 考试必须先建草稿再组卷，不允许创建时直接发布
        if serializer.validated_data.get("status") == Exam.Status.PUBLISHED:
            raise ValidationError("请先创建草稿，完成组卷后再发布")
        instance = serializer.save()
        self._notify_if_published(instance, None)

    def perform_update(self, serializer):
        previous = serializer.instance.status
        incoming = serializer.validated_data.get("status", previous)
        if incoming == Exam.Status.PUBLISHED and previous != Exam.Status.PUBLISHED:
            self._ensure_composed(serializer.instance)
        instance = serializer.save()
        self._notify_if_published(instance, previous)

    @action(detail=True, methods=["post"], url_path="compose", permission_classes=[IsTeacher])
    def compose(self, request, pk=None):
        """随机 / 手动组卷（需求 T-E-02 / T-E-03 / 8.2）。"""
        exam = self.get_object()
        if exam.status != Exam.Status.DRAFT:
            raise ValidationError("考试发布后不能重新组卷")
        mode = request.data.get("mode", "random")
        try:
            if mode == "manual":
                raw_questions = request.data.get("questions", [])
                if not isinstance(raw_questions, list) or not raw_questions:
                    raise ValidationError({"questions": "请至少选择一道题目"})
                question_ids = [int(item["question_id"]) for item in raw_questions]
                if len(question_ids) != len(set(question_ids)):
                    raise ValidationError({"questions": "同一道题不能重复添加"})
                if any(Decimal(str(item.get("score", 5))) <= 0 for item in raw_questions):
                    raise ValidationError({"questions": "题目分值必须大于 0"})
                allowed = Question.objects.filter(
                    id__in=question_ids,
                    course=exam.course,
                    status=Question.Status.PUBLISHED,
                ).count()
                if allowed != len(question_ids):
                    raise ValidationError({"questions": "包含其他课程、未发布或不存在的题目"})
                items, total = compose_manual(raw_questions)
            elif mode == "random":
                items, total = compose_random(exam.course_id, request.data.get("rules", []))
            else:
                raise ValidationError({"mode": "组卷模式不正确"})
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ValidationError("组卷参数格式不正确") from exc
        if not items or total <= 0:
            raise ValidationError("没有选出有效题目，请检查组卷规则和题目分值")

        exam.papers.all().delete()
        paper = Paper.objects.create(
            course_id=exam.course_id,
            exam=exam,
            mode=mode,
            question_items=items,
            total_score=total,
        )
        exam.total_score = total
        exam.save(update_fields=["total_score", "updated_at"])
        return api_response(PaperSerializer(paper).data, message=f"组卷完成，共 {len(items)} 题")

    @action(detail=True, methods=["get"], url_path="paper", permission_classes=[IsTeacher])
    def paper_detail(self, request, pk=None):
        """查看试卷（只读）：组卷后、发布后均可查看；发布后不可再组卷。"""
        exam = self.get_object()
        papers = list(exam.papers.all())
        paper = next((p for p in papers if p.student_id is None), None)
        if paper is None and papers:
            paper = papers[0]
        if paper is None:
            return api_response(message="尚未组卷", code=404, status=404)
        items = sorted(paper.question_items or [], key=lambda x: x.get("order", 0))
        q_map = {q.id: q for q in Question.objects.filter(id__in=[i["question_id"] for i in items])}
        questions = []
        for idx, item in enumerate(items):
            q = q_map.get(item["question_id"])
            questions.append({
                "order": idx + 1,
                "question_id": item["question_id"],
                "score": item.get("score"),
                "stem": q.stem if q else "（题目已删除）",
                "image_url": (f"/media/{q.image.name}" if q.image else "") if q else "",
                "qtype": q.qtype if q else "",
                "qtype_display": q.get_qtype_display() if q else "-",
                "difficulty": q.difficulty if q else "",
                "difficulty_display": q.get_difficulty_display() if q else "-",
                # 完整题目信息：供教师端「查看试卷」hover 详情与组卷界面回填使用
                "options": q.options if q else [],
                "answer": q.answer if q else None,
                "analysis": q.analysis if q else "",
            })
        return api_response({
            "mode": paper.mode,
            "mode_display": paper.get_mode_display(),
            "total_score": str(paper.total_score),
            "per_student": bool(paper.student_id),
            "questions": questions,
        })

    @action(detail=True, methods=["get"], url_path="monitor", permission_classes=[IsTeacher])
    def monitor(self, request, pk=None):
        """考试监控：各学生答卷状态（需求 T-E-06）。"""
        exam = self.get_object()
        subs = exam.submissions.select_related("student")
        return api_response(ExamSubmissionSerializer(subs, many=True, context={"request": request}).data)

    @action(detail=True, methods=["get"], url_path="stats", permission_classes=[IsTeacher])
    def stats(self, request, pk=None):
        """考试统计（需求 T-E-07）：考后全员答题情况分析。

        总览（应考/交卷/缺考、均分、及格率、优秀率）、总分分段分布、
        逐题得分与选项分布、全班成绩排名。权限同 monitor（本班本校教师）。
        """
        exam = self.get_object()
        return api_response(build_exam_stats(exam))

    @action(detail=True, methods=["post"], url_path="release-scores", permission_classes=[IsTeacher])
    def release_scores(self, request, pk=None):
        """统一出分：发布本场考试所有已完成批改的答卷成绩（需求 T-E-04）。

        返回发布数量与因主观题未批改而跳过的学生名单。
        """
        exam = self.get_object()
        subs = list(exam.submissions.select_related("student", "paper").filter(
            status__in=[ExamSubmission.Status.SUBMITTED, ExamSubmission.Status.TIMEOUT],
        ))
        short_qids_by_paper = {}
        for sub in subs:
            if sub.paper_id and sub.paper_id not in short_qids_by_paper:
                items = sub.paper.question_items or []
                qtypes = Question.objects.filter(
                    id__in=[i["question_id"] for i in items]
                ).values("id", "qtype")
                short_qids_by_paper[sub.paper_id] = {
                    str(q["id"]) for q in qtypes if q["qtype"] == Question.QType.SHORT
                }
        released, skipped = 0, []
        for sub in subs:
            need = short_qids_by_paper.get(sub.paper_id, set())
            graded = set((sub.subjective_scores or {}).keys())
            if need - graded:
                skipped.append(sub.student.real_name or sub.student.username)
                continue
            if not sub.score_released:
                sub.score_released = True
                sub.save(update_fields=["score_released", "updated_at"])
            released += 1
        return api_response(
            {"released": released, "skipped": skipped},
            message=f"已发布 {released} 份成绩" + (f"，{len(skipped)} 份因主观题未批改被跳过" if skipped else ""),
        )


class ExamSubmissionViewSet(BaseModelViewSet):
    serializer_class = ExamSubmissionSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["exam", "student", "status"]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs = ExamSubmission.objects.select_related("student", "exam")
        if getattr(user, "is_student", False):
            qs = qs.filter(student=user)
        elif getattr(user, "is_teacher", False):
            qs = qs.filter(exam__course__teacher=user)
        elif not is_platform_admin(user):
            qs = qs.none()
        return qs

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed("POST", detail="请使用 start 接口开始考试")

    @action(detail=False, methods=["post"], url_path="start")
    @transaction.atomic
    def start(self, request):
        """学生开始考试，分配试卷（需求 S-E-02）。"""
        if not request.user.is_student:
            raise PermissionDenied("仅学生可开始考试")
        exam_id = request.data.get("exam")
        exam = get_object_or_404(
            Exam.objects.filter(
                status=Exam.Status.PUBLISHED,
                classroom__students__student=request.user,
                classroom__students__learn_status="active",
            ).distinct(),
            id=exam_id,
        )
        now = timezone.now()
        if exam.start_at and now < exam.start_at:
            return api_response(message="考试尚未开始", code=400, status=400)
        if exam.end_at and now > exam.end_at:
            return api_response(message="考试已结束", code=400, status=400)
        # per_student_paper：优先取学生专属卷，否则取共用卷
        paper = (
            exam.papers.filter(student=request.user).first()
            or exam.papers.filter(student__isnull=True).first()
        )
        if not paper:
            raise ValidationError("考试尚未完成组卷，请联系教师")
        sub, created = ExamSubmission.objects.select_for_update().get_or_create(
            exam=exam,
            student=request.user,
            defaults={"paper": paper, "started_at": now, "status": ExamSubmission.Status.IN_PROGRESS},
        )
        if not created and sub.status in (
            ExamSubmission.Status.SUBMITTED,
            ExamSubmission.Status.TIMEOUT,
        ):
            if not exam.allow_resubmit:
                raise ValidationError("本次考试已经提交，不能重复作答")
            sub.answers = {}
            sub.submitted_at = None
            sub.objective_score = None
            sub.total_score = None
            sub.subjective_scores = {}
            sub.score_released = False
            sub.abnormal = False
            # 重交 = 新一轮作答，乱序重新生成（保存时清掉，下方重建）
            sub.question_layout = {}
        if created or sub.status != ExamSubmission.Status.IN_PROGRESS or sub.started_at is None:
            sub.started_at = now
            sub.status = ExamSubmission.Status.IN_PROGRESS
            sub.paper = paper
            sub.save()
        # 题目/选项乱序在开始考试时生成并固化：刷新/误关/重进都按同一顺序作答，
        # 不再重排（教师改组卷导致题目集合变化时才会重新生成）
        items = paper.question_items or []
        if not layout_matches(sub.question_layout, items):
            q_map = {q.id: q for q in Question.objects.filter(id__in=[i["question_id"] for i in items])}
            sub.question_layout = build_layout(items, q_map, exam)
            sub.save(update_fields=["question_layout", "updated_at"])
        # 交卷截止时间 = 开始时间 + 考试时长（且不晚于考试结束时间）。
        # 重开/刷新/误关页面都从服务端 started_at 续算剩余时间，避免前端重置倒计时。
        deadline = sub.started_at + timedelta(minutes=exam.duration)
        if exam.end_at:
            deadline = min(deadline, exam.end_at)
        remaining_seconds = max(0, int((deadline - now).total_seconds()))
        return api_response(
            {
                "submission": ExamSubmissionSerializer(
                    sub, context={"request": request}
                ).data,
                "questions": build_for_taking(paper, exam, sub.question_layout),
                "anti_cheat": exam.anti_cheat,
                "duration": exam.duration,
                "remaining_seconds": remaining_seconds,
            },
            message="考试已开始",
        )

    @action(detail=True, methods=["post"], url_path="save")
    def save(self, request, pk=None):
        """保存答案（不提交）：考试中途暂存作答，刷新/重进后回填继续答。

        仅更新 answers 与 saved_at：不算分、不改状态、不动开始时间；
        超过截止时间后不再接受保存（此时应直接交卷）。
        """
        if not request.user.is_student:
            raise PermissionDenied("仅学生可保存答卷")
        sub = self.get_object()
        if sub.status != ExamSubmission.Status.IN_PROGRESS or not sub.started_at:
            raise ValidationError("答卷不在作答状态，不能保存")
        answers = request.data.get("answers")
        if not isinstance(answers, dict):
            raise ValidationError({"answers": "答案格式不正确"})
        now = timezone.now()
        deadlines = [sub.started_at + timedelta(minutes=sub.exam.duration)]
        if sub.exam.end_at:
            deadlines.append(sub.exam.end_at)
        if now > min(deadlines):
            return api_response(message="考试时间已到，请直接交卷", code=400, status=400)
        sub.answers = answers
        sub.saved_at = now
        sub.save(update_fields=["answers", "saved_at", "updated_at"])
        return api_response(
            ExamSubmissionSerializer(sub, context={"request": request}).data,
            message="答案已保存",
        )

    @action(detail=True, methods=["get"], url_path="review")
    def review(self, request, pk=None):
        """考后回看答卷与解析（需求 S-E-05）。

        交卷即可查看，不再要求教师统一出分或考试结束：
        - 客观题：正确答案/解析/得分即时可见
        - 主观题：展示正确答案与学生作答，得分按批改进度可见
          （已批阅的题出分，未批阅显示待批阅；全部批阅或统一出分后可见总分）
        - 「结束后展示解析」开关仅控制解析文本，不影响答案与分数
        """
        sub = self.get_object()
        if sub.student_id != request.user.id:
            return api_response(message="无权查看", code=403, status=403)
        if sub.status not in (
            ExamSubmission.Status.SUBMITTED,
            ExamSubmission.Status.TIMEOUT,
        ):
            return api_response(message="交卷后才能查看", code=400, status=400)
        return api_response(
            {
                "submission": ExamSubmissionSerializer(
                    sub, context={"request": request}
                ).data,
                "questions": build_for_review(sub.paper, sub, sub.exam),
                "score_released": sub.score_released,
                # 本场考试是否发生过选项乱序（答卷固化的 layout 含选项 perm）。
                # 回看按原题顺序展示（S4），前端据此提示学生顺序可能与考试时不同。
                # 注：random.shuffle 有极小概率产出恒等排列，此处按 perm 存在性判断，
                # 提示文案为「可能不同」，恒等排列时多一句提示无实质影响。
                "options_shuffled": bool(
                    (getattr(sub, "question_layout", None) or {}).get("options")
                ),
            }
        )

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        """交卷：客观题自动评分，主观题留待教师批改（需求 S-E-04 / T-E-07）。"""
        if not request.user.is_student:
            raise PermissionDenied("仅学生可提交答卷")
        sub = self.get_object()
        if sub.status != ExamSubmission.Status.IN_PROGRESS or not sub.started_at:
            raise ValidationError("答卷不在作答状态，请先开始考试")
        if not sub.paper:
            raise ValidationError("答卷未分配试卷，请联系教师")
        answers = request.data.get("answers", sub.answers)
        if not isinstance(answers, dict):
            raise ValidationError({"answers": "答案格式不正确"})
        now = timezone.now()
        deadlines = [sub.started_at + timedelta(minutes=sub.exam.duration)]
        if sub.exam.end_at:
            deadlines.append(sub.exam.end_at)
        timeout = now > min(deadlines)

        objective_total = Decimal("0")
        items = sub.paper.question_items if sub.paper else []
        q_map = {q.id: q for q in Question.objects.filter(id__in=[i["question_id"] for i in items])}
        option_perms = (sub.question_layout or {}).get("options") or {}
        for item in items:
            q = q_map.get(item["question_id"])
            if not q:
                continue
            stu_ans = answers.get(str(q.id)) or answers.get(q.id) or {}
            # 选项乱序时学生答案存于展示 key 空间，先还原回题库原始 key 再判分
            perm = option_perms.get(str(q.id))
            if perm:
                stu_ans = unmap_student_answer(stu_ans, perm, q.options or [])
            # 按试卷题目分值折算（题库分值与试卷分值可能不同）；主观题不自动评分
            _, score = score_for_item(q, item.get("score", q.score), stu_ans)
            if score is not None:
                objective_total += score

        sub.answers = answers
        sub.objective_score = objective_total
        sub.total_score = objective_total  # 含主观题时，教师批改后再累加
        sub.submitted_at = now
        sub.status = ExamSubmission.Status.TIMEOUT if timeout else ExamSubmission.Status.SUBMITTED
        sub.save()
        return api_response(
            ExamSubmissionSerializer(sub, context={"request": request}).data,
            message="交卷成功",
        )

    def _subjective_items(self, sub):
        """返回答卷试卷中的主观题（题目、卷面分值、学生答案）。"""
        items = sub.paper.question_items if sub.paper else []
        q_map = {q.id: q for q in Question.objects.filter(id__in=[i["question_id"] for i in items])}
        result = []
        answers = sub.answers or {}
        for item in sorted(items, key=lambda x: x.get("order", 0)):
            q = q_map.get(item["question_id"])
            if not q or q.qtype != Question.QType.SHORT:
                continue
            result.append({
                "question_id": q.id,
                "order": item.get("order", 0),
                "score": str(item.get("score", q.score)),
                "stem": q.stem,
                "image_url": f"/media/{q.image.name}" if q.image else "",
                "reference_answer": q.answer,
                "analysis": q.analysis,
                "student_answer": answers.get(str(q.id)) or answers.get(q.id) or {},
            })
        return result

    @action(detail=True, methods=["get"], url_path="grading-detail", permission_classes=[IsTeacher])
    def grading_detail(self, request, pk=None):
        """教师查看答卷明细，用于批改（需求 T-E-07）。

        返回主观题待批列表 + 全卷作答回看（含标准答案与已得分），批改体验与作业一致。
        """
        sub = self.get_object()
        return api_response({
            "submission": ExamSubmissionSerializer(sub, context={"request": request}).data,
            "subjective_questions": self._subjective_items(sub),
            "subjective_scores": sub.subjective_scores or {},
            "answer_review": build_for_review(sub.paper, sub, sub.exam),
        })

    @action(detail=True, methods=["post"], url_path="grade", permission_classes=[IsTeacher])
    def grade(self, request, pk=None):
        """教师批改考试主观题并核算总分（需求 T-E-07）。

        参数：{"scores": {question_id: 得分}}，可多次提交直至全部主观题完成评分。
        """
        sub = self.get_object()
        if sub.status not in (ExamSubmission.Status.SUBMITTED, ExamSubmission.Status.TIMEOUT):
            return api_response(message="该答卷尚未提交，不能批改", code=400, status=400)

        subjective = self._subjective_items(sub)
        if not subjective:
            return api_response(message="该试卷没有主观题", code=400, status=400)

        full_map = {str(item["question_id"]): Decimal(str(item["score"])) for item in subjective}
        saved = {str(k): Decimal(str(v)) for k, v in (sub.subjective_scores or {}).items()}
        incoming = request.data.get("scores", {}) or {}
        for qid, raw in incoming.items():
            qid = str(qid)
            if qid not in full_map:
                return api_response(message=f"题目 {qid} 不是本卷主观题", code=400, status=400)
            try:
                score = Decimal(str(raw)).quantize(Decimal("0.1"))
            except Exception:
                return api_response(message="分值格式不正确", code=400, status=400)
            if score < 0 or score > full_map[qid]:
                return api_response(message=f"题目 {qid} 得分须在 0~{full_map[qid]} 之间", code=400, status=400)
            saved[qid] = score

        missing = [qid for qid in full_map if qid not in saved]
        sub.subjective_scores = {k: str(v) for k, v in saved.items()}
        if not missing:
            subjective_total = sum(saved.values(), Decimal("0"))
            sub.total_score = (sub.objective_score or Decimal("0")) + subjective_total
        sub.save(update_fields=["subjective_scores", "total_score", "updated_at"])
        return api_response(
            ExamSubmissionSerializer(sub, context={"request": request}).data,
            message="批改完成" if not missing else f"已保存，仍有 {len(missing)} 道主观题未评分",
        )

    @action(detail=True, methods=["post"], url_path="release", permission_classes=[IsTeacher])
    def release(self, request, pk=None):
        """发布单个学生成绩（统一出分，需求 T-E-04）。"""
        sub = self.get_object()
        if sub.status not in (ExamSubmission.Status.SUBMITTED, ExamSubmission.Status.TIMEOUT):
            return api_response(message="该答卷尚未提交", code=400, status=400)
        subjective = self._subjective_items(sub)
        graded = set((sub.subjective_scores or {}).keys())
        if any(str(item["question_id"]) not in graded for item in subjective):
            return api_response(message="尚有主观题未批改，不能发布成绩", code=400, status=400)
        sub.score_released = True
        sub.save(update_fields=["score_released", "updated_at"])
        return api_response(
            ExamSubmissionSerializer(sub, context={"request": request}).data,
            message="成绩已发布",
        )


class ExamLogViewSet(BaseModelViewSet):
    serializer_class = ExamLogSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["exam", "student", "action"]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs = ExamLog.objects.all()
        if getattr(user, "is_student", False):
            qs = qs.filter(student=user)
        elif getattr(user, "is_teacher", False):
            qs = qs.filter(exam__course__teacher=user)
        elif not is_platform_admin(user):
            qs = qs.none()
        return qs

    def create(self, request, *args, **kwargs):
        """前端上报防作弊行为日志（需求 T-E-05）。异常行为同时标记答卷。"""
        if not request.user.is_student:
            raise PermissionDenied("仅学生可上报考试行为")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        exam = serializer.validated_data["exam"]
        submission = ExamSubmission.objects.filter(
            exam=exam,
            student=request.user,
            status=ExamSubmission.Status.IN_PROGRESS,
        ).first()
        if not submission:
            raise PermissionDenied("考试未开始、已结束或无权访问")
        log = serializer.save(
            student=request.user,
            ip=request.META.get("REMOTE_ADDR", ""),
            device=request.META.get("HTTP_USER_AGENT", "")[:255],
        )
        ExamSubmission.objects.filter(pk=submission.pk).update(abnormal=True)
        return api_response(self.get_serializer(log).data, message="已记录", status=201)
