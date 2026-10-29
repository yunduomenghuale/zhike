"""平台端督管聚合服务（概览趋势/待办异常/课程·班级·教师统计）。

与教师端 analytics.services 的分工：
- 跨班级/跨教师的平台级汇总放这里；
- 单个班级的逐学生学习统计仍用 analytics.services.build_class_stats（复用，勿重写）。
性能约定（当前 SQLite 数据量下的取舍）：
- 趋势序列跨度上限 90 天（视图层强校验）；
- 班级进度汇总按「页大小 ≤10」循环，每班约 6 条聚合查询（与班级人数无关）；
- 课程最近更新用 3 条分组查询批量算，不逐行查。
"""
from collections import defaultdict
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Max, OuterRef, Q, Subquery, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.courses.models import Catalog, Course, PPTResource, VideoWatchProgress
from apps.classroom.models import ClassCourse, ClassRoom, ClassStudent
from apps.exams.models import Exam, ExamSubmission
from apps.homework.models import Homework, HomeworkSubmission
from apps.questions.models import AnswerRecord
from apps.ai.models import AICallLog

User = get_user_model()

TRENDS_MAX_DAYS = 90
INACTIVE_DAYS = 14  # 教师未登录 / 班级无学习记录的告警阈值

# 概览重聚合的短 TTL 按需缓存（trends/alerts）：看板爆发刷新时保护数据库，
# 60s 陈旧对运营看板可接受；改口径时升 _CACHE_VERSION 即可整体失效。
OVERSIGHT_CACHE_TTL = 60
_CACHE_VERSION = "v1"


def _oversight_cache():
    from django.core.cache import caches

    return caches["oversight"]


def cached_platform_trends(days: int) -> dict:
    """platform_trends 的缓存版（key 含 days，不同窗口互不污染）。"""
    key = f"{_CACHE_VERSION}:trends:{days}"
    cache = _oversight_cache()
    hit = cache.get(key)
    if hit is not None:
        return hit
    data = platform_trends(days)
    cache.set(key, data, OVERSIGHT_CACHE_TTL)
    return data


def cached_platform_alerts() -> list:
    """platform_alerts 的缓存版（无参数，单 key）。"""
    key = f"{_CACHE_VERSION}:alerts"
    cache = _oversight_cache()
    hit = cache.get(key)
    if hit is not None:
        return hit
    data = platform_alerts()
    cache.set(key, data, OVERSIGHT_CACHE_TTL)
    return data


# ---------------------------------------------------------------------------
# 概览趋势（A1）
# ---------------------------------------------------------------------------

def _daily_counts(queryset, date_field: str, start, end) -> dict:
    """按本地时区分组的日计数（TruncDate 单条分组查询）。"""
    tz = timezone.get_current_timezone()
    rows = (
        queryset.filter(**{f"{date_field}__gte": start, f"{date_field}__lt": end})
        .annotate(day=TruncDate(date_field, tzinfo=tz))
        .values("day")
        .annotate(n=Count("id"))
    )
    return {row["day"].isoformat(): row["n"] for row in rows if row["day"]}


def _active_students_daily(start, end) -> dict:
    """日活跃学生（去重）：视频学习进度 + 章节练习两类行为取并集。

    数据量说明：按 (day, student_id) 取数后在 Python 侧求并集，
    90 天窗口在千级学生规模下为十万行以内，可接受；
    规模再增长应先落宽表再改此实现。
    """
    tz = timezone.get_current_timezone()
    per_day = defaultdict(set)
    for day, sid in (
        VideoWatchProgress.objects.filter(updated_at__gte=start, updated_at__lt=end)
        .annotate(day=TruncDate("updated_at", tzinfo=tz))
        .values_list("day", "student_id")
    ):
        per_day[day.isoformat()].add(sid)
    for day, sid in (
        AnswerRecord.objects.filter(submitted_at__gte=start, submitted_at__lt=end)
        .annotate(day=TruncDate("submitted_at", tzinfo=tz))
        .values_list("day", "student_id")
    ):
        per_day[day.isoformat()].add(sid)
    return {day: len(ids) for day, ids in per_day.items()}


def platform_trends(days: int) -> dict:
    """近 N 天平台趋势：新增用户/课程/班级 + 日活跃学生，附上周期环比。"""
    tz = timezone.get_current_timezone()
    now = timezone.now()
    start = now - timedelta(days=days)
    prev_start = start - timedelta(days=days)

    def window_series(w_start, w_end):
        users = _daily_counts(User.objects.all(), "date_joined", w_start, w_end)
        courses = _daily_counts(Course.objects.all(), "created_at", w_start, w_end)
        classes = _daily_counts(ClassRoom.objects.all(), "created_at", w_start, w_end)
        active = _active_students_daily(w_start, w_end)
        # 以本地日期补零，保证前端图表 x 轴连续
        days_list = []
        cursor = w_start.astimezone(tz).date()
        last = (w_end - timedelta(seconds=1)).astimezone(tz).date()
        while cursor <= last:
            key = cursor.isoformat()
            days_list.append({
                "date": key,
                "new_users": users.get(key, 0),
                "new_courses": courses.get(key, 0),
                "new_classes": classes.get(key, 0),
                "active_students": active.get(key, 0),
            })
            cursor += timedelta(days=1)
        return days_list

    current = window_series(start, now)
    previous = window_series(prev_start, start)

    def _total(rows, field):
        return sum(row[field] for row in rows)

    summary = {}
    for field, label in (
        ("new_users", "新增用户"),
        ("new_courses", "新增课程"),
        ("new_classes", "新增班级"),
        ("active_students", "活跃学生"),
    ):
        cur, prev = _total(current, field), _total(previous, field)
        summary[field] = {
            "label": label,
            "current": cur,
            "previous": prev,
            "delta": cur - prev,
            "delta_pct": round((cur - prev) / prev, 4) if prev else None,
        }
    return {"days": days, "daily": current, "summary": summary}


# ---------------------------------------------------------------------------
# 待办与异常（A2）
# ---------------------------------------------------------------------------

def ai_health_alerts(since) -> list:
    """AI 近端时间异常（失败率 / Mock 回退 / 慢响应）。

    与 AdminAICallStatsView._alerts 共用（阈值一致，避免两处漂移）。
    """
    recent = AICallLog.objects.filter(created_at__gte=since)
    stats = recent.aggregate(calls=Count("id"), failed=Count("id", filter=Q(success=False)))
    calls = stats["calls"] or 0
    alerts = []
    if calls >= 5 and (stats["failed"] or 0) / calls > 0.2:
        alerts.append({
            "level": "warning",
            "message": f"AI 近 24 小时失败率 {(stats['failed'] / calls):.0%}"
                       f"（{stats['failed']}/{calls}），请检查服务商配置与网络",
        })
    fallback = recent.filter(is_mock=True).exclude(provider="mock").count()
    if fallback:
        alerts.append({
            "level": "warning",
            "message": f"AI 近 24 小时有 {fallback} 次真实模型调用回退到模拟模式，相关业务结果可能不可信",
        })
    slow = recent.filter(capability="chat").aggregate(avg=Avg("latency_ms"))["avg"]
    if slow and slow > 15000:
        alerts.append({
            "level": "info",
            "message": f"AI 近 24 小时对话平均耗时 {slow / 1000:.1f}s，本地模型可调大超时或扩容",
        })
    return alerts


def platform_alerts() -> list:
    """平台待办与异常清单（每项带数量与前端跳转路径）。"""
    now = timezone.now()
    cutoff = now - timedelta(days=INACTIVE_DAYS)
    items = []

    def _add(key, title, count, level, jump_url, hint=""):
        if count > 0:
            items.append({
                "key": key, "title": title, "count": count,
                "level": level, "jump_url": jump_url, "hint": hint,
            })

    # 1. 待批改作业提交（教师动作，平台可见积压）
    _add(
        "pending_grading", "作业待批改",
        HomeworkSubmission.objects.filter(
            correct_status=HomeworkSubmission.CorrectStatus.SUBMITTED
        ).count(),
        "warning", "/admin/teaching",
        "学生已提交、教师尚未批改的作业",
    )
    # 2. 成绩未发布的考试（score_released 在答卷上：有已交卷但未发布成绩的考试，按考试去重）
    unreleased_exams = len(set(
        ExamSubmission.objects.filter(
            status__in=[ExamSubmission.Status.SUBMITTED, ExamSubmission.Status.TIMEOUT],
            score_released=False,
            exam__status__in=[Exam.Status.PUBLISHED, Exam.Status.FINISHED],
        ).values_list("exam_id", flat=True)
    ))
    _add(
        "unreleased_exams", "考试成绩未发布",
        unreleased_exams,
        "warning", "/admin/teaching",
        "已有学生交卷但成绩尚未发布，发布后学生才可见分数",
    )
    # 3. AI 健康（复用同一套阈值）
    for alert in ai_health_alerts(now - timedelta(hours=24)):
        key = "ai_failure" if "失败率" in alert["message"] else (
            "ai_mock_fallback" if "回退" in alert["message"] else "ai_slow"
        )
        _add(key, "AI 调用异常", 1, alert["level"], "/admin/ai-settings", alert["message"])
    # 4. 解析失败的课件（PPT 入知识库失败会静默影响检索）
    _add(
        "failed_ppt", "课件解析失败",
        PPTResource.objects.filter(parse_status=PPTResource.ParseStatus.FAILED).count(),
        "warning", "/admin/teaching",
        "解析失败的课件不会进入知识库，需教师重新上传",
    )
    # 5. 长期未登录的教师
    _add(
        "inactive_teachers", f"{INACTIVE_DAYS} 天未登录教师",
        User.objects.filter(role=User.Role.TEACHER, is_active=True)
        .filter(Q(last_login__lt=cutoff) | Q(last_login__isnull=True))
        .count(),
        "info", "/admin/teaching",
        "可能已停止使用平台，建议联系确认",
    )
    # 6. 长期无学习记录的班级（按班级学生最近一次视频学习/练习判定）
    latest_learn = Subquery(
        VideoWatchProgress.objects.filter(
            student__joined_classes__classroom=OuterRef("pk")
        ).order_by().values("student__joined_classes__classroom")
        .annotate(m=Max("updated_at")).values("m")[:1]
    )
    _add(
        "inactive_classes", f"{INACTIVE_DAYS} 天无学习记录班级",
        ClassRoom.objects.filter(status=ClassRoom.Status.ACTIVE)
        .annotate(last_learn=latest_learn)
        .filter(Q(last_learn__isnull=True) | Q(last_learn__lt=cutoff))
        .count(),
        "info", "/admin/teaching",
        "开课中但学生近期无学习行为",
    )
    return items


# ---------------------------------------------------------------------------
# 课程监管统计（A3/A4）
# ---------------------------------------------------------------------------

def course_last_updates(course_ids) -> dict:
    """批量计算课程最近内容更新（章节/课件/题目三者 updated_at 最大值，3 条分组查询）。"""
    from apps.questions.models import Question

    result = {cid: None for cid in course_ids}
    for model in (Catalog, PPTResource, Question):
        for cid, ts in (
            model.objects.filter(course_id__in=course_ids)
            .values_list("course_id")
            .annotate(m=Max("updated_at"))
        ):
            if ts is not None and (result.get(cid) is None or ts > result[cid]):
                result[cid] = ts
    return result


# ---------------------------------------------------------------------------
# 班级监管统计（A6/A8）
# ---------------------------------------------------------------------------

def class_progress_summary(classroom) -> dict:
    """班级学习进度轻量汇总（列表页用，不逐学生查）。

    口径与教师端 build_class_stats 的 summary 对齐：
    作业提交率 = 已提交份数 / (已发布作业数 × 在读学生数)；
    考试完成率 = 已交卷份数 / (已发布考试数 × 在读学生数)；
    预警人数 = 存在缺交或缺考的学生数（未活跃/正确率维度在详情页呈现）。
    课程默认取班级关联的第一门（与教师端 _resolve_classroom_course 一致）。
    """
    course = classroom.courses.order_by("id").first()
    if course is None:
        return {"course_id": None, "course_name": None, "homework_rate": None,
                "exam_rate": None, "warning_count": None}
    students = list(
        ClassStudent.objects.filter(classroom=classroom)
        .exclude(learn_status=ClassStudent.LearnStatus.REMOVED)
        .values_list("student_id", flat=True)
    )
    student_count = len(students)
    hw_list = list(Homework.objects.filter(
        classroom=classroom, course_id=course.id, status=Homework.Status.PUBLISHED
    ).values_list("id", flat=True))
    exam_list = list(Exam.objects.filter(
        classroom=classroom, course_id=course.id,
        status__in=[Exam.Status.PUBLISHED, Exam.Status.FINISHED],
    ).values_list("id", flat=True))
    hw_total, exam_total = len(hw_list), len(exam_list)

    hw_sub_slots = exam_taken_slots = 0
    warning_count = None
    if student_count:
        if hw_list:
            per_student = {
                sid: n for sid, n in HomeworkSubmission.objects.filter(
                    homework_id__in=hw_list, student_id__in=students
                ).values_list("student_id").annotate(n=Count("homework_id", distinct=True))
            }
            hw_sub_slots = sum(per_student.values())
            missing_hw = {
                sid for sid in students
                if per_student.get(sid, 0) < hw_total
            }
        else:
            missing_hw = set()
        if exam_list:
            per_exam = {
                sid: n for sid, n in ExamSubmission.objects.filter(
                    exam_id__in=exam_list, student_id__in=students,
                    status__in=[ExamSubmission.Status.SUBMITTED, ExamSubmission.Status.TIMEOUT],
                ).values_list("student_id").annotate(n=Count("exam_id", distinct=True))
            }
            exam_taken_slots = sum(per_exam.values())
            missing_exam = {sid for sid in students if per_exam.get(sid, 0) < exam_total}
        else:
            missing_exam = set()
        warning_count = len(missing_hw | missing_exam)

    return {
        "course_id": course.id,
        "course_name": course.name,
        "homework_rate": round(hw_sub_slots / (hw_total * student_count) * 100) if hw_total and student_count else None,
        "exam_rate": round(exam_taken_slots / (exam_total * student_count) * 100) if exam_total and student_count else None,
        "warning_count": warning_count,
    }


# ---------------------------------------------------------------------------
# 教师监管统计（A9/A10）
# ---------------------------------------------------------------------------

def teacher_rows(search: str = "") -> list:
    """教师维度统计：课程/班级/学生数、AI 调用与 Token 消耗、最近活跃。

    最近活跃 = max(last_login, 课程/班级/内容更新时间)，反映"还在用平台"。
    """
    teachers = User.objects.filter(role=User.Role.TEACHER).order_by("-date_joined")
    if search:
        teachers = teachers.filter(
            Q(username__icontains=search) | Q(real_name__icontains=search)
        )
    teachers = list(teachers)

    # 资产与 AI 消耗：按教师分组各一次聚合
    course_counts = {
        row["teacher"]: row["n"] for row in
        Course.objects.filter(teacher__in=teachers).values("teacher").annotate(n=Count("id"))
    }
    # 班级归口管理员后，"建班人"不再代表带班教师，教师维度要按"其课程挂过的班"统计
    class_counts = {
        row["course__teacher"]: row["n"] for row in
        ClassCourse.objects.filter(course__teacher__in=teachers)
        .values("course__teacher").annotate(n=Count("classroom_id", distinct=True))
    }
    student_counts = {
        row["classroom__courses__teacher"]: row["n"] for row in
        ClassStudent.objects.filter(
            classroom__courses__teacher__in=teachers,
            learn_status__in=ClassStudent.OCCUPYING_STATUSES,
        ).values("classroom__courses__teacher").annotate(n=Count("student_id", distinct=True))
    }
    ai_stats = {
        row["triggered_by"]: row for row in
        AICallLog.objects.filter(triggered_by__in=teachers)
        .values("triggered_by")
        .annotate(
            calls=Count("id"),
            tokens=Sum("total_tokens"),
            chars=Sum("input_chars"),
            items=Sum("item_count"),
        )
    }
    # 内容最近更新（课程/章节/课件/题目 4 条分组查询）
    last_content = {t.id: None for t in teachers}
    for model, fk in ((Course, "teacher"), (Catalog, "course__teacher"),
                      (PPTResource, "course__teacher"), ):
        for tid, ts in (
            model.objects.filter(**{f"{fk}__in": teachers})
            .values_list(fk).annotate(m=Max("updated_at"))
        ):
            if ts is not None and (last_content.get(tid) is None or ts > last_content[tid]):
                last_content[tid] = ts

    rows = []
    for t in teachers:
        ai = ai_stats.get(t.id, {})
        content_at = last_content.get(t.id)
        last_active = max(
            [x for x in (t.last_login, content_at) if x is not None], default=None
        )
        rows.append({
            "id": t.id,
            "username": t.username,
            "real_name": t.real_name,
            "is_active": t.is_active,
            "date_joined": t.date_joined,
            "last_login": t.last_login,
            "course_count": course_counts.get(t.id, 0),
            "class_count": class_counts.get(t.id, 0),
            "student_count": student_counts.get(t.id, 0),
            "ai_calls": ai.get("calls", 0),
            "ai_tokens": ai.get("tokens") or 0,
            # 语音合成等无 token 口径的能力按字符计量（input_chars），条数兜底
            "ai_chars": ai.get("chars") or 0,
            "ai_items": ai.get("items") or 0,
            "last_active": last_active,
        })
    return rows
