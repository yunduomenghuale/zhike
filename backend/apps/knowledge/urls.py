from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    MaterialViewSet,
    QARecordViewSet,
    QASessionViewSet,
    TeacherQAIssueListView,
    TeacherQAQualityStatsView,
)

router = DefaultRouter()
router.register("materials", MaterialViewSet, basename="material")
router.register("qa-records", QARecordViewSet, basename="qa-record")
router.register("qa-sessions", QASessionViewSet, basename="qa-session")

# 教师端问答质量（质量看板 Phase 2）：统计与问题下钻。
# 显式 path 置于 router.urls 前，避免与 router 前缀匹配互相遮蔽。
urlpatterns = [
    path("qa-quality-stats/", TeacherQAQualityStatsView.as_view(), name="teacher-qa-quality-stats"),
    path("qa-issues/", TeacherQAIssueListView.as_view(), name="teacher-qa-issues"),
] + router.urls
