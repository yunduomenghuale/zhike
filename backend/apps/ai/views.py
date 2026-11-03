from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.response import api_response

from .calllog import ai_scene
from .models import AICallLog
from .providers.factory import get_provider
from .providers.fallback import consume_fallback


class AIProviderInfoSerializer(serializers.Serializer):
    provider = serializers.CharField(read_only=True)


class TTSPreviewSerializer(serializers.Serializer):
    text = serializers.CharField(write_only=True)
    voice = serializers.CharField(write_only=True, required=False)
    speed = serializers.FloatField(write_only=True, required=False)
    audio_url = serializers.CharField(read_only=True)


class AIProviderInfoView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AIProviderInfoSerializer

    def get(self, request):
        from apps.ai.models import AICapabilityConfig

        providers = {}
        for capability, _label in AICapabilityConfig.Capability.choices:
            providers[capability] = get_provider(capability).name
        return api_response({"providers": providers})


class TTSPreviewView(APIView):
    """AI 配音试听（需求 T-V-03）。返回音频地址。"""

    permission_classes = [IsAuthenticated]
    serializer_class = TTSPreviewSerializer

    def post(self, request):
        text = request.data.get("text", "")
        voice = request.data.get("voice", "default")
        speed = float(request.data.get("speed", 1.0))
        try:
            with ai_scene(AICallLog.Scene.TTS_PREVIEW):
                url = get_provider("tts").tts(text, voice=voice, speed=speed)
        except NotImplementedError as exc:
            return api_response(message=str(exc), code=501, status=501)
        data = {"audio_url": url}
        # P5-B7：Mock 回退显性化（配音试听是演示高频入口）
        fallback = consume_fallback()
        data["provider_fallback"] = bool(fallback)
        if fallback:
            data["fallback_reason"] = fallback
        return api_response(data)


class AITaskSerializer(serializers.Serializer):
    """Schema marker for AI async task polling responses."""

    id = serializers.IntegerField(read_only=True)
    task_type = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    version = serializers.IntegerField(read_only=True)
    progress = serializers.JSONField(read_only=True)
    result = serializers.JSONField(read_only=True)
    error = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    finished_at = serializers.DateTimeField(read_only=True)


def _task_visible(task, user) -> bool:
    """任务可见性 4 条规则（F7）：满足任一即放行，否则 404 不暴露存在性。

    1. 发起人本人；2. 班级归属教师；3. 章节总结场景：课程教师或总结对象
    学生本人；4. 平台管理员。
    """
    from apps.common.access import is_platform_admin

    if is_platform_admin(user):
        return True
    if task.triggered_by_id and task.triggered_by_id == user.id:
        return True
    if task.classroom_id and task.course_id and task.course and task.course.teacher_id == user.id:
        return True
    if task.catalog_id:
        if task.course_id and task.course and task.course.teacher_id == user.id:
            return True
        if task.student_id and task.student_id == user.id:
            return True
    return False


class AITaskDetailView(APIView):
    """AI 异步任务轮询（班级学情分析 / 章节学习总结 / AI 生题/讲稿/配音通用）。

    前端 2.5s 轮询（与讲稿生成同款）：{status, progress, result, error}；
    进度与结果全程落 AITask 行，刷新/重登后轮询同一 task_id 继续。
    queue_position/eta_seconds 读时现算不落库（评审 C5）。
    """

    permission_classes = [IsAuthenticated]
    serializer_class = AITaskSerializer

    def get(self, request, task_id):
        from .models import AITask
        from .queue import queue_position

        task = AITask.objects.filter(id=task_id).first()
        if not task or not _task_visible(task, request.user):
            return api_response(message="任务不存在或无权查看", code=404, status=404)
        position = queue_position(task)
        return api_response({
            "id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "version": task.version,
            "progress": task.progress,
            "result": task.result,
            "error": task.error,
            "queue_position": position,
            "eta_seconds": max(0, (position or 1) - 1) * 60 if position else 0,
            "cancel_requested": task.cancel_requested,
            "created_at": task.created_at,
            "finished_at": task.finished_at,
        })


class AITaskActiveView(APIView):
    """当前用户进行中的 AI 任务列表（任务中心「离开页面不丢失」恢复入口）。

    ?task_type=all 返回全部类型（任务中心用）；默认 question_gen 兼容旧前端。
    只返回本人发起的任务（triggered_by）。结果按用户 3s 文件缓存（C10：
    多教师轮询不会放大成 DB 常驻压力；文件缓存跨 gunicorn worker 一致）。
    """

    permission_classes = [IsAuthenticated]
    serializer_class = AITaskSerializer

    def get(self, request):
        from django.core.cache import caches

        from .models import AITask
        from .queue import queue_position

        task_type = request.query_params.get("task_type", AITask.TaskType.QUESTION_GEN)
        cache = caches["oversight"]
        cache_key = f"ai_active:{request.user.id}:{task_type or 'all'}"
        cached = cache.get(cache_key)
        if cached is not None:
            return api_response(cached)

        qs = AITask.objects.filter(
            triggered_by=request.user,
            status__in=[AITask.Status.PENDING, AITask.Status.RUNNING],
        ).select_related("course", "catalog").order_by("-created_at")
        if task_type and task_type != "all":
            qs = qs.filter(task_type=task_type)
        data = [
            {
                "id": t.id,
                "task_type": t.task_type,
                "status": t.status,
                "version": t.version,
                "progress": t.progress,
                "queue_position": queue_position(t),
                "course": t.course_id,
                "course_name": t.course.name if t.course_id else "",
                "catalog": t.catalog_id,
                "catalog_title": t.catalog.title if t.catalog_id else "",
                "created_at": t.created_at,
            }
            for t in qs[:20]
        ]
        cache.set(cache_key, data, 3)
        return api_response(data)


class AITaskCancelView(APIView):
    """取消任务（任务中心取消按钮，§6）：pending 立即取消；running 在批次边界退出。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, task_id):
        from .models import AITask
        from .queue import cancel

        task = AITask.objects.filter(id=task_id).first()
        if not task or not _task_visible(task, request.user):
            return api_response(message="任务不存在或无权操作", code=404, status=404)
        outcome = cancel(task.id)
        if outcome == "invalid_state":
            return api_response(message="任务已结束，无法取消", code=400, status=400)
        task.refresh_from_db()
        return api_response({"id": task.id, "status": task.status, "cancel_outcome": outcome}, message="已取消")


class AITaskRetryView(APIView):
    """重试失败/已取消的任务（复用同一行，attempts 归零回 pending，§7.2）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, task_id):
        from django.utils import timezone

        from .models import AITask

        task = AITask.objects.filter(id=task_id).first()
        if not task or not _task_visible(task, request.user):
            return api_response(message="任务不存在或无权操作", code=404, status=404)
        if task.status not in (AITask.Status.FAILED, AITask.Status.CANCELLED):
            return api_response(message="仅失败或已取消的任务可重试", code=400, status=400)
        task.status = AITask.Status.PENDING
        task.attempts = 0
        task.error = ""
        task.cancel_requested = False
        task.finished_at = None
        task.claimed_by = ""
        task.heartbeat_at = None
        task.next_run_at = timezone.now()
        task.save(update_fields=["status", "attempts", "error", "cancel_requested", "finished_at", "claimed_by", "heartbeat_at", "next_run_at", "updated_at"])
        return api_response({"id": task.id, "status": task.status}, message="已重新排队")


class AIQueueDashboardView(APIView):
    """管理端「任务队列」看板（C9/方案 §10）：全量统计、活跃任务明细与近期失败列表。

    pending/running/failed 按类型分布、近 24h 平均排队时长（created→started）、
    活跃任务明细（用户/课程/章节/内容量/排队位）、失败原因 Top5、
    近期失败/完成记录、当前 worker 心跳（另见 worker-health 的槽位明细）。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.common.access import is_platform_admin

        if not is_platform_admin(request.user):
            return api_response(message="仅平台管理员可查看", code=403, status=403)

        from .queue import queue_position

        from django.db.models import Count
        from django.utils import timezone

        from .models import AITask

        by_status = {
            row["status"]: row["n"]
            for row in AITask.objects.filter(
                status__in=[AITask.Status.PENDING, AITask.Status.RUNNING, AITask.Status.FAILED]
            ).values("status").annotate(n=Count("id"))
        }
        by_type = {
            row["task_type"]: row["n"]
            for row in AITask.objects.filter(
                status__in=[AITask.Status.PENDING, AITask.Status.RUNNING]
            ).values("task_type").annotate(n=Count("id"))
        }
        day_ago = timezone.now() - timezone.timedelta(hours=24)
        # 平均排队时长（created→started）：样本量小（近 24h 启动的任务），
        # Python 侧算均值，不依赖 ORM 时间差方言（ExtractEpoch 是第三方库的）
        rows = AITask.objects.filter(started_at__isnull=False, created_at__gte=day_ago).values_list(
            "created_at", "started_at"
        )[:500]
        waits = [(s - c).total_seconds() for c, s in rows if c and s]
        avg_wait = sum(waits) / len(waits) if waits else None
        top_errors = [
            {"error": row["error"][:120], "count": row["n"]}
            for row in AITask.objects.filter(status=AITask.Status.FAILED, error__gt="")
            .values("error").annotate(n=Count("id")).order_by("-n")[:5]
        ]

        def _task_row(t, with_position=False):
            row = {
                "id": t.id,
                "task_type": t.task_type,
                "status": t.status,
                "priority": t.priority,
                "attempts": t.attempts,
                "user": (
                    {"username": t.triggered_by.username, "real_name": t.triggered_by.real_name}
                    if t.triggered_by_id
                    else None
                ),
                "course": {"id": t.course_id, "name": t.course.name} if t.course_id else None,
                "catalog": {"id": t.catalog_id, "title": t.catalog.title} if t.catalog_id else None,
                "progress": t.progress or {},
                "error": (t.error or "")[:200],
                "created_at": t.created_at,
                "started_at": t.started_at,
                "finished_at": t.finished_at,
            }
            if with_position:
                row["queue_position"] = queue_position(t)
            return row

        active_qs = AITask.objects.filter(
            status__in=[AITask.Status.PENDING, AITask.Status.RUNNING]
        ).select_related("triggered_by", "course", "catalog").order_by("priority", "id")[:50]
        active_tasks = [_task_row(t, with_position=True) for t in active_qs]
        recent_failed = [
            _task_row(t)
            for t in AITask.objects.filter(status=AITask.Status.FAILED)
            .select_related("triggered_by", "course", "catalog")
            .order_by("-id")[:10]
        ]
        recent_success = [
            _task_row(t)
            for t in AITask.objects.filter(status=AITask.Status.SUCCESS)
            .select_related("triggered_by", "course", "catalog")
            .order_by("-id")[:10]
        ]
        last_hb = AITask.objects.filter(
            status=AITask.Status.RUNNING, heartbeat_at__isnull=False
        ).values_list("heartbeat_at", flat=True).order_by("-heartbeat_at").first()
        return api_response(
            {
                "by_status": by_status,
                "active_by_type": by_type,
                "avg_wait_seconds_24h": round(avg_wait, 1) if avg_wait is not None else None,
                "top_errors": top_errors,
                "active_tasks": active_tasks,
                "recent_failed": recent_failed,
                "recent_success": recent_success,
                "worker_last_heartbeat": last_hb,
            }
        )


class AIWorkerHealthView(APIView):
    """worker/队列健康（管理端，§2.5.6 兜底：渲染并发在 Windows 本地看不到
    2 个 soffice，靠槽位占用自报验证并发生效）。

    输出：各类型 pending/running 深度、最近心跳（worker 存活）、渲染并发配置
    与当前占用的槽位号（读 render-guard 的 slots.json，worker 与 API 共享
    /app/data 卷；读不到/过期则报 unknown 而不是编造）。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.common.access import is_platform_admin

        if not is_platform_admin(request.user):
            return api_response(message="仅平台管理员可查看", code=403, status=403)

        import json as _json
        import sys
        from pathlib import Path

        from django.conf import settings
        from django.db.models import Count
        from django.utils import timezone

        from .models import AITask

        by_type: dict = {}
        for row in AITask.objects.filter(status__in=[AITask.Status.PENDING, AITask.Status.RUNNING]).values(
            "task_type", "status"
        ).annotate(n=Count("id")):
            bucket = by_type.setdefault(row["task_type"], {"pending": 0, "running": 0})
            bucket[row["status"]] = row["n"]
        last_heartbeat = AITask.objects.filter(
            status=AITask.Status.RUNNING, heartbeat_at__isnull=False
        ).values_list("heartbeat_at", flat=True).order_by("-heartbeat_at").first()

        occupied_slots: list = []
        try:
            registry = Path(getattr(settings, "AI_RENDER_GUARD_DIR", "")) / "slots.json"
            if registry.exists():
                data = _json.loads(registry.read_text(encoding="utf-8") or "{}")
                occupied_slots = sorted({int(v) for v in data.values()})
        except Exception:
            occupied_slots = []

        return api_response(
            {
                "queue_depth": by_type,
                "worker_last_heartbeat": last_heartbeat,
                "worker_heartbeat_seconds_ago": (
                    (timezone.now() - last_heartbeat).total_seconds() if last_heartbeat else None
                ),
                "ai_render_concurrency": getattr(settings, "AI_RENDER_CONCURRENCY", None),
                "render_slots_occupied": occupied_slots,
                "render_slot_mode": "windows-1" if sys.platform == "win32" else "multi",
            }
        )
