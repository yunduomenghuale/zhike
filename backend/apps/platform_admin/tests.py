from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.courses.models import Course
from apps.ai.models import AIConfiguration
from apps.ai.providers.factory import get_provider

User = get_user_model()


class PlatformAdminApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="platform_admin",
            password="admin-pass-123",
            real_name="平台管理员",
            role=User.Role.ADMIN,
        )
        self.teacher = User.objects.create_user(
            username="teacher_one",
            password="teacher-pass-123",
            real_name="测试教师",
            role=User.Role.TEACHER,
        )
        self.course = Course.objects.create(
            name="Java 程序设计",
            teacher=self.teacher,
            status=Course.Status.ACTIVE,
        )

    def test_only_admin_can_view_overview(self):
        self.client.force_authenticate(self.teacher)
        forbidden = self.client.get("/api/admin-panel/overview/")
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_authenticate(self.admin)
        response = self.client.get("/api/admin-panel/overview/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["teaching"]["courses"], 1)

    def test_admin_can_create_user_and_unique_phone_is_enforced(self):
        self.client.force_authenticate(self.admin)
        payload = {
            "username": "student_one",
            "real_name": "测试学生",
            "phone": "13800138000",
            "role": User.Role.STUDENT,
            "is_active": True,
            "password": "student-pass-123",
        }
        created = self.client.post("/api/admin-panel/users/", payload, format="json")
        self.assertEqual(created.status_code, 201)

        payload["username"] = "student_two"
        duplicate = self.client.post("/api/admin-panel/users/", payload, format="json")
        self.assertEqual(duplicate.status_code, 400)

    def test_admin_can_reset_password(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            f"/api/admin-panel/users/{self.teacher.id}/reset-password/",
            {"password": "new-teacher-pass"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.check_password("new-teacher-pass"))

    def test_admin_can_change_course_status(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            f"/api/admin-panel/courses/{self.course.id}/status/",
            {"status": Course.Status.ARCHIVED},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.course.refresh_from_db()
        self.assertEqual(self.course.status, Course.Status.ARCHIVED)

    def test_django_superuser_is_exposed_as_admin_role(self):
        superuser = User.objects.create_superuser(
            username="root_admin",
            password="root-pass-123",
        )
        self.client.force_authenticate(superuser)
        profile = self.client.get("/api/auth/me/")
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.data["data"]["role"], User.Role.ADMIN)
        self.assertEqual(self.client.get("/api/admin-panel/overview/").status_code, 200)

        self.client.force_authenticate(self.admin)
        protected = self.client.patch(
            f"/api/admin-panel/users/{superuser.id}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(protected.status_code, 403)

    def test_admin_can_save_encrypted_ai_configuration(self):
        self.client.force_authenticate(self.admin)
        response = self.client.put(
            "/api/admin-panel/ai-configuration/",
            {
                "provider": "deepseek",
                "enabled": True,
                "base_url": "https://api.deepseek.com/v1",
                "chat_model": "deepseek-chat",
                "embed_model": "",
                "tts_model": "",
                "api_key": "sk-sensitive-value",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("api_key", response.data["data"])
        self.assertTrue(response.data["data"]["api_key_configured"])

        saved = AIConfiguration.objects.get()
        self.assertNotIn("sk-sensitive-value", saved.api_key_ciphertext)
        self.assertEqual(saved.get_api_key(), "sk-sensitive-value")
        self.assertEqual(get_provider().name, "deepseek")

    def test_ai_configuration_requires_admin_and_mock_can_be_tested(self):
        self.client.force_authenticate(self.teacher)
        self.assertEqual(self.client.get("/api/admin-panel/ai-configuration/").status_code, 403)

        self.client.force_authenticate(self.admin)
        saved = self.client.put(
            "/api/admin-panel/ai-configuration/",
            {"provider": "mock", "enabled": False, "base_url": "", "chat_model": "", "embed_model": "", "tts_model": ""},
            format="json",
        )
        self.assertEqual(saved.status_code, 200)
        tested = self.client.post("/api/admin-panel/ai-configuration/test/", {}, format="json")
        self.assertEqual(tested.status_code, 200)
        self.assertEqual(tested.data["data"]["last_test_status"], "success")
