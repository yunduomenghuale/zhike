from django.contrib import admin

from .models import Homework, HomeworkSubmission


@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "classroom", "deadline", "total_score", "status")
    list_filter = ("course", "status")
    search_fields = ("title",)


@admin.register(HomeworkSubmission)
class HomeworkSubmissionAdmin(admin.ModelAdmin):
    list_display = ("student", "homework", "score", "correct_status", "is_late", "submitted_at")
    list_filter = ("correct_status", "is_late")
