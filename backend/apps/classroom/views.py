from django.contrib.auth import get_user_model
from rest_framework.decorators import action

from apps.common.access import classrooms_for_user
from apps.common.permissions import IsStudent, IsTeacher, IsTeacherOrReadOnly
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet

from . import services
from .models import ClassRoom, ClassStudent
from .serializers import ClassRoomSerializer, ClassStudentSerializer


def has_complete_profile(user):
    """入班前必须填写姓名（手机号已停止采集，不再作为资料完整度条件）。"""
    return bool(user.real_name.strip())


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

    @action(detail=True, methods=["get"], url_path="search-students", permission_classes=[IsTeacher])
    def search_students(self, request, pk=None):
        """教师搜索候选学生（学号/姓名模糊匹配），供班级添加学生用。
        返回：学号、姓名、当前所在班级、是否已在目标班级。"""
        classroom = self.get_object()
        keyword = (request.query_params.get("keyword") or "").strip()
        if not keyword:
            return api_response([], message="请输入学号或姓名关键词")
        User = get_user_model()
        from django.db.models import Q
        students = (
            User.objects.filter(role=User.Role.STUDENT, is_active=True)
            .filter(Q(username__icontains=keyword) | Q(real_name__icontains=keyword))
            .prefetch_related("joined_classes__classroom")
            .order_by("username")[:50]
        )
        in_class_ids = set(
            ClassStudent.objects.filter(classroom=classroom, learn_status=ClassStudent.LearnStatus.ACTIVE)
            .values_list("student_id", flat=True)
        )
        rows = []
        for s in students:
            current_class = (
                s.joined_classes.filter(learn_status=ClassStudent.LearnStatus.ACTIVE)
                .exclude(classroom=classroom)
                .select_related("classroom")
                .first()
            )
            rows.append({
                "id": s.id,
                "username": s.username,
                "real_name": s.real_name,
                "current_class": current_class.classroom.name if current_class else None,
                "already_in": s.id in in_class_ids,
                "profile_complete": has_complete_profile(s),
            })
        return api_response(rows, message="ok")

    @action(detail=True, methods=["post"], url_path="add-students-batch", permission_classes=[IsTeacher])
    def add_students_batch(self, request, pk=None):
        """教师批量添加学生（勾选候选后一次提交多个学号）。

        写入统一走 services.assign_students：单班规则由数据库条件唯一约束强制，
        直接 get_or_create 会在"学生已在别的班"时抛 IntegrityError 变成 500。
        """
        classroom = self.get_object()
        usernames = request.data.get("usernames") or []
        if not isinstance(usernames, list) or not usernames:
            return api_response(message="请提供学号列表", code=400, status=400)
        if len(usernames) > 100:
            return api_response(message="单次最多添加 100 人", code=400, status=400)
        User = get_user_model()
        students = {u.username: u for u in User.objects.filter(username__in=usernames, role=User.Role.STUDENT)}
        added, skipped, not_found, conflicted = 0, 0, [], []
        incomplete_names = []  # 资料不全（缺姓名）：照加但标黄提示
        for name in usernames:
            stu = students.get(name)
            if not stu:
                not_found.append(name)
                continue
            try:
                result = services.assign_students(classroom, [stu], operator=request.user)
            except services.ClassServiceError as exc:
                if exc.code == 409:
                    conflicted.append(f"{stu.username}（{exc.detail}）")
                    continue
                raise
            if result["created"]:
                added += 1
            elif result["unchanged"]:
                skipped += 1
                continue
            if not has_complete_profile(stu):
                incomplete_names.append(f"{stu.username}({stu.real_name or '未填姓名'})")
        parts = [f"成功 {added} 人"]
        if skipped:
            parts.append(f"跳过 {skipped} 人（已在班）")
        if conflicted:
            parts.append(f"{len(conflicted)} 人已在其他班级（需转班）")
        if not_found:
            parts.append(f"未找到 {len(not_found)} 个学号")
        if incomplete_names:
            parts.append(f"提醒：{len(incomplete_names)} 人资料不全——{'、'.join(incomplete_names[:3])}{'等' if len(incomplete_names) > 3 else ''}")
        return api_response(
            {
                "added": added, "skipped": skipped, "not_found": not_found,
                "conflicted": conflicted, "incomplete": incomplete_names,
            },
            message="、".join(parts),
        )

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
        if not has_complete_profile(student):
            return api_response(
                message="该学生尚未填写姓名，暂时无法加入班级",
                code=400,
                status=400,
            )
        obj = ClassStudent.objects.filter(classroom=classroom, student=student).first()
        if obj and obj.learn_status in (ClassStudent.LearnStatus.ACTIVE, ClassStudent.LearnStatus.INACTIVE):
            return api_response(ClassStudentSerializer(obj).data, message="该学生已在班级中")
        try:
            result = services.assign_students(classroom, [student], operator=request.user)
        except services.ClassServiceError as exc:
            return api_response(message=exc.detail, code=exc.code, status=exc.code)
        obj = ClassStudent.objects.get(classroom=classroom, student=student)
        return api_response(
            ClassStudentSerializer(obj).data,
            message="添加成功" if result["created"] else "该学生已在班级中",
        )

    @action(detail=False, methods=["post"], url_path="join", permission_classes=[IsStudent])
    def join(self, request):
        """学生输入邀请码加入班级（需求 S-B-01）。"""
        if not has_complete_profile(request.user):
            return api_response(
                message="请先在个人中心填写姓名，完善资料后才能加入班级",
                code=400,
                status=400,
            )
        code = request.data.get("invite_code", "").strip().upper()
        try:
            classroom = ClassRoom.objects.get(
                invite_code=code,
                invite_enabled=True,
                status=ClassRoom.Status.ACTIVE,
            )
        except ClassRoom.DoesNotExist:
            return api_response(message="邀请码无效或已关闭", code=404, status=404)
        existing = ClassStudent.objects.filter(
            classroom=classroom,
            student=request.user,
            learn_status__in=ClassStudent.OCCUPYING_STATUSES,
        ).first()
        if existing:
            return api_response(ClassStudentSerializer(existing).data, message="你已在该班级中")
        try:
            services.assign_students(classroom, [request.user], operator=request.user)
        except services.ClassServiceError as exc:
            return api_response(message=exc.detail, code=exc.code, status=exc.code)
        obj = ClassStudent.objects.get(classroom=classroom, student=request.user)
        return api_response(ClassStudentSerializer(obj).data, message="加入成功")


class ClassStudentViewSet(BaseModelViewSet):
    serializer_class = ClassStudentSerializer
    permission_classes = [IsTeacherOrReadOnly]
    http_method_names = ["get", "patch", "delete", "head", "options"]
    filterset_fields = ["classroom", "learn_status"]

    def get_queryset(self):
        return ClassStudent.objects.filter(
            classroom__in=classrooms_for_user(self.request.user)
        ).select_related("student", "classroom").order_by("id")

    def perform_destroy(self, instance):
        """移出班级一律软删（learn_status=removed），不物理删除。

        硬删会同时丢掉"曾经在过这个班"的留痕，使学生历史成绩失去归属依据；
        且软删后同一学生加回本班仍能复用原记录。
        """
        services.remove_students(
            instance.classroom,
            [instance.student],
            operator=self.request.user if self.request.user.is_authenticated else None,
            reason="名单移出",
            withdraw=False,
        )
