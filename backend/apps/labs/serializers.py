from rest_framework import serializers

from apps.courses.models import Course

from .models import (
    Lab,
    LabAnswer,
    LabAttemptToken,
    LabGuide,
    LabQuestion,
    LabReport,
    LabSchedule,
    LabSubmission,
    LabTemplate,
)


class LabTemplateSerializer(serializers.ModelSerializer):
    page_url = serializers.CharField(read_only=True)

    class Meta:
        model = LabTemplate
        fields = [
            "id", "code", "title", "description", "page_url",
            "default_standard_minutes", "random_config", "cover", "is_active", "order",
        ]


class LabScheduleSerializer(serializers.ModelSerializer):
    lab_title = serializers.CharField(source="lab.title", read_only=True)
    classroom_name = serializers.CharField(source="classroom.name", read_only=True)

    class Meta:
        model = LabSchedule
        fields = ["id", "lab", "lab_title", "classroom", "classroom_name", "open_at", "close_at"]
        # 唯一性交给视图层 upsert（同班重排=更新窗口），这里不生成 UniqueTogetherValidator
        validators = []

    def validate(self, attrs):
        lab, classroom = attrs.get("lab"), attrs.get("classroom")
        if lab and classroom:
            user = self.context["request"].user
            if lab.course.teacher_id != user.id or classroom.teacher_id != user.id:
                raise serializers.ValidationError("只能给自己课程的实验、自己的班级排课")
            if not classroom.courses.filter(id=lab.course_id).exists():
                raise serializers.ValidationError("该班级未关联此课程，无法排课")
        open_at, close_at = attrs.get("open_at"), attrs.get("close_at")
        if open_at and close_at and open_at >= close_at:
            raise serializers.ValidationError("开放时间必须早于截止时间")
        return attrs


class LabSerializer(serializers.ModelSerializer):
    template_code = serializers.CharField(source="template.code", read_only=True)
    template_title = serializers.CharField(source="template.title", read_only=True)
    page_url = serializers.CharField(source="template.page_url", read_only=True)
    course_name = serializers.CharField(source="course.name", read_only=True)
    standard_minutes_display = serializers.IntegerField(source="effective_standard_minutes", read_only=True)
    # 排课窗口（教师排课管理 / 学生判断是否在开放时间内）
    schedules = LabScheduleSerializer(many=True, read_only=True)
    # 缺省继承模板（见 validate），创建时可不传
    title = serializers.CharField(required=False, allow_blank=True, max_length=128)
    description = serializers.CharField(required=False, allow_blank=True)
    random_config = serializers.JSONField(required=False)

    class Meta:
        model = Lab
        fields = [
            "id", "template", "template_code", "template_title", "page_url",
            "course", "course_name", "catalog", "title", "description",
            "standard_minutes", "standard_minutes_display",
            "total_score", "pass_score", "question_weight", "random_config",
            "time_limit_seconds", "allow_resubmit", "status", "order",
            "schedules", "created_at", "updated_at",
        ]
        read_only_fields = ["status"]

    def validate_course(self, value: Course):
        user = self.context["request"].user
        if not (getattr(user, "is_teacher", False) and value.teacher_id == user.id):
            raise serializers.ValidationError("只能给自己的课程创建实验")
        return value

    def validate_question_weight(self, value):
        if value and (value < 0 or value > 1):
            raise serializers.ValidationError("题目权重须在 0~1 之间")
        return value

    def validate(self, attrs):
        """title/description/random_config 缺省继承模板（教师建实验=选模板+配置）。"""
        template = attrs.get("template")
        if template:
            if not attrs.get("title"):
                attrs["title"] = template.title
            if not attrs.get("description"):
                attrs["description"] = template.description
            if attrs.get("random_config") in (None, {}):
                attrs["random_config"] = template.random_config
        return attrs


class LabQuestionSerializer(serializers.ModelSerializer):
    stem = serializers.CharField(source="snapshot.stem", read_only=True)
    qtype = serializers.CharField(source="snapshot.qtype", read_only=True)

    class Meta:
        model = LabQuestion
        fields = ["id", "lab", "question", "score", "order", "snapshot", "stem", "qtype"]
        read_only_fields = ["snapshot"]


class LabAnswerSerializer(serializers.ModelSerializer):
    lab_question = LabQuestionSerializer(read_only=True)

    class Meta:
        model = LabAnswer
        fields = [
            "id", "lab_question", "student_answer", "is_correct", "score",
            "auto_score", "auto_comment", "similarity", "pending_review", "graded_at",
        ]


class LabSubmissionSerializer(serializers.ModelSerializer):
    """对本人/教师始终返回分数（提交即见分，无 score_released 门控）。"""

    student_name = serializers.CharField(source="student.real_name", read_only=True)
    student_username = serializers.CharField(source="student.username", read_only=True)
    lab_title = serializers.CharField(source="lab.title", read_only=True)
    course_name = serializers.CharField(source="lab.course.name", read_only=True)
    lab_total_score = serializers.CharField(source="lab.total_score", read_only=True)
    answers = LabAnswerSerializer(many=True, read_only=True)

    class Meta:
        model = LabSubmission
        fields = [
            "id", "lab", "lab_title", "course_name", "lab_total_score",
            "student", "student_name", "student_username",
            "status", "attempt", "error_log", "steps_result", "elapsed_seconds",
            "error_count", "passed_steps", "total_steps",
            "base_score", "accuracy_score", "efficiency_score", "completion_score",
            "question_score", "total_score", "score_breakdown", "subjective_scores",
            "reviewed", "abnormal", "started_at", "submitted_at",
            "answers",
        ]


class LabAttemptTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabAttemptToken
        fields = ["id", "token", "submission", "expires_at", "consumed"]


class LabGuideSerializer(serializers.ModelSerializer):
    """实验必读：content 为空时由后端返回平台预设内容（前端不需要感知兜底逻辑）。"""

    is_preset = serializers.SerializerMethodField()
    updated_by_name = serializers.CharField(source="updated_by.real_name", read_only=True)

    class Meta:
        model = LabGuide
        fields = ["id", "title", "content", "is_preset", "updated_by_name", "updated_at"]

    def get_is_preset(self, obj) -> bool:
        return not (obj.content or "").strip()

    def validate_content(self, value: str) -> str:
        # 基础防护：封死脚本执行面；富文本样式经 .lab-guide-doc 作用域，不污染全局
        lowered = value.lower()
        for tag in ("<script", "onerror=", "onload=", "javascript:"):
            if tag in lowered:
                raise serializers.ValidationError("内容包含不允许的标签或属性")
        return value


class LabReportSerializer(serializers.ModelSerializer):
    file_docx_url = serializers.FileField(source="file_docx", read_only=True)
    file_pdf_url = serializers.FileField(source="file_pdf", read_only=True)

    class Meta:
        model = LabReport
        fields = [
            "id", "submission", "conclusion",
            "file_docx", "file_docx_url", "file_pdf", "file_pdf_url",
            "file_name", "generated_at",
        ]
