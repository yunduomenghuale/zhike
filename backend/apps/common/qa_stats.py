"""问答质量统计共享口径（质量看板 Phase 1 / Phase 2）。

平台端（AdminQAQualityStatsView）与教师端（TeacherQAQualityStatsView）共用：

- 窗口解析与环比基线：call_log_window / call_log_qs / qa_record_qs
- 指标聚合：quality_totals（含成本可选）/ quality_by_course / quality_daily
  / quality_by_source
- 告警：quality_alerts（为空率 + L4 突增；平台级与课程级按 include_platform 收放）
- 视图装配基类：BaseQAQualityStatsView（窗口解析 + 当前/上周期汇总 + 环比注入）

行级过滤由调用方负责：qa_record_qs(start, end, base=...) 的 base 传权限
收窄后的 QARecord queryset（平台传全量，教师传 course__teacher=user）。
AICallLog 无课程归属，教师端不含成本（include_cost=False）。

指标口径（与管理端看板卡片 tooltip 文案一致）：
- 检索为空率：cited_chunks=[] 且非纯图片默认文案（skip_retrieval）÷（总数 - skip）
- 改写触发率：rewritten_question 非空 ÷ 总数（多轮追问才触发，首轮天然不触发）
- 降级分布：context_snapshot.degraded_level 分桶 L0/L1/L2/L4
- 好评率：feedback=1 ÷（feedback∈{1,-1}）；覆盖率：有评价 ÷ 总数
- 兜底触发率：context_snapshot.fallback_used=True ÷ 总数（检索为空补上一轮片段）
- 来源分布：cited_chunks[].source 计数（一条多引用各计一次）
- 成本：AICallLog scene=QA 窗口内 token 合计（无单价字段，不折算金额）
"""
import logging
from datetime import date, datetime, time as dtime, timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.views import APIView

from apps.ai.models import AICallLog
from apps.common.response import api_response
from apps.knowledge.models import QARecord

logger = logging.getLogger(__name__)

# 单次统计最大跨度（约一年，超出直接 400）
CALL_LOG_MAX_SPAN_DAYS = 366

# 来源分布扫描样本上限（SQLite 无法 ORM 聚合 JSON 数组，Python 侧扫描）
QA_SOURCE_SCAN_LIMIT = 20000

# 告警阈值（建议值，上线后按实际分布调整）
EMPTY_RATE_WARN = 0.30
EMPTY_RATE_ERROR = 0.50
L4_RATE_WARN = 0.10
L4_SURGE_RATIO = 2.0
COURSE_ALERT_MIN_QUESTIONS = 20  # 课程级告警最小样本量，防小样本噪声


class CallLogWindowError(ValueError):
    """统计窗口参数非法（日期格式错误 / 跨度超限 / start 晚于 end）。"""


def call_log_window(request, default_days: int = 7) -> dict:
    """解析调用统计窗口。

    优先级：start+end（YYYY-MM-DD 本地时区日历窗）> days（滚动窗，1~365）。
    返回 {start, end, days, source, previous_start, previous_end}：
    - 日历窗按本地时区取当日 00:00:00 ~ 23:59:59；只传一侧时另一侧补成今天
    - end 在未来时截断为当前时刻（数据只可能积累到现在）
    - 上周期 = 紧邻当前周期前一段等长周期（环比对比基线）
    - 跨度超过 366 天或 start 晚于 end 抛 CallLogWindowError（由视图转 400）
    """
    now = timezone.now()
    tz = timezone.get_current_timezone()
    start_raw = (request.query_params.get("start") or "").strip()
    end_raw = (request.query_params.get("end") or "").strip()
    if start_raw or end_raw:
        try:
            start_date = date.fromisoformat(start_raw) if start_raw else None
            end_date = date.fromisoformat(end_raw) if end_raw else None
        except ValueError:
            raise CallLogWindowError("日期格式不正确，请使用 YYYY-MM-DD") from None
        if start_date is None:
            start_date = end_date
        if end_date is None:
            end_date = now.astimezone(tz).date()
        if start_date > end_date:
            raise CallLogWindowError("开始日期不能晚于结束日期")
        span_days = (end_date - start_date).days + 1
        if span_days > CALL_LOG_MAX_SPAN_DAYS:
            raise CallLogWindowError(f"时间范围不能超过 {CALL_LOG_MAX_SPAN_DAYS} 天")
        window_start = timezone.make_aware(datetime.combine(start_date, datetime.min.time()), tz)
        window_end = timezone.make_aware(datetime.combine(end_date, dtime(23, 59, 59)), tz)
        source = "range"
    else:
        try:
            span_days = min(365, max(1, int(request.query_params.get("days", default_days))))
        except (TypeError, ValueError):
            span_days = default_days
        window_end = now
        window_start = now - timedelta(days=span_days)
        source = "days"
    if window_end > now:
        window_end = now
    return {
        "start": window_start,
        "end": window_end,
        "days": span_days,
        "source": source,
        "previous_start": window_start - timedelta(days=span_days),
        "previous_end": window_start - timedelta(seconds=1),
    }


def call_log_qs(start, end):
    """按 [start, end] 闭区间过滤（end 多为 23:59:59，+1s 兼容微秒级 created_at）。"""
    return AICallLog.objects.filter(
        created_at__gte=start, created_at__lt=end + timedelta(seconds=1)
    )


def qa_record_qs(start, end, base=None):
    """按 [start, end] 闭区间过滤问答记录（口径同调用日志：end +1s 兼容微秒级）。

    base：调用方按权限收窄后的 QARecord 基础 queryset（平台传全量，
    教师传 course__teacher=user）；为空表示全量。
    """
    qs = base if base is not None else QARecord.objects
    return qs.filter(created_at__gte=start, created_at__lt=end + timedelta(seconds=1))


def qa_rate(count, denom):
    """比率统一出口：分母为 0 时返回 None（前端显示「—」）。"""
    return round(count / denom, 4) if denom else None


def quality_totals(qs, start, end, include_cost=True) -> dict:
    """窗口内总量指标（totals）+ 降级分布（degraded）。

    qs 应为已按窗口与权限过滤的 QARecord queryset（见 qa_record_qs）；
    include_cost=False 时省略成本段（AICallLog 无课程归属，教师端不折算）。
    """
    agg = qs.aggregate(
        questions=Count("id"),
        skip=Count("id", filter=Q(skip_retrieval=True)),
        # 注意：聚合别名避开 filter 引用的字段名（empty/rewritten 等）
        empty=Count("id", filter=Q(cited_chunks=[]) & Q(skip_retrieval=False)),
        rewritten=Count("id", filter=Q(rewritten_question__gt="")),
        rated=Count("id", filter=Q(feedback__in=[1, -1])),
        positive=Count("id", filter=Q(feedback=1)),
        fallback=Count("id", filter=Q(context_snapshot__fallback_used=True)),
        degraded_l1=Count("id", filter=Q(context_snapshot__degraded_level=1)),
        degraded_l2=Count("id", filter=Q(context_snapshot__degraded_level=2)),
        degraded_l4=Count("id", filter=Q(context_snapshot__degraded_level=4)),
    )
    questions = agg["questions"] or 0
    skip = agg["skip"] or 0
    empty_denom = questions - skip
    degraded_total = (
        (agg["degraded_l1"] or 0) + (agg["degraded_l2"] or 0) + (agg["degraded_l4"] or 0)
    )
    totals = {
        "questions": questions,
        "skip_retrieval": skip,
        "empty_retrieval": {
            "count": agg["empty"] or 0,
            "rate": qa_rate(agg["empty"] or 0, empty_denom),
        },
        "rewrite": {
            "count": agg["rewritten"] or 0,
            "rate": qa_rate(agg["rewritten"] or 0, questions),
        },
        "feedback": {
            "rated": agg["rated"] or 0,
            "positive": agg["positive"] or 0,
            "rate": qa_rate(agg["positive"] or 0, agg["rated"] or 0),
            "coverage": qa_rate(agg["rated"] or 0, questions),
        },
        "fallback": {
            "count": agg["fallback"] or 0,
            "rate": qa_rate(agg["fallback"] or 0, questions),
        },
    }
    if include_cost:
        # 成本：AICallLog scene=QA 窗口内 token 合计（无单价字段，不折算金额）
        cost = call_log_qs(start, end).filter(scene=AICallLog.Scene.QA).aggregate(
            calls=Count("id"),
            prompt_tokens=Sum("prompt_tokens"),
            completion_tokens=Sum("completion_tokens"),
            total_tokens=Sum("total_tokens"),
        )
        totals["cost"] = {
            "calls": cost["calls"] or 0,
            "prompt_tokens": cost["prompt_tokens"] or 0,
            "completion_tokens": cost["completion_tokens"] or 0,
            "total_tokens": cost["total_tokens"] or 0,
        }
    return {
        "totals": totals,
        "degraded": {
            "L0": questions - degraded_total,
            "L1": agg["degraded_l1"] or 0,
            "L2": agg["degraded_l2"] or 0,
            "L4": agg["degraded_l4"] or 0,
            "degraded_rate": qa_rate(degraded_total, questions),
        },
    }


def quality_by_course(qs) -> list[dict]:
    """课程排行：提问量 / 为空率 / 好评率 / 降级率（红绿由前端按阈值标注）。"""
    rows = list(
        qs.values(
            "course_id", "course__name",
            "course__teacher__username", "course__teacher__real_name",
        )
        .annotate(
            questions=Count("id"),
            skip=Count("id", filter=Q(skip_retrieval=True)),
            empty=Count("id", filter=Q(cited_chunks=[]) & Q(skip_retrieval=False)),
            rated=Count("id", filter=Q(feedback__in=[1, -1])),
            positive=Count("id", filter=Q(feedback=1)),
            degraded=Count("id", filter=Q(context_snapshot__degraded_level__gt=0)),
        )
        .order_by("-questions")
    )
    return [
        {
            "course_id": row["course_id"],
            "course_name": row["course__name"],
            "teacher": row["course__teacher__real_name"] or row["course__teacher__username"],
            "questions": row["questions"] or 0,
            "empty_rate": qa_rate(row["empty"] or 0, (row["questions"] or 0) - (row["skip"] or 0)),
            "feedback_rate": qa_rate(row["positive"] or 0, row["rated"] or 0),
            "rated": row["rated"] or 0,
            "degraded_rate": qa_rate(row["degraded"] or 0, row["questions"] or 0),
        }
        for row in rows
    ]


def quality_daily(qs) -> list[dict]:
    """日趋势（本地时区）：提问量 / 为空率 / 好评率 / 降级率。"""
    rows = list(
        qs.annotate(day=TruncDate("created_at", tzinfo=timezone.get_current_timezone()))
        .values("day")
        .annotate(
            questions=Count("id"),
            skip=Count("id", filter=Q(skip_retrieval=True)),
            empty=Count("id", filter=Q(cited_chunks=[]) & Q(skip_retrieval=False)),
            rated=Count("id", filter=Q(feedback__in=[1, -1])),
            positive=Count("id", filter=Q(feedback=1)),
            degraded=Count("id", filter=Q(context_snapshot__degraded_level__gt=0)),
        )
        .order_by("day")
    )
    return [
        {
            "date": row["day"].isoformat() if row["day"] else None,
            "questions": row["questions"] or 0,
            "empty_rate": qa_rate(row["empty"] or 0, (row["questions"] or 0) - (row["skip"] or 0)),
            "feedback_rate": qa_rate(row["positive"] or 0, row["rated"] or 0),
            "degraded_rate": qa_rate(row["degraded"] or 0, row["questions"] or 0),
        }
        for row in rows
    ]


def quality_by_source(qs) -> dict:
    """引用来源分布：cited_chunks[].source 计数（一条多引用各计一次）。

    SQLite 无 JSON 数组聚合函数，Python 侧扫描窗口样本（上限 QA_SOURCE_SCAN_LIMIT
    条记录，超出截断并记服务端日志；正常数据量下不会触发）。
    """
    counter: dict[str, int] = {}
    scanned = 0
    truncated = False
    for cited in qs.values_list("cited_chunks", flat=True).iterator(chunk_size=500):
        if scanned >= QA_SOURCE_SCAN_LIMIT:
            truncated = True
            break
        scanned += 1
        if not isinstance(cited, list):
            continue
        for item in cited:
            source = (item or {}).get("source") or "unknown"
            counter[source] = counter.get(source, 0) + 1
    if truncated:
        logger.warning(
            "qa-quality by_source 扫描超过 %d 条记录上限，结果已截断",
            QA_SOURCE_SCAN_LIMIT,
        )
    return counter


def quality_alerts(base=None, *, include_platform=False, now=None) -> list[dict]:
    """问答质量告警（仅展示不推送）：为空率超阈值（平台 + 课程级）、L4 突增。

    固定按「近 7 天」评估——告警是运维信号，与看板窗口选择解耦。
    base：调用方按权限收窄后的 QARecord 基础 queryset（平台传全量，
    教师传本人课程）；为空表示全量。
    include_platform：是否产出平台级为空率告警（全量口径；教师端不产出，
    课程级告警始终产出）。
    """
    now = now or timezone.now()
    alerts: list[dict] = []
    week_start = now - timedelta(days=7)
    qs = qa_record_qs(week_start, now, base=base)
    agg = qs.aggregate(
        questions=Count("id"),
        skip=Count("id", filter=Q(skip_retrieval=True)),
        empty=Count("id", filter=Q(cited_chunks=[]) & Q(skip_retrieval=False)),
        degraded_l4=Count("id", filter=Q(context_snapshot__degraded_level=4)),
    )
    questions = agg["questions"] or 0
    empty_rate = qa_rate(agg["empty"] or 0, questions - (agg["skip"] or 0))
    if include_platform and empty_rate is not None and questions >= 10:
        if empty_rate > EMPTY_RATE_ERROR:
            alerts.append({
                "type": "empty_retrieval_high",
                "level": "error",
                "title": "检索为空率偏高",
                "detail": f"近 7 天检索为空率 {empty_rate:.1%}，"
                          f"超过 {EMPTY_RATE_ERROR:.0%} 阈值，建议检查课程资料覆盖",
                "course_id": None,
            })
        elif empty_rate > EMPTY_RATE_WARN:
            alerts.append({
                "type": "empty_retrieval_high",
                "level": "warning",
                "title": "检索为空率偏高",
                "detail": f"近 7 天检索为空率 {empty_rate:.1%}，"
                          f"超过 {EMPTY_RATE_WARN:.0%} 阈值，建议关注资料覆盖",
                "course_id": None,
            })
    # 课程级为空率告警（最小样本量防噪声）
    for row in quality_by_course(qs):
        rate = row["empty_rate"]
        if rate is None or row["questions"] < COURSE_ALERT_MIN_QUESTIONS:
            continue
        level = "error" if rate > EMPTY_RATE_ERROR else (
            "warning" if rate > EMPTY_RATE_WARN else None
        )
        if level:
            crossed = EMPTY_RATE_ERROR if level == "error" else EMPTY_RATE_WARN
            alerts.append({
                "type": "empty_retrieval_high",
                "level": level,
                "title": f"检索为空率偏高 · {row['course_name']}",
                "detail": f"近 7 天该课程为空率 {rate:.1%}，"
                          f"超过 {crossed:.0%} 阈值",
                "course_id": row["course_id"],
            })
    # L4 突增：近 7 天占比超阈值，或较前 7 天翻倍
    l4_rate = qa_rate(agg["degraded_l4"] or 0, questions)
    prev = qa_record_qs(
        week_start - timedelta(days=7), week_start - timedelta(seconds=1), base=base
    ).aggregate(
        questions=Count("id"),
        degraded_l4=Count("id", filter=Q(context_snapshot__degraded_level=4)),
    )
    prev_questions = prev["questions"] or 0
    prev_l4_rate = qa_rate(prev["degraded_l4"] or 0, prev_questions)
    if l4_rate is not None and l4_rate > L4_RATE_WARN:
        alerts.append({
            "type": "l4_surge",
            "level": "warning",
            "title": "上下文全丢（L4）占比偏高",
            "detail": f"近 7 天 L4 占比 {l4_rate:.1%}，超过 {L4_RATE_WARN:.0%} 阈值，"
                      "通常意味着长会话频繁触发上下文超限",
            "course_id": None,
        })
    elif (
        l4_rate is not None
        and l4_rate > 0
        and prev_l4_rate is not None
        and prev_l4_rate > 0  # 上周期零 L4 时无正基数可比（0→超阈值已由绝对阈值分支覆盖）
        and prev_questions >= 10
        and l4_rate >= prev_l4_rate * L4_SURGE_RATIO
    ):
        alerts.append({
            "type": "l4_surge",
            "level": "warning",
            "title": "上下文全丢（L4）环比突增",
            "detail": f"近 7 天 L4 占比 {l4_rate:.1%}，为前 7 天（{prev_l4_rate:.1%}）的 "
                      f"{l4_rate / prev_l4_rate:.1f} 倍",
            "course_id": None,
        })
    return alerts


class BaseQAQualityStatsView(APIView):
    """问答质量看板统计视图基类（平台 / 教师端共用装配）。

    子类声明：
    - permission_classes：平台 IsPlatformAdmin / 教师 IsTeacher
    - qa_base_queryset(request)：行级过滤后的 QARecord 基础 queryset
    - include_cost：是否产出成本段（教师端 False，AICallLog 无课程归属）
    - include_platform_alerts：是否产出平台级为空率告警（仅平台端）
    - extra_alerts(request)：追加特有告警（如平台端 AI 服务健康）

    响应形状（data）：window / totals / degraded / by_course / daily /
    by_source / alerts；环比基线（rate_previous 等）由本类统一注入。
    """

    default_days = 30
    include_cost = True
    include_platform_alerts = False

    def qa_base_queryset(self, request):
        """行级过滤后的 QARecord 基础 queryset（子类必须实现）。"""
        raise NotImplementedError("qa_base_queryset 必须由子类实现")

    def extra_alerts(self, request) -> list[dict]:
        """子类可追加的特有告警（如平台端 AI 服务健康）；默认无。"""
        return []

    def get(self, request):
        try:
            window = call_log_window(request, default_days=self.default_days)
        except CallLogWindowError as exc:
            return api_response(message=str(exc), code=400, status=400)
        base = self.qa_base_queryset(request)
        current = self._collect(window["start"], window["end"], base)
        previous = self._collect(
            window["previous_start"], window["previous_end"], base, breakdowns=False
        )
        totals = current["totals"]
        # 环比基线：各比率附前一等长周期同口径值（None=上周期无数据）
        for name in ("empty_retrieval", "rewrite", "fallback"):
            totals[name]["rate_previous"] = previous["totals"][name]["rate"]
        totals["feedback"]["rate_previous"] = previous["totals"]["feedback"]["rate"]
        totals["feedback"]["coverage_previous"] = previous["totals"]["feedback"]["coverage"]
        degraded = current["degraded"]
        degraded["degraded_rate_previous"] = previous["degraded"]["degraded_rate"]
        return api_response({
            # 统一转本地时区输出（同调用统计页口径）
            "window": {
                "start": timezone.localtime(window["start"]).isoformat(),
                "end": timezone.localtime(window["end"]).isoformat(),
                "days": window["days"],
                "source": window["source"],
                "previous_start": timezone.localtime(window["previous_start"]).isoformat(),
                "previous_end": timezone.localtime(window["previous_end"]).isoformat(),
            },
            "totals": totals,
            "degraded": degraded,
            "by_course": current["by_course"],
            "daily": current["daily"],
            "by_source": current["by_source"],
            "alerts": (
                quality_alerts(base=base, include_platform=self.include_platform_alerts)
                + self.extra_alerts(request)
            ),
        })

    @classmethod
    def _collect(cls, start, end, base, breakdowns: bool = True) -> dict:
        """汇总一个时间窗的指标（totals / 降级分布；breakdowns 时再加课程排行/日趋势/来源）。"""
        qs = qa_record_qs(start, end, base=base)
        result = quality_totals(qs, start, end, include_cost=cls.include_cost)
        if breakdowns:
            result["by_course"] = quality_by_course(qs)
            result["daily"] = quality_daily(qs)
            result["by_source"] = quality_by_source(qs)
        return result
