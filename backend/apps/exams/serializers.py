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
        start_at = attrs.get("start_at", getattr(self.instance, "start_at", None))
        end_at = attrs.get("end_at", getattr(self.instance, "end_at", None))
        duration = attrs.get("duration", getattr(self.instance, "duration", None))
        if classroom and course and not classroom.courses.filter(id=course.id).exists():
            raise serializers.ValidationError({"course": "该课程未关联到所选班级"})
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.is_teacher:
            if not course or course.teacher_id != user.id:
                raise serializers.ValidationError("只能维护自己负责课程的考试")
            if not classroom or classroom.teacher_id != user.id:
                raise serializers.ValidationError("只能维护自己负责班级的考试")
        if start_at and end_at and end_at <= start_at:
            raise serializers.ValidationError({"end_at": "结束时间必须晚于开始时间"})
        if duration is not None and duration <= 0:
            raise serializers.ValidationError({"duration": "考试时长必须大于 0 分钟"})
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
