from rest_framework.routers import DefaultRouter

from .views import AnswerRecordViewSet, QuestionViewSet, WrongNoteViewSet

router = DefaultRouter()
router.register("questions", QuestionViewSet, basename="question")
router.register("answer-records", AnswerRecordViewSet, basename="answer-record")
router.register("wrong-notes", WrongNoteViewSet, basename="wrong-note")

urlpatterns = router.urls

from django.urls import path as _path
from .views import WrongMasteryView as _WrongMasteryView

urlpatterns += [
    _path("wrong-mastery/", _WrongMasteryView.as_view(), name="wrong-mastery"),
]
