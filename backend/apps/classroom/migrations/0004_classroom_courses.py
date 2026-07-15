import django.db.models.deletion
from django.db import migrations, models


def copy_existing_courses(apps, schema_editor):
    ClassRoom = apps.get_model("classroom", "ClassRoom")
    ClassCourse = apps.get_model("classroom", "ClassCourse")
    ClassCourse.objects.bulk_create(
        [
            ClassCourse(classroom_id=classroom.id, course_id=classroom.course_id)
            for classroom in ClassRoom.objects.exclude(course_id=None).iterator()
        ],
        ignore_conflicts=True,
    )


def restore_primary_course(apps, schema_editor):
    ClassRoom = apps.get_model("classroom", "ClassRoom")
    ClassCourse = apps.get_model("classroom", "ClassCourse")
    for classroom in ClassRoom.objects.all().iterator():
        link = ClassCourse.objects.filter(classroom_id=classroom.id).order_by("id").first()
        if link:
            classroom.course_id = link.course_id
            classroom.save(update_fields=["course"])


class Migration(migrations.Migration):
    dependencies = [
        ("classroom", "0003_initial"),
        ("courses", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="classroom",
            name="course",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="legacy_classes",
                to="courses.course",
                verbose_name="课程",
            ),
        ),
        migrations.CreateModel(
            name="ClassCourse",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                (
                    "classroom",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="course_links",
                        to="classroom.classroom",
                        verbose_name="班级",
                    ),
                ),
                (
                    "course",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="classroom_links",
                        to="courses.course",
                        verbose_name="课程",
                    ),
                ),
            ],
            options={
                "verbose_name": "班级课程",
                "verbose_name_plural": "班级课程",
                "ordering": ["id"],
            },
        ),
        migrations.AddConstraint(
            model_name="classcourse",
            constraint=models.UniqueConstraint(
                fields=("classroom", "course"), name="unique_classroom_course"
            ),
        ),
        migrations.AddField(
            model_name="classroom",
            name="courses",
            field=models.ManyToManyField(
                related_name="classes",
                through="classroom.ClassCourse",
                to="courses.course",
                verbose_name="课程",
            ),
        ),
        migrations.RunPython(copy_existing_courses, restore_primary_course),
        migrations.RemoveField(model_name="classroom", name="course"),
    ]
