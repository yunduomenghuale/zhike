# -*- coding: utf-8 -*-
"""教师端 AI 重操作限流（题库导入/AI 生题，阶段 4）。

参照 platform_admin/throttles.py 的 AdminScopedThrottle 模式，按 ViewSet
action 分档（action_scopes 声明，未声明的动作直接放行）：

  teacher_ai_generate  AI 生题提交（后台 LLM 逐组生成，分钟级耗时）
  teacher_ai_import    文档导入解析（文件解析 + 建批次，秒级但吃 CPU）

速率读 settings.TEACHER_AI_THROTTLE_RATES（独立设置项，测试可整体置 None
关闭，避免覆盖 REST_FRAMEWORK 整字典时其它键回退 DRF 默认值）。
计数维度：已登录用户按 user.pk（DRF UserRateThrottle 语义），未登录按 IP。
"""
from django.conf import settings
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle


class TeacherAiScopedThrottle(ScopedRateThrottle):
    """按视图 action_scopes 声明的分档限流：未声明 scope 的动作放行。"""

    def allow_request(self, request, view):
        # scope 取决于本次请求的动作，故在此解析后再走 SimpleRateThrottle 常规逻辑。
        # 注意：必须直接调 SimpleRateThrottle.allow_request——父类 ScopedRateThrottle 的
        # allow_request 会用 view.throttle_scope 重置 scope（本项目视图用 action_scopes，
        # 没有该属性），若走 super() 会永远放行。
        action = getattr(view, "action", None)  # ViewSet 经 as_view 映射后由 DRF 写入
        self.scope = (getattr(view, "action_scopes", None) or {}).get(action)
        if not self.scope:
            return True
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return SimpleRateThrottle.allow_request(self, request, view)

    def get_rate(self):
        rates = getattr(settings, "TEACHER_AI_THROTTLE_RATES", None) or {}
        return rates.get(self.scope)
