from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.courses.models import Catalog, Course, PPTResource, TeachingVideo, VideoWatchProgress


User = get_user_model()


class PptReplacementTests(APITestCase):
    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.media_override.enable()

        self.teacher = User.objects.create_user(
            username="ppt-teacher", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.student = User.objects.create_user(
            username="ppt-student", password="StrongPass!123", role=User.Role.STUDENT
        )
        self.course = Course.objects.create(name="Java", teacher=self.teacher)
        self.catalog = Catalog.objects.create(
            course=self.course, title="第一章", is_published=True
        )
        self.old_ppt = PPTResource.objects.create(
            course=self.course,
            catalog=self.catalog,
            file_name="old.pptx",
            version=1,
            is_active=True,
            parse_status=PPTResource.ParseStatus.DONE,
            parsed_pages=[{"page": 1, "title": "旧课件", "body": "旧内容"}],
        )
        self.video = TeachingVideo.objects.create(
            course=self.course,
            catalog=self.catalog,
            ppt=self.old_ppt,
            scripts=[{"page": 1, "script": "旧讲解稿", "audio_url": "/media/old.mp3"}],
            audio_url="/media/old.mp3",
            subtitle_url="/media/old.srt",
            video_url="/media/old.mp4",
            gen_status=TeachingVideo.GenStatus.DONE,
            is_published=True,
            published_at=timezone.now(),
        )
        self.progress = VideoWatchProgress.objects.create(
            student=self.student,
            video=self.video,
            last_page=3,
            last_position=12,
            watch_seconds=90,
            total_seconds=180,
            page_durations={"1": 30},
            page_watched={"1": 30},
            page_count=6,
            status=VideoWatchProgress.Status.IN_PROGRESS,
        )
        self.client.force_authenticate(user=self.teacher)

    def tearDown(self):
        self.media_override.disable()
        self.media_directory.cleanup()

    def upload(self, parsed_pages):
        upload = SimpleUploadedFile(
            "new.pptx",
            b"test presentation",
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        with (
            patch(
                "apps.courses.ppt_parser.parse_teaching_file_pages",
                return_value=parsed_pages,
            ),
            patch(
                "apps.courses.ppt_parser.render_presentation_slide_images",
                return_value=[],
            ),
            patch(
                "apps.courses.ppt_parser.attach_slide_images",
                side_effect=lambda pages, images: pages,
            ),
        ):
            return self.client.post(
                "/api/ppts/",
                {
                    "course": self.course.id,
                    "catalog": self.catalog.id,
                    "file_name": upload.name,
                    "file": upload,
                },
                format="multipart",
            )

    def test_successful_upload_replaces_active_ppt_and_invalidates_old_content(self):
        response = self.upload([{"page": 1, "title": "新课件", "body": "新内容"}])

        self.assertEqual(response.status_code, 201)
        new_ppt = PPTResource.objects.get(pk=response.data["data"]["id"])
        self.old_ppt.refresh_from_db()
        self.video.refresh_from_db()
        self.progress.refresh_from_db()

        self.assertFalse(self.old_ppt.is_active)
        self.assertTrue(new_ppt.is_active)
        self.assertEqual(new_ppt.version, 2)
        self.assertEqual(self.video.ppt_id, new_ppt.id)
        self.assertEqual(self.video.scripts, [])
        self.assertEqual(self.video.audio_url, "")
        self.assertEqual(self.video.subtitle_url, "")
        self.assertEqual(self.video.video_url, "")
        self.assertEqual(self.video.gen_status, TeachingVideo.GenStatus.DRAFT)
        self.assertFalse(self.video.is_published)
        self.assertIsNone(self.video.published_at)
        self.assertEqual(self.progress.last_page, 0)
        self.assertEqual(self.progress.watch_seconds, 0)
        self.assertEqual(self.progress.status, VideoWatchProgress.Status.NOT_STARTED)

    def test_failed_upload_keeps_previous_content_active(self):
        response = self.upload([])

        self.assertEqual(response.status_code, 201)
        failed_ppt = PPTResource.objects.get(pk=response.data["data"]["id"])
        self.old_ppt.refresh_from_db()
        self.video.refresh_from_db()
        self.progress.refresh_from_db()

        self.assertTrue(self.old_ppt.is_active)
        self.assertFalse(failed_ppt.is_active)
        self.assertEqual(failed_ppt.parse_status, PPTResource.ParseStatus.FAILED)
        self.assertEqual(self.video.ppt_id, self.old_ppt.id)
        self.assertEqual(self.video.scripts[0]["script"], "旧讲解稿")
        self.assertTrue(self.video.is_published)
        self.assertEqual(self.progress.last_page, 3)

    def test_regenerated_script_publishes_replacement_content(self):
        self.upload([{"page": 1, "title": "新课件", "body": "新内容"}])

        def fake_batched(video, pages, batch_size=6):
            # 模拟分批生成全部完成：写入新讲稿并按主线语义自动发布
            video.scripts = [{"page": 1, "script": "新讲解稿"}]
            video.gen_status = TeachingVideo.GenStatus.SCRIPT_READY
            video.is_published = True
            video.published_at = timezone.now()
            video.save()
            return {"generated": 1, "pages": 1, "script_pages": 1, "remaining": 0, "done": True}

        with patch(
            "apps.ai.services.generate_script_pages_batched",
            side_effect=fake_batched,
        ):
            response = self.client.post(
                f"/api/catalogs/{self.catalog.id}/generate-script/",
                {"limit": 1},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.video.refresh_from_db()
        self.assertEqual(self.video.scripts, [{"page": 1, "script": "新讲解稿"}])
        self.assertTrue(self.video.is_published)
        self.assertIsNotNone(self.video.published_at)
