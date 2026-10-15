from django.db import migrations, models


def backfill_attachment_name(apps, schema_editor):
    """历史附件原文件名缺失：先用存储文件名（uuid 化）回填，前端可正常展示扩展名。"""
    Homework = apps.get_model("homework", "Homework")
    for homework in Homework.objects.exclude(attachment="").exclude(attachment__isnull=True):
        if not homework.attachment_name:
            homework.attachment_name = homework.attachment.name.rsplit("/", 1)[-1]
            homework.save(update_fields=["attachment_name"])


class Migration(migrations.Migration):

    dependencies = [
        ("homework", "0008_homeworksubmission_attachments"),
    ]

    operations = [
        migrations.AddField(
            model_name="homework",
            name="attachment_name",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="附件原文件名"),
        ),
        migrations.RunPython(backfill_attachment_name, migrations.RunPython.noop),
    ]
