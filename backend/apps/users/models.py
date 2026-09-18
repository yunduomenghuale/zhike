from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.common.models import BaseModel


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
    # 批量导入/管理员重置密码后置为 True，前端据此提示首次登录修改密码（可跳过）
    must_change_password = models.BooleanField("首次登录需修改密码", default=False)

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


class Notification(BaseModel):
    """站内通知（作业/考试发布等推送给学生）。"""

    class Type(models.TextChoices):
        HOMEWORK = "homework", "作业"
        EXAM = "exam", "考试"
        SYSTEM = "system", "系统"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications", verbose_name="接收人"
    )
    ntype = models.CharField("类型", max_length=16, choices=Type.choices, default=Type.SYSTEM)
    title = models.CharField("标题", max_length=200)
    content = models.TextField("内容", blank=True)
    link = models.CharField("跳转链接", max_length=300, blank=True)  # 前端路由
    is_read = models.BooleanField("已读", default=False)

    class Meta:
        verbose_name = "通知"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.user} - {self.title}"


def notify_class_students(classroom, *, ntype, title, content="", link="") -> int:
    """给班级的在册学生批量发通知，返回发送数。"""
    from apps.classroom.models import ClassStudent

    students = [
        cs.student
        for cs in ClassStudent.objects.filter(
            classroom=classroom, learn_status=ClassStudent.LearnStatus.ACTIVE
        ).select_related("student")
    ]
    Notification.objects.bulk_create(
        [Notification(user=u, ntype=ntype, title=title, content=content, link=link) for u in students]
    )
    return len(students)
