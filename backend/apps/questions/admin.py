from django.contrib import admin

from .models import AnswerRecord, Question, QuestionDraftBatch


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "stem", "course", "qtype", "difficulty", "status", "source")
    list_filter = ("qtype", "difficulty", "status", "source")
    search_fields = ("stem",)


@admin.register(QuestionDraftBatch)
class QuestionDraftBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "origin", "course", "catalog", "creator", "status", "file_name", "created_at")
    list_filter = ("origin", "status")
    search_fields = ("file_name",)


@admin.register(AnswerRecord)
class AnswerRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "question", "scene", "is_correct", "score", "submitted_at")
    list_filter = ("scene", "is_correct")
