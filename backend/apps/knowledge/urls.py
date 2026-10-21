from rest_framework.routers import DefaultRouter

from .views import MaterialViewSet, QARecordViewSet, QASessionViewSet

router = DefaultRouter()
router.register("materials", MaterialViewSet, basename="material")
router.register("qa-records", QARecordViewSet, basename="qa-record")
router.register("qa-sessions", QASessionViewSet, basename="qa-session")

urlpatterns = router.urls
