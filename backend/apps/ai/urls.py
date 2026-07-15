from django.urls import path

from .views import AIProviderInfoView, TTSPreviewView

urlpatterns = [
    path("provider/", AIProviderInfoView.as_view(), name="ai-provider"),
    path("tts/preview/", TTSPreviewView.as_view(), name="ai-tts-preview"),
]
