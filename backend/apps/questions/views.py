from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.ai.services import generate_questions
from apps.common.access import courses_for_user, is_platform_admin
from apps.common.permissions import IsStudent, IsTeacher, IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet
from django.db.models import Q
from apps.courses.models import Catalog

from .grading import grade_objective
from .models import AnswerRecord, Question, WrongMastery, WrongNote
from .serializers import (
    AnswerRecordSerializer,
    QuestionSerializer,
    StudentQuestionSerializer,
)


class QuestionViewSet(BaseModelViewSet):
    serializer_class = QuestionSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "catalog", "qtype", "difficulty", "status", "source"]
    search_fields = ["stem"]

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
                "correct_answer": q.answer,
                "analysis": q.analysis,
            })
        return api_response(
            {"total": total, "correct": correct, "results": results},
            message="练习提交完成",
        )

    @action(detail=False, methods=["post"], url_path="generate", permission_classes=[IsTeacher])
    def generate(self, request):
        """基于章节 PPT / 知识库自动生成题目（需求 T-Q-01）。

        生成结果为草稿，教师审核编辑后再发布。
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
        count = int(request.data.get("count", 5))
        qtype = request.data.get("qtype", "single")
        objective = request.data.get("objective", "")
        drafts = generate_questions(
            course_id=course_id, catalog_id=catalog_id, count=count, qtype=qtype, objective=objective
        )

        created = []
        for d in drafts:
            q = Question.objects.create(
                course_id=course_id,
                catalog=catalog,
                qtype=d.get("qtype", qtype),
                stem=d.get("stem", ""),
                options=d.get("options", []),
                answer=d.get("answer", {}),
                analysis=d.get("analysis", ""),
                difficulty=d.get("difficulty", "medium"),
                knowledge_tags=d.get("knowledge_tags", []),
                source=Question.Source.AI,
                status=Question.Status.DRAFT,
                creator=request.user,
            )
            created.append(q)
        return api_response(
            QuestionSerializer(created, many=True).data,
            message=f"已生成 {len(created)} 道题目（草稿），请审核后发布",
        )


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
