from django.contrib import admin

from .models import AnswerRecord, Question


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "stem", "course", "qtype", "difficulty", "status", "source")
    list_filter = ("qtype", "difficulty", "status", "source")
    search_fields = ("stem",)


@admin.register(AnswerRecord)
class AnswerRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "question", "scene", "is_correct", "score", "submitted_at")
    list_filter = ("scene", "is_correct")
