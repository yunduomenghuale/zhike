"""知识库向量重建（rebuild_vectors）测试。

重点覆盖出错处理方案：
- 模拟模式 / 模型不可用：事前校验失败即止，不动任何数据；
- 数量/维度不一致：该项失败，旧向量保留；
- 单项失败可续跑，不影响其他项；
- 写入异常（bulk_create 抛错）：事务回滚，旧片段原样保留；
- 全链路 allow_fallback=False（fake provider 内断言）。

覆盖范围同时包含教辅资料与课件 PPT（课件每页一个片段，是向量库主要内容）。
"""
from unittest.mock import patch
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.ai.models import AICapabilityConfig
from apps.ai.providers.mock import MockProvider
from apps.knowledge.models import KnowledgeChunk, Material
from apps.knowledge.services import rebuild_vectors

User = get_user_model()

# 事前校验探针文本（与 services._DIMENSION_PROBE 保持一致）
PROBE = "向量重建维度校验样本"


class _FakeEmbedProvider:
    """真实向量服务替身。

    dimension: 正常向量维度。
    fail_on: {内容关键词: 失败模式}——error=抛异常 / count=少返回一条 / dim=返回错维度。
    probe_error: 非空时试嵌样本直接抛错（模拟模型不可用）。
    """

    name = "tongyi"
    embed_model = "text-embedding-v3"

    def __init__(self, dimension=8, fail_on=None, probe_error=None):
        self.dimension = dimension
        self.fail_on = fail_on or {}
        self.probe_error = probe_error
        self.calls = []

    def embed(self, texts, *, allow_fallback=True):
        # 重建向量必须禁用 mock 兜底：64 维假向量混进真实空间比不重建更糟
        assert allow_fallback is False, "rebuild_vectors 必须传 allow_fallback=False"
        self.calls.append(list(texts))
        if self.probe_error is not None:
            raise self.probe_error
        mode = next((m for kw, m in self.fail_on.items() if any(kw in t for t in texts)), None)
        if mode == "error":
            raise RuntimeError("embed 服务 503 Service Unavailable")
        vectors = [[1.0] * self.dimension for _ in texts]
        if mode == "count":
            vectors = vectors[:-1]
        elif mode == "dim":
            vectors = [[1.0] * (self.dimension + 4) for _ in texts]
        return vectors


class RebuildVectorsTests(TestCase):
    def setUp(self):
        from apps.courses.models import Course

        self.teacher = User.objects.create_user(
            username="t_kb", password="pw123456!", role=User.Role.TEACHER
        )
        self.course = Course.objects.create(
            name="Java 程序设计", teacher=self.teacher, term="2026-2027-1"
        )
        self.material_a = self._make_material("资料A.txt", "甲" * 1200)  # 3 个片段（500 字/片）
        self.material_b = self._make_material("资料B.txt", "乙" * 700)   # 2 个片段
        self._seed_old_chunks(self.material_a, count=3, dim=3)
        self._seed_old_chunks(self.material_b, count=2, dim=3)
        self.ppt = self._make_ppt(
            "课件.pptx",
            [
                {"page": 1, "title": "第一章", "body": "Java 简介"},
                {"page": 2, "title": "第二章", "body": "面向对象"},
            ],
        )
        self._seed_ppt_chunks(self.ppt, count=2, dim=3)

    def _make_material(self, file_name, content):
        material = Material.objects.create(
            course=self.course, file_name=file_name, file_type="txt", file=f"materials/{file_name}"
        )
        material._test_text = content  # 供 extract_text 替身返回
        return material

    def _make_ppt(self, file_name, parsed_pages):
        from apps.courses.models import Catalog, PPTResource

        catalog = Catalog.objects.create(course=self.course, title=file_name, is_published=True)
        return PPTResource.objects.create(
            course=self.course,
            catalog=catalog,
            file_name=file_name,
            version=1,
            is_active=True,
            parse_status=PPTResource.ParseStatus.DONE,
            parsed_pages=parsed_pages,
        )

    def _seed_old_chunks(self, material, *, count, dim):
        """旧向量：3 维假维度（模拟换模型前的历史数据）。"""
        KnowledgeChunk.objects.bulk_create(
            [
                KnowledgeChunk(
                    material=material,
                    course_id=material.course_id,
                    content=f"{material.file_name} 旧片段{i}",
                    embedding=[0.1 * (i + 1)] * dim,
                )
                for i in range(count)
            ]
        )

    def _seed_ppt_chunks(self, ppt, *, count, dim):
        KnowledgeChunk.objects.bulk_create(
            [
                KnowledgeChunk(
                    ppt=ppt,
                    course_id=ppt.course_id,
                    content=f"{ppt.file_name} 旧片段{i}",
                    page=i + 1,
                    embedding=[0.1 * (i + 1)] * dim,
                )
                for i in range(count)
            ]
        )

    def _patch_extract(self):
        # extract_text 按文件名返回预置文本（_test_text），避免依赖真实文件
        texts = {
            self.material_a.file_name: self.material_a._test_text,
            self.material_b.file_name: self.material_b._test_text,
        }

        def fake_extract(file_path):
            return texts.get(Path(file_path).name, "")

        return patch("apps.knowledge.extractor.extract_text", side_effect=fake_extract)

    # ---------- 成功路径 ----------

    def test_rebuild_replaces_chunks_and_reports(self):
        provider = _FakeEmbedProvider(dimension=8)
        with patch("apps.ai.providers.factory.get_provider", return_value=provider), self._patch_extract():
            report = rebuild_vectors([self.material_a, self.material_b])

        self.assertEqual(report["error"], "")
        self.assertEqual((report["total"], report["success"]), (2, 2))
        self.assertEqual(report["failed"], [])
        self.assertEqual(report["dimension"], 8)
        self.assertEqual(report["model"], "text-embedding-v3")
        # 片段按 500 字切分：A=3、B=2，旧的全被替换
        self.assertEqual(report["chunks"], 5)
        self.assertEqual(report["materials"], {"total": 2, "success": 2, "failed": []})
        self.assertEqual(self.material_a.chunks.count(), 3)
        self.assertEqual(self.material_b.chunks.count(), 2)
        self.assertEqual(self.material_a.chunks.first().content, "甲" * 500)
        for chunk in KnowledgeChunk.objects.filter(material__isnull=False):
            self.assertEqual(len(chunk.embedding), 8)
        self.material_a.refresh_from_db()
        self.material_b.refresh_from_db()
        self.assertEqual(self.material_a.parse_status, Material.ParseStatus.DONE)
        self.assertEqual(self.material_b.parse_status, Material.ParseStatus.DONE)
        # 探针 + 每资料一次 embed，全部禁用兜底
        self.assertEqual(len(provider.calls), 3)

    def test_rebuild_ppt_pages_replaces_chunks_and_reports(self):
        """课件重建：每页一个片段，页码保留，旧片段替换。"""
        provider = _FakeEmbedProvider(dimension=8)
        with patch("apps.ai.providers.factory.get_provider", return_value=provider):
            report = rebuild_vectors(ppts=[self.ppt])

        self.assertEqual(report["error"], "")
        self.assertEqual(report["ppts"], {"total": 1, "success": 1, "chunks": 2, "failed": []})
        self.assertEqual(report["chunks"], 2)
        chunks = list(self.ppt.chunks.order_by("page"))
        self.assertEqual([c.page for c in chunks], [1, 2])
        self.assertEqual(chunks[0].content, "第一章\nJava 简介")
        self.assertEqual(chunks[0].course_id, self.course.id)
        self.assertEqual(chunks[0].material_id, None)
        for c in chunks:
            self.assertEqual(len(c.embedding), 8)
        # 探针 + 课件一次 embed（两页一批）
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.calls[-1], ["第一章\nJava 简介", "第二章\n面向对象"])

    def test_rebuild_materials_and_ppts_together(self):
        provider = _FakeEmbedProvider(dimension=8)
        with patch("apps.ai.providers.factory.get_provider", return_value=provider), self._patch_extract():
            report = rebuild_vectors([self.material_a, self.material_b], [self.ppt])

        self.assertEqual((report["total"], report["success"]), (3, 3))
        self.assertEqual(report["materials"]["success"], 2)
        self.assertEqual(report["ppts"]["success"], 1)
        self.assertEqual(report["chunks"], 5 + 2)
        self.assertEqual(KnowledgeChunk.objects.filter(material__isnull=False).count(), 5)
        self.assertEqual(KnowledgeChunk.objects.filter(ppt__isnull=False).count(), 2)

    def test_ppt_empty_pages_marks_failed_and_keeps_old(self):
        self.ppt.parsed_pages = []
        self.ppt.save(update_fields=["parsed_pages", "updated_at"])
        provider = _FakeEmbedProvider(dimension=8)
        with patch("apps.ai.providers.factory.get_provider", return_value=provider):
            report = rebuild_vectors(ppts=[self.ppt])

        self.assertEqual(report["success"], 0)
        failed = report["failed"][0]
        self.assertEqual(failed["kind"], "ppt")
        self.assertEqual(failed["ppt_id"], self.ppt.id)
        self.assertIn("没有可入库的页面文本", failed["reason"])
        self.assertEqual(self.ppt.chunks.count(), 2)  # 旧片段保留

    def test_ppt_dimension_mismatch_keeps_old_vectors(self):
        provider = _FakeEmbedProvider(dimension=8, fail_on={"第二章": "dim"})
        with patch("apps.ai.providers.factory.get_provider", return_value=provider):
            report = rebuild_vectors(ppts=[self.ppt])

        self.assertEqual(report["success"], 0)
        self.assertIn("向量维度不一致", report["failed"][0]["reason"])
        self.assertEqual(self.ppt.chunks.count(), 2)
        self.assertEqual(len(self.ppt.chunks.first().embedding), 3)

    def test_ppt_embed_error_continues_and_retry(self):
        provider = _FakeEmbedProvider(dimension=8, fail_on={"第二章": "error"})
        with patch("apps.ai.providers.factory.get_provider", return_value=provider):
            report = rebuild_vectors(ppts=[self.ppt])
        self.assertEqual(report["success"], 0)
        self.assertIn("向量生成失败", report["failed"][0]["reason"])
        self.assertEqual(self.ppt.chunks.count(), 2)  # 旧向量保留

        provider.fail_on = {}
        with patch("apps.ai.providers.factory.get_provider", return_value=provider):
            report = rebuild_vectors(ppts=[self.ppt])
        self.assertEqual((report["total"], report["success"]), (1, 1))
        self.assertEqual(self.ppt.chunks.count(), 2)
        self.assertEqual(len(self.ppt.chunks.first().embedding), 8)

    def test_ppt_write_failure_rolls_back_delete(self):
        provider = _FakeEmbedProvider(dimension=8)
        with patch("apps.ai.providers.factory.get_provider", return_value=provider), patch.object(
            KnowledgeChunk.objects, "bulk_create", side_effect=OSError("disk full")
        ):
            report = rebuild_vectors(ppts=[self.ppt])

        self.assertEqual(report["success"], 0)
        self.assertIn("disk full", report["failed"][0]["reason"])
        self.assertEqual(self.ppt.chunks.count(), 2)  # delete 已回滚
        self.assertEqual(self.ppt.chunks.first().content, "课件.pptx 旧片段0")

    # ---------- 事前校验：失败即止，不动数据 ----------

    def test_mock_provider_rejected_without_touching_data(self):
        with patch("apps.ai.providers.factory.get_provider", return_value=MockProvider()):
            report = rebuild_vectors([self.material_a], [self.ppt])

        self.assertIn("向量模型未配置", report["error"])
        self.assertEqual(report["success"], 0)
        self.assertEqual(self.material_a.chunks.count(), 3)  # 旧向量原样保留
        self.assertEqual(self.ppt.chunks.count(), 2)
        self.assertEqual(self.material_a.chunks.first().content, "资料A.txt 旧片段0")

    def test_probe_failure_aborts_before_any_change(self):
        provider = _FakeEmbedProvider(probe_error=RuntimeError("HTTP 401: Invalid API key"))
        with patch("apps.ai.providers.factory.get_provider", return_value=provider), self._patch_extract():
            report = rebuild_vectors([self.material_a, self.material_b], [self.ppt])

        self.assertIn("向量模型调用失败", report["error"])
        self.assertIn("401", report["error"])
        self.assertEqual(len(provider.calls), 1)  # 只有探针调用，未触及任何资料/课件
        self.assertEqual(KnowledgeChunk.objects.count(), 7)
        self.material_a.refresh_from_db()
        self.assertEqual(self.material_a.parse_status, Material.ParseStatus.PENDING)

    # ---------- 单资料失败：旧向量保留，可续跑 ----------

    def test_dimension_mismatch_keeps_old_vectors(self):
        provider = _FakeEmbedProvider(dimension=8, fail_on={"乙": "dim"})
        with patch("apps.ai.providers.factory.get_provider", return_value=provider), self._patch_extract():
            report = rebuild_vectors([self.material_a, self.material_b])

        self.assertEqual(report["success"], 1)
        self.assertEqual(len(report["failed"]), 1)
        failed = report["failed"][0]
        self.assertEqual(failed["kind"], "material")
        self.assertEqual(failed["material_id"], self.material_b.id)
        self.assertIn("向量维度不一致", failed["reason"])
        # B 旧向量保留（仍是 3 维旧片段）；A 已替换
        self.assertEqual(self.material_b.chunks.count(), 2)
        self.assertEqual(self.material_b.chunks.first().content, "资料B.txt 旧片段0")
        self.assertEqual(len(self.material_b.chunks.first().embedding), 3)
        self.assertEqual(self.material_a.chunks.count(), 3)
        self.assertEqual(len(self.material_a.chunks.first().embedding), 8)

    def test_count_mismatch_keeps_old_vectors(self):
        provider = _FakeEmbedProvider(dimension=8, fail_on={"乙": "count"})
        with patch("apps.ai.providers.factory.get_provider", return_value=provider), self._patch_extract():
            report = rebuild_vectors([self.material_a, self.material_b])

        self.assertEqual(report["success"], 1)
        self.assertIn("向量数量与文本片段不一致", report["failed"][0]["reason"])
        self.assertEqual(self.material_b.chunks.count(), 2)

    def test_embed_error_continues_to_next_material(self):
        provider = _FakeEmbedProvider(dimension=8, fail_on={"乙": "error"})
        with patch("apps.ai.providers.factory.get_provider", return_value=provider), self._patch_extract():
            report = rebuild_vectors([self.material_a, self.material_b])

        self.assertEqual(report["success"], 1)
        self.assertIn("向量生成失败", report["failed"][0]["reason"])
        self.assertIn("503", report["failed"][0]["reason"])

    def test_empty_text_marks_parse_failed(self):
        provider = _FakeEmbedProvider(dimension=8)
        with patch("apps.ai.providers.factory.get_provider", return_value=provider), self._patch_extract(), patch(
            "apps.knowledge.extractor.extract_text", return_value=""
        ):
            report = rebuild_vectors([self.material_a])

        self.assertEqual(report["success"], 0)
        self.assertIn("未能抽取到文本内容", report["failed"][0]["reason"])
        self.material_a.refresh_from_db()
        self.assertEqual(self.material_a.parse_status, Material.ParseStatus.FAILED)
        self.assertEqual(self.material_a.chunks.count(), 3)  # 旧向量保留

    def test_retry_only_failed_material(self):
        """续跑：只对失败资料再次调用即可补齐，不重复劳动。"""
        provider = _FakeEmbedProvider(dimension=8, fail_on={"乙": "error"})
        with patch("apps.ai.providers.factory.get_provider", return_value=provider), self._patch_extract():
            rebuild_vectors([self.material_a, self.material_b])

        provider.fail_on = {}
        with patch("apps.ai.providers.factory.get_provider", return_value=provider), self._patch_extract():
            report = rebuild_vectors([self.material_b])

        self.assertEqual(report["error"], "")
        self.assertEqual((report["total"], report["success"]), (1, 1))
        self.assertEqual(self.material_b.chunks.count(), 2)
        self.assertEqual(len(self.material_b.chunks.first().embedding), 8)

    def test_write_failure_rolls_back_delete(self):
        """防线 2：bulk_create 抛错时事务回滚，旧片段原样保留。"""
        provider = _FakeEmbedProvider(dimension=8)
        with patch("apps.ai.providers.factory.get_provider", return_value=provider), self._patch_extract(), patch.object(
            KnowledgeChunk.objects, "bulk_create", side_effect=OSError("disk full")
        ):
            report = rebuild_vectors([self.material_a])

        self.assertEqual(report["success"], 0)
        self.assertTrue(report["failed"])
        self.assertIn("disk full", report["failed"][0]["reason"])
        self.assertEqual(self.material_a.chunks.count(), 3)  # delete 已回滚
        self.assertEqual(self.material_a.chunks.first().content, "资料A.txt 旧片段0")

    def test_empty_lists(self):
        report = rebuild_vectors([], [])
        self.assertEqual(report["error"], "没有需要重建的资料或课件")
        self.assertEqual(report["total"], 0)
        self.assertEqual(report["ppts"]["total"], 0)


class RebuildVectorsAPITests(TestCase):
    """教师端 POST /api/materials/rebuild-vectors/ 的权限与参数校验。"""

    def setUp(self):
        from apps.courses.models import Catalog, Course, PPTResource

        self.teacher = User.objects.create_user(
            username="t_kb2", password="pw123456!", role=User.Role.TEACHER
        )
        self.other_teacher = User.objects.create_user(
            username="t_kb3", password="pw123456!", role=User.Role.TEACHER
        )
        self.course = Course.objects.create(name="数据结构", teacher=self.teacher)
        self.other_course = Course.objects.create(name="操作系统", teacher=self.other_teacher)
        self.catalog = Catalog.objects.create(
            course=self.course, title="第一章", is_published=True
        )
        self.material = Material.objects.create(
            course=self.course, file_name="a.txt", file_type="txt", file="materials/a.txt"
        )
        self.ppt = PPTResource.objects.create(
            course=self.course,
            catalog=self.catalog,
            file_name="a.pptx",
            version=1,
            is_active=True,
            parse_status=PPTResource.ParseStatus.DONE,
            parsed_pages=[{"page": 1, "title": "标题", "body": "正文"}],
        )
        # 旧版本课件：不在重建范围内（is_active=False）
        self.old_ppt = PPTResource.objects.create(
            course=self.course,
            catalog=self.catalog,
            file_name="a-old.pptx",
            version=1,
            is_active=False,
            parse_status=PPTResource.ParseStatus.DONE,
            parsed_pages=[{"page": 1, "title": "旧", "body": "旧文"}],
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.teacher)

    def test_rebuild_own_course(self):
        provider = _FakeEmbedProvider(dimension=8)
        with patch("apps.ai.providers.factory.get_provider", return_value=provider), patch(
            "apps.knowledge.extractor.extract_text", return_value="甲" * 600
        ):
            resp = self.client.post(
                "/api/materials/rebuild-vectors/", {"course": self.course.id}, format="json"
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.data["data"]
        self.assertEqual(data["materials"]["success"], 1)
        self.assertEqual(data["ppts"]["success"], 1)
        self.assertEqual(data["chunks"], 2 + 1)
        self.assertEqual(self.material.chunks.count(), 2)
        self.assertEqual(self.ppt.chunks.count(), 1)
        self.assertEqual(self.ppt.chunks.first().page, 1)
        # 旧版本课件不在范围内，无片段
        self.assertEqual(self.old_ppt.chunks.count(), 0)

    def test_rebuild_single_ppt(self):
        provider = _FakeEmbedProvider(dimension=8)
        with patch("apps.ai.providers.factory.get_provider", return_value=provider):
            resp = self.client.post(
                "/api/materials/rebuild-vectors/", {"ppt": self.ppt.id}, format="json"
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["data"]["ppts"]["success"], 1)
        self.assertEqual(self.ppt.chunks.count(), 1)
        self.assertEqual(self.material.chunks.count(), 0)

    def test_rebuild_ppt_of_other_teacher_forbidden(self):
        """行级过滤：不能重建其他教师课程的课件。"""
        from apps.courses.models import Catalog, PPTResource

        other_ppt = PPTResource.objects.create(
            course=self.other_course,
            catalog=Catalog.objects.create(course=self.other_course, title="第一章"),
            file_name="b.pptx",
            version=1,
            is_active=True,
            parse_status=PPTResource.ParseStatus.DONE,
            parsed_pages=[{"page": 1, "title": "x", "body": "y"}],
        )
        resp = self.client.post(
            "/api/materials/rebuild-vectors/", {"ppt": other_ppt.id}, format="json"
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(other_ppt.chunks.count(), 0)

    def test_rebuild_other_teachers_course_forbidden(self):
        """行级过滤：不能重建其他教师课程的资料（queryset 过滤后按空处理）。"""
        resp = self.client.post(
            "/api/materials/rebuild-vectors/", {"course": self.other_course.id}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("没有需要重建的资料或课件", resp.data["message"])

    def test_rebuild_without_course_rejected(self):
        resp = self.client.post("/api/materials/rebuild-vectors/", {}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_rebuild_mock_provider_returns_error(self):
        with patch("apps.ai.providers.factory.get_provider", return_value=MockProvider()):
            resp = self.client.post(
                "/api/materials/rebuild-vectors/", {"course": self.course.id}, format="json"
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("向量模型未配置", resp.data["message"])
        self.assertEqual(self.material.chunks.count(), 0)
        self.assertEqual(self.ppt.chunks.count(), 0)

    def test_student_forbidden(self):
        student = User.objects.create_user(
            username="s_kb", password="pw123456!", role=User.Role.STUDENT
        )
        client = APIClient()
        client.force_authenticate(user=student)
        resp = client.post(
            "/api/materials/rebuild-vectors/", {"course": self.course.id}, format="json"
        )
        self.assertEqual(resp.status_code, 403)


class QaVisionCapabilityTests(TestCase):
    """GET /api/qa-records/vision-capability/：按对话配置返回图片支持标志。

    学生/教师端问答据此决定是否显示图片上传入口；接口只暴露布尔值，不泄露配置与密钥。
    """

    def setUp(self):
        self.client = APIClient()

    def _chat_row(self, supports_vision):
        AICapabilityConfig.objects.create(
            capability="chat",
            provider="tongyi",
            enabled=True,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_name="qwen3.7-plus",
            supports_vision=supports_vision,
        )

    def test_flag_off_returns_false(self):
        self._chat_row(supports_vision=False)
        student = User.objects.create_user(
            username="s_vision_off", password="pw123456!", role=User.Role.STUDENT
        )
        self.client.force_authenticate(user=student)
        resp = self.client.get("/api/qa-records/vision-capability/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["data"]["supports_vision"])

    def test_flag_on_returns_true(self):
        self._chat_row(supports_vision=True)
        teacher = User.objects.create_user(
            username="t_vision_on", password="pw123456!", role=User.Role.TEACHER
        )
        self.client.force_authenticate(user=teacher)
        resp = self.client.get("/api/qa-records/vision-capability/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["data"]["supports_vision"])

    def test_anonymous_unauthorized(self):
        resp = self.client.get("/api/qa-records/vision-capability/")
        self.assertEqual(resp.status_code, 401)
