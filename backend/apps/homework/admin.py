from django.contrib import admin

from .models import Homework, HomeworkAnswer, HomeworkQuestion, HomeworkSubmission


class HomeworkQuestionInline(admin.TabularInline):
    model = HomeworkQuestion
    extra = 0
    readonly_fields = ("snapshot",)


@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "classroom", "mode", "deadline", "total_score", "status")
    list_filter = ("course", "mode", "status")
    search_fields = ("title",)
    inlines = (HomeworkQuestionInline,)


@admin.register(HomeworkSubmission)
class HomeworkSubmissionAdmin(admin.ModelAdmin):
    list_display = ("student", "homework", "score", "correct_status", "is_late", "submitted_at")
    list_filter = ("correct_status", "is_late")


@admin.register(HomeworkAnswer)
class HomeworkAnswerAdmin(admin.ModelAdmin):
    list_display = ("submission", "homework_question", "score", "is_correct", "graded_at")
    list_filter = ("is_correct",)
