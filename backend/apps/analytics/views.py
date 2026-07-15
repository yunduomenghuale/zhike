"""学习进度统计 / 学习预警 / 错题本（需求 T-L-01/02/03、S-Q-04）。

本模块无自有模型，纯聚合其它模块数据。
"""
from django.db.models import Avg
from django.utils import timezone
from rest_framework.views import APIView

from apps.classroom.models import ClassRoom, ClassStudent
from apps.common.permissions import IsStudent, IsTeacher
from apps.common.response import api_response
from apps.exams.models import Exam, ExamSubmission
from apps.homework.models import Homework, HomeworkSubmission
from apps.questions.models import AnswerRecord

INACTIVE_DAYS = 7
LOW_ACCURACY = 60


class ClassStatsView(APIView):
    """班级学习统计 + 逐个学生进度 + 预警（需求 T-L-01/02/03）。"""

    permission_classes = [IsTeacher]

    def get(self, request, class_id):
        classroom = ClassRoom.objects.filter(id=class_id, teacher=request.user).first()
        if not classroom:
            return api_response(message="班级不存在或无权查看", code=404, status=404)

        course_id = request.query_params.get("course")
        if course_id:
            course = classroom.courses.filter(id=course_id).first()
            if not course:
                return api_response(message="该课程未关联到此班级", code=400, status=400)
        else:
            course = classroom.courses.order_by("id").first()
            if not course:
                return api_response(message="该班级尚未关联课程", code=400, status=400)
            course_id = course.id
        hw_total = Homework.objects.filter(
            classroom=classroom, course_id=course_id, status=Homework.Status.PUBLISHED
        ).count()
        exam_total = Exam.objects.filter(
            classroom=classroom,
            course_id=course_id,
            status__in=[Exam.Status.PUBLISHED, Exam.Status.FINISHED],
        ).count()
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

            hw_sub = HomeworkSubmission.objects.filter(
                student=stu,
                homework__classroom=classroom,
                homework__course_id=course_id,
            ).count()

            exam_subs = ExamSubmission.objects.filter(
                student=stu,
                exam__classroom=classroom,
                exam__course_id=course_id,
                status__in=[ExamSubmission.Status.SUBMITTED, ExamSubmission.Status.TIMEOUT],
            )
            exam_taken = exam_subs.count()
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

        return api_response({
            "class_name": classroom.name,
            "course_id": course.id,
            "course_name": course.name,
            "summary": summary,
            "students": rows,
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
