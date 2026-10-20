"""管理端统一限流（督管增强三期）。

按请求方法分档，速率读 settings.ADMIN_THROTTLE_RATES：

  admin_read   列表/详情/趋势/告警等常规读（UI 加载，允许一定频率的连续操作）
  admin_write  状态干预/账号管理/AI 配置保存等写操作
  admin_export CSV 导出（重查询 + 流式写出，成本高）
  admin_heavy  向量重建/AI 连接测试/批量导入（分钟级耗时，从严）

未在 method_scopes 中声明的方法走最严档 admin_heavy（防新增端点忘记分档时被读档放行）。
ViewSet 的个别动作可声明 action_scopes = {动作名: 档位}（优先于 method_scopes），
用于同资源下导出等成本不同的动作单独限流。
计数维度：已登录用户按 user.pk（DRF UserRateThrottle 语义），未登录按 IP。
"""
from django.conf import settings
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle


class AdminScopedThrottle(ScopedRateThrottle):
    """按视图声明的分档限流：action_scopes（ViewSet 动作名）优先，method_scopes（HTTP 方法）兜底。"""

    def allow_request(self, request, view):
        # scope 取决于本次请求的动作/方法，故在此解析后再走 SimpleRateThrottle 常规逻辑。
        # 注意：必须直接调 SimpleRateThrottle.allow_request——父类 ScopedRateThrottle 的
        # allow_request 会用 view.throttle_scope 重置 scope（本项目的视图用 method_scopes，
        # 没有该属性），若走 super() 会永远放行。
        action = getattr(view, "action", None)  # ViewSet 经 as_view 映射后由 DRF 写入
        self.scope = (
            (getattr(view, "action_scopes", None) or {}).get(action)
            or (getattr(view, "method_scopes", None) or {}).get(request.method, "admin_heavy")
        )
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return SimpleRateThrottle.allow_request(self, request, view)

    def get_rate(self):
        # 独立设置项而非 REST_FRAMEWORK.DEFAULT_THROTTLE_RATES：
        # 测试可 override_settings(ADMIN_THROTTLE_RATES={"admin_read": None, ...}) 整体关闭，
        # 避免覆盖 REST_FRAMEWORK 整字典时其它键回退到 DRF 默认值（如认证类丢失 JWT）
        rates = getattr(settings, "ADMIN_THROTTLE_RATES", None) or {}
        return rates.get(self.scope)


class AdminThrottleMixin:
    """管理端点统一挂限流。

    只读视图无需再声明 method_scopes（默认 GET→admin_read）；
    含写操作/导出/重操作的视图按需覆写 method_scopes；
    ViewSet 中成本不同的个别动作用 action_scopes 单独分档。
    """
    throttle_classes = [AdminScopedThrottle]
    method_scopes = {"GET": "admin_read"}
