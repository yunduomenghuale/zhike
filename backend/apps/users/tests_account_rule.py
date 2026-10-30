"""账号（学号 / 工号）格式规则：6~8 位、只能由字母和数字组成。

规则在 apps/users/validators.py 统一定义，本文件覆盖四个入口
（管理端建号 / 自助改资料 / 学生导入 / 教师导入）以及历史账号的兼容边界。
"""
from io import BytesIO

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
    def test_accepts_six_to_eight_alnum(self):
        for value in ("202401", "20240101", "T2024001", "abcDEF12"):
            self.assertEqual(account_problem(value, "学号"), "", value)

    def test_rejects_length_out_of_range(self):
        self.assertIn("6～8", account_problem("20240", "学号"))
        self.assertIn("6～8", account_problem("202401011", "学号"))
        self.assertIn("6～8", account_problem("2024010112345", "学号"))

    def test_rejects_non_alnum(self):
        for value in ("2024_01", "2024-01", "2024 01", "学号1234", "2024@01", "2024.01"):
            self.assertIn("只能由字母和数字", account_problem(value, "学号"), value)

    def test_empty(self):
        self.assertEqual(account_problem("  ", "学号"), "学号不能为空")


class AdminCreateAccountTests(TestCase):
    """管理端建号与编辑：新建严格校验，编辑历史账号只校验「改动的值」。"""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin001", password="pw123456!", role=User.Role.ADMIN
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def create(self, username, role="student"):
        return self.client.post(
            "/api/admin-panel/users/",
            {"username": username, "real_name": "测试生", "role": role, "password": "pw123456!"},
            format="json",
        )

    def test_create_accepts_valid_account(self):
        for value in ("202401", "20240101", "T2024001"):
            resp = self.create(value)
            self.assertEqual(resp.status_code, 201, (value, resp.data))

    def test_create_rejects_short_account(self):
        resp = self.create("20240")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("6～8", str(resp.data))

    def test_create_rejects_long_account(self):
        resp = self.create("202401011")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("6～8", str(resp.data))

    def test_create_rejects_non_alnum_account(self):
        for value in ("2024_01", "2024-01", "学号2024"):
            resp = self.create(value)
            self.assertEqual(resp.status_code, 400, value)
            self.assertIn("只能由字母和数字", str(resp.data))

    def test_edit_legacy_account_without_touching_username(self):
        """历史账号（4 位工号）改姓名不应被自己的用户名挡死。"""
        legacy = User.objects.create_user(
            username="t01", password="pw123456!", role=User.Role.TEACHER, real_name="老账号"
        )
        resp = self.client.patch(
            f"/api/admin-panel/users/{legacy.id}/",
            {"username": "t01", "real_name": "改名后", "role": "teacher", "is_active": True},
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
    """自助改资料（PATCH /api/auth/me/）同样走统一规则。"""

    def setUp(self):
        self.client = APIClient()

    def test_legacy_username_unchanged_can_save_profile(self):
        legacy = User.objects.create_user(
            username="t101", password="pw123456!", role=User.Role.TEACHER
        )
        self.client.force_authenticate(user=legacy)
        resp = self.client.patch(
            "/api/auth/me/", {"username": "t101", "real_name": "张老师"}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        legacy.refresh_from_db()
        self.assertEqual(legacy.real_name, "张老师")

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


class ImportAccountRuleTests(TestCase):
    """批量导入：预览阶段就该把不合规学号/工号标成错误行，而不是等到提交报 500。"""

    def annotate(self, content: bytes, kind: str):
        return annotate_rows(kind, parse_excel(BytesIO(content), kind), {})

    def test_student_import_flags_underscore_and_length(self):
        content = make_xlsx(
            ["学号", "姓名", "班级编码", "班级名称", "入学年"],
            [["2024_01", "甲", "", "", ""], ["202401011", "乙", "", "", ""], ["20240101", "丙", "", "", ""]],
        )
        rows = self.annotate(content, KIND_STUDENT)["rows"]
        self.assertEqual(rows[0]["row_status"], "error")
        self.assertIn("只能由字母和数字", rows[0]["message"])
        self.assertEqual(rows[1]["row_status"], "error")
        self.assertIn("6～8", rows[1]["message"])
        self.assertEqual(rows[2]["row_status"], "ok")

    def test_teacher_import_flags_short_account(self):
        content = make_xlsx(["工号", "姓名"], [["T001", "张三"], ["T2024001", "李四"]])
        rows = self.annotate(content, KIND_TEACHER)["rows"]
        self.assertEqual(rows[0]["row_status"], "error")
        self.assertIn("工号长度应为 6～8 位", rows[0]["message"])
        self.assertEqual(rows[1]["row_status"], "ok")
        self.assertEqual(rows[1]["initial_password"], "Zk024001")
