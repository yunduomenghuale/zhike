"""客观题自动评分（需求 S-Q-02 / T-E-07）。

答案统一约定：
- single / judge: answer = {"key": "A"}，学生答案同结构
- multi:          answer = {"keys": ["A","C"]}
- blank:          answer = {"blanks": ["xxx", "yyy"]}（按顺序，忽略首尾空白，大小写不敏感）
主观题（short）返回 None，交由教师/二期 AI 批改。
"""
from decimal import Decimal


def grade_objective(question, student_answer: dict):
    """返回 (is_correct, score)。主观题返回 (None, None)。"""
    qtype = question.qtype
    correct = question.answer or {}
    full = Decimal(str(question.score))

    if qtype in ("single", "judge"):
        ok = str(student_answer.get("key", "")).strip() == str(correct.get("key", "")).strip()
    elif qtype == "multi":
        ok = sorted(map(str, student_answer.get("keys", []))) == sorted(map(str, correct.get("keys", [])))
    elif qtype == "blank":
        stu = [str(x).strip().lower() for x in student_answer.get("blanks", [])]
        std = [str(x).strip().lower() for x in correct.get("blanks", [])]
        ok = stu == std
    else:
        return None, None  # 主观题不自动评分

    return ok, (full if ok else Decimal("0"))
