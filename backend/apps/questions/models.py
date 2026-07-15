from django.conf import settings
from django.db import models

from apps.common.models import BaseModel
from apps.courses.models import Catalog, Course


class Question(BaseModel):
    """题目（需求 5.7 / 第 8.1 节 / 第 9 节·题目）。

    AI 生成与手动添加统一入库，可被章节练习、作业、考试复用。
    options / answer 用 JSON 承载不同题型结构。
    """

    class QType(models.TextChoices):
        SINGLE = "single", "单选题"
        MULTI = "multi", "多选题"
        JUDGE = "judge", "判断题"
        BLANK = "blank", "填空题"
        SHORT = "short", "简答题"

    class Difficulty(models.TextChoices):
        EASY = "easy", "简单"
        MEDIUM = "medium", "中等"
        HARD = "hard", "困难"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PENDING = "pending", "待审核"
        PUBLISHED = "published", "已发布"
        DISABLED = "disabled", "停用"

    class Source(models.TextChoices):
        AI = "ai", "AI 生成"
        MANUAL = "manual", "手动添加"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="questions", verbose_name="课程")
    catalog = models.ForeignKey(
        Catalog, null=True, blank=True, on_delete=models.SET_NULL, related_name="questions", verbose_name="章节"
    )
    qtype = models.CharField("题型", max_length=16, choices=QType.choices)
    stem = models.TextField("题干")
    options = models.JSONField("选项", default=list, blank=True)  # [{key, text}, ...]
    answer = models.JSONField("答案", default=dict, blank=True)   # 结构随题型而定
    analysis = models.TextField("解析", blank=True)
    score = models.DecimalField("分值", max_digits=5, decimal_places=1, default=5)
    difficulty = models.CharField(
        "难度", max_length=16, choices=Difficulty.choices, default=Difficulty.MEDIUM
    )
    knowledge_tags = models.JSONField("知识点标签", default=list, blank=True)
    source = models.CharField("来源", max_length=16, choices=Source.choices, default=Source.MANUAL)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.DRAFT)
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="questions", verbose_name="创建人"
    )

    class Meta:
        verbose_name = "题目"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.stem[:30]

    @property
    def is_objective(self) -> bool:
        """客观题可自动评分。"""
        return self.qtype in (self.QType.SINGLE, self.QType.MULTI, self.QType.JUDGE, self.QType.BLANK)


class AnswerRecord(BaseModel):
    """答题记录（需求 6.4 / 第 9 节·答题记录）。

    scene 区分场景，同一题在不同场景（章节练习/作业/考试）保留各自记录。
    """

    class Scene(models.TextChoices):
        PRACTICE = "practice", "章节练习"
        HOMEWORK = "homework", "作业"
        EXAM = "exam", "考试"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="answer_records", verbose_name="学生"
    )
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="answer_records", verbose_name="题目"
    )
    scene = models.CharField("场景类型", max_length=16, choices=Scene.choices, default=Scene.PRACTICE)
    scene_ref_id = models.BigIntegerField("场景对象编号", null=True, blank=True)  # 考试/作业 id
    student_answer = models.JSONField("学生答案", default=dict, blank=True)
    is_correct = models.BooleanField("是否正确", null=True, blank=True)
    score = models.DecimalField("得分", max_digits=5, decimal_places=1, null=True, blank=True)
    submitted_at = models.DateTimeField("提交时间", auto_now_add=True)

    class Meta:
        verbose_name = "答题记录"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.student} - Q{self.question_id}"
