from django.urls import path

from .views import (
    ChapterSummaryView,
    ClassAIReportView,
    ClassStatsView,
    ClassStudentDetailView,
    MyWrongQuestionsView,
)

urlpatterns = [
    path("class/<int:class_id>/", ClassStatsView.as_view(), name="class-stats"),
    path("class/<int:class_id>/ai-report/", ClassAIReportView.as_view(), name="class-ai-report"),
    path(
        "class/<int:class_id>/students/<int:student_id>/",
        ClassStudentDetailView.as_view(),
        name="class-student-detail",
    ),
    path("chapter-summaries/", ChapterSummaryView.as_view(), name="chapter-summaries"),
    path("my-wrong-questions/", MyWrongQuestionsView.as_view(), name="my-wrong-questions"),
]
