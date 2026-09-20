"""虚拟仿真实验（整合自实验平台）。

实验内容三层分离：
- LabTemplate 平台层：实验本体是代码资产（静态 HTML 页 + 步骤校验引擎），由开发者维护；
- Lab 教师层：教师引用模板 → 绑定课程 → 覆盖配置 → 可选附题 → 排课发布；
- LabSubmission 学生层：做实验、被评分（服务端按 seed 重算，唯一真相源）。
"""
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models

from apps.classroom.models import ClassRoom
from apps.common.models import BaseModel
from apps.courses.models import Catalog, Course


def _report_file_path(instance, filename):
    """实验报告文件名 uuid 化，防止路径猜测。"""
    return f"lab_reports/{uuid4().hex}{Path(filename).suffix.lower()}"


class LabTemplate(BaseModel):
    """实验模板库（平台层）。一个模板对应一个静态实验页。"""

    code = models.SlugField("模板编码", max_length=64, unique=True)  # 对应静态页名如 arp-ip-lab
    title = models.CharField("实验名称", max_length=128)
    description = models.TextField("实验说明", blank=True)
    static_path = models.CharField("静态页路径", max_length=255, blank=True)  # 缺省 /labs/{code}.html
    default_standard_minutes = models.PositiveIntegerField("标准时长(分钟)", default=30)
    # 随机参数生成规则，如 {"ranges": {"s1": [1, 9], "s2": [1, 9]}}
    random_config = models.JSONField("随机参数配置", default=dict, blank=True)
    cover = models.CharField("封面/图标", max_length=500, blank=True)
    is_active = models.BooleanField("启用", default=True)
    order = models.PositiveIntegerField("排序号", default=0)

    class Meta:
        verbose_name = "实验模板"
        verbose_name_plural = verbose_name
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.title}({self.code})"

    @property
    def page_url(self) -> str:
        return self.static_path or f"/labs/{self.code}.html"


class Lab(BaseModel):
    """实验（教师引用模板创建，挂课程）。"""

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已发布"
        CLOSED = "closed", "已下线"

    template = models.ForeignKey(
        LabTemplate, on_delete=models.PROTECT, related_name="labs", verbose_name="实验模板"
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="labs", verbose_name="课程")
    catalog = models.ForeignKey(
        Catalog, null=True, blank=True, on_delete=models.SET_NULL, related_name="labs", verbose_name="章节"
    )
    title = models.CharField("实验名称", max_length=128)
    description = models.TextField("实验说明", blank=True)
    # 评分用标准时长，缺省继承模板
    standard_minutes = models.PositiveIntegerField("标准时长(分钟)", null=True, blank=True)
    total_score = models.DecimalField("总分", max_digits=6, decimal_places=1, default=100)
    pass_score = models.DecimalField("及格分", max_digits=6, decimal_places=1, default=60)
    # 附题占总分权重：0=纯实验步骤评分；0.3 = 实验分*0.7 + 题目分*0.3
    question_weight = models.DecimalField("题目权重", max_digits=3, decimal_places=2, default=0)
    # 缺省继承模板，允许覆盖随机参数范围
    random_config = models.JSONField("随机参数配置", default=dict, blank=True)
    time_limit_seconds = models.IntegerField("限时(秒)", null=True, blank=True)
    allow_resubmit = models.BooleanField("允许学生重复提交", default=False)  # 重做主要走教师 reset
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.DRAFT)
    order = models.PositiveIntegerField("排序号", default=0)

    class Meta:
        verbose_name = "实验"
        verbose_name_plural = verbose_name
        ordering = ["course_id", "order", "id"]

    def __str__(self):
        return self.title

    @property
    def effective_standard_minutes(self) -> int:
        return self.standard_minutes or self.template.default_standard_minutes

    @property
    def effective_random_config(self) -> dict:
        return self.random_config or self.template.random_config or {}


class LabSchedule(BaseModel):
    """实验排课窗口（一个班一个窗口，重开复用改时间）。"""

    lab = models.ForeignKey(Lab, on_delete=models.CASCADE, related_name="schedules", verbose_name="实验")
    classroom = models.ForeignKey(
        ClassRoom, on_delete=models.CASCADE, related_name="lab_schedules", verbose_name="班级"
    )
    open_at = models.DateTimeField("开放时间", null=True, blank=True)
    close_at = models.DateTimeField("截止时间", null=True, blank=True)

    class Meta:
        verbose_name = "实验排课"
        verbose_name_plural = verbose_name
        ordering = ["open_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["lab", "classroom"], name="unique_lab_classroom"),
        ]

    def __str__(self):
        return f"{self.lab} @ {self.classroom}"

    def is_open(self, now=None) -> bool:
        now = now or __import__("django").utils.timezone.now()
        if self.open_at and now < self.open_at:
            return False
        if self.close_at and now > self.close_at:
            return False
        return True


class LabSubmission(BaseModel):
    """学生实验作答。unique(lab, student)：一次提交 + 教师重置后覆盖。

    与考试不同：提交即出分，无 score_released 门控；reviewed 仅标记教师复核改过分。
    """

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "进行中"
        SUBMITTED = "submitted", "已提交"

    lab = models.ForeignKey(Lab, on_delete=models.CASCADE, related_name="submissions", verbose_name="实验")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lab_submissions", verbose_name="学生"
    )
    schedule = models.ForeignKey(
        LabSchedule, null=True, blank=True, on_delete=models.SET_NULL, related_name="submissions", verbose_name="排课"
    )
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)
    attempt = models.PositiveIntegerField("第几次作答", default=1)
    # 服务端下发并持久化的随机参数，提交评分时复算标准答案，保证可复核
    random_seed = models.JSONField("随机参数", default=dict, blank=True)
    # 前端上报的过程数据（服务端不信任分数）
    error_log = models.JSONField("错误日志", default=list, blank=True)  # [{step, cmd, msg, ts}]
    steps_result = models.JSONField("步骤结果", default=dict, blank=True)  # {step_id: "pass"/"fail"}
    elapsed_seconds = models.IntegerField("用时(秒)", default=0)
    error_count = models.PositiveIntegerField("错误次数", default=0)
    passed_steps = models.PositiveIntegerField("通过步骤数", default=0)
    total_steps = models.PositiveIntegerField("总步骤数", default=0)
    # 评分明细（服务端重算）
    base_score = models.DecimalField("基础分", max_digits=6, decimal_places=1, null=True, blank=True)
    accuracy_score = models.DecimalField("操作准确性", max_digits=4, decimal_places=1, null=True, blank=True)
    efficiency_score = models.DecimalField("完成效率", max_digits=4, decimal_places=1, null=True, blank=True)
    completion_score = models.DecimalField("完成度", max_digits=4, decimal_places=1, null=True, blank=True)
    question_score = models.DecimalField("题目得分", max_digits=6, decimal_places=1, null=True, blank=True)
    total_score = models.DecimalField("总分", max_digits=6, decimal_places=1, null=True, blank=True)
    score_breakdown = models.JSONField("评分明细", default=dict, blank=True)
    subjective_scores = models.JSONField("主观题得分", default=dict, blank=True)  # {lab_question_id: score}
    # 教师复核
    reviewed = models.BooleanField("教师已复核", default=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="lab_reviews", verbose_name="复核人",
    )
    reviewed_at = models.DateTimeField("复核时间", null=True, blank=True)
    abnormal = models.BooleanField("异常标记", default=False)
    started_at = models.DateTimeField("开始时间", null=True, blank=True)
    submitted_at = models.DateTimeField("提交时间", null=True, blank=True)
    reset_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="lab_resets", verbose_name="重置人",
    )
    reset_at = models.DateTimeField("重置时间", null=True, blank=True)

    class Meta:
        verbose_name = "实验作答"
        verbose_name_plural = verbose_name
        unique_together = ("lab", "student")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.student} - {self.lab}"


class LabQuestion(BaseModel):
    """实验附题中间表；发布后以 snapshot 为唯一判题依据（仿作业快照）。"""

    lab = models.ForeignKey(Lab, on_delete=models.CASCADE, related_name="questions", verbose_name="实验")
    question = models.ForeignKey(
        "questions.Question", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="lab_items", verbose_name="来源题目",
    )
    score = models.DecimalField("题目分值", max_digits=5, decimal_places=1, default=5)
    order = models.PositiveIntegerField("题目顺序", default=0)
    snapshot = models.JSONField("题目快照", default=dict, blank=True)

    class Meta:
        verbose_name = "实验题目"
        verbose_name_plural = verbose_name
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["lab", "question"], name="unique_lab_question"),
            models.UniqueConstraint(fields=["lab", "order"], name="unique_lab_question_order"),
        ]

    @property
    def is_subjective(self) -> bool:
        return (self.snapshot or {}).get("qtype") == "short"

    def __str__(self):
        return f"{self.lab} - 第{self.order + 1}题"


class LabAnswer(BaseModel):
    """实验逐题作答。客观题自动判分；主观题相似度预评分 + pending_review 待教师复核。"""

    submission = models.ForeignKey(
        LabSubmission, on_delete=models.CASCADE, related_name="answers", verbose_name="实验作答"
    )
    lab_question = models.ForeignKey(
        LabQuestion, on_delete=models.PROTECT, related_name="answers", verbose_name="实验题目"
    )
    student_answer = models.JSONField("学生答案", default=dict, blank=True)
    is_correct = models.BooleanField("是否正确", null=True)
    score = models.DecimalField("最终得分", max_digits=5, decimal_places=1, null=True, blank=True)
    auto_score = models.DecimalField("自动评分", max_digits=5, decimal_places=1, null=True, blank=True)
    auto_comment = models.TextField("自动评语", blank=True)
    similarity = models.FloatField("相似度", null=True, blank=True)
    pending_review = models.BooleanField("待教师复核", default=False)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="lab_answer_gradings", verbose_name="批改人",
    )
    graded_at = models.DateTimeField("批改时间", null=True, blank=True)

    class Meta:
        verbose_name = "实验作答明细"
        verbose_name_plural = verbose_name
        ordering = ["lab_question__order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["submission", "lab_question"], name="unique_lab_submission_question"),
        ]

    def __str__(self):
        return f"{self.submission} - {self.lab_question}"


class LabAttemptToken(BaseModel):
    """静态实验页桥接一次性票据：可吊销、可审计。提交成功后消费。"""

    token = models.CharField("票据", max_length=64, unique=True, db_index=True)
    submission = models.OneToOneField(
        LabSubmission, on_delete=models.CASCADE, related_name="attempt_token", verbose_name="实验作答"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lab_tokens", verbose_name="学生"
    )
    issued_at = models.DateTimeField("签发时间", auto_now_add=True)
    expires_at = models.DateTimeField("过期时间")
    consumed = models.BooleanField("已消费", default=False)  # 重做时覆写 token 并复位为 False

    class Meta:
        verbose_name = "实验桥接种子票据"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.submission} ticket"


class LabGuide(BaseModel):
    """实验必读（平台级单例文档，教师可编辑；content 为空时回退平台预设内容）。

    老实验平台的"实验操作教程"静态页（/labs/lab-guide.html）已转为平台预设，
    教师可在前端直接编辑覆盖，也可一键恢复预设。
    """

    title = models.CharField("标题", max_length=128, default="实验必读")
    content = models.TextField(
        "内容HTML", blank=True,
        help_text="富文本 HTML（含受控内联 style）；留空则展示平台预设内容",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="lab_guides", verbose_name="更新人",
    )

    class Meta:
        verbose_name = "实验必读"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.title


class LabReport(BaseModel):
    """实验报告（二期生成 DOCX/PDF，一期先承载学生结论）。"""

    submission = models.OneToOneField(
        LabSubmission, on_delete=models.CASCADE, related_name="report", verbose_name="实验作答"
    )
    conclusion = models.TextField("实验结论", blank=True)  # 前端禁粘贴
    file_docx = models.FileField("DOCX", upload_to=_report_file_path, null=True, blank=True)
    file_pdf = models.FileField("PDF", upload_to=_report_file_path, null=True, blank=True)
    file_name = models.CharField("展示文件名", max_length=255, blank=True)
    generated_at = models.DateTimeField("生成时间", null=True, blank=True)

    class Meta:
        verbose_name = "实验报告"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.submission} 报告"
