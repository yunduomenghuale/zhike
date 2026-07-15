from rest_framework.routers import DefaultRouter

from .views import ExamLogViewSet, ExamSubmissionViewSet, ExamViewSet

router = DefaultRouter()
router.register("exams", ExamViewSet, basename="exam")
router.register("exam-submissions", ExamSubmissionViewSet, basename="exam-submission")
router.register("exam-logs", ExamLogViewSet, basename="exam-log")

urlpatterns = router.urls
