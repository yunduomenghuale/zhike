"""URL 路由入口。"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import Http404
from django.urls import include, path

from apps.ai.views import AITaskActiveView, AITaskDetailView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

api_patterns = [
    path("auth/", include("apps.users.urls")),
    path("", include("apps.users.notify_urls")),
    path("ai/", include("apps.ai.urls")),
    # AI 异步任务轮询（班级学情分析/章节学习总结/AI 生题通用，设计方案 §2.3）
    path("ai-tasks/active/", AITaskActiveView.as_view(), name="ai-task-active"),
    path("ai-tasks/<int:task_id>/", AITaskDetailView.as_view(), name="ai-task-detail"),
    path("analytics/", include("apps.analytics.urls")),
    path("admin-panel/", include("apps.platform_admin.urls")),
    # 各业务模块 router 直接挂在 /api/ 根下（resource 名即完整路径）
    path("", include("apps.courses.urls")),
    path("", include("apps.classroom.urls")),
    path("", include("apps.knowledge.urls")),
    path("", include("apps.questions.urls")),
    path("", include("apps.homework.urls")),
    path("", include("apps.exams.urls")),
    path("", include("apps.labs.urls")),
]

def _gated_api_docs(view_cls, **initkwargs):
    """OpenAPI 文档运行时门控（P5-A3）。

    必须在**请求期**读 settings（而非 urls.py 导入期判断）：
    ① URLconf 只在首次 import 时执行模块级 if，运行时改环境无法生效；
    ② override_settings 也要能命中，便于测试验证生产关闭行为。
    """

    def handler(request, *args, **kwargs):
        if not getattr(settings, "API_DOCS_ENABLED", False):
            raise Http404
        return view_cls.as_view(**initkwargs)(request, *args, **kwargs)

    return handler


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(api_patterns)),
    # OpenAPI 文档：默认仅 DEBUG 开放，生产关闭（settings.API_DOCS_ENABLED）
    path("api/schema/", _gated_api_docs(SpectacularAPIView), name="schema"),
    path(
        "api/docs/",
        _gated_api_docs(SpectacularSwaggerView, url_name="schema"),
        name="swagger-ui",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
