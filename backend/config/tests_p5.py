"""P5-A3：OpenAPI 文档端点生产关闭准出。

`/api/schema/` `/api/docs/` 由 settings.API_DOCS_ENABLED 门控（默认跟随 DEBUG）：
生产（DEBUG=False 且未显式开启）返回 404，非生产正常访问。
"""
from django.test import TestCase, override_settings


class ApiDocsGateTests(TestCase):
    def test_enabled_by_default_in_dev(self):
        res = self.client.get("/api/schema/")
        self.assertEqual(res.status_code, 200)
        res = self.client.get("/api/docs/")
        self.assertEqual(res.status_code, 200)

    @override_settings(API_DOCS_ENABLED=False)
    def test_disabled_production_returns_404(self):
        res = self.client.get("/api/schema/")
        self.assertEqual(res.status_code, 404)
        res = self.client.get("/api/docs/")
        self.assertEqual(res.status_code, 404)
