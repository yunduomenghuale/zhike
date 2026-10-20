"""学习数据聚合服务（教师端学情统计与平台端督管共用）。

从 views.py 平移而来，保持纯函数语义：不感知请求与用户，
行级权限由调用方 View 负责（教师端校验班级归属，平台端 IsPlatformAdmin 放行）。
"""
from django.db.models import Avg, Count
from django.utils import timezone

from apps.classroom.models import ClassStudent
from apps.exams.models import Exam, ExamSubmission
from apps.homework.models import Homework, HomeworkSubmission
from apps.labs.models import Lab, LabSubmission
from apps.questions.models import AnswerRecord

INACTIVE_DAYS = 7
LOW_ACCURACY = 60


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
    # 实验维度：本班本课程排课且已发布的实验集合
    lab_list = list(Lab.objects.filter(
        course_id=course_id, status=Lab.Status.PUBLISHED,
        schedules__classroom=classroom,
    ).distinct())
    lab_total = len(lab_list)
    lab_ids = {lab.id for lab in lab_list}
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

        # 实验维度（循环外无法按生过滤的轻量查询；量级 = 班级人数 × 实验数）
        lab_subs = LabSubmission.objects.filter(
            student=stu, lab_id__in=lab_ids, status=LabSubmission.Status.SUBMITTED
        )
        lab_done_ids = set(lab_subs.values_list("lab_id", flat=True))
        lab_done = len(lab_done_ids)
        lab_missing = [lab.title for lab in lab_list if lab.id not in lab_done_ids]
        avg_lab = lab_subs.aggregate(a=Avg("total_score"))["a"]

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
        if lab_total and lab_done < lab_total:
            warnings.append("实验缺做")

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
            "experiment_done": lab_done,
            "experiment_total": lab_total,
            "avg_experiment_score": round(float(avg_lab), 1) if avg_lab is not None else None,
            "last_active": last_active,
            "warnings": warnings,
            "homework_missing": hw_missing,
            "exam_missing": exam_missing,
            "lab_missing": lab_missing,
        })

    # 班级汇总
    acc_list = [r["accuracy"] for r in rows if r["accuracy"] is not None]
    exam_list = [r["avg_exam_score"] for r in rows if r["avg_exam_score"] is not None]
    lab_scores = [r["avg_experiment_score"] for r in rows if r["avg_experiment_score"] is not None]
    student_count = len(rows)
    total_hw_slots = hw_total * student_count
    total_hw_sub = sum(r["homework_submitted"] for r in rows)
    total_lab_slots = lab_total * student_count
    total_lab_done = sum(r["experiment_done"] for r in rows)
    summary = {
        "student_count": student_count,
        "avg_accuracy": round(sum(acc_list) / len(acc_list)) if acc_list else None,
        "avg_exam_score": round(sum(exam_list) / len(exam_list), 1) if exam_list else None,
        "avg_experiment_score": round(sum(lab_scores) / len(lab_scores), 1) if lab_scores else None,
        "homework_rate": round(total_hw_sub / total_hw_slots * 100) if total_hw_slots else None,
        "experiment_rate": round(total_lab_done / total_lab_slots * 100) if total_lab_slots else None,
        "warning_count": sum(1 for r in rows if r["warnings"]),
    }

    return {
        "class_name": classroom.name,
        "course_id": course.id,
        "course_name": course.name,
        "summary": summary,
        "students": rows,
    }
