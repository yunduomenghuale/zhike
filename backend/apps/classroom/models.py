import secrets

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel
from apps.courses.models import Course


def gen_invite_code() -> str:
    return secrets.token_urlsafe(6)[:8].upper()


class ClassRoom(BaseModel):
    """行政班级。一个班级可以同时关联多门课程。"""

    class Status(models.TextChoices):
        OPEN = "open", "开课中"
        CLOSED = "closed", "已结课"

    name = models.CharField("班级名称", max_length=200)
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="classes", verbose_name="教师"
    )
    invite_code = models.CharField("邀请码", max_length=16, unique=True, default=gen_invite_code)
    invite_enabled = models.BooleanField("邀请码开启", default=True)
    start_at = models.DateField("开课时间", null=True, blank=True)
    end_at = models.DateField("结课时间", null=True, blank=True)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.OPEN)
    courses = models.ManyToManyField(
        Course,
        through="ClassCourse",
        related_name="classes",
        verbose_name="课程",
    )

    class Meta:
        verbose_name = "班级"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.name

    def regenerate_invite_code(self):
        self.invite_code = gen_invite_code()
        self.save(update_fields=["invite_code", "updated_at"])


class ClassCourse(BaseModel):
    """班级与课程的授课关联，为后续扩展授课教师、学期等属性保留边界。"""

    classroom = models.ForeignKey(
        ClassRoom,
        on_delete=models.CASCADE,
        related_name="course_links",
        verbose_name="班级",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="classroom_links",
        verbose_name="课程",
    )

    class Meta:
        verbose_name = "班级课程"
        verbose_name_plural = verbose_name
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["classroom", "course"],
                name="unique_classroom_course",
            )
        ]

    def __str__(self):
        return f"{self.classroom} - {self.course}"


class ClassStudent(BaseModel):
    """班级学生（需求 5.5 / 第 9 节·班级学生）。"""

    class LearnStatus(models.TextChoices):
        ACTIVE = "active", "学习中"
        INACTIVE = "inactive", "未活跃"
        REMOVED = "removed", "已移除"

    classroom = models.ForeignKey(
        ClassRoom, on_delete=models.CASCADE, related_name="students", verbose_name="班级"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="joined_classes", verbose_name="学生"
    )
    joined_at = models.DateTimeField("加入时间", auto_now_add=True)
    learn_status = models.CharField(
        "学习状态", max_length=16, choices=LearnStatus.choices, default=LearnStatus.ACTIVE
    )

    class Meta:
        verbose_name = "班级学生"
        verbose_name_plural = verbose_name
        unique_together = ("classroom", "student")

    def __str__(self):
        return f"{self.student} @ {self.classroom}"
