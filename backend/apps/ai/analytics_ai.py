"""AI 分析流水线：班级学情分析（S0-S3）与章节学习总结（P2 占位）。

由 apps/ai/tasks.py 的 _run_task 在恢复的请求上下文中分发调用。

核心原则（见 docs/AI学情分析深化与章节学习总结设计方案.md §3）：
- **统计先于 AI**：S0 聚合全部由 analytics/services.py 的
  build_class_stats_v2 代码完成（正确率/知识点预聚合/缺交名单），LLM 只做
  归因解读与建议生成——同时解决「时长」与「深度」：token 预算花在洞察上；
- **分段 + 批并发**：班级报告 3 段顺序生成（后段带前文摘要续写），学生简评
  5 人/批、批内 4 并发，与分批讲稿同款思路；as_completed 增量合并落库，
  前端轮询能看到简评一条条长出；
- **失败域隔离**：单段/单批失败重试一次 → 降级为统计数字拼装，报告永远
  完整可用（result.degraded 标记，前端角标提示可重新生成）；
- **Mock**：provider.name == "mock" 时走确定性假数据（不走网络），
  无 Key 环境可演示全流程；
- 全部调用经 scene_decorator(ANALYTICS) 声明场景，AICallLog 可计量成本。
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings
from django.utils import timezone

from .calllog import copy_call_context, run_in_context, scene_decorator
from .models import AICallLog, AITask
from .providers.factory import get_provider

logger = logging.getLogger(__name__)

BATCH_SIZE = 5       # 学生简评批大小（批 prompt 总量可控）
BATCH_WORKERS = 4    # 批内并发上限（DashScope/本地模型 QPS 友好）

# 班级报告三段（每段返回的 JSON key）；顺序执行，后段带前文摘要续写
SECTION_KEYS = (("overview", "knowledge"), ("layers", "warnings"), ("advice",))
SECTION_MESSAGES = (
    "正在生成整体学情与知识点分析（1/3）…",
    "正在生成学生分层与风险预警（2/3）…",
    "正在生成教学干预建议（3/3）…",
)

_NO_DATA_REPORT = (
    "本班学生暂无学习数据（无章节练习/作业/考试/实验/问答/视频学习记录），"
    "暂无法生成学情分析。可待学生产生学习行为后再试。"
)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _save(task: AITask, *fields: str) -> None:
    """按字段落库（避免整行并发写覆盖 progress/result）。"""
    task.save(update_fields=list(fields) + ["updated_at"])


def _now_iso() -> str:
    return timezone.now().isoformat()


def _chat_timeout(provider) -> int:
    """分析类调用超时（F4）：管理端该能力 timeout > AI_ANALYTICS_TIMEOUT > 120。

    分析输入长（约 6k tokens）、输出长且跑在后台线程不占请求周期，
    口径比讲稿（AI_SCRIPT_TIMEOUT 45s）宽松，本地慢模型可调 env 加大。
    """
    return int(
        getattr(provider, "timeout", None)
        or getattr(settings, "AI_ANALYTICS_TIMEOUT", 120)
        or 120
    )


def _chat_json(provider, messages, timeout):
    """一次 chat 调用 + JSON 解析；异常上抛由调用方决定重试/降级。"""
    from .services import _safe_json

    raw = provider.chat(messages, temperature=0.3, timeout=timeout, retries=2, enable_thinking=False)
    return _safe_json(raw, default=None)


def _digest_sections(sections: dict) -> str:
    """前文摘要（给后段续写用，控制 token）。"""
    parts = []
    for value in sections.values():
        text = str(value or "").strip()
        if text:
            parts.append(text[:160])
    return "\n".join(parts)[:600]


# ---------------------------------------------------------------------------
# Prompt 上下文
# ---------------------------------------------------------------------------
def _prompt_context(stats: dict, no_data_students: list) -> dict:
    """喂给 LLM 的班级级上下文（统计先于 AI：全部代码预计算）。"""
    summary = dict(stats.get("summary") or {})
    summary.setdefault("analyzed_count", summary.get("student_count", 0) - len(no_data_students))
    summary["no_data_count"] = len(no_data_students)
    return {
        "course_name": stats.get("course_name"),
        "class_name": stats.get("class_name"),
        "summary": summary,
        "knowledge_agg": stats.get("knowledge_agg") or [],
        "chapter_matrix": stats.get("chapter_matrix") or [],
        "homework_detail": stats.get("homework_detail") or [],
        "exam_detail": stats.get("exam_detail") or [],
        "lab_detail": stats.get("lab_detail") or [],
        "qa_heat": stats.get("qa_heat") or {},
        "video_behavior": stats.get("video_behavior") or {},
        "time_trend": stats.get("time_trend") or {},
    }


def _students_brief(stats: dict) -> list:
    """R2 分层用的学生精简明细（姓名 + 关键指标 + 预警）。"""
    brief = []
    for row in stats.get("students") or []:
        if not row.get("has_data"):
            continue
        last_active = row.get("last_active")
        brief.append({
            "student_id": row.get("student_id"),
            "姓名": row.get("name"),
            "练习正确率%": row.get("accuracy"),
            "练习题量": row.get("practice_total"),
            "作业提交": f"{row.get('homework_submitted')}/{row.get('homework_total')}",
            "缺交作业": row.get("homework_missing") or [],
            "考试参加": f"{row.get('exam_taken')}/{row.get('exam_total')}",
            "缺考考试": row.get("exam_missing") or [],
            "考试均分": row.get("avg_exam_score"),
            "实验完成": f"{row.get('experiment_done')}/{row.get('experiment_total')}",
            "预警": row.get("warnings") or [],
            "最近学习": str(last_active)[:10] if last_active else "从未",
        })
    return brief


_SYSTEM_PROMPT = (
    "你是高校教学质量分析助手，擅长从学习数据中提炼可执行的教学建议。"
    "所有结论必须引用输入数据中的具体证据，禁止编造数据中不存在的数字与知识点，"
    "严格只输出规范的 JSON（不要解释文字、不要 Markdown 代码块）。"
)


def _section_messages(idx: int, ctx: dict, prev_digest: str, students_brief: list) -> list[dict]:
    """三段报告各自的 user prompt（R1/R2/R3）。"""
    ctx_json = json.dumps(ctx, ensure_ascii=False)
    common = (
        f"课程：{ctx.get('course_name')}　班级：{ctx.get('class_name')}\n"
        f"班级统计（代码预聚合，权威口径）：{ctx_json}\n"
    )
    if idx == 1:
        requirement = (
            "请生成本次学情分析的「整体学情 + 知识点掌握分析」部分。\n"
            "严格只输出 JSON，格式：{\"overview\": \"...\", \"knowledge\": \"...\"}\n"
            "要求：\n"
            "1. overview：400~600 字 markdown（可用 **加粗** 与列表），数据引用准确，"
            "像写给授课教师的周报；若班级统计中 no_data_count>0，用一句话说明"
            "「另有 N 名学生暂无学习数据，未纳入本次分析」。\n"
            "2. knowledge：300~500 字，基于「知识点预聚合」按错误率从高到低给出薄弱/扎实"
            "知识点清单，点名具体知识点名称与错误率，并分析班级共性误区；"
            "不要编造数据中没有的知识点。\n"
            "3. 语言具体自然，禁止「总体不错、有待加强」这类空话。"
        )
    elif idx == 2:
        requirement = (
            "请续写「学生分层画像 + 风险预警」部分（前文摘要见下，保持口径一致）。\n"
            "严格只输出 JSON，格式：{\"layers\": \"...\", \"warnings\": \"...\"}\n"
            "要求：\n"
            "1. layers：400~600 字，把有数据学生分「领先/稳定/风险」三层，每层列出学生"
            "姓名与特征（引用正确率、提交率等数据）；姓名必须与输入一致。\n"
            "2. warnings：300~500 字，逐条风险预警（谁、什么问题、证据数据），"
            "无风险则明确写「暂无明显风险」。\n"
            "3. 只基于输入数据推断，禁止猜测学生品行等数据外信息。"
        )
    else:
        requirement = (
            "请续写「教学干预建议 + 下阶段重点」部分（前文摘要见下，保持口径一致）。\n"
            "严格只输出 JSON，格式：{\"advice\": \"...\"}\n"
            "要求：300~500 字 markdown，建议必须可执行并落到具体章节/作业/考试名称"
            "（用输入中的名称），按优先级排序；指出下阶段教学重点。"
        )
    user = requirement + "\n" + common
    if prev_digest:
        user += f"前文摘要（续写基准）：\n{prev_digest}\n"
    if idx == 2:
        user += f"学生明细：{json.dumps(students_brief, ensure_ascii=False)}\n"
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _comments_messages(batch: list, ctx: dict) -> list[dict]:
    """学生简评批 prompt：每生 = 基础明细 + 错题 top8 + 提问 top5 + 章节覆盖 + 缺交/缺考。"""
    payload = []
    for row in batch:
        payload.append({
            "student_id": row.get("student_id"),
            "姓名": row.get("name"),
            "练习正确率%": row.get("accuracy"),
            "练习题量": row.get("practice_total"),
            "作业提交": f"{row.get('homework_submitted')}/{row.get('homework_total')}",
            "缺交作业": row.get("homework_missing") or [],
            "考试参加": f"{row.get('exam_taken')}/{row.get('exam_total')}",
            "考试均分": row.get("avg_exam_score"),
            "缺考考试": row.get("exam_missing") or [],
            "实验完成": f"{row.get('experiment_done')}/{row.get('experiment_total')}",
            "预警": row.get("warnings") or [],
            "错题": row.get("wrong_questions") or [],
            "高频提问": (row.get("qa") or {}).get("top_questions") or [],
            "章节练习覆盖": row.get("chapter_coverage") or [],
        })
    user = (
        "请为以下每名学生分别生成一段学习简评（写给授课教师参考）。\n"
        "严格只输出 JSON 数组，格式：[{\"student_id\": 数字, \"comment\": \"...\"}]，"
        "覆盖每一名输入学生。\n"
        "要求：\n"
        "1. 每条 120~200 字：先概括表现，再指出薄弱点（具体知识点或具体任务名称），"
        "最后给出教师可采取的行动。\n"
        "2. 一律第三人称（「该生」「其」），禁止第二人称喊话（「你/加油」等）。\n"
        "3. 必须引用输入中的具体证据（正确率、错题知识点、缺交/缺考名称、提问内容）。\n"
        "4. 禁止「好好学习、巩固基础」这类放之四海皆准的空泛评语。\n"
        "5. student_id 必须与输入完全一致。\n\n"
        f"课程：{ctx.get('course_name')}　班级：{ctx.get('class_name')}\n"
        f"学生数据：{json.dumps(payload, ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# Mock 确定性假数据（无 Key 环境演示全流程）
# ---------------------------------------------------------------------------
def _mock_section(idx: int, ctx: dict) -> dict:
    summary = ctx.get("summary") or {}
    accuracy = summary.get("avg_accuracy")
    count = summary.get("student_count", 0)
    no_data = summary.get("no_data_count", 0)
    weak = [item for item in (ctx.get("knowledge_agg") or []) if item.get("rate", 0) < 60][:3]
    weak_text = "、".join(
        f"{item.get('tag')}（错误率 {item.get('rate')}%）" for item in weak
    ) or "暂无明显薄弱知识点"
    if idx == 1:
        return {
            "overview": (
                f"【模拟数据】本班共 {count} 名学生，平均练习正确率 "
                f"{accuracy if accuracy is not None else '—'}%。"
                + (f"另有 {no_data} 名学生暂无学习数据，未纳入本次分析。" if no_data else "")
                + "整体学习节奏正常，建议关注下文知识点清单中的薄弱项。"
            ),
            "knowledge": (
                f"【模拟数据】知识点掌握：薄弱项为 {weak_text}；"
                "建议在课堂中对上述知识点安排专项讲解与随堂练习。"
            ),
        }
    if idx == 2:
        return {
            "layers": (
                "【模拟数据】领先层：练习正确率与提交率均高，可安排拓展任务；"
                "稳定层：按部就班完成各项任务，保持当前节奏；"
                "风险层：存在缺交/正确率偏低情况，需重点跟进。"
            ),
            "warnings": "【模拟数据】暂无明显风险（模拟数据未触发预警规则）。",
        }
    return {
        "advice": (
            "【模拟数据】建议：1) 针对薄弱知识点安排专题讲解与随堂测；"
            "2) 对缺交作业/缺考的学生逐一提醒并了解原因；"
            "3) 下阶段教学重点放在错误率最高的知识点上。"
        ),
    }


def _mock_student_comment(row: dict) -> str:
    parts = []
    accuracy = row.get("accuracy")
    if accuracy is not None:
        parts.append(f"该生章节练习正确率 {accuracy}%（{row.get('practice_correct')}/{row.get('practice_total')}）")
    else:
        parts.append("该生尚未完成章节练习")
    if row.get("avg_exam_score") is not None:
        parts.append(f"考试均分 {row.get('avg_exam_score')}")
    missing = (row.get("homework_missing") or [])[:2]
    if missing:
        parts.append("缺交作业：" + "、".join(missing))
    weak_tags = [
        tag
        for item in (row.get("wrong_questions") or [])[:3]
        for tag in (item.get("knowledge_tags") or [])
    ][:3]
    if weak_tags:
        parts.append("错题涉及知识点：" + "、".join(dict.fromkeys(weak_tags)))
    body = "；".join(parts) + "。"
    if weak_tags:
        return body + "建议安排针对性练习并检查其订正情况。"
    return body + "建议保持当前学习节奏，可适当拓展提高。"


# ---------------------------------------------------------------------------
# 降级拼装（LLM 不可用时报告仍完整可用）
# ---------------------------------------------------------------------------
def _fallback_section(idx: int, ctx: dict) -> dict:
    summary = ctx.get("summary") or {}
    accuracy = summary.get("avg_accuracy")
    count = summary.get("student_count", 0)
    no_data = summary.get("no_data_count", 0)
    weak = [item for item in (ctx.get("knowledge_agg") or []) if item.get("rate", 0) < 60][:5]
    weak_text = "、".join(f"{i.get('tag')}（{i.get('rate')}%）" for i in weak) or "暂无"
    if idx == 1:
        return {
            "overview": (
                f"本班共 {count} 名学生"
                + (f"（另有 {no_data} 名暂无学习数据，未纳入分析）" if no_data else "")
                + f"，平均练习正确率 {accuracy if accuracy is not None else '—'}%。"
                "（本节由统计数据自动生成）"
            ),
            "knowledge": f"错误率较高的知识点：{weak_text}。建议安排专项讲解与随堂练习。",
        }
    if idx == 2:
        return {
            "layers": "学生分层明细暂不可用（AI 生成失败），请参考下方学生卡片数据。",
            "warnings": "风险预警暂不可用（AI 生成失败），请以学生卡片预警标签为准。",
        }
    return {"advice": "教学建议暂不可用（AI 生成失败），请结合薄弱知识点清单人工制定。"}


# ---------------------------------------------------------------------------
# 班级学情分析流水线（S0-S3）
# ---------------------------------------------------------------------------
@scene_decorator(AICallLog.Scene.ANALYTICS, course_getter=lambda args, kwargs: getattr(args[0], "course_id", None))
def run_class_analytics(task: AITask) -> None:
    """班级学情分析：S0 聚合 → S1 三段报告 → S2 学生简评分批 → S3 汇总落库。"""
    from apps.analytics.services import build_class_stats_v2

    # ---- S0：数据聚合（纯 SQL，约 1-3s）----
    stats = build_class_stats_v2(task.classroom, task.course_id)
    rows = stats.get("students") or []
    no_data_students = [
        {"student_id": r.get("student_id"), "name": r.get("name")}
        for r in rows
        if not r.get("has_data")
    ]
    analyzed = [r for r in rows if r.get("has_data")]
    generated_at = _now_iso()

    task.progress = {
        "stage": "aggregate",
        "done": 0,
        "total": len(analyzed),
        "message": "正在聚合班级学习数据…",
    }
    _save(task, "progress")

    # ---- F5：全班无数据 → 跳过全部 LLM 调用 ----
    if not analyzed:
        task.result = {
            "report": _NO_DATA_REPORT,
            "report_sections": {},
            "comments": {},
            "no_data_students": no_data_students,
            "stats_snapshot": stats.get("summary") or {},
            "generated_at": generated_at,
            "degraded": False,
        }
        task.progress = {"stage": "done", "done": 0, "total": 0, "message": "分析完成"}
        task.status = AITask.Status.SUCCESS
        task.finished_at = timezone.now()
        _save(task, "progress", "result", "status", "finished_at")
        return

    provider = get_provider("chat")
    timeout = _chat_timeout(provider)
    ctx = _prompt_context(stats, no_data_students)
    students_brief = _students_brief(stats)
    is_mock = provider.name == "mock"

    # ---- S1：班级整体深度报告（3 段顺序生成）----
    report_sections: dict = {}
    degraded = False
    prev_digest = ""
    for idx, keys in enumerate(SECTION_KEYS, start=1):
        task.progress = {
            "stage": "report",
            "done": idx - 1,
            "total": len(SECTION_KEYS),
            "message": SECTION_MESSAGES[idx - 1],
        }
        _save(task, "progress")
        data = None
        if is_mock:
            data = _mock_section(idx, ctx)
        else:
            for attempt in (1, 2):  # 单段失败重试一次
                try:
                    data = _chat_json(provider, _section_messages(idx, ctx, prev_digest, students_brief), timeout)
                    if isinstance(data, dict) and any(str(data.get(k) or "").strip() for k in keys):
                        data = {k: str(data.get(k) or "").strip() for k in keys}
                        break
                    data = None
                except Exception:
                    logger.exception("班级报告第 %s 段生成失败（第 %s 次）", idx, attempt)
                    data = None
        if data is None:
            data = _fallback_section(idx, ctx)
            degraded = True
        for key in keys:
            report_sections[key] = data.get(key, "")
        prev_digest = _digest_sections(report_sections)

    # ---- S2：逐学生深度简评（分批并发，增量合并）----
    comments: dict = {}
    total = len(analyzed)
    task.progress = {"stage": "students", "done": 0, "total": total, "message": f"正在生成学生简评（0/{total}）…"}
    _save(task, "progress")

    def _partial_result() -> dict:
        return {
            "report": _join_report(report_sections),
            "report_sections": dict(report_sections),
            "comments": dict(comments),
            "no_data_students": no_data_students,
            "stats_snapshot": stats.get("summary") or {},
            "generated_at": generated_at,
            "degraded": degraded,
        }

    if is_mock:
        for row in analyzed:
            comments[row["student_id"]] = _mock_student_comment(row)
            task.progress = {
                "stage": "students",
                "done": len(comments),
                "total": total,
                "message": f"正在生成学生简评（{len(comments)}/{total}）…",
            }
            task.result = _partial_result()
            _save(task, "progress", "result")
    else:
        batches = [analyzed[i : i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
        failed_batches = 0

        def _run_batch(batch):
            data = _chat_json(provider, _comments_messages(batch, ctx), timeout)
            if not isinstance(data, list):
                return None
            merged = {}
            for item in data:
                if isinstance(item, dict) and item.get("student_id") is not None and item.get("comment"):
                    try:
                        sid = int(item["student_id"])
                    except (TypeError, ValueError):
                        continue
                    merged[sid] = str(item["comment"]).strip()
            return merged or None

        if len(batches) == 1:
            try:
                merged = _run_batch(batches[0])
            except Exception:
                logger.exception("学生简评批次执行失败")
                merged = None
            if merged:
                comments.update(merged)
            else:
                failed_batches += 1
            task.progress = {
                "stage": "students",
                "done": len(comments),
                "total": total,
                "message": f"正在生成学生简评（{len(comments)}/{total}）…",
            }
            task.result = _partial_result()
            _save(task, "progress", "result")
        else:
            with ThreadPoolExecutor(max_workers=min(BATCH_WORKERS, len(batches))) as pool:
                # 线程池不继承 contextvars：提交时再复制一次（已含 trace_id/场景）
                futures = [
                    pool.submit(run_in_context, copy_call_context(), _run_batch, batch)
                    for batch in batches
                ]
                for future in as_completed(futures):
                    try:
                        merged = future.result()
                    except Exception:
                        logger.exception("学生简评批次执行失败")
                        merged = None
                    if merged:
                        comments.update(merged)
                    else:
                        failed_batches += 1
                    task.progress = {
                        "stage": "students",
                        "done": len(comments),
                        "total": total,
                        "message": f"正在生成学生简评（{len(comments)}/{total}）…",
                    }
                    task.result = _partial_result()
                    _save(task, "progress", "result")

    # ---- S3：汇总落库 ----
    missing_count = total - len(comments)
    report = _join_report(report_sections)
    if missing_count > 0:
        report += f"\n\n> 注：{missing_count} 名学生的简评生成失败，可重新生成。"
    result = _partial_result()
    result["report"] = report
    result["degraded"] = degraded or missing_count > 0
    result["failed_comment_count"] = missing_count
    task.result = result
    task.progress = {"stage": "done", "done": total, "total": total, "message": "分析完成"}
    task.status = AITask.Status.SUCCESS
    task.finished_at = timezone.now()
    _save(task, "progress", "result", "status", "finished_at")


def _join_report(sections: dict) -> str:
    """三段合并为一份 markdown 报告（固定小节标题，前端 renderAiMarkdown 渲染）。"""
    ordered = [
        ("overview", "## 整体学情"),
        ("knowledge", "## 知识点掌握分析"),
        ("layers", "## 学生分层画像"),
        ("warnings", "## 风险预警"),
        ("advice", "## 教学干预建议与下阶段重点"),
    ]
    parts = []
    for key, title in ordered:
        text = str(sections.get(key) or "").strip()
        if text:
            parts.append(f"{title}\n{text}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# 章节学习总结（P2 占位；submit 前不会有此类型任务）
# ---------------------------------------------------------------------------
@scene_decorator(AICallLog.Scene.CHAPTER_SUMMARY, course_getter=lambda args, kwargs: getattr(args[0], "course_id", None))
def run_chapter_summary(task: AITask) -> None:
    raise NotImplementedError("章节学习总结将在 P2 阶段上线")
