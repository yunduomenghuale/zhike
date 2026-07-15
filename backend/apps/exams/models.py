from django.conf import settings
from django.db import models

from apps.classroom.models import ClassRoom
from apps.common.models import BaseModel
from apps.courses.models import Course


class Exam(BaseModel):
    """考试（需求 5.10 / 第 8.3 节 / 第 9 节·考试）。"""

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已发布"
        FINISHED = "finished", "已结束"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="exams", verbose_name="课程")
    classroom = models.ForeignKey(
        ClassRoom, on_delete=models.CASCADE, related_name="exams", verbose_name="班级"
    )
    name = models.CharField("考试名称", max_length=200)
    start_at = models.DateTimeField("开始时间", null=True, blank=True)
    end_at = models.DateTimeField("结束时间", null=True, blank=True)
    duration = models.IntegerField("考试时长(分钟)", default=60)
    total_score = models.DecimalField("总分", max_digits=6, decimal_places=1, default=100)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.DRAFT)

    # 考试模式（需求 8.3）
    shuffle_questions = models.BooleanField("题目乱序", default=False)
    shuffle_options = models.BooleanField("选项乱序", default=False)
    show_analysis_after = models.BooleanField("结束后展示解析", default=True)
    allow_resubmit = models.BooleanField("允许重复提交(取最后一次)", default=False)
    per_student_paper = models.BooleanField("每人不同试卷", default=False)

    # 防作弊配置（需求 T-E-05），如 {"detect_blur":true,"forbid_copy":true,...}
    anti_cheat = models.JSONField("防作弊配置", default=dict, blank=True)

    class Meta:
        verbose_name = "考试"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.name


class Paper(BaseModel):
    """试卷（需求 8.2 组卷 / 第 9 节·试卷）。

    题目以列表快照存储：[{question_id, score, order}]，避免题库改动影响已发布试卷。
    """

    class Mode(models.TextChoices):
        RANDOM = "random", "随机组卷"
        MANUAL = "manual", "手动组卷"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="papers", verbose_name="课程")
    exam = models.ForeignKey(
        Exam, on_delete=models.CASCADE, related_name="papers", verbose_name="考试"
    )
    # 每人不同试卷时，绑定到具体学生；共用试卷则为空
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, verbose_name="学生"
    )
    mode = models.CharField("组卷方式", max_length=16, choices=Mode.choices, default=Mode.RANDOM)
    question_items = models.JSONField("题目列表", default=list, blank=True)
    total_score = models.DecimalField("总分", max_digits=6, decimal_places=1, default=0)

    class Meta:
        verbose_name = "试卷"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.exam.name} 试卷#{self.id}"


class ExamSubmission(BaseModel):
    """考试答卷（需求 6.6 / 第 9 节·考试答卷）。"""

    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "未开始"
        IN_PROGRESS = "in_progress", "考试中"
        SUBMITTED = "submitted", "已提交"
        TIMEOUT = "timeout", "超时交卷"
        ABSENT = "absent", "缺考"

    exam = models.ForeignKey(
        Exam, on_delete=models.CASCADE, related_name="submissions", verbose_name="考试"
    )
    paper = models.ForeignKey(
        Paper, null=True, blank=True, on_delete=models.SET_NULL, related_name="submissions", verbose_name="试卷"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="exam_submissions", verbose_name="学生"
    )
    # 学生作答：{question_id: answer_obj}
    answers = models.JSONField("作答内容", default=dict, blank=True)
    started_at = models.DateTimeField("开始时间", null=True, blank=True)
    submitted_at = models.DateTimeField("提交时间", null=True, blank=True)
    objective_score = models.DecimalField("客观题得分", max_digits=6, decimal_places=1, null=True, blank=True)
    total_score = models.DecimalField("总分", max_digits=6, decimal_places=1, null=True, blank=True)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.NOT_STARTED)
    abnormal = models.BooleanField("异常标记", default=False)

    class Meta:
        verbose_name = "考试答卷"
        verbose_name_plural = verbose_name
        unique_together = ("exam", "student")

    def __str__(self):
        return f"{self.student} - {self.exam}"


class ExamLog(BaseModel):
    """考试操作日志（需求 T-E-05 / 第 9 节·考试操作日志）。记录切屏、复制等异常行为。"""

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="logs", verbose_name="考试")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="exam_logs", verbose_name="学生"
    )
    action = models.CharField("操作类型", max_length=50)  # blur / copy / paste / rightclick / fullscreen_exit ...
    happened_at = models.DateTimeField("操作时间", auto_now_add=True)
    ip = models.CharField("IP", max_length=64, blank=True)
    device = models.CharField("设备信息", max_length=255, blank=True)
    note = models.CharField("备注", max_length=255, blank=True)

    class Meta:
        verbose_name = "考试操作日志"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.student} {self.action}"
