"""账号格式规则：学生学号 6~8 位、教师/管理员 3~10 位，均只允许字母和数字。

规则在 apps/users/validators.py 统一定义，本文件覆盖四个入口
（管理端建号 / 自助改资料 / 学生导入 / 教师导入）、存量账号兼容边界，
以及存量整改命令 normalize_usernames。
"""
from io import BytesIO, StringIO

from django.core.management import call_command
from django.test import TestCase
from openpyxl import Workbook
from rest_framework.test import APIClient

from apps.platform_admin.imports import KIND_STUDENT, KIND_TEACHER, annotate_rows, parse_excel
from apps.users.models import User
from apps.users.validators import account_problem


def make_xlsx(headers: list, rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


class AccountFormatUnitTests(TestCase):
    def test_student_accepts_six_to_eight(self):
        for value in ("202401", "20240101", "B260401"):
            self.assertEqual(account_problem(value, "student"), "", value)

    def test_student_rejects_out_of_range(self):
        self.assertIn("6～8", account_problem("20240", "student"))
        self.assertIn("6～8", account_problem("hys", "student"))
        self.assertIn("6～8", account_problem("202401011", "student"))

    def test_teacher_and_admin_accept_three_to_ten(self):
        for role in ("teacher", "admin"):
            for value in ("wgy", "T0001", "T202400123"):
                self.assertEqual(account_problem(value, role), "", (role, value))

    def test_teacher_rejects_out_of_range(self):
        self.assertIn("3～10", account_problem("ab", "teacher"))
        self.assertIn("3～10", account_problem("T2024001234", "teacher"))

    def test_rejects_non_alnum(self):
        for role in ("student", "teacher"):
            for value in ("2024_01", "2024-01", "2024 01", "学号1234", "2024@01", "孟燕姿孟燕姿"):
                self.assertIn("只能由字母和数字", account_problem(value, role), (role, value))

    def test_short_chinese_name_fails_on_length_first(self):
        # 3 个汉字的学生账号先撞长度下限；换 6 个汉字才轮到字符集规则
        self.assertIn("6～8", account_problem("孟燕姿", "student"))
        self.assertIn("只能由字母和数字", account_problem("孟燕姿孟燕姿", "student"))

    def test_label_follows_role(self):
        self.assertTrue(account_problem("", "student").startswith("学号"))
        self.assertTrue(account_problem("", "teacher").startswith("工号"))
        self.assertTrue(account_problem("", "admin").startswith("账号"))


class AdminCreateAccountTests(TestCase):
    """管理端建号与编辑：新建严格校验，编辑存量账号只校验「改动的值」。"""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin001", password="pw123456!", role=User.Role.ADMIN
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def create(self, username, role="student"):
        return self.client.post(
            "/api/admin-panel/users/",
            {"username": username, "real_name": "测试", "role": role, "password": "pw123456!"},
            format="json",
        )

    def test_create_student_accepts_six_to_eight(self):
        for value in ("202401", "20240101", "B260401"):
            resp = self.create(value, "student")
            self.assertEqual(resp.status_code, 201, (value, resp.data))

    def test_create_student_rejects_short_long_and_symbols(self):
        for value, keyword in (("hys", "6～8"), ("202401011", "6～8"), ("2024_01", "只能由字母和数字")):
            resp = self.create(value, "student")
            self.assertEqual(resp.status_code, 400, value)
            self.assertIn(keyword, str(resp.data))

    def test_create_teacher_accepts_three_digit(self):
        for value in ("wgy", "sjy", "T0001"):
            resp = self.create(value, "teacher")
            self.assertEqual(resp.status_code, 201, (value, resp.data))

    def test_create_teacher_rejects_too_short_or_long(self):
        for value in ("ab", "T2024001234"):
            resp = self.create(value, "teacher")
            self.assertEqual(resp.status_code, 400, value)
            self.assertIn("3～10", str(resp.data))

    def test_edit_legacy_account_without_touching_username(self):
        """存量学号（3 位 hys）改姓名不应被自己的账号挡死。"""
        legacy = User.objects.create_user(
            username="hys", password="pw123456!", role=User.Role.STUDENT, real_name="黄玉钐"
        )
        resp = self.client.patch(
            f"/api/admin-panel/users/{legacy.id}/",
            {"username": "hys", "real_name": "改名后", "role": "student", "is_active": True},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        legacy.refresh_from_db()
        self.assertEqual(legacy.real_name, "改名后")

    def test_edit_changing_into_invalid_account_is_rejected(self):
        user = User.objects.create_user(
            username="20240101", password="pw123456!", role=User.Role.STUDENT
        )
        resp = self.client.patch(
            f"/api/admin-panel/users/{user.id}/",
            {"username": "2024_01", "real_name": "改坏", "role": "student", "is_active": True},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("只能由字母和数字", str(resp.data))


class SelfProfileAccountTests(TestCase):
    """自助改资料（PATCH /api/auth/me/）按本人角色校验。"""

    def setUp(self):
        self.client = APIClient()

    def test_legacy_student_username_unchanged_can_save_profile(self):
        legacy = User.objects.create_user(
            username="hys", password="pw123456!", role=User.Role.STUDENT
        )
        self.client.force_authenticate(user=legacy)
        resp = self.client.patch(
            "/api/auth/me/", {"username": "hys", "real_name": "黄玉钐"}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_change_to_invalid_username_is_rejected(self):
        user = User.objects.create_user(
            username="20240101", password="pw123456!", role=User.Role.STUDENT
        )
        self.client.force_authenticate(user=user)
        for value in ("2024_01", "202401011", "2024"):
            resp = self.client.patch("/api/auth/me/", {"username": value}, format="json")
            self.assertEqual(resp.status_code, 400, value)
        user.refresh_from_db()
        self.assertEqual(user.username, "20240101")

    def test_teacher_three_digit_username_is_allowed(self):
        teacher = User.objects.create_user(
            username="t992", password="pw123456!", role=User.Role.TEACHER
        )
        self.client.force_authenticate(user=teacher)
        resp = self.client.patch("/api/auth/me/", {"username": "t993"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)


class ImportAccountRuleTests(TestCase):
    """批量导入：预览阶段就该把不合规学号/工号标成错误行。"""

    def annotate(self, content: bytes, kind: str):
        return annotate_rows(kind, parse_excel(BytesIO(content), kind), {})

    def test_student_import_flags_short_and_symbols(self):
        content = make_xlsx(
            ["学号", "姓名", "班级编码", "班级名称", "入学年"],
            [["hys", "甲", "", "", ""], ["2024_01", "乙", "", "", ""], ["20240101", "丙", "", "", ""]],
        )
        rows = self.annotate(content, KIND_STUDENT)["rows"]
        self.assertEqual(rows[0]["row_status"], "error")
        self.assertIn("学号长度应为 6～8 位", rows[0]["message"])
        self.assertEqual(rows[1]["row_status"], "error")
        self.assertIn("只能由字母和数字", rows[1]["message"])
        self.assertEqual(rows[2]["row_status"], "ok")

    def test_teacher_import_accepts_three_and_rejects_eleven(self):
        content = make_xlsx(
            ["工号", "姓名"],
            [["wgy", "王工"], ["T2024001234", "长工号"], ["T2024001", "李工"]],
        )
        rows = self.annotate(content, KIND_TEACHER)["rows"]
        self.assertEqual(rows[0]["row_status"], "ok")
        self.assertEqual(rows[0]["initial_password"], "Zk000wgy")
        self.assertEqual(rows[1]["row_status"], "error")
        self.assertIn("工号长度应为 3～10 位", rows[1]["message"])
        self.assertEqual(rows[2]["row_status"], "ok")
        self.assertEqual(rows[2]["initial_password"], "Zk024001")


class NormalizeUsernamesCommandTests(TestCase):
    """存量整改命令：默认 dry-run，--apply 才改名，且不动密码与班级关系。"""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin", password="pw123456!", role=User.Role.ADMIN
        )
        self.legacy = User.objects.create_user(
            username="孟燕姿", password="pw123456!", role=User.Role.STUDENT,
            real_name="孟燕姿", enrollment_year=2026,
        )

    def run_command(self, *args):
        out = StringIO()
        call_command("normalize_usernames", *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_dry_run_does_not_change_anything(self):
        text = self.run_command()
        self.assertIn("孟燕姿", text)
        self.legacy.refresh_from_db()
        self.assertEqual(self.legacy.username, "孟燕姿")

    def test_apply_renames_to_compliant_and_keeps_password(self):
        before = self.legacy.password
        self.run_command("--apply")
        self.legacy.refresh_from_db()
        self.assertEqual(self.legacy.username, "B260001")
        self.assertEqual(self.legacy.password, before)
        self.assertEqual(account_problem(self.legacy.username, "student"), "")

    def test_apply_respects_manual_mapping(self):
        self.run_command("--apply", "--map", "孟燕姿=20269999")
        self.legacy.refresh_from_db()
        self.assertEqual(self.legacy.username, "20269999")

    def test_compliant_accounts_untouched(self):
        ok = User.objects.create_user(
            username="wgy", password="pw123456!", role=User.Role.TEACHER
        )
        self.run_command("--apply", "--role", "teacher")
        ok.refresh_from_db()
        self.assertEqual(ok.username, "wgy")
