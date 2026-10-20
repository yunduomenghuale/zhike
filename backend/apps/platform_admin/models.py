from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class AdminActionLog(BaseModel):
    """管理端操作审计（回答「谁在什么时候改了什么」）。

    覆盖全部管理端写操作：课程/班级状态、账号管理、AI 配置、向量重建。
    只记成功执行的动作；失败请求（4xx/5xx）不落库。
    actor 用 PROTECT：删用户不能连带抹掉审计痕迹。
    """

    class Action(models.TextChoices):
        COURSE_STATUS = "course_status", "课程状态变更"
        CLASS_STATUS = "class_status", "班级状态变更"
        USER_CREATE = "user_create", "创建账号"
        USER_UPDATE = "user_update", "编辑账号"
        USER_RESET_PWD = "user_reset_pwd", "重置密码"
        USER_IMPORT = "user_import", "批量导入账号"
        AI_CONFIG_SAVE = "ai_config_save", "保存AI配置"
        AI_CONFIG_TEST = "ai_config_test", "AI连接测试"
        VECTOR_REBUILD = "vector_rebuild", "重建向量库"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="admin_actions",
        verbose_name="操作人",
    )
    action = models.CharField("动作", max_length=32, choices=Action.choices)
    target_type = models.CharField("对象类型", max_length=32, blank=True)
    target_id = models.IntegerField("对象ID", null=True, blank=True)
    target_label = models.CharField("对象名称", max_length=200, blank=True)
    old_value = models.JSONField("变更前", null=True, blank=True)
    new_value = models.JSONField("变更后", null=True, blank=True)
    note = models.CharField("备注", max_length=255, blank=True)

    class Meta:
        verbose_name = "管理端操作审计"
        verbose_name_plural = verbose_name
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["action", "-id"]),
        ]

    def __str__(self):
        return f"{self.get_action_display()} {self.target_type}#{self.target_id} by {self.actor_id}"
