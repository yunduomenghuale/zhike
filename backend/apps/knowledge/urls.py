from rest_framework.routers import DefaultRouter

from .views import MaterialViewSet, QARecordViewSet

router = DefaultRouter()
router.register("materials", MaterialViewSet, basename="material")
router.register("qa-records", QARecordViewSet, basename="qa-record")

urlpatterns = router.urls
