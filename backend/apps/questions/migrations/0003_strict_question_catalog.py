import django.db.models.deletion
from django.db import migrations, models


def assign_orphan_questions(apps, schema_editor):
    Question = apps.get_model("questions", "Question")
    Catalog = apps.get_model("courses", "Catalog")

    course_ids = Question.objects.filter(catalog_id=None).values_list("course_id", flat=True).distinct()
    for course_id in course_ids:
        catalog = Catalog.objects.filter(course_id=course_id).order_by("order", "id").first()
        if catalog is None:
            max_order = (
                Catalog.objects.filter(course_id=course_id)
                .order_by("-order")
                .values_list("order", flat=True)
                .first()
                or 0
            )
            catalog = Catalog.objects.create(
                course_id=course_id,
                title="历史未归类（请整理）",
                order=max_order + 1,
                intro="系统迁移旧题时自动建立，请将题目调整到正式章节。",
                is_published=False,
            )
        Question.objects.filter(course_id=course_id, catalog_id=None).update(catalog_id=catalog.id)


class Migration(migrations.Migration):
    dependencies = [
        ("questions", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(assign_orphan_questions, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="question",
            name="catalog",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="questions",
                to="courses.catalog",
                verbose_name="章节",
            ),
        ),
    ]
