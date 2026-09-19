"""实验评分（整合实验平台 lab-scoring-enhance.js 规则，服务端为唯一真相源）。

原平台公式：
- 基础分 = 步骤得分 * 0.8（步骤满分 100 时基础分上限 80）
- 综合评价 20 分 = 操作准确性 5（错误次数每次扣 1）+ 完成效率 5（超时每 3 分钟扣 1）+ 完成度 10（通过步骤占比）
- 总分 = 基础分 + 综合评价；附题时按 question_weight 与题目得分加权合成。
"""
from decimal import Decimal

from django.utils import timezone

from apps.questions.grading import grade_lab_question

MAX_ACCURACY = Decimal("5")
MAX_EFFICIENCY = Decimal("5")
MAX_COMPLETION = Decimal("10")
BASE_RATIO = Decimal("0.8")  # 步骤分折算基础分的比例


def _q(value) -> Decimal:
    return Decimal(str(value))


def calc_step_scores(submission, standard_minutes: int, total_score: Decimal) -> dict:
    """按服务端持久化的过程数据重算实验步骤评分（不信任前端分数）。"""
    error_count = submission.error_count
    elapsed_min = max(0, submission.elapsed_seconds) / 60.0

    total_steps = submission.total_steps or 0
    passed = min(submission.passed_steps or 0, total_steps) if total_steps else 0
    step_score = _q(total_score) * BASE_RATIO * (Decimal(passed) / Decimal(total_steps) if total_steps else Decimal("0"))

    accuracy = max(Decimal("0"), MAX_ACCURACY - Decimal(error_count))
    over_min = max(0.0, elapsed_min - standard_minutes)
    efficiency = max(Decimal("0"), MAX_EFFICIENCY - Decimal(int(over_min // 3)))
    completion = (Decimal(passed) / Decimal(total_steps) * MAX_COMPLETION if total_steps else Decimal("0")).quantize(Decimal("0.1"))

    base = step_score.quantize(Decimal("0.1"))
    return {
        "base": base,
        "accuracy": accuracy,
        "efficiency": efficiency,
        "completion": completion,
        "step_total": base + accuracy + efficiency + completion,
        "max_base": (_q(total_score) * BASE_RATIO).quantize(Decimal("0.1")),
        "elapsed_minutes": int(elapsed_min),
        "standard_minutes": standard_minutes,
        "passed_steps": passed,
        "total_steps": total_steps,
        "error_count": error_count,
    }


def grade_submission_questions(submission) -> Decimal:
    """逐题评分实验附题：客观题 grade_objective；主观题相似度预评分。返回题目总得分。"""
    from .models import LabAnswer

    question_total = Decimal("0")
    for lq in submission.lab.questions.select_related("question").all():
        snapshot = lq.snapshot or {}
        stu_ans = {}
        answer = LabAnswer.objects.filter(submission=submission, lab_question=lq).first()
        if answer:
            stu_ans = answer.student_answer or {}
        # 用快照结构构造轻量题目对象供评分（快照为唯一判题依据）
        q_like = _SnapshotQuestion(snapshot, default_score=lq.score)
        verdict, auto_score, similarity = grade_lab_question(q_like, stu_ans)
        fields = {
            "auto_score": auto_score,
            "similarity": similarity,
            "auto_comment": {"correct": "回答正确", "wrong": "回答未命中要点", "pending_review": "系统预评分，待教师复核"}.get(verdict, ""),
            "pending_review": verdict == "pending_review",
            "is_correct": verdict == "correct",
            "score": auto_score,  # 提交即见分：先以系统评分作为最终得分，教师可复核调整
        }
        if answer:
            for k, v in fields.items():
                setattr(answer, k, v)
            answer.save(update_fields=list(fields.keys()))
        else:
            LabAnswer.objects.create(submission=submission, lab_question=lq, student_answer={}, **fields)
        question_total += _q(auto_score or 0)
    return question_total.quantize(Decimal("0.1"))


class _SnapshotQuestion:
    """以 LabQuestion.snapshot 构造的轻量题目对象，兼容 grade_objective/grade_subjective。"""

    def __init__(self, snapshot: dict, default_score=5):
        self.qtype = snapshot.get("qtype", "short")
        self.answer = snapshot.get("answer") or {}
        self.analysis = snapshot.get("analysis", "")
        self.score = snapshot.get("source_score", str(default_score))


def calc_total(submission, step: dict, question_total: Decimal, question_weight: Decimal, total_score: Decimal) -> Decimal:
    """合成总分：question_weight=0 纯步骤分；否则 实验分*(1-w) + 题目分*w。"""
    w = _q(question_weight or 0)
    step_total = _q(step["step_total"])
    if w <= 0:
        total = step_total
    else:
        step_norm = (step_total / _q(total_score) * Decimal("100")) if total_score else Decimal("0")
        total = step_norm * (Decimal("1") - w) + _q(question_total) * w
    return total.quantize(Decimal("0.1"))


def build_breakdown(submission, step: dict, question_total: Decimal, total: Decimal) -> dict:
    return {
        "base": str(step["base"]),
        "max_base": str(step["max_base"]),
        "accuracy": str(step["accuracy"]),
        "efficiency": str(step["efficiency"]),
        "completion": str(step["completion"]),
        "step_total": str(step["step_total"]),
        "question_total": str(question_total),
        "total": str(total),
        "elapsed_minutes": step["elapsed_minutes"],
        "standard_minutes": step["standard_minutes"],
        "passed_steps": step["passed_steps"],
        "total_steps": step["total_steps"],
        "error_count": step["error_count"],
        "generated_at": timezone.now().isoformat(),
    }
