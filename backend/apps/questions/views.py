from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.ai.services import generate_questions
from apps.common.permissions import IsStudent, IsTeacher, IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet

from .grading import grade_objective
from .models import AnswerRecord, Question
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
        qs = Question.objects.all()
        user = self.request.user
        # 学生只见已发布题目（用于章节练习）
        if user.is_authenticated and user.is_student:
            qs = qs.filter(status=Question.Status.PUBLISHED)
        return qs

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
        results, total, correct = [], 0, 0
        q_map = {q.id: q for q in Question.objects.filter(id__in=[int(k) for k in answers.keys()])}
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
                catalog_id=catalog_id,
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
    filterset_fields = ["scene", "question", "student"]

    def get_queryset(self):
        user = self.request.user
        qs = AnswerRecord.objects.select_related("question")
        if user.is_authenticated and user.is_student:
            qs = qs.filter(student=user)
        return qs

    def create(self, request, *args, **kwargs):
        """学生提交章节练习答案，客观题即时自动评分（需求 S-Q-01/02）。"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data["question"]
        student_answer = serializer.validated_data.get("student_answer", {})
        is_correct, score = grade_objective(question, student_answer)
        record = serializer.save(student=request.user, is_correct=is_correct, score=score)
        return api_response(
            AnswerRecordSerializer(record).data, message="提交成功", status=201
        )
