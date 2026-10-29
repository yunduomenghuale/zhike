# -*- coding: utf-8 -*-
"""教师端导出限流（班级学习数据 Excel 导出）。

参照 questions/throttles.py 的模式：独立设置项 TEACHER_EXPORT_THROTTLE_RATES
（测试可整体置 None 关闭），速率按已登录用户计数（DRF UserRateThrottle 语义）。
导出走全量查询 + openpyxl 生成，成本高于常规读，单独一档。
"""
from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class TeacherExportThrottle(SimpleRateThrottle):
    scope = "teacher_export"

    def get_cache_key(self, request, view):
        # SimpleRateThrottle 基类未实现 get_cache_key（会抛 NotImplementedError），
        # 这里按 ScopedRateThrottle 的口径：登录用户按 user.pk，未登录按 IP。
        if request.user and request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}

    def get_rate(self):
        rates = getattr(settings, "TEACHER_EXPORT_THROTTLE_RATES", None) or {}
        return rates.get(self.scope)
