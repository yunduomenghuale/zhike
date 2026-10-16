"""作业统计（对齐考试统计 T-E-07 的作业版）：发布后全员提交/完成情况分析。

输出结构（供教师端「作业统计」页消费）：
- homework：作业基本信息（标题/状态/分值/班级/课程/起止时间/模式）
- overview：应交人数、已提交、未提交、逾期提交、待批改、已发布成绩、
  平均分、最高/最低分、及格率（总分×60%）、优秀率（总分×85%）
- score_distribution：总分分段人数（按占总分百分比分段，附未出分人数）
- question_stats：逐题平均得分、满分率、零分率、客观题正确率、未作答数；
  选择题附选项分布（按快照内选项原始顺序）。填空题按空赋分存在部分对，
  不返回 correct_rate（前端按 平均分/分值 展示得分率，避免「正确率 0%」误导）
- rankings：全班学生列表（已提交按总分排名，同分同名次；待批改/未提交排后）

口径说明：
- 「出分」指 correct_status ∈ {graded, returned}（纯客观题作业提交即自动
  出分并发布，score 为最终分）；submitted 状态的 score 仅客观题部分分，
  不计入均分/分段/及格率，排名中随 objective_score 展示。
- 附件作业（mode=attachment）无题目维度数据，question_stats 为空列表。
- 作业无「考试中」状态：提交记录存在即已交，其余按班级在读名单计未提交。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .models import Homework, HomeworkAnswer, HomeworkSubmission

PASS_RATIO = Decimal("0.6")  # 及格线：总分 × 60%
EXCELLENT_RATIO = Decimal("0.85")  # 优秀线：总分 × 85%

# 客观题（提交即自动批改出分）；简答题需教师批改
_OBJECTIVE_QTYPES = ("single", "multi", "judge", "blank")
# 正确率口径题型：填空按空赋分存在部分对，不按对错计正确率
_CORRECT_RATE_QTYPES = ("single", "multi", "judge")
# 已出分（最终成绩）状态：批改即发布，graded 为兼容 release 接口的中间态
_GRADED_STATUS = (
    HomeworkSubmission.CorrectStatus.GRADED,
    HomeworkSubmission.CorrectStatus.RETURNED,
)
# 未提交的虚拟状态（仅统计输出使用，不对应模型字段）
UNSUBMITTED = "unsubmitted"


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return Decimal("0")


def _is_answered(answer: dict, qtype: str) -> bool:
    """作答是否非空（按题型口径，与提交时的空值判定一致）。"""
    if not answer:
        return False
    if qtype in ("single", "judge"):
        return answer.get("key") is not None and str(answer.get("key")) != ""
    if qtype == "multi":
        return bool(answer.get("keys"))
    if qtype == "blank":
        blanks = answer.get("blanks") or []
        return any(str(b or "").strip() for b in blanks)
    return str(answer.get("text") or "").strip() != ""


def _snapshot_correct_keys(snapshot: dict) -> list[str]:
    """快照 answer 的原始 key 空间正确答案集合。"""
    ans = snapshot.get("answer") or {}
    if snapshot.get("qtype") == "multi":
        return [str(k) for k in (ans.get("keys") or [])]
    key = ans.get("key")
    return [str(key)] if key is not None else []


def _student_keys(answer: dict, qtype: str) -> list[str]:
    """学生作答的选项 key 列表。"""
    if qtype == "multi":
        return [str(k) for k in (answer.get("keys") or [])]
    key = answer.get("key")
    return [str(key)] if key is not None else []


def build_homework_stats(homework: Homework) -> dict:
    subs = list(homework.submissions.select_related("student"))
    members = list(
        homework.classroom.students.filter(learn_status="active").select_related("student")
    )

    submitted_ids = {s.student_id for s in subs}
    member_ids = {m.student_id for m in members}

    # ---------------- overview ----------------
    total_score = _dec(homework.total_score)
    scored = [
        s for s in subs if s.correct_status in _GRADED_STATUS and s.score is not None
    ]
    totals = [_dec(s.score) for s in scored]
    pass_line = total_score * PASS_RATIO
    excellent_line = total_score * EXCELLENT_RATIO
    passed = [t for t in totals if pass_line > 0 and t >= pass_line]
    excellent = [t for t in totals if excellent_line > 0 and t >= excellent_line]

    overview = {
        "student_count": len(members),
        "submitted": len(subs),
        "unsubmitted": max(len(member_ids - submitted_ids), 0),
        "late_count": sum(1 for s in subs if s.is_late),
        "pending_count": sum(
            1 for s in subs if s.correct_status == HomeworkSubmission.CorrectStatus.SUBMITTED
        ),
        "released_count": sum(
            1 for s in subs if s.correct_status == HomeworkSubmission.CorrectStatus.RETURNED
        ),
        "avg_score": round(float(sum(totals)) / len(totals), 1) if totals else None,
        "max_score": float(max(totals)) if totals else None,
        "min_score": float(min(totals)) if totals else None,
        "pass_rate": round(len(passed) / len(totals) * 100, 1) if totals and pass_line > 0 else None,
        "excellent_rate": (
            round(len(excellent) / len(totals) * 100, 1) if totals and excellent_line > 0 else None
        ),
    }

    # ---------------- score_distribution ----------------
    bucket_defs = [
        ("60 以下", lambda p: p < 60),
        ("60-69", lambda p: 60 <= p < 70),
        ("70-79", lambda p: 70 <= p < 80),
        ("80-89", lambda p: 80 <= p < 90),
        ("90-100", lambda p: p >= 90),
    ]
    dist = [{"range": label, "count": 0} for label, _ in bucket_defs]
    if total_score > 0:
        for s in scored:
            pct = float(_dec(s.score) / total_score * 100)
            for i, (_, matcher) in enumerate(bucket_defs):
                if matcher(pct):
                    dist[i]["count"] += 1
                    break
    unscored = len(subs) - len(scored)
    if unscored > 0:
        dist.append({"range": "未出分", "count": unscored})
    score_distribution = dist

    # ---------------- question_stats（仅题库作业） ----------------
    question_stats = []
    if homework.mode == Homework.Mode.QUESTIONS:
        answers = list(
            HomeworkAnswer.objects.filter(submission__homework=homework).select_related(
                "homework_question"
            )
        )
        agg: dict[int, dict] = {}
        order_seq: list[int] = []
        for a in answers:
            hq = a.homework_question
            snapshot = hq.snapshot or {}
            qid = hq.id
            if qid not in agg:
                agg[qid] = {
                    "homework_question": hq,
                    "snapshot": snapshot,
                    "scores": [],
                    "correct": 0,
                    "objective_n": 0,
                    "unanswered": 0,
                    "option_counts": {},
                }
                order_seq.append(qid)
            item = agg[qid]
            qtype = snapshot.get("qtype")
            if a.score is not None:
                item["scores"].append(float(a.score))
            if qtype in _OBJECTIVE_QTYPES:
                item["objective_n"] += 1
                if a.is_correct:
                    item["correct"] += 1
            if not _is_answered(a.student_answer or {}, qtype):
                item["unanswered"] += 1
            if qtype in ("single", "multi", "judge"):
                for k in _student_keys(a.student_answer or {}, qtype):
                    item["option_counts"][k] = item["option_counts"].get(k, 0) + 1

        for idx, qid in enumerate(order_seq):
            item = agg[qid]
            snapshot = item["snapshot"]
            hq = item["homework_question"]
            qtype = snapshot.get("qtype")
            n = len(item["scores"])
            full = float(hq.score)
            correct_keys = _snapshot_correct_keys(snapshot)
            entry = {
                "question_id": qid,
                "order": idx + 1,
                "qtype": qtype,
                "qtype_display": snapshot.get("qtype_display") or qtype,
                "stem": snapshot.get("stem") or "",
                "score": full,
                "answered_n": n,
                "avg_score": round(sum(item["scores"]) / n, 1) if n else None,
                "full_rate": (
                    round(sum(1 for x in item["scores"] if x >= full) / n * 100, 1)
                    if n and full > 0
                    else None
                ),
                "zero_rate": round(sum(1 for x in item["scores"] if x <= 0) / n * 100, 1) if n else None,
                "correct_rate": (
                    round(item["correct"] / item["objective_n"] * 100, 1)
                    if item["objective_n"] and qtype in _CORRECT_RATE_QTYPES
                    else None
                ),
                "unanswered": item["unanswered"],
                "options": None,
            }
            if qtype in ("single", "multi", "judge"):
                entry["options"] = [
                    {
                        "key": o.get("key"),
                        "text": o.get("text"),
                        "count": item["option_counts"].get(str(o.get("key")), 0),
                        "is_correct": str(o.get("key")) in correct_keys,
                    }
                    for o in (snapshot.get("options") or [])
                ]
            question_stats.append(entry)

    # ---------------- rankings（全班列表） ----------------
    def submitted_sort_key(s: HomeworkSubmission):
        score = s.score if s.correct_status in _GRADED_STATUS else None
        return (
            score is None,
            -float(score) if score is not None else 0.0,
            s.submitted_at or s.created_at,
        )

    def student_name(user):
        return user.real_name or user.username

    def submission_row(s: HomeworkSubmission, rank):
        final = s.correct_status in _GRADED_STATUS
        return {
            "rank": rank,
            "submission_id": s.id,
            "student_id": s.student_id,
            "student_name": student_name(s.student),
            "status": s.correct_status,
            "status_display": s.get_correct_status_display(),
            # 待批改行的 score 仅客观题部分分，前端标注「客观 X 分」，不计排名
            "score": float(s.score) if final and s.score is not None else None,
            "objective_score": float(s.objective_score) if s.objective_score is not None else None,
            "submitted_at": s.submitted_at,
            "is_late": s.is_late,
        }

    rankings = []
    last_score = None
    last_rank = 0
    for i, s in enumerate(sorted(subs, key=submitted_sort_key), 1):
        final = s.correct_status in _GRADED_STATUS
        score = _dec(s.score) if final and s.score is not None else None
        if score is None:
            rank = None
        elif last_score is not None and score == last_score:
            rank = last_rank  # 同分同名次
        else:
            rank = i
            last_rank = i
            last_score = score
        rankings.append(submission_row(s, rank))

    # 未提交：在读班级中无提交记录的学生
    for m in members:
        if m.student_id in submitted_ids:
            continue
        rankings.append({
            "rank": None,
            "submission_id": None,
            "student_id": m.student_id,
            "student_name": student_name(m.student),
            "status": UNSUBMITTED,
            "status_display": "未提交",
            "score": None,
            "objective_score": None,
            "submitted_at": None,
            "is_late": False,
        })

    return {
        "homework": {
            "id": homework.id,
            "title": homework.title,
            "status": homework.status,
            "status_display": homework.get_status_display(),
            "mode": homework.mode,
            "mode_display": homework.get_mode_display(),
            "total_score": float(total_score),
            "course_name": homework.course.name,
            "class_name": homework.classroom.name,
            "start_time": homework.start_time,
            "deadline": homework.deadline,
        },
        "overview": overview,
        "score_distribution": score_distribution,
        "question_stats": question_stats,
        "rankings": rankings,
    }
