# -*- coding: utf-8 -*-
"""作业模块 E2E 种子数据：纯客观题作业（提交即出分，学生立即可见答案/解析）。

运行：venv/Scripts/python.exe manage.py shell < seed_hw_e2e.py
或：  venv/Scripts/python.exe manage.py shell -c "exec(open('seed_hw_e2e.py',encoding='utf-8').read())"
"""
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.courses.models import Course
from apps.classroom.models import ClassRoom
from apps.questions.models import Question, AnswerRecord
from apps.homework.models import Homework, HomeworkQuestion, HomeworkAnswer

User = get_user_model()
teacher = User.objects.get(username="t101")
student = User.objects.get(username="20249999")
course = Course.objects.get(id=5)
classroom = ClassRoom.objects.get(id=1)

# 清理历史 E2E 客观题作业（含提交记录）
# 注意删除顺序：HomeworkAnswer 对 HomeworkQuestion 是 PROTECT，必须先删答题记录
old_hws = list(Homework.objects.filter(title__startswith="E2E-客观题作业").values_list("id", flat=True))
if old_hws:
    HomeworkAnswer.objects.filter(homework_question__homework_id__in=old_hws).delete()
    AnswerRecord.objects.filter(scene=AnswerRecord.Scene.HOMEWORK, scene_ref_id__in=old_hws).delete()
    Homework.objects.filter(id__in=old_hws).delete()

hw = Homework.objects.create(
    title=f"E2E-客观题作业-{timezone.now().strftime('%H%M%S')}",
    description="E2E 验证：纯客观题提交后自动发布成绩，学生直接可见答案与解析",
    course=course,
    classroom=classroom,
    mode=Homework.Mode.QUESTIONS,
    status=Homework.Status.DRAFT,
    start_time=None,   # 立即开始
    deadline=None,     # 截止不限
    total_score=20,
)

qs = [
    (Question.objects.get(id=3), 10),   # 单选题
    (Question.objects.get(id=4), 10),   # 单选题
]
for order, (q, score) in enumerate(qs, start=1):
    HomeworkQuestion.objects.create(homework=hw, question=q, score=score, order=order)

# 草稿加题完成后置为已发布（queryset.update 绕过 save 的发布校验）
Homework.objects.filter(id=hw.id).update(status=Homework.Status.PUBLISHED)

# 确认快照已冻结（save() 自动填充）
hw.refresh_from_db()
for hq in hw.questions.all():
    print("HWQ:", hq.order, hq.question.qtype, "snapshot_keys:", sorted(hq.snapshot.keys()))

print("SEED_HW_ID:", hw.id)
print("SEED_HW_TITLE:", hw.title)
print("SEED_STUDENT:", student.username)
