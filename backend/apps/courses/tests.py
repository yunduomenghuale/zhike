import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.ai.providers.mock import MockProvider
from apps.courses.models import Catalog, Course, CourseResource, PPTResource, TeachingVideo, VideoWatchProgress
from apps.knowledge.models import KnowledgeChunk


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
            # 向量入库走模拟替身：上传测试不依赖真实 embedding 服务
            patch("apps.ai.services.get_provider", return_value=MockProvider()),
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


class CatalogOrderTests(APITestCase):
    """章节列表按「排序号, id」排列（视图曾硬编码 order_by("id") 使排序号失效）。"""

    def setUp(self):
        self.teacher = User.objects.create_user(
            username="order-teacher", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.course = Course.objects.create(name="排序课程", teacher=self.teacher)
        # 创建顺序与期望展示顺序相反，验证排序号而非 id 决定顺序
        self.c_late = Catalog.objects.create(course=self.course, title="变量与常量", order=2)
        self.c_first = Catalog.objects.create(course=self.course, title="概述", order=0)
        self.c_mid = Catalog.objects.create(course=self.course, title="语法", order=1)

    def test_tree_list_ordered_by_order_field(self):
        self.client.force_authenticate(self.teacher)
        res = self.client.get("/api/catalogs/", {"course": self.course.id, "tree": "1"})
        self.assertEqual(res.status_code, 200, res.data)
        titles = [item["title"] for item in res.data["data"]["results"]]
        self.assertEqual(titles, ["概述", "语法", "变量与常量"])

    def test_children_respect_order_field(self):
        self.client.force_authenticate(self.teacher)
        s_late = Catalog.objects.create(
            course=self.course, parent=self.c_first, title="1.2 小节", order=1
        )
        s_early = Catalog.objects.create(
            course=self.course, parent=self.c_first, title="1.1 小节", order=0
        )
        res = self.client.get("/api/catalogs/", {"course": self.course.id, "tree": "1"})
        first = next(item for item in res.data["data"]["results"] if item["id"] == self.c_first.id)
        self.assertEqual([c["title"] for c in first["children"]], ["1.1 小节", "1.2 小节"])


class CourseResourceTests(APITestCase):
    """课程教学资源：思维导图/交互演示（预置页）+ 文档（上传），直接归属课程。"""

    def setUp(self):
        self.teacher = User.objects.create_user(
            username="res-teacher", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.student = User.objects.create_user(
            username="res-student", password="StrongPass!123", role=User.Role.STUDENT
        )
        self.course = Course.objects.create(name="计算机网络", teacher=self.teacher)

    def _create(self, client, **overrides):
        payload = {
            "course": self.course.id,
            "kind": "mindmap",
            "title": "课程思维导图",
            "path": "mindmap/chapter4.html",
        }
        payload.update(overrides)
        return client.post("/api/course-resources/", payload, format="json")

    def test_teacher_create_and_publish(self):
        self.client.force_authenticate(self.teacher)
        res = self._create(self.client)
        self.assertEqual(res.status_code, 201, res.data)
        # 每条资源的链接唯一（按访问令牌），不再是共享的 /resources/ 路径
        self.assertIn("/api/course-resources/page/", res.data["data"]["url"])
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

    def test_duplicate_page_rejected_with_friendly_message(self):
        """同一课程重复添加同一预置页：友好提示，而非唯一约束原始报错。"""
        self.client.force_authenticate(self.teacher)
        res = self._create(self.client)
        self.assertEqual(res.status_code, 201, res.data)
        # 换标题也不行：唯一约束是 (course, path)（path 非空才生效）
        res = self._create(self.client, title="课程思维导图V2")
        self.assertEqual(res.status_code, 400)
        self.assertIn("不能重复添加", res.data["message"])
        self.assertIn("课程思维导图", res.data["message"])
        # 编辑自身（PATCH 同 path）不受影响
        listing = self.client.get(f"/api/course-resources/?course={self.course.id}")
        items = listing.data["data"]
        items = items["results"] if isinstance(items, dict) and "results" in items else items
        res = self.client.patch(
            f"/api/course-resources/{items[0]['id']}/",
            {"title": "课程思维导图改个名"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)

    def test_document_upload_and_sign_file_url(self):
        """文档类：multipart 上传 pdf → 签名拿到 file 地址（非 page）。"""
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_authenticate(self.teacher)
        pdf = SimpleUploadedFile(
            "计算机网络复习大纲.pdf", b"%PDF-1.4 fake", content_type="application/pdf"
        )
        res = self.client.post(
            "/api/course-resources/",
            {"course": self.course.id, "kind": "document", "title": "复习大纲", "file": pdf},
            format="multipart",
        )
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["data"]["file_name"], "计算机网络复习大纲.pdf")
        self.assertEqual(res.data["data"]["file_size"], len(b"%PDF-1.4 fake"))
        # 未发布时教师可签（预览），签出来的是 file 地址
        rid = res.data["data"]["id"]
        res = self.client.post(f"/api/course-resources/{rid}/sign/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIn("/api/course-resources/file/", res.data["data"]["url"])

    def test_document_rejects_bad_ext_and_oversize(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_authenticate(self.teacher)
        bad = SimpleUploadedFile("evil.exe", b"MZ", content_type="application/octet-stream")
        res = self.client.post(
            "/api/course-resources/",
            {"course": self.course.id, "kind": "document", "title": "x", "file": bad},
            format="multipart",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("pdf", res.data["message"])
        # 预置类不允许带文件、文档类必须有文件
        res = self._create(self.client)
        self.assertEqual(res.status_code, 201, res.data)
        res = self.client.post(
            "/api/course-resources/",
            {"course": self.course.id, "kind": "document", "title": "无文件"},
            format="multipart",
        )
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


class CourseResourceGateTests(APITestCase):
    """资源门控：唯一令牌链接 + 签名 URL + 发布状态门控（预置页经 Django 读出）。"""

    def setUp(self):
        self.root_dir = TemporaryDirectory()
        root = Path(self.root_dir.name)
        (root / "mindmap").mkdir(parents=True)
        (root / "demos").mkdir(parents=True)
        (root / "vendor").mkdir(parents=True)
        (root / "mindmap" / "chapter4.html").write_text(
            "<!doctype html><html><head><title>ch4</title>"
            '<link rel="stylesheet" href="../vendor/x.css"></head>'
            '<body><a href="index.html">总览</a></body></html>',
            encoding="utf-8",
        )
        (root / "mindmap" / "index.html").write_text("<html><head></head><body>overview</body></html>", encoding="utf-8")
        (root / "vendor" / "x.css").write_text("body{color:red}", encoding="utf-8")
        self.root_override = override_settings(RESOURCES_ROOT=self.root_dir.name)
        self.root_override.enable()
        self.addCleanup(self.root_override.disable)
        self.addCleanup(self.root_dir.cleanup)

        self.teacher = User.objects.create_user(
            username="gate-teacher", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.student = User.objects.create_user(
            username="gate-student", password="StrongPass!123", role=User.Role.STUDENT
        )
        self.course = Course.objects.create(name="计算机网络", teacher=self.teacher)
        self.resource = CourseResource.objects.create(
            course=self.course, kind="mindmap",
            title="课程思维导图", path="mindmap/chapter4.html",
        )
        from apps.classroom.models import ClassCourse, ClassRoom, ClassStudent

        classroom = ClassRoom.objects.create(name="网络2401", teacher=self.teacher)
        ClassCourse.objects.create(classroom=classroom, course=self.course)
        ClassStudent.objects.create(classroom=classroom, student=self.student)

    def _sign(self, client, rid=None):
        res = client.post(f"/api/course-resources/{rid or self.resource.id}/sign/")
        self.assertEqual(res.status_code, 200, res.data)
        return res.data["data"]

    def _signed_parts(self, url):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        return parsed.path, query["sig"][0], query["exp"][0]

    def test_sign_requires_authentication(self):
        res = self.client.post(f"/api/course-resources/{self.resource.id}/sign/")
        self.assertIn(res.status_code, (401, 403))

    def test_student_cannot_sign_unpublished(self):
        self.client.force_authenticate(self.student)
        res = self.client.post(f"/api/course-resources/{self.resource.id}/sign/")
        self.assertEqual(res.status_code, 404)  # queryset 已过滤未发布

    def test_teacher_signs_own_unpublished_for_preview(self):
        self.client.force_authenticate(self.teacher)
        data = self._sign(self.client)
        self.assertIn(f"/api/course-resources/page/{self.resource.access_token}/", data["url"])

    def test_student_signs_published_and_page_serves_with_base(self):
        self.resource.is_published = True
        self.resource.save(update_fields=["is_published", "updated_at"])
        self.client.force_authenticate(self.student)
        signed = self._sign(self.client)
        path, sig, exp = self._signed_parts(signed["url"])
        # 匿名直接访问入口页（签名即凭证，不依赖 JWT）
        self.client.force_authenticate(None)
        res = self.client.get(f"{path}?sig={sig}&exp={exp}")
        self.assertEqual(res.status_code, 200, res.content[:200])
        self.assertIn("text/html", res["Content-Type"])
        expected_base = f"/api/course-resources/asset/{self.resource.access_token}/{sig}/{exp}/mindmap/"
        self.assertIn(f'<base href="{expected_base}">', res.content.decode())
        # 相对引用的资产（../vendor/x.css → asset/.../vendor/x.css）
        res = self.client.get(f"/api/course-resources/asset/{self.resource.access_token}/{sig}/{exp}/vendor/x.css")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content, b"body{color:red}")
        self.assertIn("text/css", res["Content-Type"])
        # 页内相对导航（index.html → asset/.../mindmap/index.html）
        res = self.client.get(f"/api/course-resources/asset/{self.resource.access_token}/{sig}/{exp}/mindmap/index.html")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"overview", res.content)

    def test_page_rejects_tampered_and_expired_signature(self):
        self.client.force_authenticate(self.teacher)
        signed = self._sign(self.client)
        path, sig, exp = self._signed_parts(signed["url"])
        self.client.force_authenticate(None)
        # 篡改签名
        res = self.client.get(f"{path}?sig={'0' * 64}&exp={exp}")
        self.assertEqual(res.status_code, 403)
        # 过期时间戳
        res = self.client.get(f"{path}?sig={sig}&exp=1")
        self.assertEqual(res.status_code, 403)
        # 缺失签名
        res = self.client.get(path)
        self.assertEqual(res.status_code, 403)
        # 伪造令牌
        res = self.client.get(f"/api/course-resources/page/{uuid.uuid4()}/?sig={sig}&exp={exp}")
        self.assertEqual(res.status_code, 403)

    def test_asset_rejects_traversal(self):
        self.client.force_authenticate(self.teacher)
        signed = self._sign(self.client)
        _, sig, exp = self._signed_parts(signed["url"])
        res = self.client.get(
            f"/api/course-resources/asset/{self.resource.access_token}/{sig}/{exp}/../../db.sqlite3"
        )
        # <path:rest> 会规范化 ..，落到资源根之外 → 404 提示页
        self.assertEqual(res.status_code, 404)

    def test_unpublish_invalidates_signed_link(self):
        # 发布态签发 → 下架后旧签名（签名消息带发布状态）立即失效
        self.resource.is_published = True
        self.resource.save(update_fields=["is_published", "updated_at"])
        self.client.force_authenticate(self.teacher)
        signed = self._sign(self.client)
        path, sig, exp = self._signed_parts(signed["url"])
        self.resource.is_published = False
        self.resource.save(update_fields=["is_published", "updated_at"])
        self.client.force_authenticate(None)
        res = self.client.get(f"{path}?sig={sig}&exp={exp}")
        self.assertEqual(res.status_code, 403)

    def test_preset_sign_teacher_only_and_page_serves(self):
        self.client.force_authenticate(self.student)
        res = self.client.post("/api/course-resources/preset-sign/", {"path": "mindmap/chapter4.html"}, format="json")
        self.assertIn(res.status_code, (403, 404))
        self.client.force_authenticate(self.teacher)
        res = self.client.post("/api/course-resources/preset-sign/", {"path": "mindmap/chapter4.html"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        url = res.data["data"]["url"]
        self.assertIn("/api/course-resources/preset/", url)
        # 非法路径拒签
        res = self.client.post("/api/course-resources/preset-sign/", {"path": "../../etc/passwd"}, format="json")
        self.assertEqual(res.status_code, 400)
        # 预览页与预览资产
        self.client.force_authenticate(None)
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertIn("<base href=", res.content.decode())
        segs = urlparse(url).path.strip("/").split("/")  # course-resources preset {sig} {exp} mindmap chapter4.html
        sig, exp = segs[3], segs[4]
        res = self.client.get(f"/api/course-resources/preset-asset/{sig}/{exp}/vendor/x.css")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content, b"body{color:red}")
        res = self.client.get(f"/api/course-resources/preset-asset/{sig}/{'0' * 64}/vendor/x.css")
        self.assertEqual(res.status_code, 403)


class RegenerateAudioPageTests(APITestCase):
    """单页配音重生成（讲解稿与配音页「重新配音」按钮，POST /videos/{id}/regenerate-audio-page/）。"""

    class _FakeTTS:
        name = "fake-tts"

        def __init__(self):
            self.calls = []

        def tts(self, text, voice="Cherry"):
            self.calls.append(text)
            return f"/media/tts/new-{len(self.calls)}.wav"

    def setUp(self):
        self.teacher = User.objects.create_user(
            username="ra-teacher", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.other = User.objects.create_user(
            username="ra-other", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.course = Course.objects.create(name="计网", teacher=self.teacher)
        self.catalog = Catalog.objects.create(course=self.course, title="第1章 概述")
        self.video = TeachingVideo.objects.create(
            course=self.course,
            catalog=self.catalog,
            scripts=[
                {"page": 1, "script": "第一页讲稿", "audio_url": "/media/tts/old1.wav"},
                {"page": 2, "script": "第二页讲稿"},
                {"page": 3, "script": ""},
            ],
        )
        self.url = f"/api/videos/{self.video.id}/regenerate-audio-page/"

    def test_success_only_target_page_and_status(self):
        fake = self._FakeTTS()
        self.client.force_authenticate(self.teacher)
        with patch("apps.ai.providers.factory.get_provider", return_value=fake):
            res = self.client.post(self.url, {"page": 2}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(fake.calls, ["第二页讲稿"])
        self.video.refresh_from_db()
        scripts = self.video.scripts
        self.assertEqual(scripts[0]["audio_url"], "/media/tts/old1.wav")  # 其他页不受影响
        self.assertEqual(scripts[1]["audio_url"], "/media/tts/new-1.wav")
        # 第 3 页无讲稿不计入分母，1/2 页均有配音 → 与批量配音口径一致，升为 audio_ready
        self.assertEqual(self.video.gen_status, TeachingVideo.GenStatus.AUDIO_READY)

    def test_all_done_upgrades_to_audio_ready(self):
        self.video.scripts = [
            {"page": 1, "script": "第一页讲稿", "audio_url": "/media/tts/old1.wav"},
            {"page": 2, "script": "第二页讲稿"},
        ]
        self.video.gen_status = TeachingVideo.GenStatus.SCRIPT_READY
        self.video.save(update_fields=["scripts", "gen_status"])
        self.client.force_authenticate(self.teacher)
        with patch("apps.ai.providers.factory.get_provider", return_value=self._FakeTTS()):
            res = self.client.post(self.url, {"page": 2}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.video.refresh_from_db()
        self.assertEqual(self.video.gen_status, TeachingVideo.GenStatus.AUDIO_READY)

    def test_page_without_script_rejected(self):
        fake = self._FakeTTS()
        self.client.force_authenticate(self.teacher)
        with patch("apps.ai.providers.factory.get_provider", return_value=fake):
            res = self.client.post(self.url, {"page": 3}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(fake.calls, [])

    def test_mock_provider_rejected(self):
        from apps.ai.providers.mock import MockProvider

        self.client.force_authenticate(self.teacher)
        with patch("apps.ai.providers.factory.get_provider", return_value=MockProvider()):
            res = self.client.post(self.url, {"page": 1}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_row_level_permission(self):
        fake = self._FakeTTS()
        self.client.force_authenticate(self.other)  # 非课程 owner
        with patch("apps.ai.providers.factory.get_provider", return_value=fake):
            res = self.client.post(self.url, {"page": 1}, format="json")
        self.assertIn(res.status_code, (403, 404))
        self.assertEqual(fake.calls, [])


class _FakePptEmbedProvider:
    """课件入库测试用的真实向量服务替身（断言禁用 mock 兜底）。"""

    name = "tongyi"
    embed_model = "text-embedding-v3"

    def __init__(self, dimension=4):
        self.dimension = dimension
        self.calls = []

    def embed(self, texts, *, allow_fallback=True):
        assert allow_fallback is False, "课件入库必须传 allow_fallback=False"
        self.calls.append(list(texts))
        return [[0.5] * self.dimension for _ in texts]


class PptVectorIngestTests(APITestCase):
    """课件上传/重新解析后自动入向量库（每页一个片段）；旧版本片段随之清理。"""

    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.media_override.enable()

        self.teacher = User.objects.create_user(
            username="ppt-vec-teacher", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.course = Course.objects.create(name="Java", teacher=self.teacher)
        self.catalog = Catalog.objects.create(
            course=self.course, title="第一章", is_published=True
        )
        self.old_ppt = PPTResource.objects.create(
            course=self.course,
            catalog=self.catalog,
            file_name="old.pptx",
            file="ppts/old.pptx",
            version=1,
            is_active=True,
            parse_status=PPTResource.ParseStatus.DONE,
            parsed_pages=[{"page": 1, "title": "旧课件", "body": "旧内容"}],
        )
        KnowledgeChunk.objects.create(
            ppt=self.old_ppt,
            course_id=self.course.id,
            content="旧课件\n旧内容",
            page=1,
            embedding=[0.1] * 3,
        )
        self.client.force_authenticate(user=self.teacher)

    def tearDown(self):
        self.media_override.disable()
        self.media_directory.cleanup()

    def _upload(self, parsed_pages):
        upload = SimpleUploadedFile(
            "new.pptx",
            b"test presentation",
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        with (
            patch("apps.courses.ppt_parser.parse_teaching_file_pages", return_value=parsed_pages),
            patch("apps.courses.ppt_parser.render_presentation_slide_images", return_value=[]),
            patch("apps.courses.ppt_parser.attach_slide_images", side_effect=lambda pages, images: pages),
            patch("apps.ai.services.get_provider", return_value=_FakePptEmbedProvider()),
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

    def test_upload_ingests_new_ppt_and_clears_old_version_chunks(self):
        response = self._upload(
            [
                {"page": 1, "title": "新课件", "body": "新内容"},
                {"page": 2, "title": "第二章", "body": "更多内容"},
            ]
        )
        self.assertEqual(response.status_code, 201)
        new_ppt = PPTResource.objects.get(pk=response.data["data"]["id"])

        chunks = list(new_ppt.chunks.order_by("page"))
        self.assertEqual([c.page for c in chunks], [1, 2])
        self.assertEqual(chunks[0].content, "新课件\n新内容")
        self.assertEqual(chunks[0].course_id, self.course.id)
        self.assertEqual(len(chunks[0].embedding), 4)
        # 旧版本课件的片段被清理（避免旧内容参与检索）
        self.assertEqual(self.old_ppt.chunks.count(), 0)

    def test_failed_upload_keeps_old_chunks_and_ingests_nothing(self):
        response = self._upload([])
        self.assertEqual(response.status_code, 201)
        failed_ppt = PPTResource.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(failed_ppt.chunks.count(), 0)
        self.assertEqual(self.old_ppt.chunks.count(), 1)

    def test_upload_without_embed_provider_ingests_nothing(self):
        """未配置向量模型（回退模拟模式）：上传照常成功，只是暂不入库。"""
        upload = SimpleUploadedFile(
            "new.pptx",
            b"test presentation",
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        with (
            patch("apps.courses.ppt_parser.parse_teaching_file_pages",
                  return_value=[{"page": 1, "title": "新课件", "body": "新内容"}]),
            patch("apps.courses.ppt_parser.render_presentation_slide_images", return_value=[]),
            patch("apps.courses.ppt_parser.attach_slide_images", side_effect=lambda pages, images: pages),
            patch("apps.ai.services.get_provider", return_value=MockProvider()),
        ):
            response = self.client.post(
                "/api/ppts/",
                {
                    "course": self.course.id,
                    "catalog": self.catalog.id,
                    "file_name": upload.name,
                    "file": upload,
                },
                format="multipart",
            )
        self.assertEqual(response.status_code, 201)
        new_ppt = PPTResource.objects.get(pk=response.data["data"]["id"])
        # 新课件暂不入库（等配置好向量模型后重建）；旧版本被替换、其片段按设计清理
        self.assertEqual(new_ppt.chunks.count(), 0)
        self.assertEqual(self.old_ppt.chunks.count(), 0)

    def test_reparse_reingests_chunks(self):
        with (
            patch("apps.courses.ppt_parser.parse_teaching_file_pages",
                  return_value=[
                      {"page": 1, "title": "重解析一", "body": "内容一"},
                      {"page": 2, "title": "重解析二", "body": "内容二"},
                  ]),
            patch("apps.courses.ppt_parser.render_presentation_slide_images", return_value=[]),
            patch("apps.courses.ppt_parser.attach_slide_images", side_effect=lambda pages, images: pages),
            patch("apps.ai.services.get_provider", return_value=_FakePptEmbedProvider()),
        ):
            response = self.client.post(f"/api/ppts/{self.old_ppt.id}/reparse/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["chunk_count"], 2)
        chunks = list(self.old_ppt.chunks.order_by("page"))
        self.assertEqual([c.page for c in chunks], [1, 2])
        self.assertEqual(chunks[1].content, "重解析二\n内容二")


class RenderGuardTests(SimpleTestCase):
    """渲染全局锁（_render_guard）：可重复获取/释放，持锁期间阻塞其他连接的写事务。"""

    def test_guard_reacquire_after_release(self):
        from apps.courses.ppt_parser import _render_guard

        with _render_guard():
            pass
        # 释放后可再次获取（无残留、无死锁）
        with _render_guard():
            pass

    def test_guard_blocks_other_connection_while_held(self):
        import sqlite3
        import tempfile
        from pathlib import Path

        from apps.courses.ppt_parser import _RENDER_LOCK_DB_NAME, _render_guard

        with _render_guard():
            other = sqlite3.connect(
                str(Path(tempfile.gettempdir()) / _RENDER_LOCK_DB_NAME), timeout=0.2
            )
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    other.execute("BEGIN IMMEDIATE")
            finally:
                other.close()
