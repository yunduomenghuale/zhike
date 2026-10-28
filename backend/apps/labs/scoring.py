"""实验评分（整合实验平台 lab-scoring-enhance.js 规则，服务端为唯一真相源）。

原平台公式：
- 基础分 = 步骤得分 * 0.8（步骤满分 100 时基础分上限 80）
- 综合评价 20 分 = 操作准确性 5（错误次数每次扣 1）+ 完成效率 5（超时每 3 分钟扣 1）+ 完成度 10（通过步骤占比）
- 总分 = 基础分 + 综合评价

说明：曾经的「实验附题」加权合成已随附题功能整体下线（2026-10-28），
实验回归纯步骤评分。
"""
from decimal import Decimal

from django.utils import timezone

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


def calc_total(step: dict, total_score: Decimal) -> Decimal:
    """纯步骤总分（附题加权已下线）。"""
    return _q(step["step_total"]).quantize(Decimal("0.1"))


def build_breakdown(submission, step: dict, total: Decimal) -> dict:
    return {
        "base": str(step["base"]),
        "max_base": str(step["max_base"]),
        "accuracy": str(step["accuracy"]),
        "efficiency": str(step["efficiency"]),
        "completion": str(step["completion"]),
        "step_total": str(step["step_total"]),
        "total": str(total),
        "elapsed_minutes": step["elapsed_minutes"],
        "standard_minutes": step["standard_minutes"],
        "passed_steps": step["passed_steps"],
        "total_steps": step["total_steps"],
        "error_count": step["error_count"],
        "generated_at": timezone.now().isoformat(),
    }
