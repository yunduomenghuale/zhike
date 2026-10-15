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
