import mimetypes

from django.db import migrations, models


def attachment_to_item(homework) -> dict | None:
    """把旧的单附件字段转换为 attachments 列表项（原文件名优先，缺失回退存储名）。"""
    name = homework.attachment.name if homework.attachment else ""
    if not name:
        return None
    basename = name.rsplit("/", 1)[-1]
    size = 0
    try:
        size = homework.attachment.size
    except (OSError, ValueError):
        size = 0
    return {
        "name": getattr(homework, "attachment_name", "") or basename,
        "size": size,
        "type": mimetypes.guess_type(basename)[0] or "",
        "url": homework.attachment.url,
    }


def migrate_single_attachment(apps, schema_editor):
    """数据迁移：attachment/attachment_name → attachments[0]（文件本身不动，URL 不变）。"""
    Homework = apps.get_model("homework", "Homework")
    for homework in Homework.objects.exclude(attachment="").exclude(attachment__isnull=True):
        item = attachment_to_item(homework)
        if item:
            homework.attachments = [item]
            homework.save(update_fields=["attachments"])


class Migration(migrations.Migration):

    dependencies = [
        ("homework", "0009_homework_attachment_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="homework",
            name="attachments",
            field=models.JSONField(blank=True, default=list, verbose_name="附件列表"),
        ),
        # RunPython 时旧字段仍在（同一迁移内先加后删），可安全读取
        migrations.RunPython(migrate_single_attachment, migrations.RunPython.noop),
        migrations.RemoveField(model_name="homework", name="attachment"),
        migrations.RemoveField(model_name="homework", name="attachment_name"),
    ]
