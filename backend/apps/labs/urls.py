from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views
from .views import (
    LabGuideViewSet,
    LabScheduleViewSet,
    LabSubmissionViewSet,
    LabTemplateViewSet,
    LabViewSet,
)

router = DefaultRouter()
router.register("lab-templates", LabTemplateViewSet, basename="lab-template")
router.register("labs", LabViewSet, basename="lab")
router.register("lab-schedules", LabScheduleViewSet, basename="lab-schedule")
router.register("lab-submissions", LabSubmissionViewSet, basename="lab-submission")
router.register("lab-guide", LabGuideViewSet, basename="lab-guide")

urlpatterns = [
    # 实验页门控（显式 path 须在 router.urls 前；资产路径无尾斜杠，不能用 router）
    path("lab-gate/page/<uuid:token>/", views.lab_gate_page, name="lab-gate-page"),
    path("lab-gate/asset/<uuid:token>/<str:sig>/<int:exp>/<path:rest>", views.lab_gate_asset, name="lab-gate-asset"),
] + router.urls
