"""自动评分（需求 S-Q-02 / T-E-07）。

答案统一约定：
- single / judge: answer = {"key": "A"}，学生答案同结构
- multi:          answer = {"keys": ["A","C"]}
- blank:          answer = {"blanks": ["xxx", "yyy"]}（按顺序，忽略首尾空白，大小写不敏感）
主观题（short）：grade_objective 保持返回 (None, None)（作业/考试教师批改流依赖此契约）；
labs 场景经 grade_lab_question → grade_subjective 做相似度预评分。
"""
import re
import unicodedata
from decimal import Decimal
from difflib import SequenceMatcher

# 中文停用词（整合自实验平台 quiz-api-router 的算法，内置精简集合）
STOP_WORDS = {
    "的", "了", "是", "在", "和", "与", "及", "或", "对", "为", "以", "等",
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "这", "那", "这个", "那个",
    "之", "与", "并", "把", "被", "让", "向", "从", "而", "且", "但", "即", "所",
    "有", "无", "不", "没", "很", "都", "也", "就", "还", "才", "只", "会", "能",
}

_PUNCT_RE = re.compile(r"[\s，。、；：？！,.;:?!'\"“”‘’（）()\[\]【】<>《》\-—_…·]+")


def _normalize(text: str) -> str:
    """归一化：全角转半角、小写、去标点与空白。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text)).lower()
    return _PUNCT_RE.sub("", text)


def _keywords(text: str) -> set:
    """停用词过滤后的字符 2-gram 关键词集合（中文无空格分词，bigram 折中）。"""
    norm = _normalize(text)
    if len(norm) <= 1:
        return {norm} if norm else set()
    grams = {norm[i: i + 2] for i in range(len(norm) - 1)}
    return {g for g in grams if not any(ch in STOP_WORDS for ch in g)}


def levenshtein_ratio(s1: str, s2: str) -> float:
    """编辑距离比例（0~1）。纯标准库实现，避免新依赖。"""
    if not s1 or not s2:
        return 0.0
    return SequenceMatcher(None, s1, s2).ratio()


def keyword_match_ratio(user_answer: str, correct_answer: str) -> float:
    """关键词命中率（去停用词后）。"""
    kw_user, kw_ref = _keywords(user_answer), _keywords(correct_answer)
    if not kw_ref:
        return 0.0
    return len(kw_user & kw_ref) / len(kw_ref)


def string_similarity(user_answer: str, correct_answer: str) -> float:
    return levenshtein_ratio(_normalize(user_answer), _normalize(correct_answer))


# 阈值（对齐实验平台已验证算法）
SIM_WRONG = 0.3    # 低于此判 0 分
SIM_CORRECT = 0.9  # 高于此判满分
WEIGHT_KW = 0.7    # 关键词命中权重
WEIGHT_STR = 0.3   # 编辑距离权重


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
        return None, None  # 主观题不自动评分（契约不变，作业/考试教师批改流依赖）

    return ok, (full if ok else Decimal("0"))


def subjective_similarity(user_answer: str, correct_answer: str) -> float:
    """综合相似度 = 0.7*关键词命中 + 0.3*编辑距离（实验平台同款加权）。"""
    return WEIGHT_KW * keyword_match_ratio(user_answer, correct_answer) + WEIGHT_STR * string_similarity(
        user_answer, correct_answer
    )


def grade_subjective(question, student_answer: dict):
    """主观题相似度预评分。返回 (verdict, score, similarity)。

    - sim < 0.3 → wrong / 0 分
    - sim >= 0.9 → correct / 满分
    - 中间 → pending_review / 比例部分分（教师可复核调整）
    """
    correct = question.answer or {}
    ref_text = str(correct.get("text") or correct.get("value") or question.analysis or "")
    stu_text = str(student_answer.get("text") or student_answer.get("value") or "")
    full = Decimal(str(question.score)) or Decimal("1")

    if not stu_text.strip():
        return "wrong", Decimal("0"), 0.0
    if not ref_text.strip():
        # 无参考答案，无法自动评分，交教师批改
        return "pending_review", None, None

    sim = subjective_similarity(stu_text, ref_text)
    if sim < SIM_WRONG:
        return "wrong", Decimal("0"), round(sim, 4)
    if sim >= SIM_CORRECT:
        return "correct", full, round(sim, 4)
    return "pending_review", (full * Decimal(str(round(sim, 4)))).quantize(Decimal("0.1")), round(sim, 4)


def grade_lab_question(question, student_answer: dict):
    """labs 评分派发入口：客观题走 grade_objective，主观题走 grade_subjective。

    返回统一三元组 (verdict, score, similarity)：
    - 客观题 correct → (correct, score, None)；错误 → (wrong, 0, None)
    - 主观题 → grade_subjective 结果；None 分数表示交教师批改
    """
    if getattr(question, "qtype", None) == "short":
        return grade_subjective(question, student_answer)
    is_correct, score = grade_objective(question, student_answer)
    if is_correct is None:
        return "pending_review", None, None
    return ("correct" if is_correct else "wrong"), (score if is_correct else Decimal("0")), None
