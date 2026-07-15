"""把试卷的题目快照解析为可下发给学生的题目列表。

- 应用考试模式的题目乱序 / 选项乱序（需求 T-E-04）
- 学生作答时隐藏答案与解析；考后回看时附带答案、解析与对错
"""
from __future__ import annotations

import random

from apps.questions.models import Question


def _load_questions(items: list[dict]) -> dict[int, Question]:
    ids = [it["question_id"] for it in items]
    return {q.id: q for q in Question.objects.filter(id__in=ids)}


def build_for_taking(paper, exam) -> list[dict]:
    """学生答题用：不含答案/解析。"""
    if not paper:
        return []
    items = list(paper.question_items)
    q_map = _load_questions(items)

    result = []
    for it in items:
        q = q_map.get(it["question_id"])
        if not q:
            continue
        options = list(q.options or [])
        if exam.shuffle_options and options:
            options = options[:]
            random.shuffle(options)
        result.append(
            {
                "question_id": q.id,
                "order": it.get("order", 0),
                "score": it.get("score", float(q.score)),
                "qtype": q.qtype,
                "qtype_display": q.get_qtype_display(),
                "stem": q.stem,
                "options": options,
            }
        )

    result.sort(key=lambda x: x["order"])
    if exam.shuffle_questions:
        random.shuffle(result)
    return result


def build_for_review(paper, submission) -> list[dict]:
    """考后回看用：含正确答案、解析、学生作答与对错。"""
    if not paper:
        return []
    items = list(paper.question_items)
    q_map = _load_questions(items)
    answers = submission.answers or {}

    result = []
    for it in sorted(items, key=lambda x: x.get("order", 0)):
        q = q_map.get(it["question_id"])
        if not q:
            continue
        stu = answers.get(str(q.id)) or answers.get(q.id) or {}
        result.append(
            {
                "question_id": q.id,
                "score": it.get("score", float(q.score)),
                "qtype": q.qtype,
                "qtype_display": q.get_qtype_display(),
                "stem": q.stem,
                "options": q.options,
                "correct_answer": q.answer,
                "analysis": q.analysis,
                "student_answer": stu,
                "is_objective": q.is_objective,
            }
        )
    return result
