from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.common.delete_protection import UserProtectedError
from apps.common.models import BaseModel


class User(AbstractUser):
    """平台用户。角色区分教师 / 学生 / 管理员（对齐需求文档第 3 节）。

    account、course、班级与学生关系均由平台内部维护，不接入外部教务系统。
    """

    class Role(models.TextChoices):
        TEACHER = "teacher", "教师"
        STUDENT = "student", "学生"
        ADMIN = "admin", "管理员"

    class EduStatus(models.TextChoices):
        """学籍状态（仅 role=student 有意义）。

        状态可回退（休学复学、退学重新入学、毕业批次撤销），不做一次性写死；
        每次变更必须同时写 status_changed_at + status_note 并留审计。
        """

        ENROLLED = "enrolled", "在读"
        SUSPENDED = "suspended", "休学"
        GRADUATED = "graduated", "已毕业"
        WITHDRAWN = "withdrawn", "退学/转出"

    role = models.CharField("角色", max_length=16, choices=Role.choices, default=Role.STUDENT)
    real_name = models.CharField("姓名", max_length=64, blank=True)
    phone = models.CharField("手机号", max_length=20, blank=True, null=True, unique=True)
    avatar = models.CharField("头像", max_length=500, blank=True)
    # 批量导入/管理员重置密码后置为 True，前端据此提示首次登录修改密码（可跳过）
    must_change_password = models.BooleanField("首次登录需修改密码", default=False)

    # ===== 学籍（仅学生）=====
    # 注意：学生当前所属班级**不落字段**，唯一事实源是 ClassStudent 的占用关系
    # （learn_status in active/inactive，且全库唯一，见 classroom/models.py 的条件唯一约束）。
    # 不要再加 User.classroom —— 那会造成同一事实两处存储，必然漂移。
    edu_status = models.CharField(
        "学籍状态", max_length=16, choices=EduStatus.choices, default=EduStatus.ENROLLED
    )
    enrollment_year = models.PositiveSmallIntegerField("入学年份", null=True, blank=True)
    duration_years = models.PositiveSmallIntegerField("学制（年）", null=True, blank=True)
    status_changed_at = models.DateTimeField("学籍状态变更时间", null=True, blank=True)
    status_note = models.CharField("学籍状态说明", max_length=200, blank=True)
    # P5-A2：登出/停用时置为当前时刻，认证链拒绝该时刻之前签发的 access
    tokens_invalid_before = models.DateTimeField(
        "token 作废线（该时刻前签发全部失效）", null=True, blank=True
    )

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.real_name or self.username}({self.get_role_display()})"

    def delete(self, *args, **kwargs):
        """用户禁止实例级物理删除（P5-B5，方案 X-25 / X-26）。

        删教师会级联删课程及全部教学内容，删学生会级联清空作业/答卷/成绩，
        均不可恢复。处置：离职/退学一律停用（is_active=False，学生另置
        edu_status=withdrawn，管理端用户详情 PATCH 已联动）。确有物理清理
        需求的运维场景（测试数据回收）走脚本通道
        `User.objects.filter(...).delete()`（queryset 删除不经过本方法）。
        """
        raise UserProtectedError(
            "用户账号不支持物理删除：请在管理端停用账号（离职/退学走停用，"
            "学生停用会自动置为退学）。如确需清理测试数据，走脚本 queryset 通道。"
        )

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
        LAB = "lab", "实验"
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
