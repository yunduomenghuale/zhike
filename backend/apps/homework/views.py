from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.common.permissions import IsTeacher, IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet

from .models import Homework, HomeworkSubmission
from .serializers import HomeworkSerializer, HomeworkSubmissionSerializer


class HomeworkViewSet(BaseModelViewSet):
    serializer_class = HomeworkSerializer
    permission_classes = [IsTeacherOrReadOnly]
    filterset_fields = ["course", "classroom", "status"]

    def get_queryset(self):
        user = self.request.user
        qs = Homework.objects.select_related("course", "classroom")
        # 学生仅见自己所在班级的已发布作业
        if user.is_authenticated and user.is_student:
            qs = qs.filter(classroom__students__student=user, status=Homework.Status.PUBLISHED)
        return qs.distinct()


class HomeworkSubmissionViewSet(BaseModelViewSet):
    serializer_class = HomeworkSubmissionSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["homework", "student", "correct_status"]

    def get_queryset(self):
        user = self.request.user
        qs = HomeworkSubmission.objects.select_related("student", "homework")
        if user.is_authenticated and user.is_student:
            qs = qs.filter(student=user)
        return qs

    def create(self, request, *args, **kwargs):
        """学生提交作业（需求 S-H-02）。自动判断是否逾期。"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        homework = serializer.validated_data["homework"]
        is_late = bool(homework.deadline and timezone.now() > homework.deadline)
        obj = serializer.save(student=request.user, is_late=is_late)
        return api_response(self.get_serializer(obj).data, message="提交成功", status=201)

    @action(detail=True, methods=["post"], url_path="grade", permission_classes=[IsTeacher])
    def grade(self, request, pk=None):
        """教师批改：填写分数与评语（需求 T-H-03）。"""
        submission = self.get_object()
        submission.score = request.data.get("score", submission.score)
        submission.comment = request.data.get("comment", submission.comment)
        submission.correct_status = HomeworkSubmission.CorrectStatus.GRADED
        submission.save(update_fields=["score", "comment", "correct_status", "updated_at"])
        return api_response(self.get_serializer(submission).data, message="批改完成")
