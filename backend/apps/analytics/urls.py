from django.urls import path

from .views import (
    ChapterSummaryView,
    ClassAIReportHistoryView,
    ClassAIReportView,
    ClassChapterSummariesView,
    ClassExportView,
    ClassStatsView,
    ClassStudentDetailView,
    MyWrongQuestionsView,
)

urlpatterns = [
    path("class/<int:class_id>/", ClassStatsView.as_view(), name="class-stats"),
    path("class/<int:class_id>/export/", ClassExportView.as_view(), name="class-export"),
    path("class/<int:class_id>/ai-report/", ClassAIReportView.as_view(), name="class-ai-report"),
    path(
        "class/<int:class_id>/ai-reports/",
        ClassAIReportHistoryView.as_view(),
        name="class-ai-report-history",
    ),
    path(
        "class/<int:class_id>/chapter-summaries/",
        ClassChapterSummariesView.as_view(),
        name="class-chapter-summaries",
    ),
    path(
        "class/<int:class_id>/students/<int:student_id>/",
        ClassStudentDetailView.as_view(),
        name="class-student-detail",
    ),
    path("chapter-summaries/", ChapterSummaryView.as_view(), name="chapter-summaries"),
    path("my-wrong-questions/", MyWrongQuestionsView.as_view(), name="my-wrong-questions"),
]
