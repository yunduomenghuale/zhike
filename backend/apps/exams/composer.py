"""随机组卷（需求 8.2）。

按章节 / 题型 / 难度规则从课程题库随机抽题，套内去重，自动累计总分。
rules 形如：
[
  {"catalog": 3, "qtype": "single", "difficulty": "easy", "count": 5, "score": 2},
  {"qtype": "judge", "count": 5, "score": 2},
]
"""
import random
from decimal import Decimal

from apps.questions.models import Question


def compose_random(course_id: int, rules: list[dict]) -> tuple[list[dict], Decimal]:
    """返回 (question_items, total_score)。question_items: [{question_id, score, order}]"""
    picked_ids: set[int] = set()
    items: list[dict] = []
    order = 0
    total = Decimal("0")

    for rule in rules:
        qs = Question.objects.filter(
            course_id=course_id, status=Question.Status.PUBLISHED
        ).exclude(id__in=picked_ids)
        if rule.get("catalog"):
            qs = qs.filter(catalog_id=rule["catalog"])
        if rule.get("qtype"):
            qs = qs.filter(qtype=rule["qtype"])
        if rule.get("difficulty"):
            qs = qs.filter(difficulty=rule["difficulty"])

        candidates = list(qs.values_list("id", flat=True))
        random.shuffle(candidates)
        count = int(rule.get("count", 0))
        chosen = candidates[:count]

        for qid in chosen:
            picked_ids.add(qid)
            score = Decimal(str(rule.get("score", 5)))
            items.append({"question_id": qid, "score": float(score), "order": order})
            total += score
            order += 1

    return items, total


def compose_manual(question_score_pairs: list[dict]) -> tuple[list[dict], Decimal]:
    """手动组卷：[{question_id, score}] -> question_items。"""
    items, total, order = [], Decimal("0"), 0
    for pair in question_score_pairs:
        score = Decimal(str(pair.get("score", 5)))
        items.append({"question_id": pair["question_id"], "score": float(score), "order": order})
        total += score
        order += 1
    return items, total
