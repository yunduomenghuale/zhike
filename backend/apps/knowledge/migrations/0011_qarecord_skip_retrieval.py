from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0010_qarecord_feedback_qarecord_turn_index_qasession_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="qarecord",
            name="skip_retrieval",
            field=models.BooleanField(default=False, verbose_name="跳过检索"),
        ),
    ]
