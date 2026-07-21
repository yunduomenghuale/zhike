from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APITestCase

User = get_user_model()


class ProfileApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="profile_user",
            password="old-pass-123",
            real_name="测试用户",
            phone="13800138000",
            role=User.Role.STUDENT,
        )
        self.client.force_authenticate(self.user)

    def test_update_profile(self):
        response = self.client.patch(
            "/api/auth/me/",
            {
                "username": "profile_renamed",
                "real_name": "新姓名",
                "phone": "138 0013 8001",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["username"], "profile_renamed")
        self.assertEqual(response.data["data"]["phone"], "13800138001")
        self.user.refresh_from_db()
        self.assertEqual(self.user.real_name, "新姓名")

    def test_login_with_username_or_phone(self):
        self.client.force_authenticate(user=None)
        for identifier in ("profile_user", "13800138000", "138 0013 8000"):
            response = self.client.post(
                "/api/auth/login/",
                {"username": identifier, "password": "old-pass-123"},
                format="json",
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("access", response.data["data"]["token"])

    def test_phone_must_be_unique(self):
        other = User.objects.create_user(
            username="phone_owner",
            password="another-pass-123",
            phone="13900139000",
        )
        response = self.client.patch(
            "/api/auth/me/",
            {"phone": other.phone},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_change_password_requires_current_password(self):
        invalid = self.client.post(
            "/api/auth/password/",
            {
                "current_password": "wrong-password",
                "new_password": "new-pass-456",
                "confirm_password": "new-pass-456",
            },
            format="json",
        )
        self.assertEqual(invalid.status_code, 400)

        valid = self.client.post(
            "/api/auth/password/",
            {
                "current_password": "old-pass-123",
                "new_password": "new-pass-456",
                "confirm_password": "new-pass-456",
            },
            format="json",
        )
        self.assertEqual(valid.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("new-pass-456"))

    def test_upload_avatar(self):
        image_bytes = BytesIO()
        Image.new("RGB", (64, 64), "#2563eb").save(image_bytes, format="PNG")
        avatar = SimpleUploadedFile(
            "avatar.png",
            image_bytes.getvalue(),
            content_type="image/png",
        )

        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                "/api/auth/avatar/",
                {"avatar": avatar},
                format="multipart",
            )

            self.assertEqual(response.status_code, 200)
            avatar_url = response.data["data"]["avatar"]
            self.assertTrue(avatar_url.startswith("/media/avatars/"))
            self.assertTrue(Path(media_root, avatar_url.removeprefix("/media/")).exists())
