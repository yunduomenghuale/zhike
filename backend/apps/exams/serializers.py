from rest_framework import serializers

from apps.common.access import teacher_teaches
from apps.questions.models import Question

from .models import Exam, ExamLog, ExamSubmission, Paper


class ExamSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    class_name = serializers.CharField(source="classroom.name", read_only=True)
    my_submission = serializers.SerializerMethodField()
    has_paper = serializers.SerializerMethodField()
    question_count = serializers.SerializerMethodField()

    class Meta:
        model = Exam
        fields = [
            "id", "course", "classroom", "class_name", "name",
            "start_at", "end_at", "duration", "total_score", "status", "status_display",
            "shuffle_questions", "shuffle_options", "show_analysis_after",
            "allow_resubmit", "per_student_paper", "anti_cheat", "created_at",
            "has_paper", "question_count", "my_submission",
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
            if not classroom or not teacher_teaches(user, course, classroom):
                raise serializers.ValidationError("只能维护自己负责班级的考试")
        if start_at and end_at and end_at <= start_at:
            raise serializers.ValidationError({"end_at": "结束时间必须晚于开始时间"})
        if duration is not None and duration <= 0:
            raise serializers.ValidationError({"duration": "考试时长必须大于 0 分钟"})
        return attrs

    def get_my_submission(self, obj):
        """学生视角：本人在该考试下的答卷摘要（供列表区分 进入考试/重考/已完成/查看成绩）。"""
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated and getattr(user, "is_student", False)):
            return None
        sub = ExamSubmission.objects.filter(exam=obj, student=user).first()
        if not sub:
            return None
        return ExamSubmissionSerializer(
            sub, context={"request": request, "brief": True}
        ).data

    def _shared_paper(self, obj):
        """共用试卷（每人一卷时取第一套），未组卷返回 None。"""
        papers = list(obj.papers.all())
        return next((p for p in papers if p.student_id is None), None) or (papers[0] if papers else None)

    def get_has_paper(self, obj):
        """是否已完成组卷（决定草稿考试能否发布）。"""
        paper = self._shared_paper(obj)
        return bool(paper and paper.question_items)

    def get_question_count(self, obj):
        paper = self._shared_paper(obj)
        return len(paper.question_items) if paper else 0


class PaperSerializer(serializers.ModelSerializer):
    class Meta:
        model = Paper
        fields = ["id", "course", "exam", "student", "mode", "question_items", "total_score", "created_at"]


class ExamSubmissionSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.real_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    exam_name = serializers.CharField(source="exam.name", read_only=True)
    objective_score = serializers.SerializerMethodField()
    total_score = serializers.SerializerMethodField()
    subjective_scores = serializers.SerializerMethodField()
    has_subjective = serializers.SerializerMethodField()
    subjective_count = serializers.SerializerMethodField()
    graded_subjective_count = serializers.SerializerMethodField()
    abnormal_count = serializers.SerializerMethodField()

    class Meta:
        model = ExamSubmission
        fields = [
            "id", "exam", "exam_name", "paper", "student", "student_name", "answers",
            "started_at", "saved_at", "submitted_at", "objective_score", "total_score",
            "subjective_scores", "score_released", "has_subjective",
            "subjective_count", "graded_subjective_count", "abnormal_count",
            "status", "status_display", "abnormal",
        ]
        read_only_fields = ["student", "objective_score", "total_score", "subjective_scores", "score_released"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # 列表场景（my_submission）不需要完整作答内容，瘦身响应
        if self.context.get("brief"):
            data.pop("answers", None)
        return data

    # ---- 成绩可见性 ----

    def _is_student(self):
        user = self.context.get("request").user if self.context.get("request") else None
        return bool(user and user.is_authenticated and getattr(user, "is_student", False))

    def _is_submitted(self, obj):
        return obj.status in (
            ExamSubmission.Status.SUBMITTED,
            ExamSubmission.Status.TIMEOUT,
        )

    def _short_qids(self, obj):
        """本卷主观题（简答）question_id 集合（同实例内缓存，避免重复查询）。"""
        cache = getattr(self, "_short_qids_cache", None)
        if cache is None:
            cache = self._short_qids_cache = {}
        if obj.pk in cache:
            return cache[obj.pk]
        items = obj.paper.question_items if obj.paper else []
        result = set()
        if items:
            qtypes = Question.objects.filter(
                id__in=[i["question_id"] for i in items]
            ).values_list("id", "qtype")
            result = {str(qid) for qid, qtype in qtypes if qtype == Question.QType.SHORT}
        cache[obj.pk] = result
        return result

    def _all_subjective_graded(self, obj):
        need = self._short_qids(obj)
        if not need:
            return True
        return not (need - set(map(str, (obj.subjective_scores or {}).keys())))

    def get_objective_score(self, obj):
        # 学生：交卷后立即可见客观题得分（作答中隐藏）；教师/管理员始终可见
        if self._is_student() and not self._is_submitted(obj):
            return None
        return obj.objective_score

    def get_total_score(self, obj):
        # 学生：统一出分后、或主观题全部批阅后可见总分；否则等教师批阅
        if self._is_student():
            if not self._is_submitted(obj):
                return None
            if not (obj.score_released or self._all_subjective_graded(obj)):
                return None
        return obj.total_score

    def get_subjective_scores(self, obj):
        # 学生：交卷后可见已批阅部分（未批阅的不出现，前端按缺省展示「待批阅」）
        if self._is_student() and not self._is_submitted(obj):
            return {}
        return obj.subjective_scores

    def get_has_subjective(self, obj):
        """试卷中是否含主观题（决定是否需要教师批改）。"""
        return bool(self._short_qids(obj))

    def get_subjective_count(self, obj):
        return len(self._short_qids(obj))

    def get_graded_subjective_count(self, obj):
        graded = set(map(str, (obj.subjective_scores or {}).keys()))
        return len(graded & self._short_qids(obj))

    def get_abnormal_count(self, obj):
        """本场考试的异常行为次数（切屏/复制等，来自 ExamLog）。同实例内缓存。"""
        cache = getattr(self, "_abnormal_count_cache", None)
        if cache is None:
            cache = self._abnormal_count_cache = {}
        if obj.pk in cache:
            return cache[obj.pk]
        count = ExamLog.objects.filter(exam=obj.exam, student=obj.student).count()
        cache[obj.pk] = count
        return count


class ExamLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExamLog
        fields = ["id", "exam", "student", "action", "happened_at", "ip", "device", "note"]
        read_only_fields = ["student", "happened_at"]
