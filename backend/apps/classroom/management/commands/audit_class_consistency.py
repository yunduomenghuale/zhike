"""班级/学籍一致性巡检。

单班规则已由数据库条件唯一约束强制，正常情况不该出现多条占用；
这个命令的价值在于抓「约束管不到」的那类矛盾：

1. 多条占用关系 —— 约束上线前的历史脏数据，或有人用 raw SQL 绕过；
2. 学籍与班级状态矛盾 —— 班级已毕业，学生还是 enrolled；
3. 关系与账号状态矛盾 —— 学生在读但账号被停用，或账号是教师却挂在学生名单里；
4. 有占用关系却学籍退学 —— 退学必须同时移出班级，否则统计分母会算进他。

用法：
    python manage.py audit_class_consistency            # 只报告
    python manage.py audit_class_consistency --verbose  # 附带明细行
"""

from collections import Counter

from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.classroom.models import ClassRoom, ClassStudent
from apps.users.models import User

OCCUPYING = list(ClassStudent.OCCUPYING_STATUSES)


class Command(BaseCommand):
    help = "巡检班级归属与学籍一致性"

    def add_arguments(self, parser):
        parser.add_argument("--verbose", action="store_true", help="打印每条问题明细")

    def handle(self, *args, **options):
        verbose = options["verbose"]
        problems = Counter()
        details = []

        # 1) 多条占用
        dup = (
            ClassStudent.objects.filter(learn_status__in=OCCUPYING)
            .values("student_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        for row in dup:
            problems["多条占用关系"] += 1
            rows = ClassStudent.objects.filter(
                student_id=row["student_id"], learn_status__in=OCCUPYING
            ).select_related("classroom", "student")
            desc = "、".join(f"{r.classroom.name}(id={r.classroom_id})" for r in rows)
            details.append(f"[多条占用] 学生 {rows[0].student.username}(id={row['student_id']}) → {desc}")

        # 2) 班级已毕业，学生仍 enrolled
        stale = ClassStudent.objects.filter(
            learn_status__in=OCCUPYING,
            classroom__status=ClassRoom.Status.GRADUATED,
            student__edu_status=User.EduStatus.ENROLLED,
        ).select_related("classroom", "student")
        for rel in stale:
            problems["班级已毕业但学生仍视为在读"] += 1
            details.append(
                f"[学籍矛盾] {rel.student.username} 在已毕业班「{rel.classroom.name}」仍是 enrolled"
            )

        # 3) 学生关系指向非学生账号 / 已停用账号
        bad_role = ClassStudent.objects.filter(learn_status__in=OCCUPYING).exclude(
            student__role=User.Role.STUDENT
        ).select_related("student", "classroom")
        for rel in bad_role:
            problems["非学生账号占用班级名额"] += 1
            details.append(f"[角色错误] {rel.student.username} 角色={rel.student.role} 却在「{rel.classroom.name}」")

        inactive_account = ClassStudent.objects.filter(
            learn_status__in=OCCUPYING, student__is_active=False
        ).select_related("student", "classroom")
        for rel in inactive_account:
            problems["账号停用但仍在班"] += 1
            details.append(f"[账号停用] {rel.student.username} 已停用，仍占用「{rel.classroom.name}」")

        # 4) 学籍退学却仍占班
        withdrawn = ClassStudent.objects.filter(
            learn_status__in=OCCUPYING, student__edu_status=User.EduStatus.WITHDRAWN
        ).select_related("student", "classroom")
        for rel in withdrawn:
            problems["退学学生仍在班"] += 1
            details.append(f"[学籍矛盾] {rel.student.username} 已退学，仍占用「{rel.classroom.name}」")

        total_students = User.objects.filter(role=User.Role.STUDENT, is_active=True).count()
        unassigned = (
            User.objects.filter(role=User.Role.STUDENT, is_active=True)
            .exclude(id__in=ClassStudent.objects.filter(learn_status__in=OCCUPYING).values("student_id"))
            .count()
        )

        if details and verbose:
            self.stdout.write("—— 明细 ——")
            for line in details:
                self.stdout.write("  " + line)

        self.stdout.write("")
        self.stdout.write(
            f"在册学生 {total_students} 人，未分班 {unassigned} 人（未分班是正常状态，不告警）"
        )
        if not problems:
            self.stdout.write(self.style.SUCCESS("一致性巡检通过：0 项问题"))
            return

        self.stdout.write(self.style.WARNING(f"发现 {sum(problems.values())} 项问题："))
        for name, count in problems.items():
            self.stdout.write(f"  · {name}: {count}")
        self.stdout.write("处理方式见 docs/组织体系重构与智课复用-方案设计.md §5.2")
