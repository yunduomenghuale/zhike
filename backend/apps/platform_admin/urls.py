from django.urls import path

from .views import (
    AdminAICallLogExportView,
    AdminAICallLogListView,
    AdminAICallStatsView,
    AdminAIConfigChangeLogListView,
    AdminOverviewView,
    AdminPasswordResetView,
    AdminRebuildVectorsView,
    AdminUserDetailView,
    AdminUserImportConfirmView,
    AdminUserImportPreviewView,
    AdminUserImportTemplateView,
    AdminUserListCreateView,
    AdminAIConfigurationView,
    AdminAIConnectionTestView,
)
from .oversight_views import (
    AdminActionLogViewSet,
    AdminAlertsView,
    AdminClassViewSet,
    AdminCourseViewSet,
    AdminTeacherViewSet,
    AdminTrendsView,
)

# 督管三维/审计已 ViewSet 化（同资源多动作收口，2026-10-19）：URL 与映射逐条显式声明，
# 前端路径不变；as_view({HTTP 方法: 动作名}) 与 DRF router 内部机制一致。
urlpatterns = [
    path("overview/", AdminOverviewView.as_view(), name="admin-overview"),
    path("overview/trends/", AdminTrendsView.as_view(), name="admin-overview-trends"),
    path("overview/alerts/", AdminAlertsView.as_view(), name="admin-overview-alerts"),
    path("users/", AdminUserListCreateView.as_view(), name="admin-users"),
    path("users/import-template/", AdminUserImportTemplateView.as_view(), name="admin-user-import-template"),
    path("users/import-preview/", AdminUserImportPreviewView.as_view(), name="admin-user-import-preview"),
    path("users/import-confirm/", AdminUserImportConfirmView.as_view(), name="admin-user-import-confirm"),
    path("users/<int:user_id>/", AdminUserDetailView.as_view(), name="admin-user-detail"),
    path("users/<int:user_id>/reset-password/", AdminPasswordResetView.as_view(), name="admin-reset-password"),
    # 课程监管（列表带资产计数；状态变更带影响预览 + 审计）
    path("courses/", AdminCourseViewSet.as_view({"get": "list"}), name="admin-courses"),
    path("courses/export/", AdminCourseViewSet.as_view({"get": "export"}), name="admin-courses-export"),
    path("courses/<int:course_id>/detail/", AdminCourseViewSet.as_view({"get": "retrieve"}), name="admin-course-detail"),
    path("courses/<int:course_id>/status/", AdminCourseViewSet.as_view({"patch": "status"}), name="admin-course-status"),
    # 班级监管（列表带进度汇总；详情复用教师端聚合；状态干预带审计）
    path("classes/", AdminClassViewSet.as_view({"get": "list"}), name="admin-classes"),
    path("classes/export/", AdminClassViewSet.as_view({"get": "export"}), name="admin-classes-export"),
    path("classes/<int:class_id>/detail/", AdminClassViewSet.as_view({"get": "retrieve"}), name="admin-class-detail"),
    path("classes/<int:class_id>/status/", AdminClassViewSet.as_view({"patch": "status"}), name="admin-class-status"),
    # 教师监管
    path("teachers/", AdminTeacherViewSet.as_view({"get": "list"}), name="admin-teachers"),
    path("teachers/export/", AdminTeacherViewSet.as_view({"get": "export"}), name="admin-teachers-export"),
    path("teachers/<int:teacher_id>/detail/", AdminTeacherViewSet.as_view({"get": "retrieve"}), name="admin-teacher-detail"),
    # 操作审计
    path("action-logs/", AdminActionLogViewSet.as_view({"get": "list"}), name="admin-action-logs"),
    path("action-logs/export/", AdminActionLogViewSet.as_view({"get": "export"}), name="admin-action-logs-export"),
    path("ai-configuration/", AdminAIConfigurationView.as_view(), name="admin-ai-configuration"),
    path("ai-configuration/test/", AdminAIConnectionTestView.as_view(), name="admin-ai-test"),
    path("ai-call-logs/", AdminAICallLogListView.as_view(), name="admin-ai-call-logs"),
    path("ai-call-logs/export/", AdminAICallLogExportView.as_view(), name="admin-ai-call-logs-export"),
    path("ai-call-stats/", AdminAICallStatsView.as_view(), name="admin-ai-call-stats"),
    path("ai-config-changes/", AdminAIConfigChangeLogListView.as_view(), name="admin-ai-config-changes"),
    path("rebuild-vectors/", AdminRebuildVectorsView.as_view(), name="admin-rebuild-vectors"),
]
