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


class IsTeacherOrReadOnly(BasePermission):
    """教师可写，其余登录用户只读。"""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return request.user.is_teacher
