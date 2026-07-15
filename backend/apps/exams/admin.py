from django.contrib import admin

from .models import Exam, ExamLog, ExamSubmission, Paper


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("name", "course", "classroom", "start_at", "duration", "status")
    list_filter = ("status",)
    search_fields = ("name",)


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin):
    list_display = ("id", "exam", "mode", "student", "total_score")
    list_filter = ("mode",)


@admin.register(ExamSubmission)
class ExamSubmissionAdmin(admin.ModelAdmin):
    list_display = ("student", "exam", "status", "objective_score", "total_score", "abnormal")
    list_filter = ("status", "abnormal")


@admin.register(ExamLog)
class ExamLogAdmin(admin.ModelAdmin):
    list_display = ("student", "exam", "action", "happened_at", "ip")
    list_filter = ("action",)
