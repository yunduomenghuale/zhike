from rest_framework.routers import DefaultRouter

from .views import CatalogViewSet, CourseViewSet, PPTResourceViewSet, TeachingVideoViewSet

router = DefaultRouter()
router.register("courses", CourseViewSet, basename="course")
router.register("catalogs", CatalogViewSet, basename="catalog")
router.register("ppts", PPTResourceViewSet, basename="ppt")
router.register("videos", TeachingVideoViewSet, basename="video")

urlpatterns = router.urls
