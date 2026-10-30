from django.contrib.auth import get_user_model
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission

from apps.common.access import classrooms_for_user, is_platform_admin
from apps.common.permissions import IsPlatformAdmin, IsStudent, IsTeacherOrAdmin
from apps.common.response import api_response
from apps.common.viewsets import BaseModelViewSet

from . import graduation, services
from .models import ClassRoom, ClassStudent
from .serializers import ClassRoomSerializer, ClassStudentSerializer


def _as_bool(value) -> bool:
    """DRF 的 BooleanField 在 FormData 下会把 "false" 之外的字符串都判真。

    毕业的 force 参数走 multipart/JSON 两种提交，必须显式识别常见假值，
    否则 URL 查询串里的 force=false 会被当成强制确认（P4）。
    """
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def has_complete_profile(user):
    """入班前必须填写姓名（手机号已停止采集，不再作为资料完整度条件）。"""
    return bool(user.real_name.strip())


class IsAdminOrReadOnly(BasePermission):
    """班级写操作归管理员；其余登录用户只读（教师看自己课挂过的班，学生看自己班）。"""

    message = "班级由学校统一分配，仅平台管理员可维护"

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return is_platform_admin(request.user)


# 组织层字段：只有管理员能改。courses 不在其中（教师可以把自己的课挂进班级）。
ORG_ONLY_FIELDS = {
    "code", "name", "status", "enrollment_year", "duration_years",
    "start_at", "end_at", "invite_enabled",
}


class ClassRoomViewSet(BaseModelViewSet):
    serializer_class = ClassRoomSerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = ["status"]
    search_fields = ["name", "courses__name"]

    def get_permissions(self):
        # PATCH/PUT 放开到「教师或管理员」：教师挂自己的课是教学动作。
        # 组织字段与成员仍然只有管理员能动（见下面 update 的字段级校验）。
        if self.action in ("update", "partial_update"):
            return [IsTeacherOrAdmin()]
        return [perm() for perm in self.permission_classes]

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        # 教师挂课是追加（不覆盖其他教师的课），管理员仍是整体覆盖
        if self.action in ("update", "partial_update") and not is_platform_admin(self.request.user):
            ctx["courses_append"] = True
        return ctx

    def update(self, request, *args, **kwargs):
        classroom = self.get_object()  # 教师只能 get 到自己授课的班，无需额外判权
        if not is_platform_admin(request.user):
            touched = ORG_ONLY_FIELDS & set(request.data.keys())
            if touched:
                return api_response(
                    message=f"班级信息由学校统一维护，不能修改：{'、'.join(sorted(touched))}",
                    code=403,
                    status=403,
                )
            if "courses" not in request.data:
                return api_response(
                    message="教师只能调整班级的课程关联", code=403, status=403
                )
        return super().update(request, *args, **kwargs)

    def get_queryset(self):
        qs = classrooms_for_user(self.request.user).prefetch_related("course_links__course")

        course_id = self.request.query_params.get("course")
        if course_id:
            qs = qs.filter(courses__id=course_id)
        return qs.distinct()

    def perform_create(self, serializer):
        # teacher 字段已降级为"建班人"留痕，仅作审计线索，不参与权限
        serializer.save(teacher=self.request.user)

    def destroy(self, request, *args, **kwargs):
        """班级不提供物理删除（P5-B5，方案 X-04）。

        删班会级联清空名单、作业、考试与成绩；管理操作一律走归档
        （PATCH status=archived），历史成绩与学籍保留。模型层 delete() 同步
        拦截兜底；运维清理走脚本 queryset 通道。
        """
        return api_response(
            message="班级不支持删除：请将班级归档（历史成绩与学籍保留）",
            code=400,
            status=400,
        )

    @action(detail=True, methods=["post"], url_path="regenerate-code", permission_classes=[IsPlatformAdmin])
    def regenerate_code(self, request, pk=None):
        classroom = self.get_object()
        classroom.regenerate_invite_code()
        return api_response({"invite_code": classroom.invite_code}, message="邀请码已重新生成")

    # ---- 整班毕业（P4 流转；权限：仅平台管理员）----
    @action(detail=True, methods=["post"], url_path="edu-status", permission_classes=[IsPlatformAdmin])
    def change_student_edu_status(self, request, pk=None):
        """个别学籍变更（休学/复学/毕业/退学），P0 service 的管理端入口。

        与整班毕业互补：提前毕业、休学复学这类"单人事务"走这里；
        整班事务走 graduate。变更走 `services.change_edu_status`——
        状态可回退，每次写 status_changed_at + status_note + 审计。
        """
        classroom = self.get_object()
        student_id = request.data.get("student")
        edu_status = str(request.data.get("edu_status") or "").strip()
        student = get_user_model().objects.filter(pk=student_id, role="student").first()
        if student is None:
            return api_response(message="学生不存在", code=404, status=404)
        if not ClassStudent.objects.filter(
            classroom=classroom, student=student, learn_status__in=ClassStudent.OCCUPYING_STATUSES
        ).exists():
            return api_response(message="该学生不在本班", code=400, status=400)
        try:
            services.change_edu_status(
                student,
                edu_status,
                operator=request.user,
                note=str(request.data.get("note") or "")[:200],
            )
        except services.ClassServiceError as exc:
            return api_response(message=exc.detail, code=exc.code, status=exc.code)
        return api_response(
            {"student": student.pk, "edu_status": student.edu_status},
            message=f"学籍状态已更新为{student.get_edu_status_display()}",
        )

    @action(detail=True, methods=["get"], url_path="graduate-preview", permission_classes=[IsPlatformAdmin])
    def graduate_preview(self, request, pk=None):
        """毕业前名单预览（不写库）：将被毕业的学生 + 被排除的转班学生 + 在途清单。"""
        classroom = self.get_object()
        try:
            data = graduation.graduate_preview(classroom)
        except graduation.GraduationError as exc:
            return api_response(message=exc.detail, code=exc.code, status=exc.code)
        return api_response(data)

    @action(detail=True, methods=["post"], url_path="graduate", permission_classes=[IsPlatformAdmin])
    def graduate(self, request, pk=None):
        """执行整班毕业。有在途考试/未截止作业时需 force=true 强制确认（X-14）。"""
        classroom = self.get_object()
        try:
            result = graduation.graduate_class(
                classroom,
                operator=request.user,
                force=_as_bool(request.data.get("force")),
                note=str(request.data.get("note") or "")[:200],
            )
        except graduation.GraduationError as exc:
            return api_response(message=exc.detail, code=exc.code, status=exc.code, data=exc.data)
        return api_response(result, message=f"已毕业 {result['graduated_count']} 名学生")

    @action(detail=True, methods=["post"], url_path="graduate-revoke", permission_classes=[IsPlatformAdmin])
    def graduate_revoke(self, request, pk=None):
        """撤销整班毕业（授位审核退回）：班级回 active，本班已毕业学生回 enrolled。"""
        classroom = self.get_object()
        try:
            result = graduation.revoke_graduation(
                classroom,
                operator=request.user,
                note=str(request.data.get("note") or "")[:200],
            )
        except graduation.GraduationError as exc:
            return api_response(message=exc.detail, code=exc.code, status=exc.code, data=exc.data)
        return api_response(result, message=f"已撤销 {result['reverted_count']} 名学生的毕业状态")

    @action(detail=True, methods=["get"], url_path="search-students", permission_classes=[IsPlatformAdmin])
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

    @action(detail=True, methods=["post"], url_path="add-students-batch", permission_classes=[IsPlatformAdmin])
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

    @action(detail=True, methods=["post"], url_path="add-student", permission_classes=[IsPlatformAdmin])
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
        """邀请码入班已下线（方案 §4.4）。

        保留路由而不是直接删掉：老客户端、学生端缓存页、收藏的旧链接仍会打这个地址，
        返回 410 + 可读文案，比 404 更容易让人明白"功能没了，不是坏了"。
        班级统一由管理员分配，学生无需也无法自行入班。
        """
        return api_response(
            message="班级由学校统一分配，请联系管理员；邀请码入班已停用",
            code=410,
            status=410,
        )


class ClassStudentViewSet(BaseModelViewSet):
    serializer_class = ClassStudentSerializer
    # 名单可读；增删改一律管理员（移出 = 组织动作，不是教学动作）
    permission_classes = [IsAdminOrReadOnly]
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
