"""URL 路由入口。"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

api_patterns = [
    path("auth/", include("apps.users.urls")),
    path("ai/", include("apps.ai.urls")),
    path("analytics/", include("apps.analytics.urls")),
    path("admin-panel/", include("apps.platform_admin.urls")),
    # 各业务模块 router 直接挂在 /api/ 根下（resource 名即完整路径）
    path("", include("apps.courses.urls")),
    path("", include("apps.classroom.urls")),
    path("", include("apps.knowledge.urls")),
    path("", include("apps.questions.urls")),
    path("", include("apps.homework.urls")),
    path("", include("apps.exams.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(api_patterns)),
    # OpenAPI 文档
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
