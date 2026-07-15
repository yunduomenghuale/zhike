from rest_framework import serializers

from .models import Exam, ExamLog, ExamSubmission, Paper


class ExamSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    class_name = serializers.CharField(source="classroom.name", read_only=True)

    class Meta:
        model = Exam
        fields = [
            "id", "course", "classroom", "class_name", "name",
            "start_at", "end_at", "duration", "total_score", "status", "status_display",
            "shuffle_questions", "shuffle_options", "show_analysis_after",
            "allow_resubmit", "per_student_paper", "anti_cheat", "created_at",
        ]

    def validate(self, attrs):
        classroom = attrs.get("classroom", getattr(self.instance, "classroom", None))
        course = attrs.get("course", getattr(self.instance, "course", None))
        if classroom and course and not classroom.courses.filter(id=course.id).exists():
            raise serializers.ValidationError({"course": "该课程未关联到所选班级"})
        return attrs


class PaperSerializer(serializers.ModelSerializer):
    class Meta:
        model = Paper
        fields = ["id", "course", "exam", "student", "mode", "question_items", "total_score", "created_at"]


class ExamSubmissionSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.real_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ExamSubmission
        fields = [
            "id", "exam", "paper", "student", "student_name", "answers",
            "started_at", "submitted_at", "objective_score", "total_score",
            "status", "status_display", "abnormal",
        ]
        read_only_fields = ["student", "objective_score", "total_score"]


class ExamLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExamLog
        fields = ["id", "exam", "student", "action", "happened_at", "ip", "device", "note"]
        read_only_fields = ["student", "happened_at"]
