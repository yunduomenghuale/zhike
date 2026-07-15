from rest_framework import serializers

from apps.courses.models import Course

from .models import Homework, HomeworkSubmission


class HomeworkSerializer(serializers.ModelSerializer):
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.all(), required=False)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    submission_count = serializers.IntegerField(source="submissions.count", read_only=True)

    class Meta:
        model = Homework
        fields = [
            "id", "course", "classroom", "title", "description", "attachment",
            "deadline", "total_score", "status", "status_display",
            "submission_count", "created_at",
        ]

    def validate(self, attrs):
        classroom = attrs.get("classroom", getattr(self.instance, "classroom", None))
        course = attrs.get("course", getattr(self.instance, "course", None))
        if classroom and not course:
            course = classroom.courses.order_by("id").first()
            if course:
                attrs["course"] = course
        if not course:
            raise serializers.ValidationError({"course": "请先为班级关联课程"})
        if classroom and course and not classroom.courses.filter(id=course.id).exists():
            raise serializers.ValidationError({"course": "该课程未关联到所选班级"})
        return attrs


class HomeworkSubmissionSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.real_name", read_only=True)
    correct_status_display = serializers.CharField(source="get_correct_status_display", read_only=True)

    class Meta:
        model = HomeworkSubmission
        fields = [
            "id", "homework", "student", "student_name", "content", "attachment",
            "submitted_at", "is_late", "score", "comment",
            "correct_status", "correct_status_display", "auto_score", "auto_comment",
        ]
        read_only_fields = ["student", "submitted_at", "is_late", "auto_score", "auto_comment"]
