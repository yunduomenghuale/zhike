from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.classroom.models import ClassRoom
from apps.common.models import BaseModel
from apps.courses.models import Course


class Homework(BaseModel):
    """作业（需求 5.9 / 第 9 节·作业）。"""

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已发布"
        CLOSED = "closed", "已截止"

    class Mode(models.TextChoices):
        ATTACHMENT = "attachment", "附件/文本作业"
        QUESTIONS = "questions", "题库选题作业"

    classroom = models.ForeignKey(
        ClassRoom, on_delete=models.CASCADE, related_name="homeworks", verbose_name="班级"
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="homeworks", verbose_name="课程"
    )
    title = models.CharField("标题", max_length=200)
    description = models.TextField("说明", blank=True)
    attachment = models.FileField("附件", upload_to="homework/", null=True, blank=True)
    mode = models.CharField("作业模式", max_length=16, choices=Mode.choices, default=Mode.ATTACHMENT)
    start_time = models.DateTimeField("开始时间", null=True, blank=True)
    deadline = models.DateTimeField("截止时间", null=True, blank=True)
    total_score = models.DecimalField("分值", max_digits=6, decimal_places=1, default=100)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        verbose_name = "作业"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.title


def question_snapshot(question):
    """生成可脱离题库独立使用的题目快照。"""
    return {
        "question_id": question.id,
        "catalog_id": question.catalog_id,
        "catalog_title": question.catalog.title if question.catalog_id else "",
        "qtype": question.qtype,
        "qtype_display": question.get_qtype_display(),
        "stem": question.stem,
        "options": question.options or [],
        "answer": question.answer or {},
        "analysis": question.analysis,
        "difficulty": question.difficulty,
        "difficulty_display": question.get_difficulty_display(),
        "knowledge_tags": question.knowledge_tags or [],
        "source_score": str(question.score),
    }


class HomeworkQuestion(BaseModel):
    """作业题目中间表；发布后以 snapshot 为唯一判题依据。"""

    homework = models.ForeignKey(
        Homework, on_delete=models.CASCADE, related_name="questions", verbose_name="作业"
    )
    question = models.ForeignKey(
        "questions.Question",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="homework_items",
        verbose_name="来源题目",
    )
    score = models.DecimalField("题目分值", max_digits=5, decimal_places=1, default=5)
    order = models.PositiveIntegerField("题目顺序", default=0)
    snapshot = models.JSONField("题目快照", default=dict, blank=True)

    class Meta:
        verbose_name = "作业题目"
        verbose_name_plural = verbose_name
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["homework", "question"], name="unique_homework_question"),
            models.UniqueConstraint(fields=["homework", "order"], name="unique_homework_question_order"),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.select_related("homework").get(pk=self.pk)
            if old.homework.status != Homework.Status.DRAFT:
                raise ValidationError("已发布作业的题目快照不可修改")
        elif self.homework.status != Homework.Status.DRAFT:
            raise ValidationError("已发布作业不能新增题目")
        if self.question_id and not self.snapshot:
            self.snapshot = question_snapshot(self.question)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.homework.status != Homework.Status.DRAFT:
            raise ValidationError("已发布作业的题目快照不可删除")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.homework} - 第{self.order + 1}题"


class HomeworkSubmission(BaseModel):
    """作业提交（需求 5.9 / 6.5 / 第 9 节·作业提交）。

    一期教师手动批改；二期接入大模型自动批改（保留 auto_* 字段占位）。
    """

    class CorrectStatus(models.TextChoices):
        SUBMITTED = "submitted", "已提交"
        GRADED = "graded", "已批改"
        RETURNED = "returned", "已发布成绩"

    homework = models.ForeignKey(
        Homework, on_delete=models.CASCADE, related_name="submissions", verbose_name="作业"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="homework_submissions", verbose_name="学生"
    )
    content = models.TextField("提交内容", blank=True)
    attachment = models.FileField("附件", upload_to="homework_submit/", null=True, blank=True)
    submitted_at = models.DateTimeField("提交时间", auto_now_add=True)
    is_late = models.BooleanField("逾期提交", default=False)
    score = models.DecimalField("得分", max_digits=6, decimal_places=1, null=True, blank=True)
    comment = models.TextField("评语", blank=True)
    correct_status = models.CharField(
        "批改状态", max_length=16, choices=CorrectStatus.choices, default=CorrectStatus.SUBMITTED
    )
    # 二期：大模型自动批改建议（教师复核后采纳）
    auto_score = models.DecimalField("AI 建议分", max_digits=6, decimal_places=1, null=True, blank=True)
    auto_comment = models.TextField("AI 建议评语", blank=True)
    objective_score = models.DecimalField("客观题得分", max_digits=6, decimal_places=1, default=0)

    class Meta:
        verbose_name = "作业提交"
        verbose_name_plural = verbose_name
        unique_together = ("homework", "student")

    def __str__(self):
        return f"{self.student} - {self.homework}"


class HomeworkAnswer(BaseModel):
    """作业逐题作答记录；客观题自动评分，主观题由教师填写得分。"""

    submission = models.ForeignKey(
        HomeworkSubmission, on_delete=models.CASCADE, related_name="answer_items", verbose_name="作业提交"
    )
    homework_question = models.ForeignKey(
        HomeworkQuestion, on_delete=models.PROTECT, related_name="answers", verbose_name="作业题目"
    )
    student_answer = models.JSONField("学生答案", default=dict, blank=True)
    is_correct = models.BooleanField("是否正确", null=True, blank=True)
    score = models.DecimalField("得分", max_digits=5, decimal_places=1, null=True, blank=True)
    comment = models.TextField("批改评语", blank=True)
    graded_at = models.DateTimeField("批改时间", null=True, blank=True)

    class Meta:
        verbose_name = "作业答题记录"
        verbose_name_plural = verbose_name
        ordering = ["homework_question__order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "homework_question"], name="unique_submission_homework_question"
            )
        ]

    def __str__(self):
        return f"{self.submission} - Q{self.homework_question_id}"
