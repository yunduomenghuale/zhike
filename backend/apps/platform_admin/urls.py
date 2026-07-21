from django.urls import path

from .views import (
    AdminClassListView,
    AdminCourseListView,
    AdminCourseStatusView,
    AdminOverviewView,
    AdminPasswordResetView,
    AdminUserDetailView,
    AdminUserListCreateView,
    AdminAIConfigurationView,
    AdminAIConnectionTestView,
)

urlpatterns = [
    path("overview/", AdminOverviewView.as_view(), name="admin-overview"),
    path("users/", AdminUserListCreateView.as_view(), name="admin-users"),
    path("users/<int:user_id>/", AdminUserDetailView.as_view(), name="admin-user-detail"),
    path("users/<int:user_id>/reset-password/", AdminPasswordResetView.as_view(), name="admin-reset-password"),
    path("courses/", AdminCourseListView.as_view(), name="admin-courses"),
    path("courses/<int:course_id>/status/", AdminCourseStatusView.as_view(), name="admin-course-status"),
    path("classes/", AdminClassListView.as_view(), name="admin-classes"),
    path("ai-configuration/", AdminAIConfigurationView.as_view(), name="admin-ai-configuration"),
    path("ai-configuration/test/", AdminAIConnectionTestView.as_view(), name="admin-ai-test"),
]
