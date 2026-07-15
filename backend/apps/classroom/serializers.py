from django.db import transaction
from rest_framework import serializers

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
    student_count = serializers.IntegerField(source="students.count", read_only=True)

    class Meta:
        model = ClassRoom
        fields = [
            "id", "course", "course_name", "courses", "course_names", "name", "teacher",
            "invite_code", "invite_enabled", "start_at", "end_at",
            "status", "student_count", "created_at",
        ]
        read_only_fields = ["teacher", "invite_code"]

    def get_course_name(self, obj):
        link = next(iter(obj.course_links.all()), None)
        return link.course.name if link else ""

    def get_course_names(self, obj):
        return [link.course.name for link in obj.course_links.all()]

    def validate(self, attrs):
        legacy_course = attrs.get("course")
        selected = attrs.get("courses")
        if selected is None and legacy_course is not None:
            selected = [legacy_course]

        if self.instance is None and not selected:
            raise serializers.ValidationError({"courses": "请至少选择一门课程"})
        if selected is not None and not selected:
            raise serializers.ValidationError({"courses": "班级至少需要关联一门课程"})

        request = self.context.get("request")
        user = getattr(request, "user", None)
        if selected is not None and user and user.is_authenticated and not user.is_superuser:
            invalid = [course.name for course in selected if course.teacher_id != user.id]
            if invalid:
                raise serializers.ValidationError(
                    {"courses": f"不能关联其他教师的课程：{'、'.join(invalid)}"}
                )
        return attrs

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

    class Meta:
        model = ClassStudent
        fields = [
            "id", "classroom", "student", "student_name", "username",
            "joined_at", "learn_status",
        ]
        read_only_fields = ["joined_at"]
