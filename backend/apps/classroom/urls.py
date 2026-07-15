from rest_framework.routers import DefaultRouter

from .views import ClassRoomViewSet, ClassStudentViewSet

router = DefaultRouter()
router.register("classes", ClassRoomViewSet, basename="class")
router.register("class-students", ClassStudentViewSet, basename="class-student")

urlpatterns = router.urls
