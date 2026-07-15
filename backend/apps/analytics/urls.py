from django.urls import path

from .views import ClassStatsView, MyWrongQuestionsView

urlpatterns = [
    path("class/<int:class_id>/", ClassStatsView.as_view(), name="class-stats"),
    path("my-wrong-questions/", MyWrongQuestionsView.as_view(), name="my-wrong-questions"),
]
