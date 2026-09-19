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


class CourseResourceTests(APITestCase):
    """二期B：思维导图/交互演示挂课程资源。"""

    def setUp(self):
        self.teacher = User.objects.create_user(
            username="res-teacher", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.student = User.objects.create_user(
            username="res-student", password="StrongPass!123", role=User.Role.STUDENT
        )
        self.course = Course.objects.create(name="计算机网络", teacher=self.teacher)
        self.catalog = Catalog.objects.create(course=self.course, title="第4章 网络层", is_published=True)

    def _create(self, client, **overrides):
        payload = {
            "course": self.course.id,
            "catalog": self.catalog.id,
            "kind": "mindmap",
            "title": "第4章思维导图",
            "path": "mindmap/chapter4.html",
        }
        payload.update(overrides)
        return client.post("/api/course-resources/", payload, format="json")

    def test_teacher_create_and_publish(self):
        self.client.force_authenticate(self.teacher)
        res = self._create(self.client)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIn("/resources/mindmap/chapter4.html", res.data["data"]["url"])
        rid = res.data["data"]["id"]
        res = self.client.post(f"/api/course-resources/{rid}/publish/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["data"]["is_published"])

    def test_path_whitelist_rejects_traversal(self):
        self.client.force_authenticate(self.teacher)
        res = self._create(self.client, path="../../etc/passwd")
        self.assertEqual(res.status_code, 400)
        res = self._create(self.client, path="https://evil.com/x.html")
        self.assertEqual(res.status_code, 400)

    def test_student_sees_only_published_of_enrolled_course(self):
        from apps.classroom.models import ClassCourse, ClassRoom, ClassStudent

        classroom = ClassRoom.objects.create(name="网络2401", teacher=self.teacher)
        ClassCourse.objects.create(classroom=classroom, course=self.course)
        ClassStudent.objects.create(classroom=classroom, student=self.student)
        self.client.force_authenticate(self.teacher)
        res = self._create(self.client)
        self.assertEqual(res.status_code, 201, res.data)
        # 未发布 → 学生不可见
        self.client.force_authenticate(self.student)
        res = self.client.get(f"/api/course-resources/?course={self.course.id}")
        self.assertEqual(len(res.data["data"]["results"] if isinstance(res.data["data"], dict) else res.data["data"]), 0)
        # 发布后可见
        self.client.force_authenticate(self.teacher)
        rid = res.data["data"]["id"] if res.status_code == 201 else None
        # 重新拿 id（上面学生视角返回结构可能不同）
        listing = self.client.get(f"/api/course-resources/?course={self.course.id}")
        # 教师视角可见
        self.client.force_authenticate(self.teacher)
        listing = self.client.get(f"/api/course-resources/?course={self.course.id}")
        data = listing.data["data"]
        items = data["results"] if isinstance(data, dict) and "results" in data else data
        self.assertGreaterEqual(len(items), 1)
        rid = items[0]["id"]
        self.client.post(f"/api/course-resources/{rid}/publish/")
        self.client.force_authenticate(self.student)
        res = self.client.get(f"/api/course-resources/?course={self.course.id}")
        data = res.data["data"]
        items = data["results"] if isinstance(data, dict) and "results" in data else data
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["path"], "mindmap/chapter4.html")

    def test_other_teacher_cannot_modify(self):
        other = User.objects.create_user(
            username="res-other", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.client.force_authenticate(other)
        res = self._create(self.client)
        self.assertEqual(res.status_code, 400)  # 序列化器拒绝非自己课程


class CourseVideoTests(APITestCase):
    """二期C：数字人视频上传/发布/学生可见性。"""

    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)

        self.teacher = User.objects.create_user(
            username="vid-teacher", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.student = User.objects.create_user(
            username="vid-student", password="StrongPass!123", role=User.Role.STUDENT
        )
        self.course = Course.objects.create(name="计算机网络", teacher=self.teacher)
        self.catalog = Catalog.objects.create(course=self.course, title="第5章 传输层", is_published=True)

    def _tiny_mp4(self, name="dh.mp4", size_kb=64):
        # 合法 mp4 头 + 填充，几 KB 即可（仅存储与接口冒烟，不做真解码）
        return SimpleUploadedFile(name, b"\x00\x00\x00\x18ftypmp42" + b"\0" * size_kb * 1024,
                                  content_type="video/mp4")

    def test_teacher_upload_publish_and_student_visible(self):
        from apps.classroom.models import ClassCourse, ClassRoom, ClassStudent

        classroom = ClassRoom.objects.create(name="网络2402", teacher=self.teacher)
        ClassCourse.objects.create(classroom=classroom, course=self.course)
        ClassStudent.objects.create(classroom=classroom, student=self.student)

        self.client.force_authenticate(self.teacher)
        res = self.client.post("/api/course-videos/", {
            "course": self.course.id,
            "catalog": self.catalog.id,
            "title": "第5章数字人精讲",
            "file": self._tiny_mp4(),
        }, format="multipart")
        self.assertEqual(res.status_code, 201, res.data)
        data = res.data["data"]
        self.assertEqual(data["file_size"], 64 * 1024 + 12)  # 12 字节 mp4 头
        self.assertIn("course_videos/", data["file_url"])
        vid = data["id"]

        # 未发布学生不可见
        self.client.force_authenticate(self.student)
        res = self.client.get(f"/api/course-videos/?course={self.course.id}")
        items = res.data["data"]["results"] if isinstance(res.data["data"], dict) else res.data["data"]
        self.assertEqual(len(items or []), 0)

        # 发布后可见
        self.client.force_authenticate(self.teacher)
        res = self.client.post(f"/api/course-videos/{vid}/publish/")
        self.assertEqual(res.status_code, 200)
        self.client.force_authenticate(self.student)
        res = self.client.get(f"/api/course-videos/?course={self.course.id}")
        items = res.data["data"]["results"] if isinstance(res.data["data"], dict) else res.data["data"]
        self.assertEqual(len(items or []), 1)
        self.assertEqual(items[0]["title"], "第5章数字人精讲")

    def test_oversize_rejected(self):
        from unittest.mock import patch

        from apps.courses import views as course_views

        self.client.force_authenticate(self.teacher)
        # patch 上限常量到极小值，验证超限拒绝逻辑（避免真实生成 500MB 数据）
        with patch.object(course_views, "MAX_COURSE_VIDEO_SIZE", 1024):
            res = self.client.post("/api/course-videos/", {
                "course": self.course.id,
                "title": "超限视频",
                "file": self._tiny_mp4(size_kb=64),
            }, format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("500MB", res.data["message"])

    def test_other_teacher_cannot_upload(self):
        other = User.objects.create_user(
            username="vid-other", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.client.force_authenticate(other)
        res = self.client.post("/api/course-videos/", {
            "course": self.course.id,
            "title": "越权上传",
            "file": self._tiny_mp4(),
        }, format="multipart")
        self.assertEqual(res.status_code, 400)
