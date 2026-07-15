from rest_framework.routers import DefaultRouter

from .views import AnswerRecordViewSet, QuestionViewSet

router = DefaultRouter()
router.register("questions", QuestionViewSet, basename="question")
router.register("answer-records", AnswerRecordViewSet, basename="answer-record")

urlpatterns = router.urls
