from django.db import migrations, models


def populate_display_names(apps, schema_editor):
    User = apps.get_model("users", "User")
    for user in User.objects.only("id", "username", "real_name").iterator():
        user.display_name = user.real_name or user.username
        user.save(update_fields=["display_name"])


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="display_name",
            field=models.CharField(blank=True, max_length=64, verbose_name="用户名"),
        ),
        migrations.RunPython(populate_display_names, migrations.RunPython.noop),
    ]
