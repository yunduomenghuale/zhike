from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    CatalogViewSet,
    CourseResourceViewSet,
    CourseVideoViewSet,
    CourseViewSet,
    PPTResourceViewSet,
    TeachingVideoViewSet,
    WatchProgressViewSet,
    course_resource_asset,
    course_resource_page,
    course_resource_preset_asset,
    course_resource_preset_page,
)

router = DefaultRouter()
router.register("courses", CourseViewSet, basename="course")
router.register("catalogs", CatalogViewSet, basename="catalog")
router.register("ppts", PPTResourceViewSet, basename="ppt")
router.register("videos", TeachingVideoViewSet, basename="video")
router.register("watch-progress", WatchProgressViewSet, basename="watch-progress")
router.register("course-resources", CourseResourceViewSet, basename="course-resource")
router.register("course-videos", CourseVideoViewSet, basename="course-video")

# 资源门控端点（签名 URL 直出静态页，须先于 router 的 detail 路由匹配）
urlpatterns = [
    path(
        "course-resources/page/<uuid:token>/",
        course_resource_page,
        name="course-resource-page",
    ),
    path(
        "course-resources/asset/<uuid:token>/<str:sig>/<int:exp>/<path:rest>",
        course_resource_asset,
        name="course-resource-asset",
    ),
    path(
        "course-resources/preset/<str:sig>/<int:exp>/<path:rest>",
        course_resource_preset_page,
        name="course-resource-preset-page",
    ),
    path(
        "course-resources/preset-asset/<str:sig>/<int:exp>/<path:rest>",
        course_resource_preset_asset,
        name="course-resource-preset-asset",
    ),
]
urlpatterns += router.urls
