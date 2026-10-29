from django.db import migrations, models
from django.db.models import Count


def check_single_class(apps, schema_editor):
    """加唯一约束前先自查：一个学生不允许同时占两个班。

    存量若有冲突（历史代码对单班零校验，邀请码可重复加入），直接让迁移**中止**并
    打印清单，绝不自动替学生挑一个班 —— 归属是业务事实，只能人定。
    处理方式见 docs/组织体系重构与智课复用-方案设计.md §5.2「存量数据卡口」。
    """
    ClassStudent = apps.get_model("classroom", "ClassStudent")
    dup = (
        ClassStudent.objects.filter(learn_status__in=["active", "inactive"])
        .values("student_id")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
    )
    if not dup:
        return

    lines = []
    for row in dup:
        rows = ClassStudent.objects.filter(
            student_id=row["student_id"], learn_status__in=["active", "inactive"]
        ).select_related("classroom", "student")
        desc = "、".join(f"{r.classroom.name}({r.classroom_id})" for r in rows)
        student = rows[0].student
        lines.append(f"  学生 {student.username}(id={row['student_id']}) 占: {desc}")
    raise RuntimeError(
        "存在学生同时占用多个班级的数据，无法建立单班唯一约束。\n"
        "请先人工指定归属（把其中一条 learn_status 置为 transferred），再重新 migrate：\n"
        + "\n".join(lines)
    )


class Migration(migrations.Migration):
    """单班唯一约束（方案 §5.2 的核心）。

    条件唯一索引而不是普通唯一约束：只有 active/inactive 占位，
    transferred/removed 是历史留痕，允许同一学生留多条。
    """

    dependencies = [
        ("classroom", "0005_classroom_org_fields"),
    ]

    operations = [
        migrations.RunPython(check_single_class, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="classstudent",
            constraint=models.UniqueConstraint(
                condition=models.Q(("learn_status__in", ["active", "inactive"])),
                fields=("student",),
                name="uniq_occupied_class_per_student",
            ),
        ),
    ]
