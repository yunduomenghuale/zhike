import re

import django.db.models.deletion
from django.db import migrations, models


def _parse_term_text(text: str):
    """把历史学期的自由文本解析成 (year, season)。

    支持 "2026秋" / "2026 春" / "2026-2027-1" / "2026-2027学年第一学期" 等常见写法。
    解析不出返回 None，对应课程 term 留空，由管理端标「学期待归属」人工补齐。
    """
    if not text:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    # 全角数字/连接符归一
    table = str.maketrans("０１２３４５６７８９－—～", "0123456789---")
    raw = raw.translate(table)

    year_match = re.search(r"(20\d{2})", raw)
    if not year_match:
        return None
    year = int(year_match.group(1))

    season = None
    if re.search(r"秋|下", raw):
        season = "autumn"
    elif re.search(r"春|上", raw):
        season = "spring"
    # "2026-2027-1" 这类按学期序号：1=秋，2=春
    if season is None:
        tail = re.search(r"[-_](\d)\s*$", raw)
        if tail:
            season = "autumn" if tail.group(1) == "1" else "spring"
    if season is None:
        return None
    return year, season


SEASON_LABEL = {"spring": "春", "autumn": "秋"}


def forwards(apps, schema_editor):
    Term = apps.get_model("courses", "Term")
    Course = apps.get_model("courses", "Course")

    mapping = {}
    for course in Course.objects.all().iterator():
        text = (course.term_text or "").strip()
        if not text:
            continue
        parsed = _parse_term_text(text)
        if not parsed:
            continue
        year, season = parsed
        key = (year, season)
        if key not in mapping:
            term, _ = Term.objects.get_or_create(
                year=year,
                season=season,
                defaults={"name": f"{year}{SEASON_LABEL[season]}"},
            )
            mapping[key] = term
        course.term = mapping[key]
        course.save(update_fields=["term"])

    # 唯一一个当前学期：取最新学年/季节（无数据则不设，避免误标）
    if not Term.objects.filter(is_current=True).exists():
        latest = Term.objects.order_by("-year", "-season").first()
        if latest:
            latest.is_current = True
            latest.save(update_fields=["is_current"])


def backwards(apps, schema_editor):
    Course = apps.get_model("courses", "Course")
    for course in Course.objects.select_related("term").all().iterator():
        if course.term_id:
            course.term_text = course.term.name
            course.save(update_fields=["term_text"])


class Migration(migrations.Migration):
    """学期字典 Term + Course.term 从自由文本改为外键（方案 §12）。

    原 CharField 改名 term_text 保留一版备份，确认迁移无误后再删列。
    """

    dependencies = [
        ("courses", "0011_remove_coursevideo_catalog_remove_coursevideo_course_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Term",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("year", models.PositiveSmallIntegerField(verbose_name="学年起始年")),
                (
                    "season",
                    models.CharField(
                        choices=[("spring", "春季"), ("autumn", "秋季")], max_length=8, verbose_name="季节"
                    ),
                ),
                ("name", models.CharField(max_length=50, unique=True, verbose_name="显示名")),
                ("start_at", models.DateField(blank=True, null=True, verbose_name="开始日期")),
                ("end_at", models.DateField(blank=True, null=True, verbose_name="结束日期")),
                ("is_current", models.BooleanField(default=False, verbose_name="当前学期")),
            ],
            options={
                "verbose_name": "学期",
                "verbose_name_plural": "学期",
                "ordering": ["-year", "season"],
            },
        ),
        migrations.AddConstraint(
            model_name="term",
            constraint=models.UniqueConstraint(fields=("year", "season"), name="unique_term_year_season"),
        ),
        migrations.AddConstraint(
            model_name="term",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_current", True)), fields=("is_current",), name="unique_current_term"
            ),
        ),
        migrations.RenameField(model_name="course", old_name="term", new_name="term_text"),
        migrations.AlterField(
            model_name="course",
            name="term_text",
            field=models.CharField(blank=True, max_length=50, verbose_name="学期（原始文本）"),
        ),
        migrations.AddField(
            model_name="course",
            name="term",
            field=models.ForeignKey(
                blank=True,
                help_text="允许为空：历史课程可能未归属学期，列表按「学期待归属」提示补齐",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="courses",
                to="courses.term",
                verbose_name="学期",
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
