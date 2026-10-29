from django.db import migrations, models


class Migration(migrations.Migration):
    """学生学籍字段（方案 §5.1）。

    注意：**不新增 User.classroom**。"学生当前属于哪个班"的唯一事实源是
    ClassStudent 的占用关系，理由见方案 §5.2 与 classroom/migrations/0006。
    """

    dependencies = [
        ("users", "0007_alter_notification_ntype"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="edu_status",
            field=models.CharField(
                choices=[
                    ("enrolled", "在读"),
                    ("suspended", "休学"),
                    ("graduated", "已毕业"),
                    ("withdrawn", "退学/转出"),
                ],
                default="enrolled",
                max_length=16,
                verbose_name="学籍状态",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="enrollment_year",
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="入学年份"),
        ),
        migrations.AddField(
            model_name="user",
            name="duration_years",
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="学制（年）"),
        ),
        migrations.AddField(
            model_name="user",
            name="status_changed_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="学籍状态变更时间"),
        ),
        migrations.AddField(
            model_name="user",
            name="status_note",
            field=models.CharField(blank=True, max_length=200, verbose_name="学籍状态说明"),
        ),
    ]
