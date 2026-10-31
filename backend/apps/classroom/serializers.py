from django.db import transaction
from rest_framework import serializers

from apps.common.access import is_platform_admin
from apps.courses.models import Course

from .models import ClassCourse, ClassRoom, ClassStudent


class ClassRoomSerializer(serializers.ModelSerializer):
    courses = serializers.PrimaryKeyRelatedField(
        queryset=Course.objects.all(), many=True, required=False
    )
    # 兼容旧客户端的单课程提交；响应中的 course/course_name 仍返回第一门课程。
    course = serializers.PrimaryKeyRelatedField(
        queryset=Course.objects.all(), required=False, allow_null=True, write_only=True
    )
    course_name = serializers.SerializerMethodField()
    course_names = serializers.SerializerMethodField()
    # 当前用户在该班任课的课程 id（管理员=全部）：列表页点学生详情时用它选默认课程
    my_course_ids = serializers.SerializerMethodField()
    student_count = serializers.IntegerField(source="students.count", read_only=True)
    teacher_name = serializers.CharField(source="teacher.real_name", read_only=True, default="")
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    graduate_year = serializers.IntegerField(read_only=True)

    class Meta:
        model = ClassRoom
        fields = [
            "id", "course", "course_name", "courses", "course_names", "my_course_ids", "code", "name",
            "teacher", "teacher_name", "enrollment_year", "duration_years", "graduate_year",
            "invite_code", "invite_enabled", "start_at", "end_at",
            "status", "status_display", "student_count", "created_at",
        ]
        # teacher 是「建班人」留痕，由后端写入，不接受前端赋值
        read_only_fields = ["teacher", "invite_code"]

    def get_course_name(self, obj) -> str:
        link = next(iter(obj.course_links.all()), None)
        return link.course.name if link else ""

    def get_course_names(self, obj) -> list[str]:
        return [link.course.name for link in obj.course_links.all()]

    def get_my_course_ids(self, obj) -> list[int]:
        """当前用户在该班任课的课程 id（管理员=全部）。

        列表页点学生详情时用它取默认课程：原来前端取「班级第一门课」，
        多教师共用班级时会取到别人的课，详情接口直接 403。
        """
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return []
        qs = obj.courses.all() if is_platform_admin(user) else obj.courses.filter(teacher=user)
        return list(qs.order_by("id").values_list("id", flat=True))

    def validate(self, attrs):
        legacy_course = attrs.get("course")
        selected = attrs.get("courses")
        if selected is None and legacy_course is not None:
            selected = [legacy_course]

        if self.instance is None and not selected:
            raise serializers.ValidationError({"courses": "请至少选择一门课程"})
        if selected is not None and not selected:
            raise serializers.ValidationError({"courses": "班级至少需要关联一门课程"})

        self._validate_code(attrs)

        request = self.context.get("request")
        user = getattr(request, "user", None)
        # 管理员代表学校建班，可以挂任意教师的课；教师只能挂自己的课。
        if (
            selected is not None
            and user
            and user.is_authenticated
            and not is_platform_admin(user)
        ):
            invalid = [course.name for course in selected if course.teacher_id != user.id]
            if invalid:
                raise serializers.ValidationError(
                    {"courses": f"不能关联其他教师的课程：{'、'.join(invalid)}"}
                )
        return attrs

    def _validate_code(self, attrs):
        """班级编码：新建必填、统一大写、唯一。

        编码是导入的匹配键（P2），大小写不同视为同一个班（方案 X-32），
        所以入库前统一 normalize，避免 `CS-2401` 与 `cs-2401` 并存。
        """
        code = attrs.get("code")
        if code is None and self.instance is not None:
            return
        code = (code or "").strip().upper()
        if not code:
            if self.instance is None:
                raise serializers.ValidationError({"code": "请填写班级编码"})
            # 历史班级允许为空（迁移前无此列），编辑时不强制补
            attrs.pop("code", None)
            return
        if len(code) > 32:
            raise serializers.ValidationError({"code": "班级编码不能超过 32 个字符"})
        qs = ClassRoom.objects.filter(code__iexact=code)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError({"code": f"班级编码「{code}」已被占用"})
        attrs["code"] = code

    @staticmethod
    def _sync_courses(classroom, courses):
        course_ids = list(dict.fromkeys(course.id for course in courses))
        classroom.course_links.exclude(course_id__in=course_ids).delete()
        existing = set(
            classroom.course_links.filter(course_id__in=course_ids).values_list(
                "course_id", flat=True
            )
        )
        ClassCourse.objects.bulk_create(
            [
                ClassCourse(classroom=classroom, course_id=course_id)
                for course_id in course_ids
                if course_id not in existing
            ]
        )
        # 列表/详情接口 prefetch 了 course_links，写入后必须清缓存：
        # 否则响应体里的 courses 还是改动前的列表——教师刚挂上课，接口回
        # 「没挂上」，前端若拿响应渲染会直接回退（P3 选班抽屉实测踩到）。
        if hasattr(classroom, "_prefetched_objects_cache"):
            classroom._prefetched_objects_cache.pop("course_links", None)

    @transaction.atomic
    def create(self, validated_data):
        legacy_course = validated_data.pop("course", None)
        courses = validated_data.pop("courses", None)
        selected = courses if courses is not None else [legacy_course]
        classroom = ClassRoom.objects.create(**validated_data)
        self._sync_courses(classroom, selected)
        return classroom

    @transaction.atomic
    def update(self, instance, validated_data):
        legacy_course = validated_data.pop("course", None)
        courses = validated_data.pop("courses", None)
        instance = super().update(instance, validated_data)
        if courses is not None:
            # 教师挂课走「追加」语义：一个班有多位教师时，A 挂自己的课不能把 B 的课踢掉。
            # 管理员维护班级时仍是整体覆盖（前端提交的是一份完整清单）。
            if self.context.get("courses_append"):
                existing = {link.course_id for link in instance.course_links.all()}
                courses = list(instance.courses.all()) + [c for c in courses if c.id not in existing]
            self._sync_courses(instance, courses)
        elif legacy_course is not None:
            self._sync_courses(instance, [legacy_course])
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        links = list(instance.course_links.all())
        course_ids = [link.course_id for link in links]
        course_names = [link.course.name for link in links]
        data["courses"] = course_ids
        data["course_names"] = course_names
        data["course"] = course_ids[0] if course_ids else None
        data["course_name"] = course_names[0] if course_names else ""
        return data


class ClassStudentSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.real_name", read_only=True)
    username = serializers.CharField(source="student.username", read_only=True)
    avatar = serializers.CharField(source="student.avatar", read_only=True)
    last_login = serializers.DateTimeField(source="student.last_login", read_only=True)
    learn_status_display = serializers.CharField(source="get_learn_status_display", read_only=True)
    # 学籍状态：毕业生留在班级名单（历史档案区，方案 §5.4），但不进统计分母；
    # 管理端据此判断谁能提交、谁已停学。
    edu_status = serializers.CharField(source="student.edu_status", read_only=True)
    edu_status_display = serializers.CharField(source="student.get_edu_status_display", read_only=True)

    class Meta:
        model = ClassStudent
        fields = [
            "id", "classroom", "student", "student_name", "username",
            "avatar", "joined_at", "last_login", "learn_status", "learn_status_display",
            "edu_status", "edu_status_display",
        ]
        # learn_status 只读：入班/转班/移出必须走 services，否则会绕过单班唯一约束
        read_only_fields = ["classroom", "student", "joined_at", "learn_status"]
