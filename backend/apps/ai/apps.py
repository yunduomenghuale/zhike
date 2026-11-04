from django.apps import AppConfig


class AiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai"
    verbose_name = "AI 能力"

    def ready(self):
        # 片段写/删与 Qdrant 的同步（RAG_VECTOR_BACKEND=json 时是空操作）
        from .vector_sync import connect_signals

        connect_signals()
