"""学习数据聚合服务（教师端学情统计与平台端督管共用）。

从 views.py 平移而来，保持纯函数语义：不感知请求与用户，
行级权限由调用方 View 负责（教师端校验班级归属，平台端 IsPlatformAdmin 放行）。
"""
from datetime import timedelta

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from apps.classroom.models import ClassStudent
from apps.courses.models import Catalog, VideoWatchProgress
from apps.exams.models import Exam, ExamSubmission
from apps.exams.resolver import build_for_review
from apps.homework.models import Homework, HomeworkAnswer, HomeworkSubmission
from apps.knowledge.models import QARecord
from apps.labs.models import Lab, LabSubmission
from apps.questions.models import AnswerRecord, Question, WrongMastery, WrongNote

INACTIVE_DAYS = 7
LOW_ACCURACY = 60

# AI 学情分析（build_class_stats_v2）输入裁剪硬规则：按 token 预算倒推，
# 班级报告 prompt 控制在 6k tokens 内；本地小模型可调小条数。
WRONG_TOP_N = 8           # 每生错题条数上限
QA_TOP_N = 5              # 每生高频提问条数上限
QA_DISLIKED_N = 3         # 每生被点「无用」的提问条数上限


def build_class_stats(classroom, course_id) -> dict:
    """聚合班级在某课程下的学习统计（班级汇总 + 逐学生明细 + 预警）。"""
    course = classroom.courses.get(id=course_id)
    hw_list = list(Homework.objects.filter(
        classroom=classroom, course_id=course_id, status=Homework.Status.PUBLISHED
    ))
    exam_list_qs = list(Exam.objects.filter(
        classroom=classroom,
        course_id=course_id,
        status__in=[Exam.Status.PUBLISHED, Exam.Status.FINISHED],
    ))
    hw_total = len(hw_list)
    exam_total = len(exam_list_qs)
    # 实验维度：本班本课程排课且已发布的实验集合
    lab_list = list(Lab.objects.filter(
        course_id=course_id, status=Lab.Status.PUBLISHED,
        schedules__classroom=classroom,
    ).distinct())
    lab_total = len(lab_list)
    lab_ids = {lab.id for lab in lab_list}
    now = timezone.now()

    rows = []
    for cs in ClassStudent.objects.filter(classroom=classroom).select_related("student"):
        stu = cs.student
        practice = AnswerRecord.objects.filter(
            student=stu, scene=AnswerRecord.Scene.PRACTICE, question__course_id=course_id
        )
        p_total = practice.count()
        p_correct = practice.filter(is_correct=True).count()
        accuracy = round(p_correct / p_total * 100) if p_total else None

        hw_sub_ids = set(HomeworkSubmission.objects.filter(
            student=stu,
            homework__classroom=classroom,
            homework__course_id=course_id,
        ).values_list("homework_id", flat=True))
        hw_sub = len(hw_sub_ids)
        hw_missing = [hw.title for hw in hw_list if hw.id not in hw_sub_ids]

        exam_subs = ExamSubmission.objects.filter(
            student=stu,
            exam__classroom=classroom,
            exam__course_id=course_id,
            status__in=[ExamSubmission.Status.SUBMITTED, ExamSubmission.Status.TIMEOUT],
        )
        exam_taken_ids = set(exam_subs.values_list("exam_id", flat=True))
        exam_taken = len(exam_taken_ids)
        exam_missing = [ex.name for ex in exam_list_qs if ex.id not in exam_taken_ids]
        avg_exam = exam_subs.aggregate(a=Avg("total_score"))["a"]

        # 实验维度（循环外无法按生过滤的轻量查询；量级 = 班级人数 × 实验数）
        lab_subs = LabSubmission.objects.filter(
            student=stu, lab_id__in=lab_ids, status=LabSubmission.Status.SUBMITTED
        )
        lab_done_ids = set(lab_subs.values_list("lab_id", flat=True))
        lab_done = len(lab_done_ids)
        lab_missing = [lab.title for lab in lab_list if lab.id not in lab_done_ids]
        avg_lab = lab_subs.aggregate(a=Avg("total_score"))["a"]

        last_ar = practice.order_by("-submitted_at").first()
        last_active = last_ar.submitted_at if last_ar else None

        warnings = []
        if last_active is None or (now - last_active).days >= INACTIVE_DAYS:
            warnings.append("长期未学习")
        if accuracy is not None and accuracy < LOW_ACCURACY:
            warnings.append("练习正确率低")
        if hw_total and hw_sub < hw_total:
            warnings.append("作业缺交")
        if exam_total and exam_taken < exam_total:
            warnings.append("考试缺考")
        if lab_total and lab_done < lab_total:
            warnings.append("实验缺做")

        rows.append({
            "student_id": stu.id,
            "name": stu.real_name or stu.username,
            "username": stu.username,
            "practice_total": p_total,
            "practice_correct": p_correct,
            "accuracy": accuracy,
            "homework_submitted": hw_sub,
            "homework_total": hw_total,
            "exam_taken": exam_taken,
            "exam_total": exam_total,
            "avg_exam_score": round(float(avg_exam), 1) if avg_exam is not None else None,
            "experiment_done": lab_done,
            "experiment_total": lab_total,
            "avg_experiment_score": round(float(avg_lab), 1) if avg_lab is not None else None,
            "last_active": last_active,
            "warnings": warnings,
            "homework_missing": hw_missing,
            "exam_missing": exam_missing,
            "lab_missing": lab_missing,
        })

    # 班级汇总
    acc_list = [r["accuracy"] for r in rows if r["accuracy"] is not None]
    exam_list = [r["avg_exam_score"] for r in rows if r["avg_exam_score"] is not None]
    lab_scores = [r["avg_experiment_score"] for r in rows if r["avg_experiment_score"] is not None]
    student_count = len(rows)
    total_hw_slots = hw_total * student_count
    total_hw_sub = sum(r["homework_submitted"] for r in rows)
    total_lab_slots = lab_total * student_count
    total_lab_done = sum(r["experiment_done"] for r in rows)
    summary = {
        "student_count": student_count,
        "avg_accuracy": round(sum(acc_list) / len(acc_list)) if acc_list else None,
        "avg_exam_score": round(sum(exam_list) / len(exam_list), 1) if exam_list else None,
        "avg_experiment_score": round(sum(lab_scores) / len(lab_scores), 1) if lab_scores else None,
        "homework_rate": round(total_hw_sub / total_hw_slots * 100) if total_hw_slots else None,
        "experiment_rate": round(total_lab_done / total_lab_slots * 100) if total_lab_slots else None,
        "warning_count": sum(1 for r in rows if r["warnings"]),
    }

    return {
        "class_name": classroom.name,
        "course_id": course.id,
        "course_name": course.name,
        "summary": summary,
        "students": rows,
    }


# ---------------------------------------------------------------------------
# AI 学情分析专用聚合（build_class_stats_v2）
# ---------------------------------------------------------------------------
def _answer_text(answer) -> str:
    """把 JSON 结构的学生/标准答案压成紧凑文本（喂 prompt 用，截断防爆）。"""
    if not answer:
        return ""
    if isinstance(answer, str):
        return answer[:120]
    if isinstance(answer, dict):
        if answer.get("key"):
            return str(answer["key"])
        if answer.get("keys"):
            return "、".join(str(k) for k in answer["keys"])
        blanks = answer.get("blanks")
        if isinstance(blanks, list):
            parts = [
                str(b.get("text", "")) if isinstance(b, dict) else str(b)
                for b in blanks
            ]
            return " / ".join(p for p in parts if p)[:120]
        if answer.get("text"):
            return str(answer["text"])[:120]
    return str(answer)[:120]


def _chapter_maps(course_id):
    """课程章节元数据：(parent_of, title_of, root_id 函数)。

    root_id 归属逻辑与 ClassStudentDetailView 保持一致（沿 parent 上浮到顶层章节）。
    """
    catalogs = list(Catalog.objects.filter(course_id=course_id).only("id", "parent_id", "title"))
    parent_of = {c.id: c.parent_id for c in catalogs}
    title_of = {c.id: c.title for c in catalogs}

    def root_id(cid):
        seen = set()
        while cid and parent_of.get(cid) and cid not in seen:
            seen.add(cid)
            cid = parent_of[cid]
        return cid

    return parent_of, title_of, root_id


def build_class_stats_v2(classroom, course_id) -> dict:
    """AI 学情分析专用聚合（build_class_stats 的超集，教师端全量口径）。

    在基础统计（前端学生卡片同款字段）之上，新增喂给 LLD 的维度：
    - has_data 标记（D6：六类行为记录全无即无数据，不分析不打简评）；
    - 逐生错题 TOP N（题干/我的答案/正确答案/解析/知识点，截断）；
    - 知识点预聚合（班级级 tag→错题数/总题数，纯计算先归因）；
    - 章节正确率矩阵（班级级 + 逐生覆盖）；
    - 作业/考试/实验得分明细（班级级汇总，教师视角不受成绩门控限制）；
    - 提问热度（QARecord 按章节聚合 + 高频问题 + 被点「无用」）；
    - 视频学习行为与时间趋势（近 7/30 天练习量）。

    统计先于 AI：能 SQL 算的全部代码算好，LLM 只做归因解读（见设计方案 §3.2）。
    """
    base = build_class_stats(classroom, course_id)
    course_id = base["course_id"]
    rows = base["students"]
    student_ids = [r["student_id"] for r in rows]
    _parent_of, title_of, root_id = _chapter_maps(course_id)

    def root_title(cid) -> str:
        rid = root_id(cid)
        return title_of.get(rid, "未分类章节") if rid else "未分类章节"

    now = timezone.now()
    practice_qs = AnswerRecord.objects.filter(
        student_id__in=student_ids, scene=AnswerRecord.Scene.PRACTICE, question__course_id=course_id
    )

    # ---- 班级级：章节正确率矩阵 + 逐生章节覆盖（一次聚合查询）----
    chapter_stat: dict = {}
    per_student_cov: dict = {}
    for item in (
        practice_qs.values("student_id", "question__catalog_id").annotate(
            practiced=Count("question", distinct=True),
            total=Count("id"),
            correct=Count("id", filter=Q(is_correct=True)),
        )
    ):
        rid = root_id(item["question__catalog_id"])
        if not rid:
            continue
        agg = chapter_stat.setdefault(rid, {"total": 0, "correct": 0})
        agg["total"] += item["total"]
        agg["correct"] += item["correct"]
        cov = per_student_cov.setdefault(item["student_id"], {})
        cagg = cov.setdefault(rid, {"practiced": 0, "total": 0, "correct": 0})
        cagg["practiced"] += item["practiced"]
        cagg["total"] += item["total"]
        cagg["correct"] += item["correct"]
    chapter_matrix = [
        {
            "chapter": title_of.get(cid, ""),
            "total": s["total"],
            "correct": s["correct"],
            "accuracy": round(s["correct"] / s["total"] * 100) if s["total"] else None,
        }
        for cid, s in chapter_stat.items()
    ]
    chapter_matrix.sort(key=lambda x: x["accuracy"] if x["accuracy"] is not None else 101)

    # ---- 班级级：知识点预聚合（tag → 错题数/总题数）----
    tag_stat: dict = {}
    for tags, is_correct in practice_qs.values_list("question__knowledge_tags", "is_correct"):
        for tag in tags or []:
            stat = tag_stat.setdefault(str(tag), {"wrong": 0, "total": 0})
            stat["total"] += 1
            if not is_correct:
                stat["wrong"] += 1
    knowledge_agg = sorted(
        (
            {
                "tag": tag,
                "wrong": s["wrong"],
                "total": s["total"],
                "rate": round(s["wrong"] / s["total"] * 100) if s["total"] else 0,
            }
            for tag, s in tag_stat.items()
        ),
        key=lambda x: -x["rate"],
    )

    # ---- 班级级：作业/考试/实验得分明细（教师视角，无成绩门控）----
    homework_detail = []
    for hw in Homework.objects.filter(
        classroom=classroom, course_id=course_id, status=Homework.Status.PUBLISHED
    ).order_by("id"):
        subs = HomeworkSubmission.objects.filter(homework=hw)
        submitted = subs.count()
        avg_score = subs.filter(score__isnull=False).aggregate(a=Avg("score"))["a"]
        homework_detail.append({
            "title": hw.title,
            "submitted": submitted,
            "student_count": len(rows),
            "avg_score": round(float(avg_score), 1) if avg_score is not None else None,
        })
    exam_detail = []
    for exam in Exam.objects.filter(
        classroom=classroom,
        course_id=course_id,
        status__in=[Exam.Status.PUBLISHED, Exam.Status.FINISHED],
    ).order_by("id"):
        subs = ExamSubmission.objects.filter(
            exam=exam, status__in=[ExamSubmission.Status.SUBMITTED, ExamSubmission.Status.TIMEOUT]
        )
        taken = subs.count()
        avg_score = subs.aggregate(a=Avg("total_score"))["a"]
        exam_detail.append({
            "name": exam.name,
            "taken": taken,
            "student_count": len(rows),
            "avg_score": round(float(avg_score), 1) if avg_score is not None else None,
        })
    lab_detail = []
    for lab in Lab.objects.filter(
        course_id=course_id, status=Lab.Status.PUBLISHED, schedules__classroom=classroom
    ).distinct().order_by("id"):
        subs = LabSubmission.objects.filter(lab=lab, status=LabSubmission.Status.SUBMITTED)
        done = subs.count()
        avg_score = subs.aggregate(a=Avg("total_score"))["a"]
        lab_detail.append({
            "title": lab.title,
            "done": done,
            "student_count": len(rows),
            "avg_score": round(float(avg_score), 1) if avg_score is not None else None,
            "reviewed": subs.filter(reviewed=True).count(),
        })

    # ---- 班级级：提问热度 / 学习行为 / 时间趋势 ----
    qa_course = QARecord.objects.filter(course_id=course_id, student_id__in=student_ids)
    qa_by_chapter = [
        {"chapter": title_of.get(item["catalog_id"], "课程级问答"), "count": item["n"]}
        for item in qa_course.values("catalog_id").annotate(n=Count("id"))
        if item["catalog_id"]
    ]
    qa_heat = {
        "total": qa_course.count(),
        "by_chapter": sorted(qa_by_chapter, key=lambda x: -x["count"]),
        "top_questions": [
            q[:60]
            for q in qa_course.order_by("-created_at").values_list("question", flat=True)[:10]
        ],
        "disliked": [
            q[:60]
            for q in qa_course.filter(feedback=-1).order_by("-created_at").values_list("question", flat=True)[:5]
        ],
    }
    video_qs = VideoWatchProgress.objects.filter(
        video__course_id=course_id, student_id__in=student_ids
    )
    video_behavior = {
        "students_with_progress": video_qs.values("student_id").distinct().count(),
        "completed_chapters": video_qs.filter(status=VideoWatchProgress.Status.COMPLETED).count(),
        "avg_watch_seconds": round(
            float(video_qs.aggregate(a=Avg("watch_seconds"))["a"] or 0)
        ),
    }
    time_trend = {
        "practice_last_7d": practice_qs.filter(submitted_at__gte=now - timedelta(days=7)).count(),
        "practice_last_30d": practice_qs.filter(submitted_at__gte=now - timedelta(days=30)).count(),
    }

    # ---- 逐生 enrichment：错题/提问/视频/章节覆盖/has_data ----
    for row in rows:
        stu_id = row["student_id"]
        wrong = list(
            AnswerRecord.objects.filter(
                student_id=stu_id,
                scene=AnswerRecord.Scene.PRACTICE,
                is_correct=False,
                question__course_id=course_id,
            )
            .select_related("question")
            .order_by("-submitted_at")[:WRONG_TOP_N]
        )
        row["wrong_questions"] = [
            {
                "stem": (ar.question.stem or "")[:80],
                "my_answer": _answer_text(ar.student_answer),
                "correct_answer": _answer_text(ar.question.answer),
                "analysis": (ar.question.analysis or "")[:120],
                "knowledge_tags": ar.question.knowledge_tags or [],
                "difficulty": ar.question.get_difficulty_display(),
                "chapter": root_title(ar.question.catalog_id),
            }
            for ar in wrong
        ]
        qa_stu = QARecord.objects.filter(student_id=stu_id, course_id=course_id)
        row["qa"] = {
            "count": qa_stu.count(),
            "top_questions": [
                q[:60] for q in qa_stu.order_by("-created_at").values_list("question", flat=True)[:QA_TOP_N]
            ],
            "disliked": [
                q[:60]
                for q in qa_stu.filter(feedback=-1).order_by("-created_at").values_list("question", flat=True)[:QA_DISLIKED_N]
            ],
        }
        video_stu = VideoWatchProgress.objects.filter(student_id=stu_id, video__course_id=course_id)
        row["video"] = {
            "watch_seconds": video_stu.aggregate(s=Sum("watch_seconds"))["s"] or 0,
            "completed_chapters": video_stu.filter(status=VideoWatchProgress.Status.COMPLETED).count(),
        }
        row["chapter_coverage"] = [
            {
                "chapter": title_of.get(cid, ""),
                "practiced": s["practiced"],
                "correct": s["correct"],
                "accuracy": round(s["correct"] / s["total"] * 100) if s["total"] else None,
            }
            for cid, s in sorted(
                per_student_cov.get(stu_id, {}).items(), key=lambda kv: title_of.get(kv[0], "")
            )
        ]
        # D6：六类行为记录（章节练习/作业/考试/实验/问答/视频进度）全无即无数据
        row["has_data"] = bool(
            row["practice_total"]
            or row["homework_submitted"]
            or row["exam_taken"]
            or row["experiment_done"]
            or row["qa"]["count"]
            or video_stu.exists()
        )

    summary = base["summary"]
    analyzed_count = sum(1 for r in rows if r["has_data"])
    summary["analyzed_count"] = analyzed_count
    summary["no_data_count"] = len(rows) - analyzed_count

    return {
        **base,
        "knowledge_agg": knowledge_agg,
        "chapter_matrix": chapter_matrix,
        "homework_detail": homework_detail,
        "exam_detail": exam_detail,
        "lab_detail": lab_detail,
        "qa_heat": qa_heat,
        "video_behavior": video_behavior,
        "time_trend": time_trend,
    }


# ---------------------------------------------------------------------------
# 章节学习总结（P2）：build_chapter_profile
# 统计先于 AI：能 SQL 算的全部代码算好，LLM 只做归因解读与建议生成。
# ---------------------------------------------------------------------------
CHAPTER_WRONG_TOP_N = 8       # 章节练习错题条数上限（与班级口径一致）
CHAPTER_QA_TOP_N = 5          # 章节提问条数上限
CHAPTER_QA_DISLIKED_N = 3     # 章节被点「无用」的提问条数上限
CHAPTER_TAG_TOP_N = 8         # 知识点预聚合条数上限


def build_chapter_profile(student, catalog, *, for_student: bool) -> dict:
    """聚合某学生某章节的学习画像（喂章节总结 LLM 用）。

    for_student=True 时执行成绩可见性门控（F1）：作业只纳入 correct_status=RETURNED
    的分数、考试只纳入 score_released=True 的分数；未发布的只进 visibility 计数，
    表述为「成绩尚未发布」，不把分值/批改写进产物。客观题答案/解析学生提交后
    即可见，练习错题证据不受门控。for_student=False（教师视角）看全量。
    """
    course = catalog.course
    course_id = course.id

    # ---- 视频学习行为（video↔catalog 1:1，聚合兜底多视频）----
    progresses = list(
        VideoWatchProgress.objects.filter(video__catalog_id=catalog.id, student=student)
    )
    completed_at = None
    if progresses:
        done = [p for p in progresses if p.status == VideoWatchProgress.Status.COMPLETED]
        watch = max(progresses, key=lambda p: p.watch_seconds)
        if done:
            completed_at = max(p.updated_at for p in done).isoformat()
        page_count = watch.page_count or 0
        learning = {
            "watch_seconds": watch.watch_seconds,
            "pages_watched": f"{min(watch.last_page + 1, page_count)}/{page_count}" if page_count else "0/0",
            "completed": bool(done),
            "completed_at": completed_at,
        }
    else:
        learning = {"watch_seconds": 0, "pages_watched": "0/0", "completed": False, "completed_at": None}

    # ---- 章节练习（AnswerRecord scene=PRACTICE, question__catalog=本章）----
    practice_qs = AnswerRecord.objects.filter(
        student=student, scene=AnswerRecord.Scene.PRACTICE, question__catalog_id=catalog.id
    ).select_related("question")
    p_total = practice_qs.count()
    p_correct = practice_qs.filter(is_correct=True).count()
    wrong_rows = [
        {
            "stem": r.question.stem,
            "my_answer": _answer_text(r.student_answer),
            "correct_answer": _answer_text(r.question.answer),
            "analysis": r.question.analysis,
            "knowledge_tags": r.question.knowledge_tags or [],
            "difficulty": r.question.get_difficulty_display(),
        }
        for r in practice_qs.filter(is_correct=False).select_related("question")[:CHAPTER_WRONG_TOP_N]
    ]
    practice = {
        "total": p_total,
        "correct": p_correct,
        "accuracy": round(p_correct / p_total * 100) if p_total else None,
        "wrong": wrong_rows,
    }

    # ---- 知识点预聚合（本章练习 tag → 错题数/总题数，纯计算）----
    tag_stat: dict = {}
    for tags, is_correct in practice_qs.values_list("question__knowledge_tags", "is_correct"):
        for tag in tags or []:
            stat = tag_stat.setdefault(str(tag), {"wrong": 0, "total": 0})
            stat["total"] += 1
            if not is_correct:
                stat["wrong"] += 1
    knowledge_agg = sorted(
        (
            {
                "tag": tag,
                "wrong": s["wrong"],
                "total": s["total"],
                "rate": round(s["wrong"] / s["total"] * 100) if s["total"] else 0,
            }
            for tag, s in tag_stat.items()
        ),
        key=lambda x: (-x["wrong"], -x["total"]),
    )[:CHAPTER_TAG_TOP_N]

    # ---- 作业（章节归属：homework_question__question__catalog 实时 join，F9）----
    homework_pending_release = 0
    hw_answers = (
        HomeworkAnswer.objects.filter(
            submission__student=student,
            homework_question__question__catalog_id=catalog.id,
        )
        .select_related("submission", "submission__homework", "homework_question")
        .order_by("submission__homework_id", "homework_question__order")
    )
    homework_map: dict = {}
    for ans in hw_answers:
        sub = ans.submission
        entry = homework_map.setdefault(
            sub.homework_id,
            {"title": sub.homework.title, "score": None, "total_score": float(sub.homework.total_score),
             "rate": None, "wrong_points": []},
        )
        # 客观题错题证据不受成绩门控（先收集，门控只挡分值）
        snap = ans.homework_question.snapshot or {}
        if ans.is_correct is False:
            entry["wrong_points"].append({
                "stem": snap.get("stem", ""),
                "knowledge_tags": snap.get("knowledge_tags") or [],
            })
        if for_student:
            if sub.correct_status != HomeworkSubmission.CorrectStatus.RETURNED:
                homework_pending_release += 1
                continue
        if sub.score is not None:
            entry["score"] = float(sub.score)
            if sub.homework.total_score:
                entry["rate"] = round(float(sub.score) / float(sub.homework.total_score) * 100)
    homework = list(homework_map.values())

    # ---- 考试（逐题对错复用 exams/resolver.py：乱序映射 + layout，F8）----
    exam_pending_release = 0
    chapter_qids = set(
        Question.objects.filter(catalog_id=catalog.id).values_list("id", flat=True)
    )
    exams_out = []
    submissions = (
        ExamSubmission.objects.filter(
            student=student,
            exam__course_id=course_id,
            status__in=[ExamSubmission.Status.SUBMITTED, ExamSubmission.Status.TIMEOUT],
        )
        .select_related("exam", "paper")
        .order_by("-submitted_at")
    )
    for sub in submissions:
        if not sub.paper or not chapter_qids:
            continue
        released = sub.score_released
        if for_student and not released:
            exam_pending_release += 1
        entries = build_for_review(sub.paper, sub, sub.exam)
        wrong_points = [
            {
                "stem": e.get("stem", ""),
                "correct_answer": _answer_text(e.get("correct_answer")),
                "my_answer": _answer_text(e.get("student_answer")),
                "my_score": e.get("my_score"),
            }
            for e in entries
            if e.get("question_id") in chapter_qids and e.get("is_correct") is False
        ]
        if not wrong_points:
            continue  # 本卷不含本章错题，不占总结篇幅
        item = {"name": sub.exam.name, "score": None, "wrong_points": wrong_points}
        if not for_student or released:
            item["score"] = float(sub.total_score) if sub.total_score is not None else None
        exams_out.append(item)

    # ---- 实验（提交即出分，无门控）----
    labs_out = []
    for lab in Lab.objects.filter(course_id=course_id, catalog_id=catalog.id, status=Lab.Status.PUBLISHED):
        sub = LabSubmission.objects.filter(lab=lab, student=student).first()
        if not sub:
            continue
        labs_out.append({
            "title": lab.title,
            "total_score": float(sub.total_score) if sub.total_score is not None else None,
            "passed_steps": sub.passed_steps,
            "total_steps": sub.total_steps,
        })

    # ---- 章节问答 ----
    qa_qs = QARecord.objects.filter(student=student, catalog_id=catalog.id).order_by("-created_at")
    qa_count = qa_qs.count()
    qa_questions = [q.question[:80] for q in qa_qs[:CHAPTER_QA_TOP_N]]
    qa_disliked = [q.question[:80] for q in qa_qs.filter(feedback=-1)[:CHAPTER_QA_DISLIKED_N]]
    qa = {"count": qa_count, "questions": qa_questions, "disliked": qa_disliked}

    # ---- 错题本（D3：手动错题按 catalog 归属；历史数据 catalog 为空按课程级不计入本章）----
    note_ids = list(
        WrongNote.objects.filter(student=student, catalog_id=catalog.id).values_list("id", flat=True)
    )
    mastered = (
        WrongMastery.objects.filter(student=student, note_id__in=note_ids, removed=False).count()
        if note_ids else 0
    )
    wrong_book = {"mastered": mastered, "pending": max(len(note_ids) - mastered, 0)}

    visibility = {}
    if for_student:
        visibility = {
            "homework_pending_release": homework_pending_release,
            "exam_pending_release": exam_pending_release,
        }

    return {
        "chapter": {"title": catalog.title, "course": course.name},
        "learning": learning,
        "practice": practice,
        "homework": homework,
        "exams": exams_out,
        "labs": labs_out,
        "qa": qa,
        "wrong_book": wrong_book,
        "knowledge_agg": knowledge_agg,
        "visibility": visibility,
    }
