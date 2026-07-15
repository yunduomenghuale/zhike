from django.contrib import admin

from .models import KnowledgeChunk, Material, QARecord


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("file_name", "course", "file_type", "parse_status", "qa_open", "created_at")
    list_filter = ("parse_status", "qa_open", "file_type")
    search_fields = ("file_name",)


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(admin.ModelAdmin):
    list_display = ("id", "material", "course", "page")
    search_fields = ("content",)


@admin.register(QARecord)
class QARecordAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "course", "question", "created_at")
    search_fields = ("question", "answer")
