"""把试卷的题目快照解析为可下发给学生的题目列表。

- 题目乱序（需求 T-E-04）：在单选/多选/判断/填空/简答五类内部打乱，类间顺序固定
- 选项乱序：开启后选择题选项内容随机排列，A/B/C/D 标签位置固定；
  正确答案跟随内容——按乱序结果重映射选项 key，学生答案同样在新 key 空间存储
- 乱序结果在开始考试时生成并固化到答卷（ExamSubmission.question_layout），
  刷新/重进/切后台都不再重排
- 学生作答时隐藏答案与解析；考后回看时附带答案、解析与对错（选项顺序与学生当时所见一致）
- 填空题只下发空数量（blank_count），不下发答案本身，多空题按空数渲染输入框
"""
from __future__ import annotations

import random
import re
from decimal import Decimal, InvalidOperation

from apps.questions.grading import grade_objective
from apps.questions.models import Question

# 题干中的占位空：连续下划线 / 全角括号 / 半角括号（与前端作业端计数口径一致）
_BLANK_MARKER_RE = re.compile(r"_{2,}|（\s*）|\(\s*\)")

# 题型展示顺序：乱序时五类题目按此顺序分段，类内打乱、类间不变
QTYPE_ORDER = ["single", "multi", "judge", "blank", "short"]


def _load_questions(items: list[dict]) -> dict[int, Question]:
    ids = [it["question_id"] for it in items]
    return {q.id: q for q in Question.objects.filter(id__in=ids)}


def blank_count_of(question) -> int:
    """填空题的空数量：优先取答案空数，其次题干占位符计数，至少 1。"""
    blanks = (question.answer or {}).get("blanks") or []
    count = len(blanks) if blanks else len(_BLANK_MARKER_RE.findall(question.stem or ""))
    return max(1, count)


def score_for_item(question, paper_score, student_answer: dict):
    """按试卷分值折算单题得分。返回 (is_correct, score: Decimal|None)。

    客观题自动评分；主观题返回 (None, None)（分数由教师批改）。
    题库分值与试卷分值可能不同，按试卷分值等比折算。
    """
    is_correct, score = grade_objective(question, student_answer or {})
    if score is None:
        return None, None
    full = Decimal(str(question.score or 1)) or Decimal("1")
    try:
        ratio = Decimal(str(paper_score)) / full
    except (InvalidOperation, ZeroDivisionError, ArithmeticError):
        ratio = Decimal("0")
    return is_correct, (score * ratio).quantize(Decimal("0.1"))


# ---------------------------------------------------------------- 乱序 layout

def _option_key(index: int) -> str:
    """展示位置的标准选项 key：0→A、1→B……（标签位置固定，内容随机排）。"""
    return chr(ord("A") + index)


def build_layout(items: list[dict], q_map: dict[int, Question], exam) -> dict:
    """生成题目乱序 + 选项乱序结果（开始考试时固化，之后不再改变）。

    返回 {"order": [question_id...], "options": {str(question_id): [perm...]}}
    - order：题目展示顺序。开启题目乱序时五类分段（类间顺序固定）、类内随机；
      未开启时保持组卷 order 原序
    - options：仅选项乱序开启的选择题有条目，perm[i] = 展示位置 i 的原始 options 下标
    """
    ordered = sorted(items, key=lambda x: x.get("order", 0))
    questions = [it for it in ordered if it["question_id"] in q_map]

    if exam.shuffle_questions:
        # 类内乱序、类间顺序固定（单选→多选→判断→填空→简答）
        by_type: dict[str, list[dict]] = {}
        for it in questions:
            q = q_map[it["question_id"]]
            by_type.setdefault(q.qtype, []).append(it)
        sequence: list[dict] = []
        for qtype in QTYPE_ORDER:
            group = by_type.get(qtype, [])
            random.shuffle(group)
            sequence.extend(group)
        # 组卷时出现的未知题型（防御）附在末尾，保持原相对顺序
        known = set(QTYPE_ORDER)
        sequence.extend(it for it in questions if q_map[it["question_id"]].qtype not in known)
    else:
        sequence = list(questions)

    layout = {"order": [it["question_id"] for it in sequence], "options": {}}
    if exam.shuffle_options:
        for it in sequence:
            q = q_map[it["question_id"]]
            if q.qtype not in ("single", "multi", "judge"):
                continue
            options = q.options or []
            if len(options) < 2:
                continue  # 选项不足以乱序（无意义且破坏展示）
            perm = list(range(len(options)))
            random.shuffle(perm)
            layout["options"][str(it["question_id"])] = perm
    return layout


def layout_matches(layout, items: list[dict]) -> bool:
    """layout 是否与当前试卷题目集合一致（教师改组卷后需重新生成）。"""
    order = (layout or {}).get("order") or []
    current = {it["question_id"] for it in items}
    return bool(order) and set(order) == current and len(order) == len(current)


def ordered_items(items: list[dict], layout: dict) -> list[dict]:
    """按 layout.order 重排题目（layout 缺失/不匹配时回退组卷 order）。"""
    order = (layout or {}).get("order") or []
    if not order:
        return sorted(items, key=lambda x: x.get("order", 0))
    by_id = {it["question_id"]: it for it in items}
    seq = [by_id[qid] for qid in order if qid in by_id]
    seen = {it["question_id"] for it in seq}
    seq.extend(it for it in sorted(items, key=lambda x: x.get("order", 0)) if it["question_id"] not in seen)
    return seq


def _perm_of(layout: dict, question_id) -> list[int] | None:
    perm = (layout or {}).get("options", {}).get(str(question_id))
    if not perm:
        return None
    return list(perm)


def permuted_options(question, perm: list[int] | None) -> list[dict]:
    """按 perm 生成下发选项：key 按展示位置重写为 A/B/C…，text 取原始选项内容。

    perm 为空时返回原始选项（key 原样）。
    """
    options = question.options or []
    if not perm:
        return [{"key": o.get("key"), "text": o.get("text")} for o in options]
    return [
        {"key": _option_key(i), "text": options[perm[i]].get("text")}
        for i in range(len(perm))
    ]


def _sorted_answer_keys(answer: dict) -> dict:
    """展示用：多选 keys 按选项字母自然序排序。

    学生答案按点击顺序存储、教师录入顺序也不保证字母序，不排序会出现
    「正确答案：C、D、B」这类乱序展示。仅影响下发展示，不改存储值，
    评分走集合比较与顺序无关。
    """
    if isinstance(answer.get("keys"), list):
        out = dict(answer)
        out["keys"] = sorted(answer["keys"], key=lambda k: str(k).upper())
        return out
    return answer


def unmap_student_answer(answer: dict, perm: list[int] | None, options: list[dict]) -> dict:
    """展示 key 空间 → 原始 key 空间（提交评分时把学生答案还原回题库口径）。"""
    if not answer or not perm:
        return answer or {}
    out = dict(answer)
    if out.get("key") is not None:
        try:
            pos = ord(str(out["key"]).upper()) - ord("A")
        except (TypeError, ValueError):
            return out
        if 0 <= pos < len(perm):
            out["key"] = options[perm[pos]].get("key")
    if isinstance(out.get("keys"), list):
        mapped = []
        for k in out["keys"]:
            try:
                pos = ord(str(k).upper()) - ord("A")
            except (TypeError, ValueError):
                mapped.append(k)
                continue
            mapped.append(options[perm[pos]].get("key") if 0 <= pos < len(perm) else k)
        out["keys"] = mapped
    return out


# ---------------------------------------------------------------- 构建下发

def build_for_taking(paper, exam, layout: dict | None = None) -> list[dict]:
    """学生答题用：不含答案/解析；选项按 layout 固化顺序；填空题带空数量。"""
    if not paper:
        return []
    items = list(paper.question_items)
    q_map = _load_questions(items)
    layout = layout or {}

    result = []
    for it in ordered_items(items, layout):
        q = q_map.get(it["question_id"])
        if not q:
            continue
        perm = _perm_of(layout, q.id)
        entry = {
            "question_id": q.id,
            "order": it.get("order", 0),
            "score": it.get("score", float(q.score)),
            "qtype": q.qtype,
            "qtype_display": q.get_qtype_display(),
            "stem": q.stem,
            "options": permuted_options(q, perm),
        }
        if q.qtype == Question.QType.BLANK:
            # 只给数量，不给答案：多空题按此渲染多个输入框
            entry["blank_count"] = blank_count_of(q)
        result.append(entry)
    return result


def build_for_review(paper, submission, exam=None) -> list[dict]:
    """考后回看/教师批改用：含正确答案、学生作答、逐题得分与对错。

    **按原题顺序展示（S4 回看归序）**：选项乱序只在考试答题时生效（防作弊），
    回看与批改统一回到原题空间——原始选项顺序、原始正确答案、学生答案
    unmap 回原始 key。这样解析文本（按原题顺序书写，如「D 错误」）、
    正确答案字母、选项顺序三者天然自洽，无需任何文本改写。
    题目顺序仍按答卷固化的 question_layout 重放（乱序做题顺序不回退）。

    得分可见性（需求：提交即可查分）：
    - 客观题：提交即自动评分，my_score 直接返回
    - 主观题：已批阅返回 my_score，未批阅 my_score 为 None 且 pending=True
    解析受考试「结束后展示解析」开关控制（show_analysis_after）。
    """
    if not paper:
        return []
    items = list(paper.question_items)
    q_map = _load_questions(items)
    answers = submission.answers or {}
    subjective_scores = submission.subjective_scores or {}
    show_analysis = True if exam is None else exam.show_analysis_after
    layout = getattr(submission, "question_layout", None) or {}

    result = []
    for it in ordered_items(items, layout):
        q = q_map.get(it["question_id"])
        if not q:
            continue
        perm = _perm_of(layout, q.id)
        stu = answers.get(str(q.id)) or answers.get(q.id) or {}
        # 学生答案存于展示 key 空间，先还原回原始 key 空间（判分与展示共用）
        raw_stu = unmap_student_answer(stu, perm, q.options or [])
        entry = {
            "question_id": q.id,
            "score": it.get("score", float(q.score)),
            "qtype": q.qtype,
            "qtype_display": q.get_qtype_display(),
            "stem": q.stem,
            # S4：回看归序——用原始选项（key 原样），不用 permuted_options
            "options": [{"key": o.get("key"), "text": o.get("text")} for o in (q.options or [])],
            "correct_answer": _sorted_answer_keys(q.answer or {}),
            "analysis": q.analysis if show_analysis else "",
            "student_answer": _sorted_answer_keys(raw_stu),
            "is_objective": q.is_objective,
            "is_correct": None,
            "my_score": None,
            "pending": False,
        }
        if q.is_objective:
            is_correct, my_score = score_for_item(q, it.get("score", q.score), raw_stu)
            entry["is_correct"] = is_correct
            entry["my_score"] = float(my_score) if my_score is not None else None
        else:
            graded = subjective_scores.get(str(q.id), subjective_scores.get(q.id))
            if graded is not None:
                entry["my_score"] = float(graded)
            else:
                entry["pending"] = True
        if q.qtype == Question.QType.BLANK:
            entry["blank_count"] = blank_count_of(q)
        result.append(entry)
    return result
