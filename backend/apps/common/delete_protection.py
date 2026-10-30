"""业务关键模型的删除保护异常（P5-B5，方案 X-04 / X-25 / X-26）。

处置口径：「停用而非物理删」。管理操作一律走停用（is_active=False）/归档
（status=archived）；模型层重写 `delete()` 抛异常拦截误删。确有物理清理
需求的运维场景（测试数据清理、冒烟空班回收）保留脚本通道——queryset 删除
`Model.objects.filter(...).delete()` 不经过实例 `delete()`，属显式运维动作。
"""


class ProtectedInstanceError(Exception):
    """实例级 delete() 被业务规则禁止（区别于数据库层 PROTECT 的 ProtectedError）。"""


class UserProtectedError(ProtectedInstanceError):
    """用户账号禁止物理删除（X-25 教师离职 / X-26 学生删除均改停用）。"""


class ClassRoomProtectedError(ProtectedInstanceError):
    """班级禁止物理删除（X-04）：删除会级联清空名单、作业、考试与成绩。"""
