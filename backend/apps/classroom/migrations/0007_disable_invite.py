from django.db import migrations, models


def disable_invites(apps, schema_editor):
    """邀请码入班整体下线（方案 §4.4）。

    建班归口管理员后，"凭邀请码自助入班"这条路径与"班级由学校统一分配"直接冲突，
    留着只会让邀请码泄露重新变成成员错乱的口子。字段与路由都保留（见 §4.4），
    只把开关关掉，需要时能一键回滚。
    """
    ClassRoom = apps.get_model("classroom", "ClassRoom")
    ClassRoom.objects.filter(invite_enabled=True).update(invite_enabled=False)


def enable_invites(apps, schema_editor):
    ClassRoom = apps.get_model("classroom", "ClassRoom")
    ClassRoom.objects.update(invite_enabled=True)


class Migration(migrations.Migration):
    dependencies = [
        ("classroom", "0006_classstudent_single_class"),
    ]

    operations = [
        migrations.AlterField(
            model_name="classroom",
            name="invite_enabled",
            field=models.BooleanField(default=False, verbose_name="邀请码开启"),
        ),
        migrations.RunPython(disable_invites, enable_invites),
    ]
