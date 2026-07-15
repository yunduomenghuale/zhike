from rest_framework.routers import DefaultRouter

from .views import HomeworkSubmissionViewSet, HomeworkViewSet

router = DefaultRouter()
router.register("homeworks", HomeworkViewSet, basename="homework")
router.register("homework-submissions", HomeworkSubmissionViewSet, basename="homework-submission")

urlpatterns = router.urls
