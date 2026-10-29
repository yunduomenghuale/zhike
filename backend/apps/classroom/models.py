import secrets

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel
from apps.courses.models import Course


def gen_invite_code() -> str:
    return secrets.token_urlsafe(6)[:8].upper()


class ClassRoom(BaseModel):
    """行政班级。一个班级可以同时关联多门课程。

    组织层（建班、导入、学籍）只由管理员操作；教师不创建班级，只能从管理员
    维护的班级里选自己任教的班（见方案 §4）。
    """

    class Status(models.TextChoices):
        PREPARING = "preparing", "筹备中"
        ACTIVE = "active", "在读"
        GRADUATED = "graduated", "已毕业"
        ARCHIVED = "archived", "已归档"

    # 班级编码：导入匹配键，管理员建班必填。历史数据可能为空（迁移前无此列）。
    code = models.CharField(
        "班级编码", max_length=32, unique=True, null=True, blank=True,
        help_text="唯一，用于导入匹配；历史班级可能为空，需管理员补齐",
    )
    name = models.CharField("班级名称", max_length=200)
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_classes",
        verbose_name="建班人",
        help_text="仅记录建班操作人，不参与任何权限判断（权限一律走 Course.teacher）",
    )
    enrollment_year = models.PositiveSmallIntegerField("届别（入学年份）", null=True, blank=True)
    duration_years = models.PositiveSmallIntegerField("学制（年）", default=4)
    invite_code = models.CharField("邀请码", max_length=16, unique=True, default=gen_invite_code)
    # 邀请码入班已于 P1 下线（join 返回 410，前端入口移除），字段保留以备回滚
    invite_enabled = models.BooleanField("邀请码开启", default=False)
    start_at = models.DateField("开课时间", null=True, blank=True)
    end_at = models.DateField("结课时间", null=True, blank=True)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.ACTIVE)
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

    @property
    def graduate_year(self):
        """预计毕业年份。届别或学制缺失时返回 None。"""
        if not self.enrollment_year or not self.duration_years:
            return None
        return self.enrollment_year + self.duration_years

    @property
    def creator(self):
        """建班人（仅展示留痕，可能为空）。

        字段名仍是 `teacher` 以免大范围改库，但语义已降级为"谁点了建班按钮"。
        业务代码一律用本属性或 `creator_name` 读取，不要直接读 `teacher`——
        这样权限锚点 grep 检查才有意义（见方案 §4.1.1）。
        """
        return self.teacher if self.teacher_id else None

    @property
    def creator_name(self) -> str:
        user = self.creator
        if not user:
            return ""
        return user.real_name or user.username

    @property
    def occupied_students(self):
        """当前占位学生（active/inactive 关系），即"这个班现在有哪些人"。"""
        return self.students.filter(
            learn_status__in=[ClassStudent.LearnStatus.ACTIVE, ClassStudent.LearnStatus.INACTIVE]
        )

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
    """班级学生（需求 5.5 / 第 9 节·班级学生）。

    这是"学生属于哪个班"的**唯一事实源**（`User` 上没有 classroom 字段）。
    单班规则由条件唯一约束 `uniq_occupied_class_per_student` 在数据库层强制：
    一个学生同时最多有一条占用关系（active / inactive），只有 transferred / removed
    不占位，允许留多条历史。

    写入必须走 `apps.classroom.services`（assign / transfer / remove），
    不要在业务代码里直接 create / 改 learn_status —— 否则冲突会以 IntegrityError
    的形式冒到接口层。
    """

    class LearnStatus(models.TextChoices):
        ACTIVE = "active", "学习中"
        INACTIVE = "inactive", "未活跃"  # 历史遗留值，当前全库无写入方；仍纳入占位条件以兼容存量
        TRANSFERRED = "transferred", "已转班"
        REMOVED = "removed", "已移除"

    #: 占位状态：学生"当前在这个班"，全库唯一
    OCCUPYING_STATUSES = ("active", "inactive")

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
        constraints = [
            models.UniqueConstraint(
                fields=["student"],
                condition=models.Q(learn_status__in=["active", "inactive"]),
                name="uniq_occupied_class_per_student",
            )
        ]

    def __str__(self):
        return f"{self.student} @ {self.classroom}"
