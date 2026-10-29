"""学习进度统计 / 学习预警 / 错题本（需求 T-L-01/02/03、S-Q-04）。

本模块无自有模型，纯聚合其它模块数据。
班级统计逻辑收敛在 services.build_class_stats（教师端督管与平台端督管共用）。
"""
import io

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
from .throttles import TeacherExportThrottle


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


class ClassExportView(APIView):
    """班级学习数据 Excel 导出（教师端学情分析页「导出 Excel」弹窗）。

    GET /api/analytics/class/<id>/export/?course=&start=&end=&sheets=
    教师视角全量口径（不受 score_released / correct_status 门控）；
    start/end 过滤行为发生时间（练习/作业/考试/实验提交、问答创建、视频进度更新），
    不传 = 全量；sheets 为逗号分隔的内容 key（不传 = 全部，overview 恒导出）。
    Sheet 口径见 export.py 模块 docstring。
    """

    permission_classes = [IsTeacher]
    throttle_classes = [TeacherExportThrottle]

    def get(self, request, class_id):
        from urllib.parse import quote

        from django.http import FileResponse

        from .export import build_class_export_workbook, parse_export_range, parse_sections

        classroom, course, error = _resolve_classroom_course(request, class_id)
        if error:
            return error

        start, end, range_error = parse_export_range(request.query_params)
        if range_error:
            return api_response(message=range_error, code=400, status=400)

        sections, section_error = parse_sections(request.query_params.get("sheets"))
        if section_error:
            return api_response(message=section_error, code=400, status=400)

        wb = build_class_export_workbook(classroom, course, start=start, end=end, sections=sections)
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        filename = f"{classroom.name}_{course.name}_学习数据导出_{timezone.localtime():%Y%m%d_%H%M%S}.xlsx"
        response = FileResponse(
            buffer,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = (
            f"attachment; filename=export.xlsx; filename*=UTF-8''{quote(filename)}"
        )
        return response


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


def _submit_chapter_summary(student, catalog, *, force: bool = False, triggered_by=None):
    """幂等提交章节总结任务。返回 (task, cached, error_message)。

    规则（设计 §4.1）：
    - 已有 PENDING/RUNNING/SUCCESS 记录 → 跳过（含重看重复触发），返回旧的；
    - force=True → 新建一版（version 递进，查询取最大版本），限频 5 分钟 1 次（D8）；
    - 上一次 FAILED → 允许再次提交（不消耗 force 限频）。
    """
    from datetime import timedelta

    from apps.ai.models import AITask
    from apps.ai.tasks import submit_ai_task

    latest = (
        AITask.objects.filter(
            task_type=AITask.TaskType.CHAPTER_SUMMARY, student=student, catalog=catalog
        )
        .order_by("-version", "-id")
        .first()
    )
    if latest and latest.status in (AITask.Status.PENDING, AITask.Status.RUNNING):
        return latest, True, None  # 进行中：不重复提交（force 也返回旧的）
    if latest and latest.status == AITask.Status.SUCCESS and not force:
        return latest, True, None
    if force and latest and latest.created_at >= timezone.now() - timedelta(minutes=5):
        return None, False, "总结刚生成过，请 5 分钟后再试"

    version = (latest.version if latest else 0) + 1
    task = submit_ai_task(
        AITask.TaskType.CHAPTER_SUMMARY,
        user=triggered_by or student,
        student=student,
        catalog=catalog,
        course=catalog.course,
        version=version,
    )
    return task, False, None


class ChapterSummaryView(APIView):
    """学生端章节学习 AI 总结（设计 §4.4，挂 analytics 不新建 app，F12）。

    POST body {course_id, catalog_id, force?} → {task_id, cached}；
    已有成功/进行中记录直接复用（幂等），force=1 新建一版（version 递进）。
    GET ?course_id=&catalog_id= → 本人最新成功版本（含 result），没有则 summary=null。
    """

    permission_classes = [IsStudent]
    serializer_class = AnalyticsResponseSerializer

    def post(self, request):
        from apps.ai.models import AITask

        catalog = Catalog.objects.filter(
            id=request.data.get("catalog_id"), course_id=request.data.get("course_id")
        ).select_related("course").first()
        # 章节存在 + 学生已通过班级选修该课程（防越权总结他人课程）
        if not catalog or not ClassStudent.objects.filter(
            student=request.user, classroom__courses=catalog.course
        ).exists():
            return api_response(message="章节不存在或未学习该课程", code=404, status=404)

        force = str(request.data.get("force") or "").lower() in ("1", "true", "yes")
        task, cached, error = _submit_chapter_summary(request.user, catalog, force=force)
        if error:
            return api_response(message=error, code=429, status=429)
        return api_response({"task_id": task.id, "cached": cached})

    def get(self, request):
        from apps.ai.models import AITask

        task = (
            AITask.objects.filter(
                task_type=AITask.TaskType.CHAPTER_SUMMARY,
                student=request.user,
                catalog_id=request.query_params.get("catalog_id"),
                status=AITask.Status.SUCCESS,
            )
            .order_by("-version", "-id")
            .first()
        )
        result = task.result if task else None
        return api_response({
            "summary": {
                "task_id": task.id,
                "version": task.version,
                "degraded": (result or {}).get("degraded", False),
                "generated_at": (result or {}).get("generated_at"),
                "result": result,
            }
            if task else None
        })


class ClassChapterSummariesView(APIView):
    """教师端查看班级学生的章节学习 AI 总结（设计 §4.4 P3，for_student=False 全量口径）。

    作为学情分析的细粒度输入：按章节聚合班级每生的最新成功总结，
    不经学生端成绩门控（教师看全量）。学生姓名取实时 Users 表。
    """

    permission_classes = [IsTeacher]
    serializer_class = AnalyticsResponseSerializer

    def get(self, request, class_id):
        from apps.ai.models import AITask

        classroom, course, error = _resolve_classroom_course(request, class_id)
        if error:
            return error

        catalog_id = request.query_params.get("catalog_id")
        if not catalog_id:
            return api_response(message="缺少 catalog_id 参数", code=400, status=400)
        catalog = Catalog.objects.filter(id=catalog_id, course_id=course.id).first()
        if not catalog:
            return api_response(message="章节不存在或不属于该课程", code=404, status=404)

        student_ids = list(
            ClassStudent.objects.filter(classroom=classroom).values_list("student_id", flat=True)
        )
        tasks = (
            AITask.objects.filter(
                task_type=AITask.TaskType.CHAPTER_SUMMARY,
                student_id__in=student_ids,
                catalog_id=catalog.id,
                status=AITask.Status.SUCCESS,
            )
            .select_related("student")
            .order_by("student_id", "-version", "-id")
        )
        latest_of = {}
        for t in tasks:
            latest_of.setdefault(t.student_id, t)  # 已按 version 倒序，首条即最新版

        items = []
        for t in sorted(latest_of.values(), key=lambda x: x.student_id):
            result = t.result or {}
            items.append({
                "student_id": t.student_id,
                "student_name": (t.student.real_name or t.student.username) if t.student else "",
                "task_id": t.id,
                "version": t.version,
                "degraded": bool(result.get("degraded")),
                "generated_at": result.get("generated_at"),
                "result": result,
            })
        return api_response({
            "catalog": {"id": catalog.id, "title": catalog.title},
            "course_id": course.id,
            "total": len(items),
            "summaries": items,
        })


class ClassAIReportHistoryView(APIView):
    """班级 AI 学情分析报告历史列表（P3，按 AITask 查）。

    旧同步接口无产物留存；异步化后每次分析落 AITask(class_analytics)，
    教师可回看过往报告（完整 result 经 GET /api/ai-tasks/<id>/ 获取，
    可见性规则：班级归属教师放行）。重新生成入口见 ClassAIReportView.post。
    """

    permission_classes = [IsTeacher]
    serializer_class = AnalyticsResponseSerializer
    HISTORY_LIMIT = 20

    def get(self, request, class_id):
        from apps.ai.models import AITask

        classroom = ClassRoom.objects.filter(id=class_id, teacher=request.user).first()
        if not classroom:
            return api_response(message="班级不存在或无权查看", code=404, status=404)

        tasks = (
            AITask.objects.filter(
                task_type=AITask.TaskType.CLASS_ANALYTICS,
                classroom=classroom,
            )
            .order_by("-id")[: self.HISTORY_LIMIT]
        )
        reports = []
        for t in tasks:
            result = t.result or {}
            snapshot = result.get("stats_snapshot") or {}
            reports.append({
                "task_id": t.id,
                "status": t.status,
                "degraded": bool(result.get("degraded")),
                "generated_at": result.get("generated_at"),
                "created_at": t.created_at,
                "finished_at": t.finished_at,
                "error": t.error,
                # 课程归属：前端刷新页面后按当前课程恢复进行中任务的轮询（多课程班级）
                "course_id": t.course_id,
                "analyzed_count": snapshot.get("analyzed_count"),
                "comment_count": len(result.get("comments") or {}),
                # 保留 markdown 原文，前端 renderAiMarkdown 渲染（与报告正文同款样式）
                "report_excerpt": (result.get("report") or "")[:120],
            })
        return api_response({"class_id": classroom.id, "total": len(reports), "reports": reports})


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
                "image_url": f"/media/{q.image.name}" if q.image else "",
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
