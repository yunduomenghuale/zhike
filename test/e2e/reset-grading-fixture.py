#!/usr/bin/env python
"""E2E 前置重置：把作业「3」(hw39) 的学生提交恢复为「已提交、未批改」态。

homework-grade-release-verify.js 的前置要求：
  - HomeworkSubmission(id=18, 学生 20249999)：correct_status='submitted'、
    score=objective_score(5.0)、comment=''
  - 主观题（简答 short）答案：score=None、is_correct=None
每次 E2E 跑完（批改即发布）后提交会变成 returned/8.0，重跑前必须重置。

注意：主观题答案 id 会随数据变化（曾误记 id=31，实为另一条提交的客观题），
故按 question.qtype == 'short' 动态定位，不要硬编码 id。

用法（backend/ 目录下）：
  venv/Scripts/python.exe ../test/e2e/reset-grading-fixture.py
"""
import os
import sys

import django

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.homework.models import HomeworkAnswer, HomeworkSubmission  # noqa: E402

SUB_ID = 18
SUBJECTIVE_QTYPES = ('short',)  # 简答题需教师评分；单选/多选/判断/填空为客观题自动批改

sub = HomeworkSubmission.objects.filter(id=SUB_ID).first()
if not sub:
    print('RESET FAIL: submission %s not found' % SUB_ID)
    sys.exit(1)

sub.correct_status = 'submitted'
sub.score = sub.objective_score
sub.comment = ''
sub.save(update_fields=['correct_status', 'score', 'comment', 'updated_at'])

cleared = list(
    HomeworkAnswer.objects.filter(
        submission=sub, homework_question__question__qtype__in=SUBJECTIVE_QTYPES
    ).values_list('id', flat=True)
)
HomeworkAnswer.objects.filter(id__in=cleared).update(score=None, is_correct=None)

print('RESET OK: submission %s -> %s / score=%s / comment=%r; subjective answers cleared: %s'
      % (sub.id, sub.correct_status, sub.score, sub.comment, cleared))
