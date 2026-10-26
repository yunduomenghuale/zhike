# -*- coding: utf-8 -*-
"""AI 多类型题目生成流水线（需求 T-Q-01，题库导入/AI 生题阶段 4）。

教师端「AI 自动生成题目」：一次提交多组「题型 × 数量 × 每题分值」，
后台 daemon 线程逐组调用 LLM 生成，全部草稿落 QuestionDraftBatch
（origin=AI_GEN），教师预览编辑后走 draft_pipeline 批量入库
（与文档导入共用同一批次池与 save 管道）。

设计要点（设计方案 §3）：
- 提交即返回 task_id（apps/ai/tasks.py submit_ai_task），进度/结果持久化
  AITask 行，前端轮询 /api/ai-tasks/<id>/，离开页面/刷新不丢失；
- 上下文收敛：章节 PPT（parsed_pages）+ 知识库 chunk，合计 CONTEXT_LIMIT
  字上限，多组题型共享一份（避免每组重复取材撑爆 token）；
- 逐组生成；组内按 GEN_CHUNK（3 题/次）分块多次调用，progress 按题计数
  （done/total 单位=题）逐块落库，前端轮询可见逐块实时推进；单组失败不整批
  失败，记 degraded + failed_groups 原因，成功组照常建批次；
- 全部组失败才抛异常（上层标 FAILED + error 摘要）；
- 无 Key 环境（provider=mock）：生成确定性假题（【模拟】前缀），
  保证演示与联调链路可用；
- 防重复提交：AITask.uniq_active_question_gen 部分唯一索引
  （同教师同课程同时只允许一条 pending/running），端点捕获转中文文案。
"""
from __future__ import annotations

import logging
import re

from django.conf import settings
from django.utils import timezone

from apps.ai.calllog import scene_decorator
from apps.ai.models import AICallLog, AITask
from apps.ai.providers.factory import get_provider

logger = logging.getLogger(__name__)

# 多组题型共享的上下文上限（旧同步版 generate_questions 为 3000，多组场景放宽）
CONTEXT_LIMIT = 8000

# 每次 LLM 调用生成的题数：按题分块多次调用，进度按题实时推进（前端 2.5s 轮询
# 可见逐块推进），且小块 JSON 输出更稳（大块易截断/单条不合规整组丢弃）
GEN_CHUNK = 3

QTYPE_LABELS = {"single": "单选题", "multi": "多选题", "judge": "判断题", "blank": "填空题", "short": "简答题"}
DIFFICULTIES = ("easy", "medium", "hard")

# 题型契约提示（与 import_parser/draft_pipeline 的答案结构一一对应）
_QTYPE_HINT = (
    "单选题 options=[{key,text}]（至少 2 个），answer={\"key\":\"X\"}（X 为选项 key）；"
    "多选题 options 至少 2 个，answer={\"keys\":[\"X\",\"Y\"]}（至少 2 个 key）；"
    "判断题 answer={\"key\":\"A\"}（A=正确）或 {\"key\":\"B\"}（B=错误），不要 options；"
    "填空题题干用「____」表示空位（至少 1 个空），options=[]，"
    "answer={\"blanks\":[{\"text\":\"该空答案\"},...]}（每空一个元素，按顺序）；"
    "简答题 options=[]，answer={\"text\":\"参考答案\"}。"
)


def _save(task: AITask, *fields: str) -> None:
    """按字段落库（避免整行并发写覆盖 progress/result）。"""
    task.save(update_fields=list(fields) + ["updated_at"])


def _chat_timeout(provider) -> int:
    """生题调用超时：管理端该能力 timeout > AI_ANALYTICS_TIMEOUT > 120（后台线程不占请求周期）。"""
    return int(
        getattr(provider, "timeout", None)
        or getattr(settings, "AI_ANALYTICS_TIMEOUT", 120)
        or 120
    )


def _gather_context(course_id, catalog_id) -> tuple[str, str]:
    """章节 PPT + 知识库资料（合计收敛 CONTEXT_LIMIT 字）；返回 (context, catalog_title)。"""
    from apps.courses.models import Catalog, PPTResource
    from apps.knowledge.models import KnowledgeChunk

    parts: list[str] = []
    catalog_title = ""
    if catalog_id:
        cat = Catalog.objects.filter(id=catalog_id).first()
        catalog_title = cat.title if cat else ""
        ppt = (
            PPTResource.objects.filter(catalog_id=catalog_id, is_active=True)
            .order_by("-version")
            .first()
        )
        if ppt and ppt.parsed_pages:
            for pg in ppt.parsed_pages[:25]:
                seg = f"{pg.get('title', '')} {pg.get('body', '')}".strip()
                if seg:
                    parts.append(seg)
    parts += list(
        KnowledgeChunk.objects.filter(course_id=course_id).values_list("content", flat=True)[:5]
    )
    return "\n".join(p for p in parts if p).strip()[:CONTEXT_LIMIT], catalog_title


def _group_messages(qtype: str, count: int, score, context: str, objective: str, catalog_title: str) -> list[dict]:
    """单组题型的生题 messages（题型契约 + 上下文 + 教学目标）。"""
    label = QTYPE_LABELS.get(qtype, qtype)
    score_text = f"{score:g}"
    user_prompt = (
        f"请依据下面的课程内容出题。\n"
        f"章节：{catalog_title or '（未指定）'}\n"
        f"教学目标/出题要求：{objective or '覆盖本章核心知识点，难度适中'}\n"
        f"题型={label}，数量={count}，每题分值={score_text} 分。\n"
        f"严格只输出 JSON 数组（不要任何解释文字），每个元素含字段："
        f"qtype, stem, options([{{key,text}}]), answer, analysis, difficulty(easy/medium/hard), knowledge_tags(数组)。\n"
        f"{_QTYPE_HINT}\n\n"
        f"课程内容：\n{context or '（暂无课件与资料，请基于该章节标题的常见知识点合理出题）'}"
    )
    return [
        {"role": "system", "content": "你是严谨的高校命题老师，只输出规范的 JSON，不输出多余文字。"},
        {"role": "user", "content": user_prompt},
    ]


def _sanitize_item(raw, qtype: str, score) -> dict | None:
    """LLM 单条输出 → 草稿结构（与 import_parser 输出同构）；不合规返回 None。"""
    if not isinstance(raw, dict):
        return None
    stem = str(raw.get("stem") or "").strip()[:1000]
    if not stem:
        return None

    options: list[dict] = []
    used: set[str] = set()
    raw_options = raw.get("options")
    if isinstance(raw_options, list):
        for o in raw_options:
            if not isinstance(o, dict):
                continue
            text = str(o.get("text") or "").strip()
            key = str(o.get("key") or "").strip().upper()
            if not text or not re.fullmatch(r"[A-Z]", key) or key in used:
                continue
            used.add(key)
            options.append({"key": key, "text": text[:500]})

    answer = raw.get("answer") if isinstance(raw.get("answer"), dict) else {}
    difficulty = str(raw.get("difficulty") or "medium").strip()
    if difficulty not in DIFFICULTIES:
        difficulty = "medium"
    raw_tags = raw.get("knowledge_tags")
    tags = (
        [str(t).strip()[:30] for t in raw_tags if str(t).strip()][:10]
        if isinstance(raw_tags, list)
        else []
    )

    item = {
        "qtype": qtype,
        "stem": stem,
        "options": options,
        "answer": {},
        "analysis": str(raw.get("analysis") or "").strip()[:2000],
        "score": score,
        "difficulty": difficulty,
        "knowledge_tags": tags,
        "_warnings": [],
    }

    if qtype == "single":
        key = str(answer.get("key") or "").strip().upper()
        if len(options) < 2 or key not in used:
            return None
        item["answer"] = {"key": key}
    elif qtype == "multi":
        raw_keys = answer.get("keys")
        if isinstance(raw_keys, str):
            raw_keys = list(re.findall(r"[A-Z]", raw_keys.upper()))
        if not isinstance(raw_keys, list):
            return None
        keys: list[str] = []
        for k in raw_keys:
            k = str(k).strip().upper()
            if k in used and k not in keys:
                keys.append(k)
        if len(options) < 2 or len(keys) < 2:
            return None
        item["answer"] = {"keys": keys}
    elif qtype == "judge":
        from .draft_pipeline import normalize_judge_key

        key = normalize_judge_key(answer.get("key") if answer.get("key") is not None else answer.get("text"))
        if key is None:
            return None
        item["answer"] = {"key": key}
    elif qtype == "blank":
        blanks = answer.get("blanks")
        if not isinstance(blanks, list):
            return None
        texts = [
            (str(b.get("text") or "").strip() if isinstance(b, dict) else str(b or "").strip())
            for b in blanks
        ]
        texts = [t for t in texts if t]
        if not texts:
            return None
        # 不逐空赋分：入库管道按每题总分均分（余数补前空，Σ=score）
        item["answer"] = {"blanks": [{"text": t[:500]} for t in texts]}
    else:  # short 简答：无结构约束
        item["answer"] = {"text": str(answer.get("text") or "").strip()[:2000]}
    return item


def _chat_group(provider, qtype: str, count: int, score, context: str, objective: str, catalog_title: str) -> list[dict]:
    """单组题型一次 LLM 调用；异常上抛由调用方计入 failed_groups。"""
    from apps.ai.services import _safe_json

    messages = _group_messages(qtype, count, score, context, objective, catalog_title)
    raw = provider.chat(
        messages,
        temperature=0.3,
        timeout=_chat_timeout(provider),
        retries=2,
        enable_thinking=False,
    )
    result = _safe_json(raw, default=[])
    return result if isinstance(result, list) else []


def _mock_group(qtype: str, count: int, score, catalog_title: str) -> list[dict]:
    """Mock 确定性假题（无 Key 环境演示用）：按题型契约拼装，结构必定合规。"""
    title = catalog_title or "本章"
    items: list[dict] = []
    for i in range(1, count + 1):
        stem = f"【模拟】{title}第 {i} 题"
        analysis = f"【模拟数据】本题考查{title}的核心概念（第 {i} 题）。"
        item = {
            "qtype": qtype,
            "stem": "",
            "options": [],
            "answer": {},
            "analysis": analysis,
            "score": score,
            "difficulty": "medium",
            "knowledge_tags": [f"{title}·模拟知识点"],
            "_warnings": [],
        }
        if qtype == "single":
            item["stem"] = f"{stem}：以下哪个选项是正确的？"
            item["options"] = [
                {"key": "A", "text": "模拟选项甲"},
                {"key": "B", "text": "模拟选项乙"},
                {"key": "C", "text": "模拟选项丙"},
                {"key": "D", "text": "模拟选项丁"},
            ]
            item["answer"] = {"key": "ABCD"[(i - 1) % 4]}
        elif qtype == "multi":
            item["stem"] = f"{stem}：以下哪些选项是正确的？（多选）"
            item["options"] = [
                {"key": "A", "text": "模拟选项甲"},
                {"key": "B", "text": "模拟选项乙"},
                {"key": "C", "text": "模拟选项丙"},
                {"key": "D", "text": "模拟选项丁"},
            ]
            keys = ["A", "B", "C", "D"]
            item["answer"] = {"keys": [keys[(i - 1) % 4], keys[i % 4]]}
        elif qtype == "judge":
            item["stem"] = f"{stem}：该说法是正确的。"
            item["answer"] = {"key": "A" if i % 2 else "B"}
        elif qtype == "blank":
            item["stem"] = f"{stem}：____ 是{title}的核心概念，另一个关键概念是 ____。"
            item["answer"] = {"blanks": [{"text": f"模拟答案{i}-1"}, {"text": f"模拟答案{i}-2"}]}
        else:  # short
            item["stem"] = f"{stem}：请简述{title}的核心内容。"
            item["answer"] = {"text": f"【模拟数据】{title}的核心内容包含概念甲、概念乙与应用丙。"}
        items.append(item)
    return items


@scene_decorator(
    AICallLog.Scene.QUESTION_GEN,
    course_getter=lambda args, kwargs: getattr(args[0], "course_id", None),
)
def run_question_gen(task: AITask) -> None:
    """AI 多类型生题：按 groups（题型×数量×每题分值）逐组生成 → 建 AI 草稿批次。

    groups/objective 由提交端点写入 task.progress（AITask 无 groups 字段）。
    成功：task.result = {batch_id, total, degraded, failed_groups}，前端凭
    batch_id 进批次预览编辑；全部组失败：抛异常由框架标 FAILED。
    """
    config = task.progress or {}
    groups = config.get("groups") or []
    objective = str(config.get("objective") or "")
    if not groups:
        raise ValueError("生题配置缺失（groups 为空）")

    provider = get_provider("chat")
    is_mock = provider.name == "mock"

    # ---- S0：上下文取材（多组共享一份，收敛 CONTEXT_LIMIT 字）----
    context, catalog_title = _gather_context(task.course_id, task.catalog_id)
    # 进度按题计数（done/total 单位=题）：每组再按 GEN_CHUNK 分块多次调用，
    # 每块落一次 progress，前端轮询可见「正在生成多选题（4/10）…」逐块推进
    total_q = sum(int(g.get("count") or 0) for g in groups)
    # progress 全程保留 groups/objective 配置（失败排查与前端分组进度展示用）
    task.progress = {
        "stage": "gen",
        "done": 0,
        "total": total_q,
        "groups": groups,
        "objective": objective,
        "message": "正在生成题目…",
    }
    _save(task, "progress")

    drafts: list[dict] = []
    failed_groups: list[dict] = []
    done_q = 0
    for group in groups:
        qtype = str(group.get("qtype") or "").strip()
        count = int(group.get("count") or 0)
        score = group.get("score")
        label = QTYPE_LABELS.get(qtype, qtype)
        dropped = 0
        remaining = count
        while remaining > 0:
            n = min(GEN_CHUNK, remaining)
            task.progress = {
                "stage": "gen",
                "done": done_q,
                "total": total_q,
                "groups": groups,
                "objective": objective,
                "message": f"正在生成{label}（{done_q}/{total_q}）…",
            }
            _save(task, "progress")
            try:
                if is_mock:
                    items = _mock_group(qtype, n, score, catalog_title)
                else:
                    items = _chat_group(provider, qtype, n, score, context, objective, catalog_title)
            except Exception as exc:
                logger.exception("AI 生题组失败（task_id=%s, qtype=%s）", task.id, qtype)
                failed_groups.append({"qtype": qtype, "error": f"{type(exc).__name__}: {exc}"[:200]})
                break  # 单块失败放弃该组余下块（同一调用大概率同样失败），进下一组
            for raw in items:
                item = _sanitize_item(raw, qtype, score)
                if item is None:
                    dropped += 1
                    continue
                drafts.append(item)
            done_q += n  # 按请求题数推进：进度稳定只增，与实际产出差额在终态消息体现
            remaining -= n
        if dropped:
            failed_groups.append({"qtype": qtype, "error": f"{dropped} 条生成结果不合规已丢弃"})

    if not drafts:
        reasons = "；".join(f"{QTYPE_LABELS.get(g.get('qtype'), g.get('qtype'))}：{g.get('error')}" for g in failed_groups)
        raise ValueError(f"所有题型均生成失败（{reasons or '未知原因'}）"[:300])

    # ---- 建草稿批次（与文档导入共用待入库池）----
    from apps.questions.models import QuestionDraftBatch

    batch = QuestionDraftBatch(
        origin=QuestionDraftBatch.Origin.AI_GEN,
        course_id=task.course_id,
        catalog_id=task.catalog_id,
        creator=task.triggered_by,
        task=task,
        drafts=drafts,
        stats={
            "total": len(drafts),
            "warned": 0,
            "groups": len(groups),
            "degraded": bool(failed_groups),
            "failed_groups": failed_groups,
        },
    )
    batch.save()

    task.result = {
        "batch_id": batch.id,
        "total": len(drafts),
        "degraded": bool(failed_groups),
        "failed_groups": failed_groups,
        "catalog_title": catalog_title,
    }
    task.progress = {
        "stage": "done",
        "done": total_q,
        "total": total_q,
        "groups": groups,
        "objective": objective,
        "message": f"已生成 {len(drafts)} 道题目，请预览编辑后入库",
    }
    task.status = AITask.Status.SUCCESS
    task.finished_at = timezone.now()
    _save(task, "progress", "result", "status", "finished_at")
