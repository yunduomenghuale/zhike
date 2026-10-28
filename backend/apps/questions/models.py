from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel
from apps.courses.models import Catalog, Course


def _question_image_path(instance, filename):
    """题目配图 uuid 化：防枚举/猜测下载，与导入文件同口径。"""
    return f"question_images/{uuid4().hex}{Path(filename).suffix.lower()}"


def _split_score(total, n: int) -> list:
    """把总分尽量均分到 n 份（余数依次补给前几份，保证 Σ=total，保留 1 位小数）。"""
    if n <= 0:
        return []
    tenths = int(Decimal(str(total or 0)).quantize(Decimal("0.1")) * 10)
    base, rem = divmod(tenths, n)
    return [Decimal(base + (1 if i < rem else 0)) / 10 for i in range(n)]


class SceneTag(BaseModel):
    """题目用途标签：章节练习 / 作业 / 考试（预置 3 条，题目可多选）。

    分类只管会"自动暴露给学生"的三个场景；实验附题不受约束。
    题库列表筛选与消费端取题均以 code 为准。
    """

    PRACTICE = "practice"
    HOMEWORK = "homework"
    EXAM = "exam"
    DEFAULT_CODES = (PRACTICE, HOMEWORK)  # 新建/兜底默认：练习+作业（考试需显式勾选防泄题）

    code = models.CharField("标识", max_length=16, unique=True)
    name = models.CharField("名称", max_length=16)

    class Meta:
        verbose_name = "题目场景标签"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.name


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
        IMPORT = "import", "文档导入"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="questions", verbose_name="课程")
    catalog = models.ForeignKey(
        Catalog, on_delete=models.PROTECT, related_name="questions", verbose_name="章节"
    )
    qtype = models.CharField("题型", max_length=16, choices=QType.choices)
    stem = models.TextField("题干")
    image = models.FileField(
        "题图", upload_to=_question_image_path, null=True, blank=True, max_length=255
    )  # 题干配图（几何图/流程图/截图等），URL 经序列器 image_url 暴露
    options = models.JSONField("选项", default=list, blank=True)  # [{key, text}, ...]
    answer = models.JSONField("答案", default=dict, blank=True)   # 结构随题型而定；填空={"blanks":[{"text","score"}]}（按空赋分，score=Σ空分）
    analysis = models.TextField("解析", blank=True)
    score = models.DecimalField("分值", max_digits=5, decimal_places=1, default=5)
    difficulty = models.CharField(
        "难度", max_length=16, choices=Difficulty.choices, default=Difficulty.MEDIUM
    )
    knowledge_tags = models.JSONField("知识点标签", default=list, blank=True)
    source = models.CharField("来源", max_length=16, choices=Source.choices, default=Source.MANUAL)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.DRAFT)
    scenes = models.ManyToManyField(
        SceneTag, related_name="questions", blank=True, verbose_name="用途分类"
    )  # 多选：一题可同时属于 练习/作业/考试；空分类由 save() 兜底默认（练习+作业）
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="questions", verbose_name="创建人"
    )

    class Meta:
        verbose_name = "题目"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.stem[:30]

    def save(self, *args, **kwargs):
        # 判断题选项兜底：手动/AI/导入等路径漏带 options 时补默认对错项，
        # 避免学生端渲染不出选项（答案 key 为 T/F 的历史数据用 T/F 选项保持一致）
        if self.qtype == self.QType.JUDGE and not self.options:
            key = str((self.answer or {}).get("key", "")).upper()
            if key in ("T", "F"):
                self.options = [{"key": "T", "text": "正确"}, {"key": "F", "text": "错误"}]
            else:
                self.options = [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}]
        if self.qtype == self.QType.BLANK:
            self._normalize_blank_answer()
        super().save(*args, **kwargs)
        # 空分类兜底（ORM/种子脚本直插路径不走序列化器）：补默认 练习+作业，
        # 保证章节练习/作业选题池不出现"静默消失"的题；显式传了分类则不动
        if not self.scenes.exists():
            self.scenes.set(SceneTag.objects.filter(code__in=SceneTag.DEFAULT_CODES))

    def _normalize_blank_answer(self):
        """填空题答案规范化：blanks 统一为 [{"text","score"}]，并重算 score=Σ空分。

        - 旧版纯字符串数组：按原 score 均分补分（Σ 不变，判分自动切换为按空给分）
        - 对象数组：仅清洗（text 去空白、score 规整），总分以 Σ空分为准
        """
        answer = self.answer if isinstance(self.answer, dict) else {}
        blanks = answer.get("blanks") or []
        if not blanks:
            return
        items = []
        for b in blanks:
            if isinstance(b, dict):
                text = str(b.get("text", "")).strip()
                if not text:
                    continue
                try:
                    score = Decimal(str(b.get("score", 0))).quantize(Decimal("0.1"))
                except (InvalidOperation, TypeError, ValueError):
                    score = Decimal("0")
                items.append({"text": text, "score": score})
            else:
                text = str(b).strip()
                if text:
                    items.append({"text": text, "score": None})  # None=待均分
        if not items:
            return
        # 旧版字符串答案：按原总分均分补分
        if any(it["score"] is None for it in items):
            per = _split_score(self.score, len(items))
            items = [{"text": it["text"], "score": per[i]} for i, it in enumerate(items)]
        answer["blanks"] = [{"text": it["text"], "score": float(it["score"])} for it in items]
        self.answer = answer
        self.score = sum((it["score"] for it in items), Decimal("0"))

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


class WrongNote(BaseModel):
    """学生手动添加的错题记录（错题本补充入口）。

    自动收录的错题来自答题记录；手动条目由学生自行整理，
    与课程关联，便于按课程复习。catalog 可空：录入时可选章节，
    历史数据留空，总结中按课程级纳入（D3 定稿）。
    """

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wrong_notes", verbose_name="学生"
    )
    course = models.ForeignKey(
        "courses.Course", on_delete=models.CASCADE, related_name="wrong_notes", verbose_name="课程"
    )
    catalog = models.ForeignKey(
        "courses.Catalog", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="wrong_notes", verbose_name="章节",
    )
    stem = models.TextField("题干")
    my_answer = models.CharField("我的答案", max_length=500, blank=True)
    correct_answer = models.CharField("正确答案", max_length=500, blank=True)
    analysis = models.TextField("解析/笔记", blank=True)

    class Meta:
        verbose_name = "手动错题"
        verbose_name_plural = verbose_name
        ordering = ["-id"]

    def __str__(self):
        return f"{self.student} - {self.stem[:20]}"


class WrongMastery(BaseModel):
    """错题巩固状态：学生将自动收录或手动添加的错题标记为已巩固。

    question 对应自动收录（答题记录派生）的错题，note 对应手动添加的错题，
    二者必居其一。
    """
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wrong_masteries", verbose_name="学生"
    )
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="mastered_by", null=True, blank=True, verbose_name="题目"
    )
    note = models.ForeignKey(
        WrongNote, on_delete=models.CASCADE, related_name="mastered_by", null=True, blank=True, verbose_name="手动错题"
    )
    removed = models.BooleanField("已从错题本移除", default=False)

    class Meta:
        verbose_name = "错题巩固状态"
        verbose_name_plural = verbose_name
        ordering = ["-id"]

    def __str__(self):
        return f"{self.student} - Q{self.question_id or self.note_id}"


def _import_file_path(instance, filename):
    """导入文件 uuid 化：防枚举/猜测下载，原文件名仅存 file_name 字段展示。"""
    return f"question_imports/{uuid4().hex}{Path(filename).suffix.lower()}"


class QuestionDraftBatch(BaseModel):
    """题目草稿批次：文档导入 / AI 生成共用的待入库题目池。

    解析/生成结果先落批次（drafts JSON），教师预览编辑确认后批量入库。
    批次是「离开页面不丢失」的持久化载体：预览编辑防抖回传 drafts，
    刷新/重登/离开页面后均可经批次列表恢复继续处理。

    drafts 元素结构（与 import_parser 输出、question_gen_ai 输出同构）：
        {qtype, stem, options, answer, analysis, score, difficulty, _warnings:[...]}
    save 成功的条目即时从 drafts 移除，批次始终等于「剩余待入库」。
    """

    class Origin(models.TextChoices):
        IMPORT = "import", "文档导入"
        AI_GEN = "ai_gen", "AI 生成"

    class Status(models.TextChoices):
        PARSED = "parsed", "待入库"
        SAVED = "saved", "已入库"

    origin = models.CharField("来源", max_length=16, choices=Origin.choices, default=Origin.IMPORT)
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="question_draft_batches", verbose_name="课程"
    )
    catalog = models.ForeignKey(
        Catalog, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="question_draft_batches", verbose_name="目标章节",
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="question_draft_batches", verbose_name="创建人",
    )
    file = models.FileField("文件", upload_to=_import_file_path, null=True, blank=True)  # 仅 import；入库即删
    file_name = models.CharField("文件名称", max_length=255, blank=True)
    raw_text = models.TextField("抽取原文", blank=True)  # 截断存储（见 views 常量），供排查
    drafts = models.JSONField("题目草稿", default=list, blank=True)
    stats = models.JSONField("统计", default=dict, blank=True)  # {"total":n,"warned":n,"truncated":bool}
    task = models.ForeignKey(
        "ai.AITask", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="draft_batches", verbose_name="关联任务",
    )
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.PARSED)

    class Meta:
        verbose_name = "题目草稿批次"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.get_origin_display()}批次 #{self.id}（{len(self.drafts or [])} 题待入库）"
