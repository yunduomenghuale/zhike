"""学习进度统计 / 学习预警 / 错题本（需求 T-L-01/02/03、S-Q-04）。

本模块无自有模型，纯聚合其它模块数据。
班级统计逻辑收敛在 services.build_class_stats（教师端督管与平台端督管共用）。
"""
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.views import APIView

from apps.classroom.models import ClassRoom, ClassStudent
from apps.common.permissions import IsStudent, IsTeacher
from apps.common.response import api_response
from apps.courses.models import Catalog
from apps.exams.models import Exam, ExamSubmission
from apps.homework.models import Homework, HomeworkSubmission
from apps.labs.models import Lab, LabSubmission
from apps.questions.models import AnswerRecord, Question

from .services import build_class_stats


class AnalyticsResponseSerializer(serializers.Serializer):
    """Schema marker for aggregation endpoints with dynamic response bodies."""

    code = serializers.IntegerField(read_only=True)
    message = serializers.CharField(read_only=True)
    data = serializers.JSONField(read_only=True)


def _resolve_classroom_course(request, class_id):
    """校验班级归属并解析课程参数。返回 (classroom, course, error_response)。"""
    classroom = ClassRoom.objects.filter(id=class_id, teacher=request.user).first()
    if not classroom:
        return None, None, api_response(message="班级不存在或无权查看", code=404, status=404)

    course_id = request.query_params.get("course")
    if course_id:
        course = classroom.courses.filter(id=course_id).first()
        if not course:
            return None, None, api_response(message="该课程未关联到此班级", code=400, status=400)
    else:
        course = classroom.courses.order_by("id").first()
        if not course:
            return None, None, api_response(message="该班级尚未关联课程", code=400, status=400)
    return classroom, course, None


class ClassStatsView(APIView):
    """班级学习统计 + 逐个学生进度 + 预警（需求 T-L-01/02/03）。"""

    permission_classes = [IsTeacher]
    serializer_class = AnalyticsResponseSerializer

    def get(self, request, class_id):
        classroom, course, error = _resolve_classroom_course(request, class_id)
        if error:
            return error
        return api_response(build_class_stats(classroom, course.id))


class ClassAIReportView(APIView):
    """AI 学情分析报告（异步，需求 T-L-04 延伸）。

    旧同步接口已直接切换（D5 定稿）：报告在后台线程分段生成（约 2-4 分钟），
    请求秒级返回 {task_id}，前端轮询 GET /api/ai-tasks/<id>/ 看阶段进度，
    完成后渲染 report + 学生卡片简评。

    频率限制（F6，DB 判定）：同班级 10 分钟内已有进行中/已完成的
    class_analytics 任务则拒绝（LLM 成本保护）；上一次失败允许立即重试。
    """

    permission_classes = [IsTeacher]
    serializer_class = AnalyticsResponseSerializer
    RATE_LIMIT_MINUTES = 10

    def post(self, request, class_id):
        from datetime import timedelta

        from apps.ai.models import AITask
        from apps.ai.tasks import submit_ai_task

        classroom, course, error = _resolve_classroom_course(request, class_id)
        if error:
            return error

        if not ClassStudent.objects.filter(classroom=classroom).exists():
            return api_response(message="班级暂无学生，无法生成分析", code=400, status=400)

        recent = AITask.objects.filter(
            task_type=AITask.TaskType.CLASS_ANALYTICS,
            classroom=classroom,
            created_at__gte=timezone.now() - timedelta(minutes=self.RATE_LIMIT_MINUTES),
        ).exclude(status=AITask.Status.FAILED).exists()
        if recent:
            return api_response(
                message="分析任务刚提交过，请稍后再试（10 分钟内限一次）",
                code=429,
                status=429,
            )

        task = submit_ai_task(
            AITask.TaskType.CLASS_ANALYTICS,
            user=request.user,
            classroom=classroom,
            course=course,
        )
        return api_response({"task_id": task.id})


class ClassStudentDetailView(APIView):
    """教师查看班级内单个学生的学习详情（练习/作业/考试/预警）。"""

    permission_classes = [IsTeacher]
    serializer_class = AnalyticsResponseSerializer

    def get(self, request, class_id, student_id):
        classroom, course, error = _resolve_classroom_course(request, class_id)
        if error:
            return error

        cs = (
            ClassStudent.objects.filter(classroom=classroom, student_id=student_id)
            .select_related("student")
            .first()
        )
        if not cs:
            return api_response(message="该学生不在此班级", code=404, status=404)
        stu = cs.student

        stats = build_class_stats(classroom, course.id)
        row = next((r for r in stats["students"] if r["student_id"] == stu.id), None)
        if row is None:
            return api_response(message="该学生不在此班级", code=404, status=404)

        homeworks = []
        for hw in Homework.objects.filter(
            classroom=classroom, course_id=course.id, status=Homework.Status.PUBLISHED
        ).order_by("id"):
            sub = HomeworkSubmission.objects.filter(homework=hw, student=stu).first()
            homeworks.append({
                "id": hw.id,
                "title": hw.title,
                "deadline": hw.deadline,
                "submitted": sub is not None,
                "score": float(sub.score) if sub and sub.score is not None else None,
                "correct_status": sub.get_correct_status_display() if sub else None,
                "is_late": sub.is_late if sub else False,
                "submitted_at": sub.submitted_at if sub else None,
            })

        exams = []
        for exam in Exam.objects.filter(
            classroom=classroom,
            course_id=course.id,
            status__in=[Exam.Status.PUBLISHED, Exam.Status.FINISHED],
        ).order_by("id"):
            sub = ExamSubmission.objects.filter(exam=exam, student=stu).first()
            taken = sub is not None and sub.status in (
                ExamSubmission.Status.SUBMITTED,
                ExamSubmission.Status.TIMEOUT,
            )
            exams.append({
                "id": exam.id,
                "name": exam.name,
                "taken": taken,
                "score": float(sub.total_score) if taken and sub.total_score is not None else None,
                "submitted_at": sub.submitted_at if taken else None,
            })

        # 学生实验明细（仿 exams 块）
        labs = []
        for lab in Lab.objects.filter(
            course_id=course.id, status=Lab.Status.PUBLISHED, schedules__classroom=classroom
        ).distinct().order_by("order", "id"):
            sub = LabSubmission.objects.filter(lab=lab, student=stu).first()
            done = sub is not None and sub.status == LabSubmission.Status.SUBMITTED
            labs.append({
                "id": lab.id,
                "title": lab.title,
                "status": sub.status if sub else None,
                "done": done,
                "score": float(sub.total_score) if done and sub.total_score is not None else None,
                "reviewed": sub.reviewed if sub else False,
                "submitted_at": sub.submitted_at if done else None,
            })

        recent = (
            AnswerRecord.objects.filter(
                student=stu, scene=AnswerRecord.Scene.PRACTICE, question__course_id=course.id
            )
            .select_related("question")
            .order_by("-submitted_at")[:8]
        )
        records = [
            {
                "question_id": ar.question_id,
                "stem": ar.question.stem[:60],
                "qtype": ar.question.get_qtype_display(),
                "is_correct": ar.is_correct,
                "submitted_at": ar.submitted_at,
            }
            for ar in recent
        ]

        # 章节学习进度：按顶层章节汇总题库覆盖（已练题数/章节题数）与正确率
        catalogs = list(Catalog.objects.filter(course_id=course.id))
        parent_of = {c.id: c.parent_id for c in catalogs}
        title_of = {c.id: c.title for c in catalogs}

        def root_id(cid):
            seen = set()
            while cid and parent_of.get(cid) and cid not in seen:
                seen.add(cid)
                cid = parent_of[cid]
            return cid

        q_total = {}
        for item in (
            Question.objects.filter(course_id=course.id, status="published")
            .values("catalog_id")
            .annotate(n=Count("id"))
        ):
            rid = root_id(item["catalog_id"])
            if rid:
                q_total[rid] = q_total.get(rid, 0) + item["n"]

        stat_of = {}
        for item in (
            AnswerRecord.objects.filter(
                student=stu, scene=AnswerRecord.Scene.PRACTICE, question__course_id=course.id
            )
            .values("question__catalog_id")
            .annotate(
                practiced=Count("question", distinct=True),
                total=Count("id"),
                correct=Count("id", filter=Q(is_correct=True)),
            )
        ):
            rid = root_id(item["question__catalog_id"])
            if not rid:
                continue
            agg = stat_of.setdefault(rid, {"practiced": 0, "total": 0, "correct": 0})
            agg["practiced"] += item["practiced"]
            agg["total"] += item["total"]
            agg["correct"] += item["correct"]

        chapters = []
        for c in sorted(catalogs, key=lambda x: (x.order, x.id)):
            if c.parent_id or not c.is_published:
                continue
            total_q = q_total.get(c.id, 0)
            stat = stat_of.get(c.id, {"practiced": 0, "total": 0, "correct": 0})
            chapters.append({
                "catalog_id": c.id,
                "title": title_of.get(c.id, ""),
                "questions_total": total_q,
                "questions_practiced": stat["practiced"],
                "coverage": round(stat["practiced"] / total_q * 100) if total_q else None,
                "accuracy": round(stat["correct"] / stat["total"] * 100) if stat["total"] else None,
            })

        sum_total = sum(ch["questions_total"] for ch in chapters)
        sum_practiced = sum(ch["questions_practiced"] for ch in chapters)
        progress = {
            "questions_total": sum_total,
            "questions_practiced": sum_practiced,
            "percent": round(sum_practiced / sum_total * 100) if sum_total else None,
            "chapters": chapters,
        }

        return api_response({
            "student": {
                "id": stu.id,
                "name": stu.real_name or stu.username,
                "username": stu.username,
                "avatar": stu.avatar,
                "joined_at": cs.joined_at,
            },
            "class_name": classroom.name,
            "course_id": course.id,
            "course_name": course.name,
            "summary": row,
            "progress": progress,
            "homeworks": homeworks,
            "exams": exams,
            "labs": labs,
            "recent_records": records,
        })


class MyWrongQuestionsView(APIView):
    """学生错题本（需求 S-Q-04）：由错误答题记录去重汇总。"""

    permission_classes = [IsStudent]
    serializer_class = AnalyticsResponseSerializer

    def get(self, request):
        qs = (
            AnswerRecord.objects.filter(student=request.user, is_correct=False)
            .select_related("question")
            .order_by("-submitted_at")
        )
        course_id = request.query_params.get("course")
        if course_id:
            qs = qs.filter(question__course_id=course_id)

        seen, items = set(), []
        for ar in qs:
            if ar.question_id in seen or ar.question is None:
                continue
            seen.add(ar.question_id)
            q = ar.question
            items.append({
                "question_id": q.id,
                "stem": q.stem,
                "qtype": q.qtype,
                "qtype_display": q.get_qtype_display(),
                "options": q.options,
                "correct_answer": q.answer,
                "analysis": q.analysis,
                "my_answer": ar.student_answer,
                "scene": ar.get_scene_display(),
                "submitted_at": ar.submitted_at,
            })
        return api_response({"total": len(items), "results": items})
