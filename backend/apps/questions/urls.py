from rest_framework.routers import DefaultRouter

from .views import (
    AnswerRecordViewSet,
    QuestionDraftBatchViewSet,
    QuestionViewSet,
    SceneTagViewSet,
    WrongNoteViewSet,
)

router = DefaultRouter()
router.register("questions", QuestionViewSet, basename="question")
router.register("question-scene-tags", SceneTagViewSet, basename="question-scene-tag")
router.register("question-draft-batches", QuestionDraftBatchViewSet, basename="question-draft-batch")
router.register("answer-records", AnswerRecordViewSet, basename="answer-record")
router.register("wrong-notes", WrongNoteViewSet, basename="wrong-note")

urlpatterns = router.urls

from django.urls import path as _path
from .views import QuestionImageUploadView as _QuestionImageUploadView
from .views import WrongMasteryView as _WrongMasteryView

urlpatterns += [
    _path("wrong-mastery/", _WrongMasteryView.as_view(), name="wrong-mastery"),
    _path("question-images/upload/", _QuestionImageUploadView.as_view(), name="question-image-upload"),
]
