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
    """教师可写，其余登录用户只读。"""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return request.user.is_teacher
