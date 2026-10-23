# -*- coding: utf-8 -*-
"""题目草稿批次入库管道（需求 T-Q-01 导入/AI 生成共用）。

流水线（设计方案 §2.4/§4.2）：
① 规范化：填空题按空数均分每题总分（_split_score，与模型 save 同口径）、
   judge 答案归一并补 A/B 选项、选项 key 规整（大写/补缺/去空文本）；
② 结构校验：single/multi ≥2 选项且答案 key ∈ 选项 keys、judge 答案 ∈ A/B，
   违者该条 failed（中文原因），不整批回滚；
③ 逐条 QuestionSerializer 校验（章节归属/教师归属/填空赋分全部复用）；
④ 精确查重：同课程同题干已存在 → skipped（防请求重试/重复导入重复入库）；
⑤ 成功条目从 drafts 移除（规范化 JSON 相等匹配，重复项按序移除首个，
   兜底按 题型+题干 匹配——前端编辑后未回传的旧版本也能移除）；
⑥ drafts 空 → status=saved 并删除上传文件（入库即删）。
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError

from .models import Question, QuestionDraftBatch, _split_score
from .serializers import QuestionSerializer

# 预览默认分值（草稿未带分值时的兜底，与 import_parser.DEFAULT_SCORES 同口径）
DEFAULT_SCORES = {"single": 2, "multi": 3, "judge": 2, "blank": 4, "short": 10}

_JUDGE_TRUE = {"A", "T", "TRUE", "√", "✓", "对", "正确", "是"}
_JUDGE_FALSE = {"B", "F", "FALSE", "×", "✗", "错", "错误", "误", "否", "不对", "不正确"}
_KEY_RE = re.compile(r"[A-Z]")


class _UserShim:
    """QuestionSerializer.validate 只访问 request.user，构造最小请求替身。"""

    def __init__(self, user):
        self.user = user


def _as_float(value):
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return None


def normalize_judge_key(raw) -> str | None:
    """判断题答案归一为 A（正确）/ B（错误）；无法归一返回 None。"""
    if raw is None:
        return None
    t = str(raw).strip().replace(" ", "").replace("　", "").upper()
    if not t:
        return None
    if t in _JUDGE_TRUE:
        return "A"
    if t in _JUDGE_FALSE:
        return "B"
    return None


def _normalize_options(raw_options) -> list[dict]:
    """选项规整：去空文本、key 大写，缺 key/重复 key 按序补下一个空闲字母。"""
    options, used, pool = [], set(), "ABCDEFGH"
    for o in raw_options or []:
        if not isinstance(o, dict):
            continue
        text = str(o.get("text") or "").strip()
        if not text:
            continue
        key = str(o.get("key") or "").strip().upper()
        if not _KEY_RE.fullmatch(key) or key in used:
            while pool and pool[0] in used:
                pool = pool[1:]
            key = pool[0] if pool else str(len(options) + 1)
            pool = pool[1:]
        used.add(key)
        options.append({"key": key, "text": text})
    return options


def _normalize_item(item, batch, source):
    """单条草稿 → QuestionSerializer 入参；返回 (payload, None) 或 (None, 中文错误)。"""
    if not isinstance(item, dict):
        return None, "草稿数据格式不正确"
    qtype = str(item.get("qtype") or "").strip()
    if qtype not in {q for q, _ in Question.QType.choices}:
        return None, f"不支持的题型：{qtype or '空'}"
    stem = str(item.get("stem") or "").strip()
    if not stem:
        return None, "题干不能为空"

    options = _normalize_options(item.get("options"))
    answer = item.get("answer") if isinstance(item.get("answer"), dict) else {}
    score = _as_float(item.get("score"))
    if score is None or score <= 0:
        score = DEFAULT_SCORES.get(qtype, 2)
    difficulty = str(item.get("difficulty") or "medium").strip() or "medium"
    tags = item.get("knowledge_tags") if isinstance(item.get("knowledge_tags"), list) else []
    analysis = str(item.get("analysis") or "").strip()

    if qtype == "single":
        if len(options) < 2:
            return None, "单选题至少需要 2 个选项"
        key = str(answer.get("key") or "").strip().upper()
        if not key:
            return None, "单选题未设置答案"
        if key not in {o["key"] for o in options}:
            return None, f"单选题答案 {key} 不在选项中"
        answer_payload = {"key": key}

    elif qtype == "multi":
        if len(options) < 2:
            return None, "多选题至少需要 2 个选项"
        raw_keys = answer.get("keys")
        if isinstance(raw_keys, str):  # "AC" / "A、C" 宽容解析
            raw_keys = _KEY_RE.findall(raw_keys.upper())
        if not isinstance(raw_keys, list):
            return None, "多选题未设置答案"
        keys = [str(k).strip().upper() for k in raw_keys if str(k).strip()]
        if len(keys) < 2:
            return None, "多选题答案至少包含 2 个选项"
        bad = [k for k in keys if k not in {o["key"] for o in options}]
        if bad:
            return None, f"多选题答案 {'、'.join(bad)} 不在选项中"
        answer_payload = {"keys": keys}

    elif qtype == "judge":
        key = normalize_judge_key(answer.get("key") if answer.get("key") is not None else answer.get("text"))
        if key is None:
            return None, "判断题答案必须为 A（正确）或 B（错误）"
        if not options:  # 兜底对错项（模型 save 也会补，这里显式补保证序列化数据完整）
            options = [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}]
        answer_payload = {"key": key}

    elif qtype == "blank":
        blanks_raw = answer.get("blanks")
        if not isinstance(blanks_raw, list) or not blanks_raw:
            return None, "填空题至少需要设置一个空"
        texts, given = [], []
        for i, b in enumerate(blanks_raw, 1):
            if not isinstance(b, dict):
                return None, f"第{i}空的答案格式不正确"
            text = str(b.get("text") or "").strip()
            if not text:
                return None, f"第{i}空的答案不能为空"
            texts.append(text)
            given.append(b.get("score"))
        if any(s is not None and str(s).strip() != "" for s in given):
            blanks = []
            for i, (text, s) in enumerate(zip(texts, given), 1):
                v = _as_float(s)
                if v is None:
                    return None, f"第{i}空的分值必须是数字"
                if v <= 0:
                    return None, f"第{i}空的分值必须大于 0"
                blanks.append({"text": text, "score": v})
        else:
            # 未逐空赋分：按每题总分均分（余数补前空，Σ=总分）
            blanks = [
                {"text": text, "score": float(part)}
                for text, part in zip(texts, _split_score(score, len(texts)))
            ]
        answer_payload = {"blanks": blanks}

    else:  # short 简答：参考答案原文，无结构约束
        answer_payload = {"text": str(answer.get("text") or "").strip()}

    return {
        "course": batch.course_id,
        "catalog": batch.catalog_id,
        "qtype": qtype,
        "stem": stem,
        "options": options,
        "answer": answer_payload,
        "analysis": analysis,
        "score": score,
        "difficulty": difficulty,
        "knowledge_tags": [str(t) for t in tags][:10],
        "source": source,
        "status": Question.Status.DRAFT,
    }, None


def _flatten_errors(errors) -> str:
    """DRF 错误 dict → 中文可读文案。"""
    parts = []
    for field, msgs in errors.items():
        text = "；".join(str(m) for m in msgs) if isinstance(msgs, list) else str(msgs)
        parts.append(text if field in ("non_field_errors", "__all__") else f"{field}: {text}")
    return "；".join(parts) or "数据校验失败"


def _draft_key(draft) -> str:
    """草稿规范化指纹：数字统一转 float（2 与 2.0 视为相等）、键排序。"""

    def norm(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return round(float(v), 6)
        if isinstance(v, dict):
            return {k: norm(x) for k, x in sorted(v.items())}
        if isinstance(v, (list, tuple)):
            return [norm(x) for x in v]
        return v

    return json.dumps(norm(draft), sort_keys=True, ensure_ascii=False)


def _remove_drafts(remaining: list, consumed: list) -> list:
    """从剩余草稿中按序移除已成功入库的条目（精确匹配优先，题干+题型兜底）。"""
    pool = list(remaining or [])
    for item in consumed:
        key = _draft_key(item)
        hit = next((i for i, d in enumerate(pool) if _draft_key(d) == key), None)
        if hit is None:
            sig = (item.get("qtype"), str(item.get("stem") or "").strip())
            hit = next(
                (i for i, d in enumerate(pool)
                 if (d.get("qtype"), str(d.get("stem") or "").strip()) == sig),
                None,
            )
        if hit is not None:
            pool.pop(hit)
    return pool


def save_batch_drafts(batch: QuestionDraftBatch, items, user) -> dict:
    """批量入库入口；返回 {saved:[id...], skipped:n, failed:[{index,error}], remaining:n}。"""
    if not isinstance(items, list) or not items:
        raise ValidationError("提交内容不能为空")
    if batch.status == QuestionDraftBatch.Status.SAVED:
        raise ValidationError("该批次已全部入库")
    if not batch.catalog_id:
        raise ValidationError("请先为批次选择目标章节")

    source = (
        Question.Source.AI
        if batch.origin == QuestionDraftBatch.Origin.AI_GEN
        else Question.Source.IMPORT
    )
    shim = _UserShim(user)
    saved_ids: list[int] = []
    skipped = 0
    failed: list[dict] = []
    consumed: list[dict] = []

    for idx, item in enumerate(items):
        payload, err = _normalize_item(item, batch, source)
        if err:
            failed.append({"index": idx, "error": err})
            continue
        serializer = QuestionSerializer(data=payload, context={"request": shim})
        if not serializer.is_valid():
            failed.append({"index": idx, "error": _flatten_errors(serializer.errors)})
            continue
        # 精确查重：同课程同题干已存在 → 跳过（草稿保留，教师可改题干后重试）
        if Question.objects.filter(course_id=batch.course_id, stem=payload["stem"]).exists():
            skipped += 1
            continue
        question = serializer.save(creator=batch.creator or user)
        saved_ids.append(question.id)
        consumed.append(item)

    remaining = _remove_drafts(batch.drafts or [], consumed)
    batch.drafts = remaining
    if not remaining:
        # 入库即删：草稿全部处理完 → 批次置 saved 并删除上传文件
        batch.status = QuestionDraftBatch.Status.SAVED
        if batch.file:
            batch.file.delete(save=False)
            batch.file = None
    stats = dict(batch.stats or {})
    stats.update({"saved": len(saved_ids), "skipped": skipped, "failed": len(failed), "remaining": len(remaining)})
    batch.stats = stats
    batch.save()
    return {"saved": saved_ids, "skipped": skipped, "failed": failed, "remaining": len(remaining)}
