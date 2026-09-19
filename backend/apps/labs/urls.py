from rest_framework.routers import DefaultRouter

from .views import LabScheduleViewSet, LabSubmissionViewSet, LabTemplateViewSet, LabViewSet

router = DefaultRouter()
router.register("lab-templates", LabTemplateViewSet, basename="lab-template")
router.register("labs", LabViewSet, basename="lab")
router.register("lab-schedules", LabScheduleViewSet, basename="lab-schedule")
router.register("lab-submissions", LabSubmissionViewSet, basename="lab-submission")

urlpatterns = router.urls
