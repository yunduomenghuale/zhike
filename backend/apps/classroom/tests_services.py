"""P0 地基：单班约束、入班/转班/移出 service、巡检命令。

这些用例是"单班"这条规则唯一可执行的规格说明：约束在数据库层，
service 在应用层，巡检在运维层，三层都要各自被验证。
"""

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.users.models import User

from . import services
from .models import ClassRoom, ClassStudent


class ClassServiceTestBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="adm_cls", password="pw123456!", role=User.Role.ADMIN
        )
        self.teacher = User.objects.create_user(
            username="t_cls", password="pw123456!", role=User.Role.TEACHER, real_name="班级教师"
        )
        self.class_a = ClassRoom.objects.create(
            name="计科2401", code="CS2401", teacher=self.teacher, enrollment_year=2024, duration_years=4
        )
        self.class_b = ClassRoom.objects.create(
            name="计科2402", code="CS2402", teacher=self.teacher, enrollment_year=2024, duration_years=4
        )
        self.stu1 = User.objects.create_user(
            username="stu_1", password="pw123456!", role=User.Role.STUDENT, real_name="学生一"
        )
        self.stu2 = User.objects.create_user(
            username="stu_2", password="pw123456!", role=User.Role.STUDENT, real_name="学生二"
        )


class AssignStudentsTests(ClassServiceTestBase):
    def test_assign_creates_active_relation(self):
        result = services.assign_students(self.class_a, [self.stu1], operator=self.admin)
        self.assertEqual([u.username for u in result["created"]], ["stu_1"])
        rel = ClassStudent.objects.get(student=self.stu1)
        self.assertEqual(rel.classroom_id, self.class_a.id)
        self.assertEqual(rel.learn_status, ClassStudent.LearnStatus.ACTIVE)

    def test_assign_is_idempotent(self):
        services.assign_students(self.class_a, [self.stu1], operator=self.admin)
        again = services.assign_students(self.class_a, [self.stu1], operator=self.admin)
        self.assertEqual(again["created"], [])
        self.assertEqual([u.username for u in again["unchanged"]], ["stu_1"])
        self.assertEqual(
            ClassStudent.objects.filter(student=self.stu1, learn_status__in=["active", "inactive"]).count(), 1
        )

    def test_assign_to_second_class_conflicts(self):
        services.assign_students(self.class_a, [self.stu1], operator=self.admin)
        with self.assertRaises(services.ClassServiceError) as ctx:
            services.assign_students(self.class_b, [self.stu1], operator=self.admin)
        self.assertEqual(ctx.exception.code, 409)
        self.assertIn("计科2401", ctx.exception.detail)
        self.assertFalse(ClassStudent.objects.filter(classroom=self.class_b, student=self.stu1).exists())

    def test_assign_rejects_teacher_account(self):
        with self.assertRaises(services.ClassServiceError) as ctx:
            services.assign_students(self.class_a, [self.teacher], operator=self.admin)
        self.assertEqual(ctx.exception.code, 400)

    def test_direct_create_bypassing_service_is_blocked_by_db(self):
        """绕过 service 直接建第二条占用关系必须被数据库拒绝。

        这条用例的价值在于证明"约束真的落到 DB 了"，而不只是 Python 层校验——
        后者一个 raw SQL 或 bulk_create 就能绕过。
        """
        services.assign_students(self.class_a, [self.stu1], operator=self.admin)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ClassStudent.objects.create(classroom=self.class_b, student=self.stu1)


class TransferStudentsTests(ClassServiceTestBase):
    def test_transfer_marks_old_relation_transferred(self):
        services.assign_students(self.class_a, [self.stu1], operator=self.admin)
        services.transfer_students(self.class_b, [self.stu1], operator=self.admin)

        old = ClassStudent.objects.get(classroom=self.class_a, student=self.stu1)
        new = ClassStudent.objects.get(classroom=self.class_b, student=self.stu1)
        # 关键：旧关系是 transferred 而不是 removed，否则学生看不到旧班成绩
        self.assertEqual(old.learn_status, ClassStudent.LearnStatus.TRANSFERRED)
        self.assertEqual(new.learn_status, ClassStudent.LearnStatus.ACTIVE)
        self.assertEqual(
            ClassStudent.objects.filter(student=self.stu1, learn_status__in=["active", "inactive"]).count(), 1
        )

    def test_transfer_syncs_enrollment_year(self):
        services.assign_students(self.class_a, [self.stu1], operator=self.admin)
        services.transfer_students(self.class_b, [self.stu1], operator=self.admin)
        self.stu1.refresh_from_db()
        self.assertEqual(self.stu1.enrollment_year, 2024)
        self.assertEqual(self.stu1.duration_years, 4)

    def test_transfer_without_class_is_rejected(self):
        with self.assertRaises(services.ClassServiceError) as ctx:
            services.transfer_students(self.class_b, [self.stu1], operator=self.admin)
        self.assertEqual(ctx.exception.code, 400)

    def test_transfer_to_same_class_is_noop(self):
        services.assign_students(self.class_a, [self.stu1], operator=self.admin)
        result = services.transfer_students(self.class_a, [self.stu1], operator=self.admin)
        self.assertEqual(result["moved"], [])
        self.assertEqual(ClassStudent.objects.filter(student=self.stu1).count(), 1)


class RemoveStudentsTests(ClassServiceTestBase):
    def test_remove_marks_removed_and_withdraws(self):
        services.assign_students(self.class_a, [self.stu1], operator=self.admin)
        services.remove_students(self.class_a, [self.stu1], operator=self.admin, reason="退学")

        rel = ClassStudent.objects.get(student=self.stu1)
        self.assertEqual(rel.learn_status, ClassStudent.LearnStatus.REMOVED)
        self.stu1.refresh_from_db()
        self.assertEqual(self.stu1.edu_status, User.EduStatus.WITHDRAWN)
        self.assertIsNotNone(self.stu1.status_changed_at)
        self.assertEqual(self.stu1.status_note, "退学")

    def test_remove_without_withdraw_keeps_enrolled(self):
        """分班纠错场景：解除班级关系但学籍仍在读，之后可以重新入班。"""
        services.assign_students(self.class_a, [self.stu1], operator=self.admin)
        services.remove_students(self.class_a, [self.stu1], operator=self.admin, withdraw=False)

        self.stu1.refresh_from_db()
        self.assertEqual(self.stu1.edu_status, User.EduStatus.ENROLLED)
        # 被移出后可以重新入班（历史行不占位）
        result = services.assign_students(self.class_b, [self.stu1], operator=self.admin)
        self.assertEqual(len(result["created"]), 1)

    def test_remove_is_idempotent(self):
        services.assign_students(self.class_a, [self.stu1], operator=self.admin)
        services.remove_students(self.class_a, [self.stu1], operator=self.admin)
        again = services.remove_students(self.class_a, [self.stu1], operator=self.admin)
        self.assertEqual(again["removed"], [])


class ChangeEduStatusTests(ClassServiceTestBase):
    def test_change_status_sets_timestamp_and_note(self):
        services.change_edu_status(
            self.stu1, User.EduStatus.SUSPENDED, operator=self.admin, note="休学一年"
        )
        self.stu1.refresh_from_db()
        self.assertEqual(self.stu1.edu_status, User.EduStatus.SUSPENDED)
        self.assertEqual(self.stu1.status_note, "休学一年")
        self.assertIsNotNone(self.stu1.status_changed_at)

    def test_change_status_rejects_unknown_value(self):
        with self.assertRaises(services.ClassServiceError):
            services.change_edu_status(self.stu1, "dropped", operator=self.admin)

    def test_graduated_keeps_class_relation(self):
        """毕业只改学籍，不动班级关系——否则学生看不到历史课程（决策 4）。"""
        services.assign_students(self.class_a, [self.stu1], operator=self.admin)
        services.change_edu_status(self.stu1, User.EduStatus.GRADUATED, operator=self.admin)
        rel = ClassStudent.objects.get(student=self.stu1)
        self.assertEqual(rel.learn_status, ClassStudent.LearnStatus.ACTIVE)


class AuditCommandTests(ClassServiceTestBase):
    def _run(self):
        from io import StringIO

        out = StringIO()
        call_command("audit_class_consistency", stdout=out)
        return out.getvalue()

    def test_clean_database_passes(self):
        services.assign_students(self.class_a, [self.stu1], operator=self.admin)
        output = self._run()
        self.assertIn("0 项问题", output)

    def test_unassigned_student_is_not_reported_as_problem(self):
        """未分班是正常状态（新生名单先到），不能当问题报。"""
        output = self._run()
        self.assertIn("0 项问题", output)
        self.assertIn("未分班", output)

    def test_withdrawn_student_still_in_class_is_reported(self):
        services.assign_students(self.class_a, [self.stu1], operator=self.admin)
        # 模拟历史脏数据：学籍退学但没有移出班级
        User.objects.filter(pk=self.stu1.pk).update(edu_status=User.EduStatus.WITHDRAWN)
        output = self._run()
        self.assertIn("退学学生仍在班", output)

    def test_graduated_class_with_enrolled_student_is_reported(self):
        services.assign_students(self.class_a, [self.stu1], operator=self.admin)
        ClassRoom.objects.filter(pk=self.class_a.pk).update(status=ClassRoom.Status.GRADUATED)
        output = self._run()
        self.assertIn("班级已毕业但学生仍视为在读", output)
