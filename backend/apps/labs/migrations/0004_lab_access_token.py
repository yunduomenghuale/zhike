import uuid

from django.db import migrations, models


def fill_access_tokens(apps, schema_editor):
    """为既有实验行逐条生成唯一令牌（SQLite 重建表时默认值只求值一次，不能依赖 AddField 默认）。"""
    Lab = apps.get_model("labs", "Lab")
    for lab in Lab.objects.filter(access_token__isnull=True):
        lab.access_token = uuid.uuid4()
        lab.save(update_fields=["access_token"])


class Migration(migrations.Migration):
    dependencies = [
        ("labs", "0003_alter_lab_allow_resubmit"),
    ]

    operations = [
        migrations.AddField(
            model_name="lab",
            name="access_token",
            field=models.UUIDField(editable=False, null=True, verbose_name="访问令牌"),
        ),
        migrations.RunPython(fill_access_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="lab",
            name="access_token",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True, verbose_name="访问令牌"),
        ),
    ]
