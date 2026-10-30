# -*- coding: utf-8 -*-
"""全站基线限流的节流类（P5-C9）。

档位集中在 `settings.GLOBAL_THROTTLE_RATES`，运行期**动态读取**（与
platform_admin/throttles.py 同款模式）——DRF 内置 SimpleRateThrottle 在类
定义时固化 THROTTLE_RATES，override_settings 与测试置 None 都打不进去，
所以自实现 get_rate：rate=None 直接放行（测试关闭限流的统一姿势）。

- GlobalAnonThrottle / GlobalUserThrottle：全局两级（匿名/登录用户）；
- LoginThrottle：登录端点按 IP 从严（另有失败锁定兜底）；
- AIAskThrottle：AI 问答按用户从严（用户级日配额是第二道闸）。
"""
from django.core.exceptions import ImproperlyConfigured
from django.conf import settings as django_settings
from rest_framework.throttling import BaseThrottle, SimpleRateThrottle


class ScopedSettingThrottle(SimpleRateThrottle):
    """速率来自 settings.<rate_setting>[scope]，动态读取、None 放行。"""

    rate_setting = "GLOBAL_THROTTLE_RATES"
    scope = None

    def get_rate(self):
        rates = getattr(django_settings, self.rate_setting, None) or {}
        if self.scope not in rates:
            raise ImproperlyConfigured(
                f"限流档位缺失：{self.rate_setting} 中没有 {self.scope!r}"
            )
        return rates[self.scope]

    def allow_request(self, request, view):
        # rate=None（测试关闭/显式不限）直接放行；parse_rate(None) 会炸，提前走
        if self.get_rate() is None:
            self.rate = None
            return True
        self.rate = self.get_rate()
        return super().allow_request(request, view)


class GlobalAnonThrottle(ScopedSettingThrottle):
    scope = "anon"

    def get_cache_key(self, request, view):
        if request.user.is_authenticated:
            return None  # 登录用户不走匿名档
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class GlobalUserThrottle(ScopedSettingThrottle):
    scope = "user"

    def get_cache_key(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": user.pk}


class LoginThrottle(ScopedSettingThrottle):
    """登录端点按 IP 从严（全局 anon 之上叠加）。"""

    scope = "login"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class AIAskThrottle(ScopedSettingThrottle):
    """AI 问答按用户从严（成本入口）。"""

    scope = "ai_ask"

    def get_cache_key(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": user.pk}


# 供需要显式引用基类的模块导入（保持 BaseThrottle 名字可用）
__all__ = [
    "BaseThrottle",
    "ScopedSettingThrottle",
    "GlobalAnonThrottle",
    "GlobalUserThrottle",
    "LoginThrottle",
    "AIAskThrottle",
]
