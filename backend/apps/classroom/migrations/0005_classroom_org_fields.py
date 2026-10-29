import re

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


#: 旧状态 → 新状态。open=开课中 → active=在读；closed=已结课 → archived=已归档
STATUS_MAP = {"open": "active", "closed": "archived"}


def forwards(apps, schema_editor):
    ClassRoom = apps.get_model("classroom", "ClassRoom")

    for classroom in ClassRoom.objects.all().iterator():
        changed = []

        # 1) 状态映射
        new_status = STATUS_MAP.get(classroom.status)
        if new_status and new_status != classroom.status:
            classroom.status = new_status
            changed.append("status")

        # 2) 届别：从名称里能认出来的先填（"网络2026届-1班" → 2026），认不出留空由管理员补
        if classroom.enrollment_year is None:
            match = re.search(r"(20\d{2})\s*届", classroom.name or "")
            if match:
                classroom.enrollment_year = int(match.group(1))
                changed.append("enrollment_year")

        # 注意：不在这里关闭 invite_enabled。邀请码下线属于 P1「归口」的动作，
        # 要和「join 接口返回 410 + 前端移除入口」一起做，否则 P0 会留下一个
        # 界面上有入口、点了必然失败的半残状态。

        if changed:
            classroom.save(update_fields=changed)


def backwards(apps, schema_editor):
    ClassRoom = apps.get_model("classroom", "ClassRoom")
    reverse = {"active": "open", "archived": "closed"}
    for classroom in ClassRoom.objects.all().iterator():
        old = reverse.get(classroom.status)
        if old:
            classroom.status = old
            classroom.save(update_fields=["status"])


class Migration(migrations.Migration):
    """班级归口管理员：编码/届别/学制/建班人降级/状态枚举（方案 §4.1）。

    历史 6 个班**不带班级编码**（迁移前无此列），需管理员补齐后才能作为导入目标；
    这里不做合成编码，避免出现看起来像真的假编码。
    """

    dependencies = [
        ("classroom", "0004_classroom_courses"),
        ("courses", "0012_term_and_course_term_fk"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="classroom",
            name="code",
            field=models.CharField(
                blank=True,
                help_text="唯一，用于导入匹配；历史班级可能为空，需管理员补齐",
                max_length=32,
                null=True,
                unique=True,
                verbose_name="班级编码",
            ),
        ),
        migrations.AddField(
            model_name="classroom",
            name="enrollment_year",
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="届别（入学年份）"),
        ),
        migrations.AddField(
            model_name="classroom",
            name="duration_years",
            field=models.PositiveSmallIntegerField(default=4, verbose_name="学制（年）"),
        ),
        migrations.AlterField(
            model_name="classroom",
            name="teacher",
            field=models.ForeignKey(
                blank=True,
                help_text="仅记录建班操作人，不参与任何权限判断（权限一律走 Course.teacher）",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_classes",
                to=settings.AUTH_USER_MODEL,
                verbose_name="建班人",
            ),
        ),
        migrations.AlterField(
            model_name="classroom",
            name="status",
            field=models.CharField(
                choices=[
                    ("preparing", "筹备中"),
                    ("active", "在读"),
                    ("graduated", "已毕业"),
                    ("archived", "已归档"),
                ],
                default="active",
                max_length=16,
                verbose_name="状态",
            ),
        ),
        migrations.AlterField(
            model_name="classstudent",
            name="learn_status",
            field=models.CharField(
                choices=[
                    ("active", "学习中"),
                    ("inactive", "未活跃"),
                    ("transferred", "已转班"),
                    ("removed", "已移除"),
                ],
                default="active",
                max_length=16,
                verbose_name="学习状态",
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
