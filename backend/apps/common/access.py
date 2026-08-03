"""Reusable row-level data scopes for API querysets."""


def is_platform_admin(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (getattr(user, "role", None) == "admin" or user.is_superuser)
    )


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
        return qs.filter(
            classes__students__student=user,
            classes__students__learn_status="active",
        ).distinct().order_by("id")
    return qs.none().order_by("id")


def classrooms_for_user(user):
    from apps.classroom.models import ClassRoom

    qs = ClassRoom.objects.order_by("id")
    if not user or not user.is_authenticated:
        return qs.none()
    if is_platform_admin(user):
        return qs
    if user.is_teacher:
        return qs.filter(teacher=user).order_by("id")
    if user.is_student:
        return qs.filter(
            students__student=user,
            students__learn_status="active",
        ).distinct().order_by("id")
    return qs.none().order_by("id")
