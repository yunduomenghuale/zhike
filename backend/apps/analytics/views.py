"""学习进度统计 / 学习预警 / 错题本（需求 T-L-01/02/03、S-Q-04）。

本模块无自有模型，纯聚合其它模块数据。
"""
from django.db.models import Avg, Count, Q
from django.utils import timezone
from rest_framework.views import APIView

from apps.classroom.models import ClassRoom, ClassStudent
from apps.common.permissions import IsStudent, IsTeacher
from apps.common.response import api_response
from apps.courses.models import Catalog
from apps.exams.models import Exam, ExamSubmission
from apps.homework.models import Homework, HomeworkSubmission
from apps.questions.models import AnswerRecord, Question

INACTIVE_DAYS = 7
LOW_ACCURACY = 60


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


def build_class_stats(classroom, course_id) -> dict:
    """聚合班级在某课程下的学习统计（班级汇总 + 逐学生明细 + 预警）。"""
    course = classroom.courses.get(id=course_id)
    hw_list = list(Homework.objects.filter(
        classroom=classroom, course_id=course_id, status=Homework.Status.PUBLISHED
    ))
    exam_list_qs = list(Exam.objects.filter(
        classroom=classroom,
        course_id=course_id,
        status__in=[Exam.Status.PUBLISHED, Exam.Status.FINISHED],
    ))
    hw_total = len(hw_list)
    exam_total = len(exam_list_qs)
    now = timezone.now()

    rows = []
    for cs in ClassStudent.objects.filter(classroom=classroom).select_related("student"):
        stu = cs.student
        practice = AnswerRecord.objects.filter(
            student=stu, scene=AnswerRecord.Scene.PRACTICE, question__course_id=course_id
        )
        p_total = practice.count()
        p_correct = practice.filter(is_correct=True).count()
        accuracy = round(p_correct / p_total * 100) if p_total else None

        hw_sub_ids = set(HomeworkSubmission.objects.filter(
            student=stu,
            homework__classroom=classroom,
            homework__course_id=course_id,
        ).values_list("homework_id", flat=True))
        hw_sub = len(hw_sub_ids)
        hw_missing = [hw.title for hw in hw_list if hw.id not in hw_sub_ids]

        exam_subs = ExamSubmission.objects.filter(
            student=stu,
            exam__classroom=classroom,
            exam__course_id=course_id,
            status__in=[ExamSubmission.Status.SUBMITTED, ExamSubmission.Status.TIMEOUT],
        )
        exam_taken_ids = set(exam_subs.values_list("exam_id", flat=True))
        exam_taken = len(exam_taken_ids)
        exam_missing = [ex.name for ex in exam_list_qs if ex.id not in exam_taken_ids]
        avg_exam = exam_subs.aggregate(a=Avg("total_score"))["a"]

        last_ar = practice.order_by("-submitted_at").first()
        last_active = last_ar.submitted_at if last_ar else None

        warnings = []
        if last_active is None or (now - last_active).days >= INACTIVE_DAYS:
            warnings.append("长期未学习")
        if accuracy is not None and accuracy < LOW_ACCURACY:
            warnings.append("练习正确率低")
        if hw_total and hw_sub < hw_total:
            warnings.append("作业缺交")
        if exam_total and exam_taken < exam_total:
            warnings.append("考试缺考")

        rows.append({
            "student_id": stu.id,
            "name": stu.real_name or stu.username,
            "username": stu.username,
            "practice_total": p_total,
            "practice_correct": p_correct,
            "accuracy": accuracy,
            "homework_submitted": hw_sub,
            "homework_total": hw_total,
            "exam_taken": exam_taken,
            "exam_total": exam_total,
            "avg_exam_score": round(float(avg_exam), 1) if avg_exam is not None else None,
            "last_active": last_active,
            "warnings": warnings,
            "homework_missing": hw_missing,
            "exam_missing": exam_missing,
        })

    # 班级汇总
    acc_list = [r["accuracy"] for r in rows if r["accuracy"] is not None]
    exam_list = [r["avg_exam_score"] for r in rows if r["avg_exam_score"] is not None]
    student_count = len(rows)
    total_hw_slots = hw_total * student_count
    total_hw_sub = sum(r["homework_submitted"] for r in rows)
    summary = {
        "student_count": student_count,
        "avg_accuracy": round(sum(acc_list) / len(acc_list)) if acc_list else None,
        "avg_exam_score": round(sum(exam_list) / len(exam_list), 1) if exam_list else None,
        "homework_rate": round(total_hw_sub / total_hw_slots * 100) if total_hw_slots else None,
        "warning_count": sum(1 for r in rows if r["warnings"]),
    }

    return {
        "class_name": classroom.name,
        "course_id": course.id,
        "course_name": course.name,
        "summary": summary,
        "students": rows,
    }


class ClassStatsView(APIView):
    """班级学习统计 + 逐个学生进度 + 预警（需求 T-L-01/02/03）。"""

    permission_classes = [IsTeacher]

    def get(self, request, class_id):
        classroom, course, error = _resolve_classroom_course(request, class_id)
        if error:
            return error
        return api_response(build_class_stats(classroom, course.id))


class ClassAIReportView(APIView):
    """AI 学情分析报告：基于班级统计数据生成整体报告 + 逐学生简评。"""

    permission_classes = [IsTeacher]

    def post(self, request, class_id):
        from apps.ai.services import analyze_class_stats

        classroom, course, error = _resolve_classroom_course(request, class_id)
        if error:
            return error

        stats = build_class_stats(classroom, course.id)
        if not stats["students"]:
            return api_response(message="班级暂无学生，无法生成分析", code=400, status=400)

        result = analyze_class_stats(stats)
        comments = {
            item["student_id"]: item["comment"]
            for item in result.get("student_comments", [])
            if isinstance(item, dict) and item.get("student_id") is not None and item.get("comment")
        }
        return api_response({
            "report": result.get("overview", ""),
            "comments": comments,
            "generated_at": timezone.now(),
        })


class ClassStudentDetailView(APIView):
    """教师查看班级内单个学生的学习详情（练习/作业/考试/预警）。"""

    permission_classes = [IsTeacher]

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
            "recent_records": records,
        })


class MyWrongQuestionsView(APIView):
    """学生错题本（需求 S-Q-04）：由错误答题记录去重汇总。"""

    permission_classes = [IsStudent]

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
