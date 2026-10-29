"""Reusable row-level data scopes for API querysets.

权限锚点只有两个：
- **管理权** 看 `Course.teacher`（谁创建了这门课，谁对内容负责）
- **教学权** = 管理权 + 该课已挂到目标班级（`ClassCourse`）

`ClassRoom.teacher` 已降级为「建班人」留痕，**禁止**用于任何权限判断、
可见性过滤或统计口径。它只回答"当初谁点了建班按钮"，与"谁能教这个班"无关
（管理员建班时建班人往往是管理员，班级随后由多位教师各挂各的课）。
"""


def is_platform_admin(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (getattr(user, "role", None) == "admin" or user.is_superuser)
    )


def teacher_can_manage_course(user, course) -> bool:
    """课程管理权。现在等价于"课程创建者"；将来接课程教师团队时只改这个函数体。"""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if is_platform_admin(user):
        return True
    return bool(getattr(user, "is_teacher", False) and course is not None and course.teacher_id == user.id)


def teacher_teaches(user, course, classroom=None) -> bool:
    """教学权 = 能管这门课 + 班级已挂该课。classroom 为空时只判断课程管理权。"""
    if not teacher_can_manage_course(user, course):
        return False
    if classroom is None:
        return True
    from apps.classroom.models import ClassCourse

    return ClassCourse.objects.filter(course=course, classroom=classroom).exists()


def courses_for_user(user):
    from apps.courses.models import Course

    qs = Course.objects.order_by("id")
    if not user or not user.is_authenticated:
        return qs.none()
    if is_platform_admin(user):
        return qs
    if user.is_teacher:
        return qs.filter(teacher=user).order_by("id")
    if user.is_student:
        from apps.classroom.models import ClassRoom, ClassStudent

        # 学生可见课程 = 自己所在班级所挂的、仍启用的课程。三个条件缺一不可：
        # - 关系是"占用"状态（转班/移出后旧课程入口消失，决策 6）
        # - 班级未归档（归档班整班停用）
        # - 课程本身 active（X-03：原实现漏了这条，停用课程仍出现在学生端）
        return (
            qs.filter(
                classes__students__student=user,
                classes__students__learn_status__in=ClassStudent.OCCUPYING_STATUSES,
                classes__status__in=[ClassRoom.Status.ACTIVE, ClassRoom.Status.GRADUATED],
                status=Course.Status.ACTIVE,
            )
            .distinct()
            .order_by("id")
        )
    return qs.none().order_by("id")


def classrooms_for_user(user):
    from apps.classroom.models import ClassRoom, ClassStudent

    qs = ClassRoom.objects.order_by("id")
    if not user or not user.is_authenticated:
        return qs.none()
    if is_platform_admin(user):
        return qs
    if user.is_teacher:
        # 教师看得到哪些班：唯一答案是他教的课挂过的班（不再看建班人）
        return qs.filter(courses__teacher=user).distinct().order_by("id")
    if user.is_student:
        return (
            qs.filter(
                students__student=user,
                students__learn_status__in=ClassStudent.OCCUPYING_STATUSES,
            )
            .distinct()
            .order_by("id")
        )
    return qs.none().order_by("id")


def teacher_classroom_ids(user):
    """教师有权操作的班级 id 集合（其课程挂过的班）。管理员返回全部。"""
    from apps.classroom.models import ClassRoom

    if is_platform_admin(user):
        return set(ClassRoom.objects.values_list("id", flat=True))
    return set(ClassRoom.objects.filter(courses__teacher=user).values_list("id", flat=True))
