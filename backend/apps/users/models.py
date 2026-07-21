from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """平台用户。角色区分教师 / 学生 / 管理员（对齐需求文档第 3 节）。

    account、course、班级与学生关系均由平台内部维护，不接入外部教务系统。
    """

    class Role(models.TextChoices):
        TEACHER = "teacher", "教师"
        STUDENT = "student", "学生"
        ADMIN = "admin", "管理员"

    role = models.CharField("角色", max_length=16, choices=Role.choices, default=Role.STUDENT)
    real_name = models.CharField("姓名", max_length=64, blank=True)
    phone = models.CharField("手机号", max_length=20, blank=True, null=True, unique=True)
    avatar = models.CharField("头像", max_length=500, blank=True)

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.real_name or self.username}({self.get_role_display()})"

    @property
    def is_teacher(self) -> bool:
        return self.role == self.Role.TEACHER

    @property
    def is_student(self) -> bool:
        return self.role == self.Role.STUDENT
