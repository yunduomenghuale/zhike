from django.contrib.auth import get_user_model
from rest_framework.decorators import action

from apps.common.access import classrooms_for_user
from apps.common.permissions import IsStudent, IsTeacher, IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet

from .models import ClassRoom, ClassStudent
from .serializers import ClassRoomSerializer, ClassStudentSerializer


class ClassRoomViewSet(BaseModelViewSet):
    serializer_class = ClassRoomSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["status"]
    search_fields = ["name", "courses__name"]

    def get_queryset(self):
        qs = classrooms_for_user(self.request.user).prefetch_related("course_links__course")

        course_id = self.request.query_params.get("course")
        if course_id:
            qs = qs.filter(courses__id=course_id)
        return qs.distinct()

    def perform_create(self, serializer):
        serializer.save(teacher=self.request.user)

    @action(detail=True, methods=["post"], url_path="regenerate-code")
    def regenerate_code(self, request, pk=None):
        classroom = self.get_object()
        classroom.regenerate_invite_code()
        return api_response({"invite_code": classroom.invite_code}, message="邀请码已重新生成")

    @action(detail=True, methods=["post"], url_path="add-student", permission_classes=[IsTeacher])
    def add_student(self, request, pk=None):
        """教师按用户名手动添加学生（需求 T-B-02）。"""
        classroom = self.get_object()
        username = request.data.get("username", "").strip()
        User = get_user_model()
        try:
            student = User.objects.get(username=username, role=User.Role.STUDENT)
        except User.DoesNotExist:
            return api_response(message="未找到该学生账号", code=404, status=404)
        obj, created = ClassStudent.objects.get_or_create(classroom=classroom, student=student)
        if not created and obj.learn_status == ClassStudent.LearnStatus.REMOVED:
            obj.learn_status = ClassStudent.LearnStatus.ACTIVE
            obj.save(update_fields=["learn_status", "updated_at"])
        return api_response(
            ClassStudentSerializer(obj).data,
            message="添加成功" if created else "该学生已在班级中",
        )

    @action(detail=False, methods=["post"], url_path="join", permission_classes=[IsStudent])
    def join(self, request):
        """学生输入邀请码加入班级（需求 S-B-01）。"""
        code = request.data.get("invite_code", "").strip().upper()
        try:
            classroom = ClassRoom.objects.get(
                invite_code=code,
                invite_enabled=True,
                status=ClassRoom.Status.OPEN,
            )
        except ClassRoom.DoesNotExist:
            return api_response(message="邀请码无效或已关闭", code=404, status=404)
        obj, created = ClassStudent.objects.get_or_create(
            classroom=classroom, student=request.user
        )
        if not created and obj.learn_status == ClassStudent.LearnStatus.REMOVED:
            obj.learn_status = ClassStudent.LearnStatus.ACTIVE
            obj.save(update_fields=["learn_status", "updated_at"])
        return api_response(
            ClassStudentSerializer(obj).data,
            message="加入成功" if created else "你已在该班级中",
        )


class ClassStudentViewSet(BaseModelViewSet):
    serializer_class = ClassStudentSerializer
    permission_classes = [IsTeacherOrReadOnly]
    http_method_names = ["get", "patch", "delete", "head", "options"]
    filterset_fields = ["classroom", "learn_status"]

    def get_queryset(self):
        return ClassStudent.objects.filter(
            classroom__in=classrooms_for_user(self.request.user)
        ).select_related("student", "classroom").order_by("id")
