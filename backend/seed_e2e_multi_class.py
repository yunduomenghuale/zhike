# -*- coding: utf-8 -*-
"""多班级场景测试数据构造（本地 E2E 用）。

场景：
- 教师 t101；学生 20249999 同时加入两个班级（课程5 计算机网络 + 新建课程B 数据结构）；
- 学生 dbg1 只加入班级1（单课程回归）；
- 每门课均造：章节/题目/作业/考试/试卷/资料/问答记录/实验/错题记录，且两门课内容可区分。
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.courses.models import Catalog
from apps.classroom.models import ClassRoom, ClassStudent
from apps.questions.models import Question, AnswerRecord
from apps.homework.models import Homework
from apps.exams.models import Exam, Paper
from apps.knowledge.models import Material, QARecord
from apps.labs.models import Lab, LabTemplate

U = get_user_model()
now = timezone.now()

# ---------- 账号 ----------
t, _ = U.objects.get_or_create(username="t101", defaults={"role": "teacher", "real_name": "张老师"})
t.role = "teacher"
t.real_name = "张老师"
t.phone = "13800000001"
t.is_staff = True
t.set_password("A0987654")
t.save()

sa, _ = U.objects.get_or_create(username="20249999", defaults={"role": "student", "real_name": "多班学生"})
sa.role = "student"
sa.real_name = "多班学生"
sa.phone = "13800000002"
sa.set_password("A0987654")
sa.save()

sb, _ = U.objects.get_or_create(username="dbg1", defaults={"role": "student", "real_name": "单班学生"})
sb.role = "student"
sb.real_name = "单班学生"
sb.phone = "13800000003"
sb.set_password("A0987654")
sb.save()

# ---------- 班级1（已有，课程5） ----------
c1, _ = ClassRoom.objects.get_or_create(
    id=1,
    defaults={"name": "测试班1789789245", "teacher": t, "status": "open", "invite_code": "TEST0001"},
)
c1.status = "open"
c1.invite_enabled = True
c1.save()

ClassStudent.objects.get_or_create(classroom=c1, student=sa, defaults={"learn_status": "active"})
ClassStudent.objects.get_or_create(classroom=c1, student=sb, defaults={"learn_status": "active"})

# ---------- 课程B + 班级2 ----------
course5 = c1.courses.first() or c1.course
cb_course, _ = type(course5).objects.get_or_create(
    name="数据结构B",
    defaults={"teacher": t, "intro": "线性表、栈队列、树与图", "status": "active"},
)
c2, _ = ClassRoom.objects.get_or_create(
    name="数据结构B班",
    defaults={"teacher": t, "status": "open", "invite_code": "TEST0002"},
)
c2.status = "open"
c2.invite_enabled = True
c2.save()
c2.courses.add(cb_course)
ClassStudent.objects.get_or_create(classroom=c2, student=sa, defaults={"learn_status": "active"})


def make_catalog(course, title, order):
    obj, _ = Catalog.objects.get_or_create(
        course=course, title=title, defaults={"order": order, "is_published": True}
    )
    obj.is_published = True
    obj.save()
    return obj


def make_question(course, catalog, stem, qtype, options, answer, analysis):
    obj, _ = Question.objects.get_or_create(
        course=course, stem=stem,
        defaults={
            "catalog": catalog, "qtype": qtype, "options": options, "answer": answer,
            "analysis": analysis, "score": 5, "status": "published", "creator": t,
        },
    )
    obj.status = "published"
    obj.save()
    return obj


def make_wrong(student, question, my_answer):
    AnswerRecord.objects.get_or_create(
        student=student, question=question, scene="practice",
        defaults={"student_answer": my_answer, "is_correct": False},
    )


def make_homework(course, classroom, title):
    obj, _ = Homework.objects.get_or_create(
        course=course, classroom=classroom, title=title,
        defaults={
            "description": f"{title}：请按时完成并提交",
            "mode": "attachment", "total_score": 100, "status": "published",
            "start_time": now - timedelta(days=2), "deadline": now + timedelta(days=7),
        },
    )
    obj.status = "published"
    obj.save()
    return obj


def make_exam(course, classroom, name, questions):
    obj, _ = Exam.objects.get_or_create(
        course=course, classroom=classroom, name=name,
        defaults={
            "start_at": now - timedelta(days=1), "end_at": now + timedelta(days=7),
            "duration": 60, "total_score": 100, "status": "published",
        },
    )
    obj.status = "published"
    obj.save()
    items = [
        {"question_id": q.id, "score": float(q.score), "order": i}
        for i, q in enumerate(questions)
    ]
    Paper.objects.get_or_create(
        exam=obj, student=None,
        defaults={"course": course, "mode": "manual", "question_items": items, "total_score": 100},
    )
    return obj


# ---------- 课程5（计算机网络）补充内容 ----------
cat5 = Catalog.objects.filter(course=course5, is_published=True).first() or make_catalog(course5, "第4章 网络层", 4)
q5a = Question.objects.filter(course=course5, status="published").first()
if q5a:
    make_wrong(sa, q5a, {"key": "Z"})
make_homework(course5, c1, "计算机网络-作业1")
make_exam(course5, c1, "计算机网络-月考1", list(Question.objects.filter(course=course5, status="published")[:3]))

# ---------- 课程B（数据结构）内容 ----------
catB1 = make_catalog(cb_course, "第1章 线性表", 1)
catB2 = make_catalog(cb_course, "第2章 栈和队列", 2)
qB1 = make_question(
    cb_course, catB1, "顺序表中访问第 i 个元素的时间复杂度为？", "single",
    [{"key": "A", "text": "O(1)"}, {"key": "B", "text": "O(n)"}, {"key": "C", "text": "O(logn)"}, {"key": "D", "text": "O(n^2)"}],
    {"key": "A"}, "顺序表随机存取，时间复杂度 O(1)。",
)
qB2 = make_question(
    cb_course, catB2, "栈的特点是后进先出（LIFO）。", "judge",
    [{"key": "T", "text": "正确"}, {"key": "F", "text": "错误"}],
    {"key": "T"}, "栈是操作受限的线性表，只允许在一端进行插入和删除。",
)
make_wrong(sa, qB1, {"key": "B"})
make_wrong(sa, qB2, {"key": "F"})
make_homework(cb_course, c2, "数据结构-作业1")
make_exam(cb_course, c2, "数据结构-期中1", [qB1, qB2])

Material.objects.get_or_create(
    course=cb_course, file_name="数据结构课件.pdf",
    defaults={"file_type": "pdf", "parse_status": "done", "qa_open": True},
)
QARecord.objects.get_or_create(
    course=cb_course, classroom=c2, student=sa, session="seed-session-b", question="什么是循环队列？",
    defaults={"answer": "循环队列把存储空间看作首尾相连的环，通过取模运算区分队空与队满。"},
)

tpl = LabTemplate.objects.filter(code="routing-ospf-lab").first()
labB, _ = Lab.objects.get_or_create(
    course=cb_course, template=tpl, title="数据结构实验：表达式求值（栈的应用）",
    defaults={
        "description": "利用栈实现中缀表达式求值", "total_score": 100, "pass_score": 60,
        "status": "published",
    },
)
labB.status = "published"
labB.save()
from apps.labs.models import LabSchedule
LabSchedule.objects.get_or_create(
    lab=labB, classroom=c2,
    defaults={"open_at": now - timedelta(days=1), "close_at": now + timedelta(days=30)},
)

print("=== 种子数据就绪 ===")
print("学生 20249999 班级:", [cs.classroom.name for cs in ClassStudent.objects.filter(student=sa, learn_status='active')])
print("学生 20249999 课程:", sorted({cid for c in ClassRoom.objects.filter(students__student=sa, students__learn_status='active').values_list('courses__id', flat=True) if cid}))
print("学生 dbg1 班级:", [cs.classroom.name for cs in ClassStudent.objects.filter(student=sb, learn_status='active')])
print("课程B id:", cb_course.id, " 班级2 id:", c2.id, " 课程5 id:", course5.id)
