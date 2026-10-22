from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.response import api_response

from .calllog import ai_scene
from .models import AICallLog
from .providers.factory import get_provider


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
        return api_response({"audio_url": url})


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
    if task.classroom_id and task.classroom.teacher_id == user.id:
        return True
    if task.catalog_id:
        if task.course_id and task.course and task.course.teacher_id == user.id:
            return True
        if task.student_id and task.student_id == user.id:
            return True
    return False


class AITaskDetailView(APIView):
    """AI 异步任务轮询（班级学情分析 / 章节学习总结通用）。

    前端 2.5s 轮询（与讲稿生成同款）：{status, progress, result, error}；
    进度与结果全程落 AITask 行，刷新/重登后轮询同一 task_id 继续。
    """

    permission_classes = [IsAuthenticated]
    serializer_class = AITaskSerializer

    def get(self, request, task_id):
        from .models import AITask

        task = AITask.objects.filter(id=task_id).first()
        if not task or not _task_visible(task, request.user):
            return api_response(message="任务不存在或无权查看", code=404, status=404)
        return api_response({
            "id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "version": task.version,
            "progress": task.progress,
            "result": task.result,
            "error": task.error,
            "created_at": task.created_at,
            "finished_at": task.finished_at,
        })
