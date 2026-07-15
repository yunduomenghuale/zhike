from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.response import api_response

from .providers.factory import get_provider


class AIProviderInfoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        provider = get_provider()
        return api_response({"provider": provider.name})


class TTSPreviewView(APIView):
    """AI 配音试听（需求 T-V-03）。返回音频地址。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        text = request.data.get("text", "")
        voice = request.data.get("voice", "default")
        speed = float(request.data.get("speed", 1.0))
        try:
            url = get_provider().tts(text, voice=voice, speed=speed)
        except NotImplementedError as exc:
            return api_response(message=str(exc), code=501, status=501)
        return api_response({"audio_url": url})
