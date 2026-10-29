"""基于角色的权限。"""
from rest_framework.permissions import BasePermission


class IsTeacher(BasePermission):
    message = "仅教师可操作"

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_teacher)


class IsStudent(BasePermission):
    message = "仅学生可操作"

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_student)


class IsPlatformAdmin(BasePermission):
    message = "仅平台管理员可操作"

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.role == "admin" or request.user.is_superuser)
        )


class IsTeacherOrAdmin(BasePermission):
    """教师或平台管理员可操作（平台管理系统内享有全量数据访问）。"""

    message = "仅教师或平台管理员可操作"

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return bool(user.is_teacher or user.role == "admin" or user.is_superuser)


class IsTeacherOrReadOnly(BasePermission):
    """教师或平台管理员可写，其余登录用户只读。

    管理员代表学校做组织层操作，必要时也要能直接补录教学数据（发作业/发考试），
    否则「管理员 200」与「教师 200」两条准出口径对不上。
    """

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return bool(user.is_teacher or user.role == "admin" or user.is_superuser)
