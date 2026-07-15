import django.db.models.deletion
from django.db import migrations, models


def copy_course_from_classroom(apps, schema_editor):
    Homework = apps.get_model("homework", "Homework")
    ClassCourse = apps.get_model("classroom", "ClassCourse")
    for homework in Homework.objects.filter(course_id=None).iterator():
        link = ClassCourse.objects.filter(classroom_id=homework.classroom_id).order_by("id").first()
        if link:
            homework.course_id = link.course_id
            homework.save(update_fields=["course"])


class Migration(migrations.Migration):
    dependencies = [
        ("classroom", "0004_classroom_courses"),
        ("courses", "0001_initial"),
        ("homework", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="homework",
            name="course",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="homeworks",
                to="courses.course",
                verbose_name="课程",
            ),
        ),
        migrations.RunPython(copy_course_from_classroom, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="homework",
            name="course",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="homeworks",
                to="courses.course",
                verbose_name="课程",
            ),
        ),
    ]
