"""考试统计（需求 T-E-07）：考后全员答题情况分析的数据构建。

输出结构（供教师端「考试统计」页消费）：
- exam：考试基本信息
- overview：应考/已交卷/考试中/缺考人数、平均分、最高/最低分、
  及格率（总分×60%）、优秀率（总分×85%）、异常答卷数、平均用时
- score_distribution：总分分段人数（按占总分百分比分段，附未出分人数）
- question_stats：逐题平均得分、满分率、零分率、客观题正确率、未作答数；
  选择题附选项分布（按原始 key 空间统计——乱序答卷答案已 unmap 回原题空间，
  与回看页 S4 归序口径一致）。填空题按空赋分存在部分对，不返回 correct_rate
  （前端按 平均分/分值 展示得分率，避免「正确率 0%」的误导）
- rankings：全班学生列表（已交卷按总分排名，同分同名次；未出分/考试中/缺考排后）

说明：每人不同试卷（per_student_paper）时按题目维度跨答卷聚合，
题目分值取该生试卷中的分值（随机组卷各卷分值一致）。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from apps.questions.models import Question

from .models import Exam, ExamSubmission
from .resolver import score_for_item, unmap_student_answer

PASS_RATIO = Decimal("0.6")  # 及格线：总分 × 60%
EXCELLENT_RATIO = Decimal("0.85")  # 优秀线：总分 × 85%

_SUBMITTED_STATUS = (ExamSubmission.Status.SUBMITTED, ExamSubmission.Status.TIMEOUT)


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return Decimal("0")


def _is_answered(answer: dict, qtype: str) -> bool:
    """作答是否非空（按题型口径，与判分时的空值判定一致）。"""
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


def _correct_keys(question) -> list[str]:
    """原始 key 空间的正确答案集合。"""
    ans = question.answer or {}
    if question.qtype == "multi":
        return [str(k) for k in (ans.get("keys") or [])]
    key = ans.get("key")
    return [str(key)] if key is not None else []


def _student_keys(answer: dict, qtype: str) -> list[str]:
    """学生作答的选项 key 列表（原始空间）。"""
    if qtype == "multi":
        return [str(k) for k in (answer.get("keys") or [])]
    key = answer.get("key")
    return [str(key)] if key is not None else []


def build_exam_stats(exam: Exam) -> dict:
    subs = list(exam.submissions.select_related("student", "paper"))
    members = list(
        exam.classroom.students.filter(learn_status="active").select_related("student")
    )

    submitted = [s for s in subs if s.status in _SUBMITTED_STATUS]
    in_progress = [s for s in subs if s.status == ExamSubmission.Status.IN_PROGRESS]
    submitted_ids = {s.student_id for s in submitted}
    member_ids = {m.student_id for m in members}

    # ---------------- overview ----------------
    total_exam = _dec(exam.total_score)
    scored = [s for s in submitted if s.total_score is not None]
    totals = [_dec(s.total_score) for s in scored]
    obj_scored = [_dec(s.objective_score) for s in submitted if s.objective_score is not None]
    pass_line = total_exam * PASS_RATIO
    excellent_line = total_exam * EXCELLENT_RATIO
    passed = [t for t in totals if pass_line > 0 and t >= pass_line]
    excellent = [t for t in totals if excellent_line > 0 and t >= excellent_line]

    durations = [
        (s.submitted_at - s.started_at).total_seconds() / 60
        for s in submitted
        if s.started_at and s.submitted_at
    ]

    overview = {
        "student_count": len(members),
        "submitted": len(submitted),
        "in_progress": len(in_progress),
        "absent": max(len(member_ids - submitted_ids), 0) + sum(
            1 for s in subs if s.student_id not in member_ids and s.status not in _SUBMITTED_STATUS
        ),
        "avg_total": round(float(sum(totals)) / len(totals), 1) if totals else None,
        "max_total": float(max(totals)) if totals else None,
        "min_total": float(min(totals)) if totals else None,
        "avg_objective": round(float(sum(obj_scored)) / len(obj_scored), 1) if obj_scored else None,
        "pass_rate": round(len(passed) / len(totals) * 100, 1) if totals and pass_line > 0 else None,
        "excellent_rate": round(len(excellent) / len(totals) * 100, 1) if totals and excellent_line > 0 else None,
        "abnormal_count": sum(1 for s in submitted if s.abnormal),
        "unreleased_count": sum(1 for s in submitted if not s.score_released),
        "avg_duration_minutes": round(sum(durations) / len(durations), 1) if durations else None,
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
    if total_exam > 0:
        for s in scored:
            pct = float(_dec(s.total_score) / total_exam * 100)
            for i, (_, matcher) in enumerate(bucket_defs):
                if matcher(pct):
                    dist[i]["count"] += 1
                    break
    unscored = len(submitted) - len(scored)
    if unscored > 0:
        dist.append({"range": "未出分", "count": unscored})
    score_distribution = dist

    # ---------------- question_stats ----------------
    # 跨答卷按题目维度聚合（每人不同卷时各卷题目分别计入）
    items_by_sub: dict[int, list[dict]] = {}
    q_ids: set[int] = set()
    for s in submitted:
        items = list((s.paper.question_items if s.paper else None) or [])
        items_by_sub[s.id] = items
        q_ids.update(it["question_id"] for it in items)
    q_map = {q.id: q for q in Question.objects.filter(id__in=q_ids)} if q_ids else {}

    agg: dict[int, dict] = {}
    order_seq: list[int] = []
    for s in submitted:
        layout_opts = (s.question_layout or {}).get("options") or {}
        answers = s.answers or {}
        for it in items_by_sub[s.id]:
            qid = it["question_id"]
            q = q_map.get(qid)
            if not q:
                continue
            if qid not in agg:
                agg[qid] = {
                    "question": q,
                    "paper_score": _dec(it.get("score", q.score)),
                    "scores": [],
                    "correct": 0,
                    "objective_n": 0,
                    "unanswered": 0,
                    "option_counts": {},
                }
                order_seq.append(qid)
            a = agg[qid]
            perm = layout_opts.get(str(qid))
            stu = answers.get(str(qid)) or answers.get(qid) or {}
            # 乱序答卷：展示 key 空间 → 原始 key 空间（与回看/判分同一函数）
            raw_stu = unmap_student_answer(stu, perm, q.options or [])
            is_correct, my_score = score_for_item(q, it.get("score", q.score), raw_stu)
            if my_score is not None:
                a["scores"].append(float(my_score))
            if q.is_objective:
                a["objective_n"] += 1
                if is_correct:
                    a["correct"] += 1
            if not _is_answered(raw_stu, q.qtype):
                a["unanswered"] += 1
            if q.qtype in ("single", "multi", "judge"):
                for k in _student_keys(raw_stu, q.qtype):
                    a["option_counts"][k] = a["option_counts"].get(k, 0) + 1

    question_stats = []
    for idx, qid in enumerate(order_seq):
        a = agg[qid]
        q = a["question"]
        n = len(a["scores"])
        full = float(a["paper_score"])
        correct_keys = _correct_keys(q)
        entry = {
            "question_id": qid,
            "order": idx + 1,
            "qtype": q.qtype,
            "qtype_display": q.get_qtype_display(),
            "stem": q.stem,
            "score": full,
            "answered_n": n,
            "avg_score": round(sum(a["scores"]) / n, 1) if n else None,
            "full_rate": round(sum(1 for x in a["scores"] if x >= full) / n * 100, 1) if n and full > 0 else None,
            "zero_rate": round(sum(1 for x in a["scores"] if x <= 0) / n * 100, 1) if n else None,
            "correct_rate": (
                round(a["correct"] / a["objective_n"] * 100, 1)
                if a["objective_n"] and q.qtype != "blank"
                else None
            ),
            "unanswered": a["unanswered"],
            "options": None,
        }
        if q.qtype in ("single", "multi", "judge"):
            entry["options"] = [
                {
                    "key": o.get("key"),
                    "text": o.get("text"),
                    "count": a["option_counts"].get(str(o.get("key")), 0),
                    "is_correct": str(o.get("key")) in correct_keys,
                }
                for o in (q.options or [])
            ]
        question_stats.append(entry)

    # ---------------- rankings（全班列表） ----------------
    def submitted_sort_key(s: ExamSubmission):
        t = s.total_score
        return (
            t is None,
            -float(t) if t is not None else 0.0,
            -(float(s.objective_score) if s.objective_score is not None else 0.0),
            s.submitted_at or s.started_at or s.created_at,
        )

    def student_name(user):
        return user.real_name or user.username

    def submission_row(s: ExamSubmission, rank):
        duration = None
        if s.started_at and s.submitted_at:
            duration = round((s.submitted_at - s.started_at).total_seconds() / 60, 1)
        return {
            "rank": rank,
            "submission_id": s.id,
            "student_id": s.student_id,
            "student_name": student_name(s.student),
            "status": s.status,
            "status_display": s.get_status_display(),
            "objective_score": float(s.objective_score) if s.objective_score is not None else None,
            "total_score": float(s.total_score) if s.total_score is not None else None,
            "submitted_at": s.submitted_at,
            "duration_minutes": duration,
            "abnormal": s.abnormal,
            "score_released": s.score_released,
        }

    rankings = []
    last_score = None
    last_rank = 0
    for i, s in enumerate(sorted(submitted, key=submitted_sort_key), 1):
        if s.total_score is None:
            rank = None
        elif last_score is not None and float(s.total_score) == last_score:
            rank = last_rank  # 同分同名次
        else:
            rank = i
            last_rank = i
            last_score = float(s.total_score)
        rankings.append(submission_row(s, rank))

    # 考试中（未交卷）排在有成绩者之后
    for s in sorted(in_progress, key=lambda x: x.started_at or x.created_at):
        rankings.append(submission_row(s, None))

    # 缺考：在读班级中无答卷记录的学生 + 有未开始答卷的学生
    seen_students = {r["student_id"] for r in rankings}
    for m in members:
        if m.student_id in seen_students:
            continue
        rankings.append({
            "rank": None,
            "submission_id": None,
            "student_id": m.student_id,
            "student_name": student_name(m.student),
            "status": ExamSubmission.Status.ABSENT,
            "status_display": ExamSubmission.Status.ABSENT.label,
            "objective_score": None,
            "total_score": None,
            "submitted_at": None,
            "duration_minutes": None,
            "abnormal": False,
            "score_released": False,
        })
        seen_students.add(m.student_id)
    # 已不属于班级但有未交卷答卷的学生（防御）
    for s in subs:
        if s.student_id in seen_students or s.status in _SUBMITTED_STATUS or s.status == ExamSubmission.Status.IN_PROGRESS:
            continue
        rankings.append(submission_row(s, None))
        seen_students.add(s.student_id)

    return {
        "exam": {
            "id": exam.id,
            "name": exam.name,
            "status": exam.status,
            "status_display": exam.get_status_display(),
            "total_score": float(total_exam),
            "course_name": exam.course.name,
            "class_name": exam.classroom.name,
            "start_at": exam.start_at,
            "end_at": exam.end_at,
            "duration": exam.duration,
            "shuffle_options": exam.shuffle_options,
        },
        "overview": overview,
        "score_distribution": score_distribution,
        "question_stats": question_stats,
        "rankings": rankings,
    }
