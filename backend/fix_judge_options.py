# -*- coding: utf-8 -*-
"""一次性修复：判断题缺选项导致学生端渲染不出对错项。
1) Question 表 qtype=judge 且 options 为空的补默认选项（走模型 save 兜底逻辑）
2) HomeworkQuestion.snapshot 中 qtype=judge 且 options 为空的同步补齐（不影响快照其他字段）
运行：venv/Scripts/python.exe manage.py shell -c "exec(open('fix_judge_options.py',encoding='utf-8').read())"
"""
from apps.questions.models import Question
from apps.homework.models import HomeworkQuestion

# 1) 题库中的判断题
fixed_q = 0
for q in Question.objects.filter(qtype=Question.QType.JUDGE):
    if not q.options:
        q.save()  # 模型 save() 内含 judge 选项兜底
        fixed_q += 1
        print(f"Question#{q.id} 补选项 -> {q.options}")
print(f"题库判断题补选项：{fixed_q} 条")

# 2) 作业快照中的判断题（只补 options，不动答案/题干等冻结字段）
# 注意：HomeworkQuestion.save() 禁止改已发布作业的快照，数据修复走 update() 绕过业务保护
from django.utils import timezone

fixed_snap = 0
for hq in HomeworkQuestion.objects.all():
    snap = hq.snapshot or {}
    if snap.get("qtype") == "judge" and not snap.get("options"):
        key = str((snap.get("answer") or {}).get("key", "")).upper()
        if key in ("T", "F"):
            snap["options"] = [{"key": "T", "text": "正确"}, {"key": "F", "text": "错误"}]
        else:
            snap["options"] = [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}]
        HomeworkQuestion.objects.filter(pk=hq.pk).update(snapshot=snap, updated_at=timezone.now())
        fixed_snap += 1
        print(f"HomeworkQuestion#{hq.id} 快照补选项 -> {snap['options']}")
print(f"作业快照补选项：{fixed_snap} 条")
print("修复完成")
