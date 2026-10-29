"""课程复用（P3）单测：资产统计、整份复制、失败回滚、可见性门控。

覆盖规范 §4 P3 的硬要求里最能被测出来的几条：
- 章节层级 / 页图 URL / 音频可播 / access_token 不同 / 片段数一致
- 删源课程后新课程资产完好（真复制而非共享路径）
- 失败回滚不留孤儿文件
- 产物 inactive 学生不可见，置 active 后可见
- 题库可选（不勾选为 0，勾选数量一致且 scenes 正确）
"""

from __future__ import annotations

import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.ai.models import AITask
from apps.classroom.models import ClassRoom, ClassStudent
from apps.common.access import courses_for_user
from apps.courses.models import (
    Catalog,
    Course,
    CourseResource,
    PPTResource,
    TeachingVideo,
    Term,
)
from apps.courses.ppt_parser import ppt_pages_dirname
from apps.courses.reuse import (
    course_asset_stats,
    human_size,
    reuse_course,
    run_course_reuse,
)
from apps.knowledge.models import KnowledgeChunk, Material
from apps.questions.models import Question, SceneTag

User = get_user_model()

PPT_BYTES = b"P" * 4096
PAGE_BYTES = b"I" * 2048
AUDIO_BYTES = b"A" * 8192
SUB_BYTES = b"S" * 512
VIDEO_BYTES = b"V" * 1024
MATERIAL_BYTES = b"M" * 6144
DOC_BYTES = b"D" * 7168
IMAGE_BYTES = b"Q" * 900
COVER_BYTES = b"C" * 300


def put(name: str, body: bytes) -> str:
    """在 storage 里放一份文件（测试不经过上传接口）。"""
    default_storage.delete(name)  # 同测试内重复放同名文件时保持幂等
    return default_storage.save(name, ContentFile(body))


class ReuseTestBase(APITestCase):
    def setUp(self):
        self._media = tempfile.TemporaryDirectory()
        self._override = override_settings(MEDIA_ROOT=self._media.name, MEDIA_URL="/media/")
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.addCleanup(self._media.cleanup)

        self.teacher = User.objects.create_user(
            username="reuse-teacher", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.other_teacher = User.objects.create_user(
            username="reuse-other", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.student = User.objects.create_user(
            username="reuse-student", password="StrongPass!123", role=User.Role.STUDENT
        )
        self.term = Term.objects.create(year=2026, season=Term.Season.AUTUMN, name="2026 秋")
        self.term2 = Term.objects.create(year=2027, season=Term.Season.SPRING, name="2027 春")

        self.practice = SceneTag.objects.get_or_create(code="practice", defaults={"name": "练习"})[0]
        self.exam = SceneTag.objects.get_or_create(code="exam", defaults={"name": "考试"})[0]

        self.course = Course.objects.create(
            name="计算机网络", teacher=self.teacher, term=self.term, intro="复用源课程"
        )

    # ---- 构造一门「什么都有」的课 -------------------------------------
    def build_full_course(self) -> dict:
        cover = put("covers/source.png", COVER_BYTES)
        self.course.cover = f"/media/{cover}"
        self.course.save(update_fields=["cover"])

        chapter = Catalog.objects.create(
            course=self.course, title="第一章 概述", order=1, is_published=True, intro="章简介"
        )
        section = Catalog.objects.create(
            course=self.course, parent=chapter, title="1.1 分层模型", order=2, is_published=True
        )
        chapter2 = Catalog.objects.create(
            course=self.course, title="第二章 物理层", order=3, is_published=False
        )

        ppt_file = put("ppt/source.pptx", PPT_BYTES)
        ppt = PPTResource.objects.create(
            course=self.course,
            catalog=section,
            file_name="分层模型.pptx",
            file=ppt_file,
            parse_status=PPTResource.ParseStatus.DONE,
            version=1,
            is_active=True,
            parsed_pages=[],
        )
        old_dir = ppt_pages_dirname(ppt.id)
        pages = []
        for index in range(1, 4):
            name = put(f"ppt_pages/{old_dir}/slide-{index:03d}.png", PAGE_BYTES)
            pages.append(
                {
                    "page": index,
                    "title": f"第 {index} 页",
                    "body": f"正文 {index}",
                    "image": f"/media/{name}",
                }
            )
        ppt.parsed_pages = pages
        ppt.save(update_fields=["parsed_pages"])

        audio1 = put("tts/audio-1.wav", AUDIO_BYTES)
        sub = put("tts/audio-1.srt", SUB_BYTES)
        video_file = put("videos/source.mp4", VIDEO_BYTES)
        video = TeachingVideo.objects.create(
            course=self.course,
            catalog=section,
            ppt=ppt,
            scripts=[
                {"page": 1, "script": "第一页讲稿", "audio_url": f"/media/{audio1}", "duration": 12},
                # 同一音频被两页引用：复制只应发生一次
                {"page": 2, "script": "第二页讲稿", "audio_url": f"/media/{audio1}", "duration": 12},
                # 外链不该被当成 media 文件
                {"page": 3, "script": "第三页讲稿", "audio_url": "https://cdn.example.com/x.mp3"},
            ],
            audio_url=f"/media/{audio1}",
            subtitle_url=f"/media/{sub}",
            video_url=f"/media/{video_file}",
            gen_status=TeachingVideo.GenStatus.DONE,
            is_published=True,
            published_at=timezone.now(),
        )

        klass = ClassRoom.objects.create(name="复用测试班", teacher=self.teacher, code="REUSE01")
        material_file = put("materials/source.pdf", MATERIAL_BYTES)
        material = Material.objects.create(
            course=self.course,
            classroom=klass,  # 班级专属资料：复用后应置空
            catalog=chapter,
            file_name="讲义.pdf",
            file_type="pdf",
            file=material_file,
            parse_status=Material.ParseStatus.DONE,
            qa_open=False,
        )

        chunks = [
            KnowledgeChunk.objects.create(
                source=KnowledgeChunk.Source.MATERIAL,
                material=material,
                course=self.course,
                catalog=chapter,
                content="教辅片段",
                page=1,
                embedding=[0.1, 0.2, 0.3],
            ),
            KnowledgeChunk.objects.create(
                source=KnowledgeChunk.Source.PPT,
                ppt=ppt,
                course=self.course,
                catalog=section,
                content="课件片段",
                page=2,
                embedding=[0.4, 0.5, 0.6],
            ),
            KnowledgeChunk.objects.create(
                source=KnowledgeChunk.Source.SCRIPT,
                video=video,
                course=self.course,
                catalog=section,
                content="讲稿片段",
                page=3,
                embedding=[0.7, 0.8, 0.9],
            ),
        ]

        CourseResource.objects.create(
            course=self.course,
            kind=CourseResource.Kind.MINDMAP,
            title="知识导图",
            path="mindmap/chapter1.html",
            is_published=True,
            order=1,
            intro="预置静态页",
        )
        doc_name = put("course_resources/source.pdf", DOC_BYTES)
        doc = CourseResource.objects.create(
            course=self.course,
            kind=CourseResource.Kind.DOCUMENT,
            title="实验手册",
            file=doc_name,
            file_name="实验手册.pdf",
            file_size=len(DOC_BYTES),
            is_published=True,
            order=2,
        )

        image = put("question_images/q1.png", IMAGE_BYTES)
        question = Question.objects.create(
            course=self.course,
            catalog=chapter,
            qtype=Question.QType.SINGLE,
            stem="OSI 有几层？",
            image=image,
            options=[{"key": "A", "text": "7"}, {"key": "B", "text": "5"}],
            answer={"value": "A"},
            analysis="七层模型",
            score=5,
            knowledge_tags=["OSI"],
            status=Question.Status.PUBLISHED,
            creator=self.teacher,
        )
        question.scenes.set([self.practice, self.exam])

        return {
            "chapter": chapter,
            "section": section,
            "chapter2": chapter2,
            "ppt": ppt,
            "video": video,
            "material": material,
            "chunks": chunks,
            "doc": doc,
            "question": question,
            "klass": klass,
            "audio_file": audio1,
            "image_file": image,
        }


class AssetStatsTests(ReuseTestBase):
    def test_stats_count_every_asset(self):
        built = self.build_full_course()
        stats = course_asset_stats(self.course)

        self.assertEqual(stats.catalog_count, 3)
        self.assertEqual(stats.catalog_depth, 2)
        self.assertEqual(stats.ppt_count, 1)
        self.assertEqual(stats.ppt_pages, 3)
        self.assertEqual(stats.video_count, 1)
        self.assertEqual(stats.script_pages, 3)
        # 3 页讲稿里只有 1 个独立音频文件（另 1 个外链不计）
        self.assertEqual(stats.audio_count, 1)
        self.assertEqual(stats.material_count, 1)
        self.assertEqual(stats.chunk_count, 3)
        self.assertEqual(stats.resource_count, 2)
        self.assertEqual(stats.resource_document_count, 1)
        self.assertEqual(stats.question_count, 1)
        self.assertEqual(built["ppt"].id, PPTResource.objects.get(course=self.course).id)

        expected = (
            len(PPT_BYTES)
            + 3 * len(PAGE_BYTES)
            + len(AUDIO_BYTES)
            + len(SUB_BYTES)
            + len(VIDEO_BYTES)
            + len(MATERIAL_BYTES)
            + len(DOC_BYTES)
            + len(COVER_BYTES)
        )  # 封面是 CharField，/media/ 形式时复用会真复制，故计入体积
        self.assertEqual(stats.media_bytes, expected)
        self.assertEqual(stats.question_media_bytes, len(IMAGE_BYTES))
        payload = stats.as_dict()
        self.assertEqual(payload["sections"], {
            "catalog": 3, "ppt": 1, "video": 1, "material": 1,
            "chunk": 3, "resource": 2, "question": 1,
        })
        self.assertTrue(payload["media_human"].endswith("KB"))
        self.assertEqual(payload["media_human"], "32.8 KB")

    def test_missing_file_does_not_break_stats(self):
        """文件被外部删掉时统计不能炸（体积算 0）。"""
        self.build_full_course()
        default_storage.delete("materials/source.pdf")
        stats = course_asset_stats(self.course)
        self.assertEqual(stats.material_count, 1)
        self.assertGreater(stats.media_bytes, 0)

    def test_human_size_units(self):
        self.assertEqual(human_size(0), "0 B")
        self.assertEqual(human_size(999), "999 B")
        self.assertEqual(human_size(2048), "2.0 KB")
        self.assertEqual(human_size(5 * 1024 * 1024), "5.0 MB")
        self.assertEqual(human_size(3 * 1024 ** 3), "3.0 GB")


class CourseCopyTests(ReuseTestBase):
    def test_course_created_inactive_with_copied_tree(self):
        built = self.build_full_course()
        result = reuse_course(self.course, teacher=self.teacher, name="复用后的课", term_id=self.term2.id)

        new = result.course
        self.assertEqual(new.name, "复用后的课")
        self.assertEqual(new.term_id, self.term2.id)
        self.assertEqual(new.teacher_id, self.teacher.id)
        self.assertEqual(new.status, Course.Status.INACTIVE)
        self.assertEqual(new.intro, self.course.intro)

        # 章节层级：3 个都在，父子关系跟着走
        chapters = {c.title: c for c in Catalog.objects.filter(course=new)}
        self.assertEqual(len(chapters), 3)
        self.assertIsNone(chapters["第一章 概述"].parent_id)
        self.assertEqual(chapters["1.1 分层模型"].parent_id, chapters["第一章 概述"].id)
        self.assertFalse(chapters["第二章 物理层"].is_published)
        self.assertEqual(result.copied["catalog"], 3)

        # 课件：新行、新 id、页图目录按新 id 派生
        new_ppt = PPTResource.objects.get(course=new)
        self.assertNotEqual(new_ppt.id, built["ppt"].id)
        self.assertEqual(new_ppt.catalog_id, chapters["1.1 分层模型"].id)
        self.assertEqual(len(new_ppt.parsed_pages), 3)
        new_dir = ppt_pages_dirname(new_ppt.id)
        self.assertNotEqual(new_dir, ppt_pages_dirname(built["ppt"].id))
        for index, page in enumerate(new_ppt.parsed_pages, start=1):
            self.assertIn(f"/media/ppt_pages/{new_dir}/slide-{index:03d}.png", page["image"])
            self.assertTrue(default_storage.exists(page["image"].replace("/media/", "", 1)))
            self.assertEqual(page["title"], f"第 {index} 页")
        self.assertTrue(default_storage.exists(new_ppt.file.name))
        self.assertNotEqual(new_ppt.file.name, built["ppt"].file.name)

        # 讲稿：scripts 深拷贝，音频重写且外链原样保留
        new_video = TeachingVideo.objects.get(course=new)
        self.assertEqual(new_video.catalog_id, chapters["1.1 分层模型"].id)
        self.assertEqual(new_video.ppt_id, new_ppt.id)
        self.assertEqual(len(new_video.scripts), 3)
        self.assertEqual(new_video.scripts[0]["audio_url"], new_video.scripts[1]["audio_url"])
        self.assertNotEqual(new_video.scripts[0]["audio_url"], f"/media/{built['audio_file']}")
        self.assertTrue(
            default_storage.exists(new_video.scripts[0]["audio_url"].replace("/media/", "", 1))
        )
        self.assertEqual(new_video.scripts[2]["audio_url"], "https://cdn.example.com/x.mp3")
        self.assertEqual(new_video.gen_status, TeachingVideo.GenStatus.DONE)
        self.assertTrue(new_video.is_published)

        # 同一音频只复制一份（去重）：tts/ 下新增的应只有 1 音频 + 1 字幕
        new_tts = [n for n in _list_media("tts")
                   if n not in (built["audio_file"], "tts/audio-1.srt")]
        self.assertEqual(len(new_tts), 2)
        self.assertEqual(len([n for n in new_tts if n.endswith(".wav")]), 1)
        self.assertEqual(len([n for n in new_tts if n.endswith(".srt")]), 1)

        # 资料：班级归属清空
        new_material = Material.objects.get(course=new)
        self.assertIsNone(new_material.classroom_id)
        self.assertEqual(new_material.catalog_id, chapters["第一章 概述"].id)
        self.assertFalse(new_material.qa_open)
        self.assertTrue(default_storage.exists(new_material.file.name))

        # 片段：数量一致、向量原样、外键指到新资产
        self.assertEqual(KnowledgeChunk.objects.filter(course=new).count(), 3)
        new_chunks = list(KnowledgeChunk.objects.filter(course=new).order_by("source"))
        self.assertEqual(result.copied["chunk"], 3)
        by_source = {c.source: c for c in new_chunks}
        self.assertEqual(by_source[KnowledgeChunk.Source.MATERIAL].embedding, [0.1, 0.2, 0.3])
        self.assertEqual(by_source[KnowledgeChunk.Source.MATERIAL].material_id, new_material.id)
        self.assertEqual(by_source[KnowledgeChunk.Source.PPT].ppt_id, new_ppt.id)
        self.assertEqual(by_source[KnowledgeChunk.Source.SCRIPT].video_id, new_video.id)
        self.assertEqual(by_source[KnowledgeChunk.Source.PPT].catalog_id, chapters["1.1 分层模型"].id)

        # 资源：access_token 天然新；预置 path 保持共享；文档文件真复制
        new_resources = {r.title: r for r in CourseResource.objects.filter(course=new)}
        self.assertEqual(len(new_resources), 2)
        self.assertEqual(new_resources["知识导图"].path, "mindmap/chapter1.html")
        self.assertNotEqual(
            new_resources["知识导图"].access_token,
            CourseResource.objects.get(course=self.course, kind=CourseResource.Kind.MINDMAP).access_token,
        )
        self.assertNotEqual(new_resources["实验手册"].file.name, built["doc"].file.name)
        self.assertTrue(default_storage.exists(new_resources["实验手册"].file.name))

        # 封面复制
        self.assertNotEqual(new.cover, self.course.cover)
        self.assertTrue(default_storage.exists(new.cover.replace("/media/", "", 1)))

        # 默认不带题目
        self.assertEqual(result.copied["question"], 0)
        self.assertEqual(Question.objects.filter(course=new).count(), 0)

    def test_questions_optional_copy_keeps_scenes(self):
        built = self.build_full_course()
        result = reuse_course(
            self.course, teacher=self.teacher, include_questions=True
        )
        questions = list(Question.objects.filter(course=result.course))
        self.assertEqual(len(questions), 1)
        self.assertEqual(result.copied["question"], 1)
        copied = questions[0]
        self.assertNotEqual(copied.id, built["question"].id)
        self.assertEqual(copied.catalog_id, Catalog.objects.get(
            course=result.course, title="第一章 概述").id)
        self.assertEqual(copied.creator_id, self.teacher.id)
        self.assertEqual(
            sorted(copied.scenes.values_list("code", flat=True)), ["exam", "practice"]
        )
        self.assertEqual(copied.knowledge_tags, ["OSI"])
        self.assertNotEqual(copied.image.name, built["question"].image.name)
        self.assertTrue(default_storage.exists(copied.image.name))

    def test_question_catalog_mapping_uses_new_catalog(self):
        """题目章节必须映射到新课程的章节行，不能指着源课程（否则删源就断）。"""
        self.build_full_course()
        result = reuse_course(self.course, teacher=self.teacher, include_questions=True)
        copied = Question.objects.get(course=result.course)
        self.assertEqual(copied.catalog.course_id, result.course.id)
        self.assertEqual(result.skipped_questions, 0)

    def test_default_name_and_term_inherited(self):
        self.build_full_course()
        result = reuse_course(self.course, teacher=self.teacher)
        self.assertEqual(result.course.name, "计算机网络（复用）")
        self.assertEqual(result.course.term_id, self.term.id)

    def test_media_growth_matches_source_within_tolerance(self):
        self.build_full_course()
        source_bytes = course_asset_stats(self.course).media_bytes
        before = _media_bytes()
        result = reuse_course(self.course, teacher=self.teacher, include_questions=True)
        grown = _media_bytes() - before
        self.assertEqual(result.media_bytes, grown)
        # 规范 P3-5：磁盘增量 ≈ 源 media 体积（允许 ±10%）
        self.assertLessEqual(abs(grown - source_bytes) / source_bytes, 0.10)

    def test_delete_source_keeps_target_intact(self):
        self.build_full_course()
        result = reuse_course(self.course, teacher=self.teacher, include_questions=True)
        new = result.course
        new_ppt = PPTResource.objects.get(course=new)
        images = [p["image"].replace("/media/", "", 1) for p in new_ppt.parsed_pages]
        audio = TeachingVideo.objects.get(course=new).scripts[0]["audio_url"].replace("/media/", "", 1)
        material_file = Material.objects.get(course=new).file.name
        doc_file = CourseResource.objects.get(
            course=new, kind=CourseResource.Kind.DOCUMENT).file.name
        teacher_cover = new.cover.replace("/media/", "", 1)

        self.course.questions.all().delete()  # Question.catalog 是 PROTECT，先清题
        self.course.delete()  # 源课程连带删掉自己的所有文件与行

        self.assertFalse(Course.objects.filter(id=self.course.id).exists())
        for name in images:
            self.assertTrue(default_storage.exists(name), name)
        for name in (audio, material_file, doc_file, teacher_cover):
            self.assertTrue(default_storage.exists(name), name)
        self.assertTrue(PPTResource.objects.filter(course=new).exists())
        self.assertEqual(KnowledgeChunk.objects.filter(course=new).count(), 3)
        self.assertEqual(Question.objects.filter(course=new).count(), 1)
        self.assertEqual(CourseResource.objects.filter(course=new).count(), 2)

    def test_failure_rolls_back_rows_and_files(self):
        self.build_full_course()
        before_files = set(_list_media(""))
        before_courses = Course.objects.count()

        with patch(
            "apps.courses.reuse._copy_resources", side_effect=RuntimeError("模拟复制中断")
        ):
            with self.assertRaises(RuntimeError):
                reuse_course(self.course, teacher=self.teacher, include_questions=True)

        self.assertEqual(Course.objects.count(), before_courses)
        self.assertFalse(Course.objects.filter(name="计算机网络（复用）").exists())
        self.assertEqual(KnowledgeChunk.objects.filter(course=self.course).count(), 3)
        self.assertEqual(set(_list_media("")), before_files)


class VisibilityTests(ReuseTestBase):
    def test_inactive_hidden_from_student_until_activated(self):
        self.build_full_course()
        result = reuse_course(self.course, teacher=self.teacher)
        new = result.course
        klass = ClassRoom.objects.create(name="复用后班级", teacher=self.teacher, code="REUSE02")
        klass.courses.add(new)
        ClassStudent.objects.create(classroom=klass, student=self.student)

        self.assertNotIn(new.id, _visible_ids(self.student))
        new.status = Course.Status.ACTIVE
        new.save(update_fields=["status"])
        self.assertIn(new.id, _visible_ids(self.student))


class ReuseTaskTests(ReuseTestBase):
    def test_run_course_reuse_writes_result_and_progress(self):
        self.build_full_course()
        task = AITask.objects.create(
            task_type=AITask.TaskType.COURSE_REUSE,
            status=AITask.Status.PENDING,
            triggered_by=self.teacher,
            course=self.course,
            progress={"options": {"name": "任务复用课", "term_id": self.term2.id,
                                  "include_questions": True}},
        )
        run_course_reuse(task)
        task.refresh_from_db()

        self.assertEqual(task.status, AITask.Status.SUCCESS)
        self.assertEqual(task.result["course_name"], "任务复用课")
        self.assertEqual(task.result["source_course_id"], self.course.id)
        self.assertEqual(task.result["copied"]["chunk"], 3)
        self.assertEqual(task.result["skipped_questions"], 0)
        self.assertEqual(task.progress["stage"], "done")
        self.assertGreater(task.result["media_bytes"], 0)
        new = Course.objects.get(id=task.result["course_id"])
        self.assertEqual(new.status, Course.Status.INACTIVE)
        self.assertEqual(new.term_id, self.term2.id)

    def test_run_without_operator_raises(self):
        self.build_full_course()
        task = AITask.objects.create(
            task_type=AITask.TaskType.COURSE_REUSE,
            status=AITask.Status.PENDING,
            course=self.course,
            progress={"options": {}},
        )
        with self.assertRaises(ValueError):
            run_course_reuse(task)
        self.assertEqual(Course.objects.count(), 1)


class ReuseApiTests(ReuseTestBase):
    """接口层：权限、参数校验、并发互斥。任务真正跑不跑由 service 单测覆盖，
    这里 patch 掉 submit_ai_task，只断言"提交了什么参数"。"""

    def setUp(self):
        super().setUp()
        self.build_full_course()
        self.admin = User.objects.create_user(
            username="reuse-admin", password="StrongPass!123", role=User.Role.ADMIN
        )

    def test_preview_returns_assets_and_terms(self):
        self.client.force_authenticate(user=self.teacher)
        resp = self.client.get(f"/api/courses/{self.course.id}/reuse-preview/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["course"]["name"], "计算机网络")
        self.assertEqual(data["course"]["term_name"], "2026 秋")
        self.assertEqual(data["assets"]["catalog_count"], 3)
        self.assertEqual(data["assets"]["ppt_pages"], 3)
        self.assertEqual(data["assets"]["chunk_count"], 3)
        self.assertEqual(data["assets"]["question_count"], 1)
        self.assertEqual(data["default_name"], "计算机网络（复用）")
        self.assertEqual(len(data["terms"]), 2)

    def test_preview_denied_for_other_teacher(self):
        self.client.force_authenticate(user=self.other_teacher)
        resp = self.client.get(f"/api/courses/{self.course.id}/reuse-preview/")
        # 课程列表按 courses_for_user 过滤，别人的课直接不存在
        self.assertEqual(resp.status_code, 404)

    def test_preview_denied_for_admin(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(f"/api/courses/{self.course.id}/reuse-preview/")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("课程创建者", resp.json()["message"])

    def test_preview_denied_for_student(self):
        self.client.force_authenticate(user=self.student)
        resp = self.client.get(f"/api/courses/{self.course.id}/reuse-preview/")
        self.assertEqual(resp.status_code, 404)

    def test_reuse_submits_task_with_options(self):
        self.client.force_authenticate(user=self.teacher)
        with patch("apps.courses.views.submit_ai_task") as submit:
            submit.return_value = AITask(id=99, status=AITask.Status.PENDING)
            resp = self.client.post(
                f"/api/courses/{self.course.id}/reuse/",
                {"name": "新学期的课", "term_id": self.term2.id, "include_questions": True},
                format="json",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"], {"task_id": 99, "status": AITask.Status.PENDING})
        args, kwargs = submit.call_args
        self.assertEqual(args[0], AITask.TaskType.COURSE_REUSE)
        self.assertEqual(kwargs["course"], self.course)
        self.assertEqual(kwargs["user"], self.teacher)
        self.assertEqual(kwargs["progress"]["options"], {
            "name": "新学期的课", "term_id": self.term2.id, "include_questions": True,
        })
        self.assertEqual(kwargs["progress"]["stage"], "pending")

    def test_reuse_defaults_name_and_term(self):
        self.client.force_authenticate(user=self.teacher)
        with patch("apps.courses.views.submit_ai_task") as submit:
            submit.return_value = AITask(id=100, status=AITask.Status.PENDING)
            self.client.post(f"/api/courses/{self.course.id}/reuse/", {}, format="json")
        options = submit.call_args.kwargs["progress"]["options"]
        self.assertEqual(options["name"], "计算机网络（复用）")
        self.assertEqual(options["term_id"], self.term.id)
        self.assertFalse(options["include_questions"])

    def test_reuse_rejects_bad_term(self):
        self.client.force_authenticate(user=self.teacher)
        with patch("apps.courses.views.submit_ai_task") as submit:
            bad_type = self.client.post(
                f"/api/courses/{self.course.id}/reuse/", {"term_id": "abc"}, format="json")
            missing = self.client.post(
                f"/api/courses/{self.course.id}/reuse/", {"term_id": 99999}, format="json")
        self.assertEqual(bad_type.status_code, 400)
        self.assertIn("学期参数", bad_type.json()["message"])
        self.assertEqual(missing.status_code, 400)
        self.assertIn("学期不存在", missing.json()["message"])
        submit.assert_not_called()

    def test_reuse_rejects_long_name(self):
        self.client.force_authenticate(user=self.teacher)
        resp = self.client.post(
            f"/api/courses/{self.course.id}/reuse/", {"name": "长" * 201}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("200", resp.json()["message"])

    def test_reuse_conflicts_with_running_task(self):
        self.client.force_authenticate(user=self.teacher)
        running = AITask.objects.create(
            task_type=AITask.TaskType.COURSE_REUSE,
            status=AITask.Status.RUNNING,
            triggered_by=self.teacher,
            course=self.course,
            progress={"options": {}},
        )
        with patch("apps.courses.views.submit_ai_task") as submit:
            resp = self.client.post(f"/api/courses/{self.course.id}/reuse/", {}, format="json")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["data"]["task_id"], running.id)
        submit.assert_not_called()

    def test_reuse_allowed_again_after_previous_succeeded(self):
        self.client.force_authenticate(user=self.teacher)
        AITask.objects.create(
            task_type=AITask.TaskType.COURSE_REUSE,
            status=AITask.Status.SUCCESS,
            triggered_by=self.teacher,
            course=self.course,
            progress={"options": {}},
        )
        with patch("apps.courses.views.submit_ai_task") as submit:
            submit.return_value = AITask(id=101, status=AITask.Status.PENDING)
            resp = self.client.post(f"/api/courses/{self.course.id}/reuse/", {}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(submit.call_count, 1)

    def test_reuse_rejects_empty_course(self):
        empty = Course.objects.create(name="空课程", teacher=self.teacher)
        self.client.force_authenticate(user=self.teacher)
        resp = self.client.post(f"/api/courses/{empty.id}/reuse/", {}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("可复用的资产", resp.json()["message"])


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _list_media(sub: str) -> list[str]:
    from pathlib import Path as _Path

    from django.conf import settings

    root = _Path(settings.MEDIA_ROOT) / sub if sub else _Path(settings.MEDIA_ROOT)
    if not root.exists():
        return []
    return sorted(str(p.relative_to(settings.MEDIA_ROOT)).replace("\\", "/")
                  for p in root.rglob("*") if p.is_file())


def _media_bytes() -> int:
    from pathlib import Path as _Path

    from django.conf import settings

    return sum(p.stat().st_size for p in _Path(settings.MEDIA_ROOT).rglob("*") if p.is_file())


def _visible_ids(user) -> set[int]:
    return set(courses_for_user(user).values_list("id", flat=True))
