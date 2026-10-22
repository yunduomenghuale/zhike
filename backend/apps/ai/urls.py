from django.urls import path

from .views import AIProviderInfoView, AITaskDetailView, TTSPreviewView

urlpatterns = [
    path("provider/", AIProviderInfoView.as_view(), name="ai-provider"),
    path("tts/preview/", TTSPreviewView.as_view(), name="ai-tts-preview"),
    path("tasks/<int:task_id>/", AITaskDetailView.as_view(), name="ai-task-detail"),
]
