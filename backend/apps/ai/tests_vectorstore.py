"""向量后端（json / qdrant）测试。

覆盖四类必须守住的东西：

1. **过滤语义**：章节候选池、学生按来源可见性、is_active、讲稿回滚开关——
   这些是「学生能不能看到不该看的内容」的边界，json 侧逐条断言；
2. **双端等价**：同样过滤下，json 与 qdrant 的 top-k 必须一致（用 qdrant-client
   本地文件模式跑真实过滤，不需要起容器）；
3. **降级**：Qdrant 连不上 / 集合没回填时回落 json 并打标；
4. **同步与回填**：新增/更新片段双写、删除同步、回填幂等与断点续跑。
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import TestCase, override_settings

from apps.ai.vector_backends import ChunkFilter, get_json_backend
from apps.ai.vectorstore import (
    consume_vector_meta,
    search_chunks,
    vector_meta,
)
from apps.classroom.models import ClassRoom
from apps.courses.models import Catalog, Course, PPTResource, TeachingVideo
from apps.knowledge.models import KnowledgeChunk, Material
from apps.users.models import User

try:  # qdrant-client 是运行依赖，缺失时相关用例自动跳过（不带崩整个套件）
    import qdrant_client  # noqa: F401

    HAS_QDRANT = True
except Exception:  # noqa: BLE001
    HAS_QDRANT = False

DIM = 8


def _vec(seed: int) -> list[float]:
    """确定性小向量（dim=8）：顺序稳定，便于对齐两套后端的排名。"""
    return [round(((seed * (i + 3)) % 11) / 11 + 0.05, 4) for i in range(DIM)]


class GraphMixin:
    """构造一棵覆盖所有过滤分支的课程图。

    8 个片段（含 1 个旧版本课件片段被全局排除）：

    ======================================  ========  ==========  =========
    片段                                     章节       学生可见     说明
    ======================================  ========  ==========  =========
    mat_general（资料，未挂章节，qa_open）      -          ✓        章节池兜底
    mat_ch1（资料，ch1，qa_open，无班级）       ch1        ✓
    mat_closed（资料，ch1，qa_open=False）      ch1        ✗        QA 关闭
    mat_classroom（资料，ch1，定向班级1）        ch1       ✓(带班级)
    ppt_active（ch1 当前版本课件）              ch1        ✓
    ppt_inactive（ch1 旧版本课件）              ch1        ✗        全局排除
    ppt_ch2_unpub（ch2 课件，章节未发布）        ch2        ✗
    video_pub（ch1 视频已发布 + 讲稿）          ch1        ✓
    video_unpub（ch2 视频未发布 + 讲稿）        ch2        ✗
    ======================================  ========  ==========  =========
    """

    def build_graph(self):
        self.teacher = User.objects.create_user(
            username="vec-teacher", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.course = Course.objects.create(name="向量测试课", teacher=self.teacher)
        self.other_course = Course.objects.create(name="别的课", teacher=self.teacher)
        self.ch1 = Catalog.objects.create(
            course=self.course, title="第1章", order=1, is_published=True
        )
        self.ch2 = Catalog.objects.create(
            course=self.course, title="第2章", order=2, is_published=False
        )
        self.classroom = ClassRoom.objects.create(name="班级1", code="B1")

        self.mat_general = Material.objects.create(
            course=self.course, file_name="教材.pdf", file_type="pdf", qa_open=True
        )
        self.mat_ch1 = Material.objects.create(
            course=self.course, catalog=self.ch1, file_name="讲义.docx", file_type="docx", qa_open=True
        )
        self.mat_closed = Material.objects.create(
            course=self.course, catalog=self.ch1, file_name="内部.pdf", file_type="pdf", qa_open=False
        )
        self.mat_classroom = Material.objects.create(
            course=self.course,
            catalog=self.ch1,
            classroom=self.classroom,
            file_name="1班专属.pdf",
            file_type="pdf",
            qa_open=True,
        )
        self.ppt_active = PPTResource.objects.create(
            course=self.course, catalog=self.ch1, file_name="ch1.pptx", version=2, is_active=True
        )
        self.ppt_inactive = PPTResource.objects.create(
            course=self.course, catalog=self.ch1, file_name="ch1.pptx", version=1, is_active=False
        )
        self.ppt_ch2 = PPTResource.objects.create(
            course=self.course, catalog=self.ch2, file_name="ch2.pptx", version=1, is_active=True
        )
        self.video_pub = TeachingVideo.objects.create(
            course=self.course,
            catalog=self.ch1,
            ppt=self.ppt_active,
            is_published=True,
            scripts=[{"page": 1, "script": "已发布讲稿"}],
        )
        self.video_unpub = TeachingVideo.objects.create(
            course=self.course,
            catalog=self.ch2,
            ppt=self.ppt_ch2,
            is_published=False,
            scripts=[{"page": 1, "script": "未发布讲稿"}],
        )

        def mk(seed, **kwargs):
            return KnowledgeChunk.objects.create(content=f"片段{seed}", embedding=_vec(seed), **kwargs)

        self.chunk_general = mk(1, source="material", material=self.mat_general,
                                course=self.course, catalog=None)
        self.chunk_ch1 = mk(2, source="material", material=self.mat_ch1,
                            course=self.course, catalog=self.ch1)
        self.chunk_closed = mk(3, source="material", material=self.mat_closed,
                               course=self.course, catalog=self.ch1)
        self.chunk_classroom = mk(4, source="material", material=self.mat_classroom,
                                  course=self.course, catalog=self.ch1)
        self.chunk_ppt = mk(5, source="ppt", ppt=self.ppt_active,
                            course=self.course, catalog=self.ch1, page=1)
        self.chunk_ppt_old = mk(6, source="ppt", ppt=self.ppt_inactive,
                                course=self.course, catalog=self.ch1, page=1)
        self.chunk_ppt_ch2 = mk(7, source="ppt", ppt=self.ppt_ch2,
                                course=self.course, catalog=self.ch2, page=1)
        self.chunk_script = mk(8, source="script", video=self.video_pub,
                               course=self.course, catalog=self.ch1, page=1)
        self.chunk_script_unpub = mk(9, source="script", video=self.video_unpub,
                                     course=self.course, catalog=self.ch2, page=1)
        # 另一门课的片段：验证课程边界
        self.other_chunk = KnowledgeChunk.objects.create(
            content="别的课片段", source="material", course=self.other_course, embedding=_vec(10)
        )

    # 各场景的期望 id 集合（json 后端是语义基准）
    def expected_ids(self):
        return {
            "all": {self.chunk_general.id, self.chunk_ch1.id, self.chunk_closed.id,
                    self.chunk_classroom.id, self.chunk_ppt.id, self.chunk_ppt_ch2.id,
                    self.chunk_script.id, self.chunk_script_unpub.id},
            "chapter_ch1": {self.chunk_general.id, self.chunk_ch1.id, self.chunk_closed.id,
                            self.chunk_classroom.id, self.chunk_ppt.id, self.chunk_script.id},
            "student_with_class": {self.chunk_general.id, self.chunk_ch1.id,
                                   self.chunk_classroom.id, self.chunk_ppt.id,
                                   self.chunk_script.id},
            "student_no_class": {self.chunk_general.id, self.chunk_ch1.id,
                                 self.chunk_ppt.id, self.chunk_script.id},
            "no_script": {self.chunk_general.id, self.chunk_ch1.id, self.chunk_closed.id,
                          self.chunk_classroom.id, self.chunk_ppt.id, self.chunk_ppt_ch2.id},
        }


class ChunkFilterTests(TestCase):
    def test_build_normalizes_classroom_ids(self):
        flt = ChunkFilter.build(7, classroom_ids=["3", "", None, 3, 0, 5])
        self.assertEqual(flt.classroom_ids, (3, 5))
        self.assertFalse(flt.student_access)

    def test_build_respects_script_switch(self):
        with override_settings(AI_QA_DISABLE_SCRIPT_SOURCE=True):
            self.assertFalse(ChunkFilter.build(1).include_script)
        with override_settings(AI_QA_DISABLE_SCRIPT_SOURCE=False):
            self.assertTrue(ChunkFilter.build(1).include_script)

    def test_build_catalog_zero_means_no_chapter(self):
        self.assertIsNone(ChunkFilter.build(1, catalog_id=0).catalog_id)
        self.assertEqual(ChunkFilter.build(1, catalog_id="5").catalog_id, 5)


class JsonBackendSemanticsTests(GraphMixin, TestCase):
    """默认后端行为回归：接入 Qdrant 不得改变 json 路径的任何结果。"""

    def setUp(self):
        super().setUp()
        self.build_graph()
        self.query = _vec(3)

    def _ids(self, **kwargs):
        hits = get_json_backend().search(
            ChunkFilter.build(self.course.id, **kwargs), self.query, 20
        )
        return {c.id for c, _ in hits}

    def test_all_chunks_excludes_old_ppt_version(self):
        self.assertEqual(self._ids(), self.expected_ids()["all"])

    def test_chapter_pool_includes_unfiled_material(self):
        self.assertEqual(self._ids(catalog_id=self.ch1.id), self.expected_ids()["chapter_ch1"])

    def test_student_visibility_with_classroom(self):
        self.assertEqual(
            self._ids(student_access=True, classroom_ids=[self.classroom.id]),
            self.expected_ids()["student_with_class"],
        )

    def test_student_visibility_without_classroom(self):
        self.assertEqual(
            self._ids(student_access=True), self.expected_ids()["student_no_class"]
        )

    def test_script_switch_excludes_scripts(self):
        with override_settings(AI_QA_DISABLE_SCRIPT_SOURCE=True):
            self.assertEqual(self._ids(), self.expected_ids()["no_script"])

    def test_other_course_never_leaks(self):
        self.assertNotIn(self.other_chunk.id, self._ids())

    def test_scores_descending(self):
        hits = get_json_backend().search(ChunkFilter.build(self.course.id), self.query, 20)
        scores = [score for _, score in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))


class VectorMetaTests(GraphMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.build_graph()

    def test_default_backend_not_marked_as_fallback(self):
        # 显式指定后端：环境里设了 RAG_VECTOR_BACKEND=qdrant 时也不能改变该用例语义
        with override_settings(RAG_VECTOR_BACKEND="json"):
            consume_vector_meta()
            search_chunks(self.course.id, _vec(3), top_k=3)
            meta = consume_vector_meta()
        self.assertEqual(meta["backend"], "json")
        self.assertFalse(meta["fallback"])

    def test_json_backend_hits_same_as_before(self):
        with override_settings(RAG_VECTOR_BACKEND="json"):
            hits = search_chunks(self.course.id, _vec(5), top_k=3)
        self.assertEqual(len(hits), 3)
        self.assertEqual(hits[0][0].id, self.chunk_ppt.id)


@unittest.skipUnless(HAS_QDRANT, "qdrant-client 未安装")
class QdrantParityTests(GraphMixin, TestCase):
    """同一份向量、同一组过滤：qdrant 必须给出与 json 完全相同的 top-k。"""

    def setUp(self):
        super().setUp()
        from apps.ai.vector_backends import reset_backend_cache

        self.tmpdir = tempfile.mkdtemp(prefix="qdrant-parity-")
        self.override = override_settings(
            QDRANT_URL=f"local:{self.tmpdir}",
            QDRANT_COLLECTION="t_parity",
            RAG_QDRANT_VECTOR_SIZE=DIM,
            RAG_VECTOR_BACKEND="qdrant",
        )
        self.override.enable()
        reset_backend_cache()
        self.build_graph()
        from apps.ai.vector_backends import get_qdrant_backend

        self.backend = get_qdrant_backend()
        self.backend.upsert(
            list(
                KnowledgeChunk.objects.select_related(
                    "material", "material__catalog", "ppt", "ppt__catalog",
                    "video", "video__catalog",
                )
            )
        )

    def tearDown(self):
        from apps.ai.vector_backends import reset_backend_cache

        reset_backend_cache()
        self.override.disable()
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        super().tearDown()

    def _pair(self, **kwargs):
        flt = ChunkFilter.build(self.course.id, **kwargs)
        query = _vec(3)
        json_ids = [c.id for c, _ in get_json_backend().search(flt, query, 20)]
        qdrant_hits = self.backend.search(flt, query, 20)
        return json_ids, [c.id for c, _ in qdrant_hits], qdrant_hits

    def test_parity_full_scope(self):
        json_ids, qdrant_ids, _ = self._pair()
        self.assertEqual(json_ids, qdrant_ids)
        self.assertEqual(set(json_ids), self.expected_ids()["all"])

    def test_parity_chapter_pool(self):
        json_ids, qdrant_ids, _ = self._pair(catalog_id=self.ch1.id)
        self.assertEqual(json_ids, qdrant_ids)
        self.assertEqual(set(json_ids), self.expected_ids()["chapter_ch1"])

    def test_parity_student_with_classroom(self):
        json_ids, qdrant_ids, _ = self._pair(
            student_access=True, classroom_ids=[self.classroom.id]
        )
        self.assertEqual(json_ids, qdrant_ids)
        self.assertEqual(set(json_ids), self.expected_ids()["student_with_class"])

    def test_parity_student_without_classroom(self):
        json_ids, qdrant_ids, _ = self._pair(student_access=True)
        self.assertEqual(json_ids, qdrant_ids)
        self.assertEqual(set(json_ids), self.expected_ids()["student_no_class"])

    def test_parity_script_switch(self):
        with override_settings(AI_QA_DISABLE_SCRIPT_SOURCE=True):
            json_ids, qdrant_ids, _ = self._pair()
        self.assertEqual(json_ids, qdrant_ids)
        self.assertEqual(set(json_ids), self.expected_ids()["no_script"])

    def test_scores_match_float_tolerance(self):
        """原样搬运：同一向量的余弦分只应有浮点误差（≤1e-6）。"""
        flt = ChunkFilter.build(self.course.id)
        query = _vec(2)
        json_scores = {c.id: s for c, s in get_json_backend().search(flt, query, 20)}
        for chunk, score in self.backend.search(flt, query, 20):
            self.assertAlmostEqual(score, json_scores[chunk.id], places=6)

    def test_search_chunks_uses_qdrant_and_marks_backend(self):
        consume_vector_meta()
        hits = search_chunks(self.course.id, _vec(3), top_k=4)
        self.assertEqual(len(hits), 4)
        meta = consume_vector_meta()
        self.assertEqual(meta["backend"], "qdrant")
        self.assertFalse(meta["fallback"])

    def test_payload_carries_filter_fields(self):
        from apps.ai.vector_backends.qdrant_backend import get_client

        points = get_client().retrieve(
            self.backend.collection, ids=[self.chunk_ch1.id], with_payload=True
        )
        payload = points[0].payload
        for key in (
            "chunk_id", "course_id", "catalog_id", "source", "page",
            "is_active", "qa_open", "classroom_id", "catalog_published",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["chunk_id"], self.chunk_ch1.id)
        self.assertEqual(payload["catalog_id"], self.ch1.id)
        self.assertEqual(payload["source"], "material")
        self.assertTrue(payload["qa_open"])

    def test_delete_removes_point(self):
        self.backend.delete([self.chunk_ch1.id])
        flt = ChunkFilter.build(self.course.id)
        ids = [c.id for c, _ in self.backend.search(flt, _vec(3), 20)]
        self.assertNotIn(self.chunk_ch1.id, ids)


@unittest.skipUnless(HAS_QDRANT, "qdrant-client 未安装")
class DegradeTests(GraphMixin, TestCase):
    """Qdrant 不可用 / 未回填时必须回落 json 且打标（问答不能变哑巴）。"""

    def setUp(self):
        super().setUp()
        self.build_graph()
        consume_vector_meta()

    def test_unreachable_server_falls_back_to_json(self):
        with override_settings(
            RAG_VECTOR_BACKEND="qdrant",
            QDRANT_URL="http://127.0.0.1:9",  # 未监听端口
            QDRANT_TIMEOUT=1,
        ):
            from apps.ai.vector_backends import reset_backend_cache

            reset_backend_cache()
            hits = search_chunks(self.course.id, _vec(3), top_k=5)
            reset_backend_cache()
        self.assertEqual(len(hits), 5)  # 有结果 = 问答仍可用
        meta = consume_vector_meta()
        self.assertEqual(meta["backend"], "json")
        self.assertTrue(meta["fallback"])
        self.assertIn("Qdrant", meta["reason"])
        self.assertNotIn("\n", meta["reason"])

    def test_empty_collection_falls_back(self):
        tmpdir = tempfile.mkdtemp(prefix="qdrant-empty-")
        try:
            with override_settings(
                RAG_VECTOR_BACKEND="qdrant",
                QDRANT_URL=f"local:{tmpdir}",
                QDRANT_COLLECTION="t_empty",
                RAG_QDRANT_VECTOR_SIZE=DIM,
            ):
                from apps.ai.vector_backends import reset_backend_cache

                reset_backend_cache()
                hits = search_chunks(self.course.id, _vec(3), top_k=5)
                reset_backend_cache()
            self.assertEqual(len(hits), 5)
            meta = consume_vector_meta()
            self.assertTrue(meta["fallback"])
            self.assertIn("未回填", meta["reason"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_bad_backend_name_falls_back_to_json(self):
        with override_settings(RAG_VECTOR_BACKEND="milvus"):
            hits = search_chunks(self.course.id, _vec(3), top_k=2)
        self.assertEqual(len(hits), 2)
        self.assertEqual(vector_meta()["backend"], "json")


class BreakerTests(GraphMixin, TestCase):
    """熔断：Qdrant 连续失败后不再逐请求空试（故障期延迟不被打穿）。"""

    def setUp(self):
        super().setUp()
        from apps.ai.vectorstore import reset_vector_breaker

        reset_vector_breaker()
        self.build_graph()

    def tearDown(self):
        from apps.ai.vectorstore import reset_vector_breaker

        reset_vector_breaker()
        super().tearDown()

    def _boom_backend(self, counter):
        class Boom:
            name = "qdrant"

            def search(self, *args, **kwargs):
                counter["n"] += 1
                raise RuntimeError("connection refused (down)")

        return Boom()

    def test_breaker_opens_and_stops_calling_qdrant(self):
        counter = {"n": 0}
        with override_settings(
            RAG_VECTOR_BACKEND="qdrant",
            RAG_QDRANT_BREAKER_THRESHOLD=2,
            RAG_QDRANT_BREAKER_SECONDS=30,
        ), patch("apps.ai.vectorstore.get_backend", return_value=self._boom_backend(counter)):
            consume_vector_meta()
            hits1 = search_chunks(self.course.id, _vec(3), top_k=3)
            hits2 = search_chunks(self.course.id, _vec(3), top_k=3)
            consume_vector_meta()  # 模拟新请求：降级标记按请求隔离
            hits3 = search_chunks(self.course.id, _vec(3), top_k=3)  # 熔断中
            meta = consume_vector_meta()
        self.assertEqual(counter["n"], 2)  # 第三次没有再打 Qdrant
        self.assertEqual(len(hits1), 3)
        self.assertEqual(len(hits2), 3)
        self.assertEqual(len(hits3), 3)  # 仍然有结果
        self.assertTrue(meta["fallback"])
        self.assertIn("熔断", meta["reason"])

    def test_breaker_resets_after_success(self):
        counter = {"n": 0}
        with override_settings(
            RAG_VECTOR_BACKEND="qdrant", RAG_QDRANT_BREAKER_THRESHOLD=2
        ), patch("apps.ai.vectorstore.get_backend", return_value=self._boom_backend(counter)):
            search_chunks(self.course.id, _vec(3), top_k=3)  # 失败 1
        from apps.ai.vectorstore import reset_vector_breaker

        reset_vector_breaker()
        with override_settings(RAG_VECTOR_BACKEND="qdrant"), patch(
            "apps.ai.vectorstore.get_backend",
            return_value=self._boom_backend(counter),
        ):
            search_chunks(self.course.id, _vec(3), top_k=3)
        self.assertEqual(counter["n"], 2)  # 复位后又试了一次（未被熔断挡住）


class _FakeQdrantBackend:
    """记录写操作的假后端（不碰网络，用于双写/删除断言）。"""

    name = "qdrant"

    def __init__(self):
        self.upserts: list[list[int]] = []
        self.deletes: list[list[int]] = []
        self.fail = False

    def upsert(self, chunks):
        if self.fail:
            raise RuntimeError("boom")
        ids = [chunk.pk for chunk in chunks]
        self.upserts.append(ids)
        return len(ids)

    def delete(self, ids):
        if self.fail:
            raise RuntimeError("boom")
        self.deletes.append(sorted(ids))


class DualWriteTests(GraphMixin, TestCase):
    """新增/更新 → upsert；删除 → delete；未开启 Qdrant 时零动作。"""

    def setUp(self):
        super().setUp()
        self.fake = _FakeQdrantBackend()
        self.patcher = patch("apps.ai.vector_sync._backend", return_value=self.fake)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.build_graph()
        self.fake.upserts.clear()
        self.fake.deletes.clear()

    def test_single_chunk_save_upserts(self):
        with override_settings(RAG_VECTOR_BACKEND="qdrant"):
            with self.captureOnCommitCallbacks(execute=True):
                chunk = KnowledgeChunk.objects.create(
                    content="新片段", source="material", course=self.course, embedding=_vec(11)
                )
        self.assertEqual(self.fake.upserts, [[chunk.id]])

    def test_update_content_upserts_again(self):
        with override_settings(RAG_VECTOR_BACKEND="qdrant"):
            with self.captureOnCommitCallbacks(execute=True):
                self.chunk_ch1.content = "改过的内容"
                self.chunk_ch1.save(update_fields=["content"])
        self.assertEqual(self.fake.upserts, [[self.chunk_ch1.id]])

    def test_empty_embedding_is_not_written(self):
        with override_settings(RAG_VECTOR_BACKEND="qdrant"):
            with self.captureOnCommitCallbacks(execute=True):
                KnowledgeChunk.objects.create(
                    content="无向量片段", source="material", course=self.course, embedding=[]
                )
        self.assertEqual(self.fake.upserts, [])

    def test_delete_syncs(self):
        chunk_id = self.chunk_ch1.id  # delete() 会把实例主键置空，先存下来
        with override_settings(RAG_VECTOR_BACKEND="qdrant"):
            with self.captureOnCommitCallbacks(execute=True):
                self.chunk_ch1.delete()
        self.assertEqual(self.fake.deletes, [[chunk_id]])

    def test_queryset_delete_is_batched_into_one_request(self):
        ids = [self.chunk_ch1.id, self.chunk_closed.id, self.chunk_ppt.id]
        with override_settings(RAG_VECTOR_BACKEND="qdrant"):
            with self.captureOnCommitCallbacks(execute=True):
                KnowledgeChunk.objects.filter(id__in=ids).delete()
        self.assertEqual(len(self.fake.deletes), 1)
        self.assertEqual(self.fake.deletes[0], sorted(ids))

    def test_cascade_delete_of_ppt_syncs_children(self):
        ids = [self.chunk_ppt.id]
        with override_settings(RAG_VECTOR_BACKEND="qdrant"):
            with self.captureOnCommitCallbacks(execute=True):
                self.ppt_active.delete()
        self.assertEqual(len(self.fake.deletes), 1)
        self.assertEqual(self.fake.deletes[0], sorted(ids))

    def test_rollback_leaves_no_stale_delete(self):
        """事务回滚后行还在：不许把仍然有效的片段从 Qdrant 删掉。

        on_commit 回调随回滚被丢弃，但删除缓冲（contextvar）会残留；下一次删除
        触发 flush 时若不做「回查库里是否还在」的校验，就会误删有效向量。
        """
        victim = self.chunk_ch1.id
        with override_settings(RAG_VECTOR_BACKEND="qdrant"):
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    KnowledgeChunk.objects.filter(id=victim).delete()
                    raise RuntimeError("boom")
        other = self.chunk_closed.id
        with override_settings(RAG_VECTOR_BACKEND="qdrant"):
            with self.captureOnCommitCallbacks(execute=True):
                KnowledgeChunk.objects.filter(id=other).delete()
        self.assertTrue(KnowledgeChunk.objects.filter(id=victim).exists())
        deleted = {i for ids in self.fake.deletes for i in ids}
        self.assertNotIn(victim, deleted)
        self.assertIn(other, deleted)

    def test_sync_owner_upserts_owner_chunks(self):
        from apps.ai.vector_sync import sync_owner

        with override_settings(RAG_VECTOR_BACKEND="qdrant"):
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    sync_owner("material", self.mat_ch1)
        self.assertEqual(self.fake.upserts, [[self.chunk_ch1.id]])

    def test_sync_course_upserts_all_course_chunks(self):
        """课程复用：整门课 bulk 复制后按课程补齐（分页写，不一次性读全量）。"""
        from apps.ai.vector_sync import sync_course

        with override_settings(RAG_VECTOR_BACKEND="qdrant"):
            with self.captureOnCommitCallbacks(execute=True):
                sync_course(self.course.id)
        upserted = {i for ids in self.fake.upserts for i in ids}
        expected = set(
            KnowledgeChunk.objects.filter(course=self.course)
            .exclude(embedding=[])
            .values_list("id", flat=True)
        )
        self.assertEqual(upserted, expected)
        self.assertNotIn(self.other_chunk.id, upserted)  # 课程边界

    def test_parent_visibility_change_refreshes_payload(self):
        """发布章节 / 开关 QA：父对象改可见性 → 重刷其名下片段 payload。

        测试环境实测的线上问题：发布章节后 Qdrant 的 catalog_published 仍是 false，
        学生在新章节提问检索不到（DB 复验只能删多余命中，补不回漏掉的）。
        """
        with override_settings(RAG_VECTOR_BACKEND="qdrant"):
            with self.captureOnCommitCallbacks(execute=True):
                self.ch1.is_published = False
                self.ch1.save(update_fields=["is_published"])
        upserted = {i for ids in self.fake.upserts for i in ids}
        expected = set(
            KnowledgeChunk.objects.filter(catalog_id=self.ch1.id)
            .exclude(embedding=[])
            .values_list("id", flat=True)
        )
        self.assertEqual(upserted, expected)

    def test_unrelated_field_save_does_not_refresh(self):
        with override_settings(RAG_VECTOR_BACKEND="qdrant"):
            with self.captureOnCommitCallbacks(execute=True):
                self.ch1.title = "第1章（改名）"
                self.ch1.save(update_fields=["title"])
        self.assertEqual(self.fake.upserts, [])

    def test_material_qa_toggle_refreshes_payload(self):
        with override_settings(RAG_VECTOR_BACKEND="qdrant"):
            with self.captureOnCommitCallbacks(execute=True):
                self.mat_ch1.qa_open = False
                self.mat_ch1.save(update_fields=["qa_open"])
        upserted = {i for ids in self.fake.upserts for i in ids}
        self.assertIn(self.chunk_ch1.id, upserted)

    def test_video_publish_refreshes_payload(self):
        with override_settings(RAG_VECTOR_BACKEND="qdrant"):
            with self.captureOnCommitCallbacks(execute=True):
                self.video_pub.is_published = False
                self.video_pub.save(update_fields=["is_published"])
        upserted = {i for ids in self.fake.upserts for i in ids}
        self.assertIn(self.chunk_script.id, upserted)

    def test_disabled_backend_does_nothing(self):
        with override_settings(RAG_VECTOR_BACKEND="json"):
            with self.captureOnCommitCallbacks(execute=True):
                KnowledgeChunk.objects.create(
                    content="json 模式片段", source="material", course=self.course, embedding=_vec(12)
                )
                self.chunk_ch1.delete()
        self.assertEqual(self.fake.upserts, [])
        self.assertEqual(self.fake.deletes, [])

    def test_sync_failure_never_breaks_business_write(self):
        """Qdrant 写失败不能把业务写入拖挂（禁止异常穿透）。"""
        self.fake.fail = True
        closed_id = self.chunk_closed.id
        with override_settings(RAG_VECTOR_BACKEND="qdrant"):
            with self.captureOnCommitCallbacks(execute=True):
                chunk = KnowledgeChunk.objects.create(
                    content="Qdrant 挂了也要能写", source="material",
                    course=self.course, embedding=_vec(13),
                )
                self.chunk_closed.delete()
        self.assertTrue(KnowledgeChunk.objects.filter(id=chunk.id).exists())
        self.assertFalse(KnowledgeChunk.objects.filter(id=closed_id).exists())


class CompareHitsTests(TestCase):
    """比对工具的「同分容差」逻辑（纯函数，用假数据构造并列场景）。

    背景（测试环境实测 2026-11-04）：同一份课件被挂到 8 个章节，同一页文本入 8 次库，
    表达式完全相同 → 8 个片段余弦分完全相同（0.834192）。top_k 截断落在并列组中间时，
    json（按库内顺序）与 qdrant（按 HNSW 内部顺序）各取并列组的不同成员，严格按 id
    比就是 14/15 = 93.3%「假不达标」。门槛比较让并列组整组计入/整组排除。
    """

    class _Chunk:
        def __init__(self, cid):
            self.id = cid

    def _hits(self, pairs):
        return [(self._Chunk(cid), score) for cid, score in pairs]

    def test_band_excludes_half_covered_tie_group(self):
        from apps.ai.management.commands.compare_retrieval import compare_hits

        # 前 3 名高分，第 4-11 名并列 0.83（8 个），k=5 → 两边各取到并列组的不同成员
        tie = [(10 + i, 0.83) for i in range(8)]
        json_hits = self._hits(
            [(1, 0.99), (2, 0.95), (3, 0.90)] + tie + [(30, 0.70), (31, 0.69)]
        )
        qdrant_hits = self._hits(
            [(1, 0.99), (2, 0.95), (3, 0.90)]
            + list(reversed(tie))  # 并列组内部顺序相反
            + [(40, 0.70), (41, 0.69)]
        )
        row = compare_hits(json_hits, qdrant_hits, 5)
        # 严格比：取到并列组不同成员 → 不达标
        self.assertLess(row["strict_rate"], 0.95)
        # 门槛比：并列组整组计入，两边一致 → 100%
        self.assertEqual(row["overlap_rate"], 1.0)
        self.assertEqual(row["band_sizes"], [11, 11])
        self.assertEqual(row["only_json"], [])
        self.assertEqual(row["only_qdrant"], [])

    def test_missing_chunk_still_detected(self):
        """真缺失（未回填）不能被容差逻辑掩盖。"""
        from apps.ai.management.commands.compare_retrieval import compare_hits

        json_hits = self._hits([(1, 0.99), (2, 0.95), (3, 0.90), (4, 0.80)])
        qdrant_hits = self._hits([(1, 0.99), (2, 0.95), (3, 0.90)])
        row = compare_hits(json_hits, qdrant_hits, 4)
        self.assertEqual(row["overlap_rate"], 0.75)
        self.assertEqual(row["only_json"], [4])
        self.assertIn(4, row["only_json"])

    def test_both_empty_counts_as_agree(self):
        """两边都没候选（如章节未发布 → 学生池为空）不是「不重合」，而是没验证到东西。"""
        from apps.ai.management.commands.compare_retrieval import compare_hits

        row = compare_hits([], [], 5)
        self.assertTrue(row["empty"])
        self.assertEqual(row["overlap_rate"], 1.0)
        self.assertEqual(row["strict_rate"], 1.0)
        self.assertEqual(row["band_sizes"], [0, 0])

    def test_one_side_empty_is_mismatch(self):
        from apps.ai.management.commands.compare_retrieval import compare_hits

        row = compare_hits(self._hits([(1, 0.9), (2, 0.8)]), [], 5)
        self.assertFalse(row["empty"])
        self.assertEqual(row["overlap_rate"], 0.0)
        self.assertEqual(row["only_json"], [1, 2])


@unittest.skipUnless(HAS_QDRANT, "qdrant-client 未安装")
class BackfillCommandTests(GraphMixin, TestCase):
    """回填：分页搬运、幂等重跑、断点续跑、不清空已有数据。"""

    def setUp(self):
        super().setUp()
        from apps.ai.vector_backends import reset_backend_cache

        self.tmpdir = tempfile.mkdtemp(prefix="qdrant-backfill-")
        self.state = f"{self.tmpdir}/state.json"
        self.override = override_settings(
            QDRANT_URL=f"local:{self.tmpdir}",
            QDRANT_COLLECTION="t_backfill",
            RAG_QDRANT_VECTOR_SIZE=DIM,
            RAG_VECTOR_BACKEND="json",  # 回填命令与检索开关无关（切换前先把数据搬进去）
        )
        self.override.enable()
        reset_backend_cache()
        self.build_graph()

    def tearDown(self):
        from apps.ai.vector_backends import reset_backend_cache

        reset_backend_cache()
        self.override.disable()
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        super().tearDown()

    def _run(self, **kwargs):
        out = StringIO()
        call_command("backfill_qdrant", checkpoint=self.state, stdout=out, **kwargs)
        return out.getvalue()

    def _count(self):
        from apps.ai.vector_backends import get_qdrant_backend

        return get_qdrant_backend().count()

    def test_backfill_pages_all_chunks(self):
        total = KnowledgeChunk.objects.exclude(embedding=[]).count()
        output = self._run(batch_size=2)
        self.assertIn("回填完成", output)
        self.assertEqual(self._count(), total)

    def test_rerun_is_idempotent(self):
        total = KnowledgeChunk.objects.exclude(embedding=[]).count()
        self._run(batch_size=3)
        self._run(batch_size=3)  # 全量重跑：upsert 幂等，点数不变
        self.assertEqual(self._count(), total)

    def test_resume_from_checkpoint_skips_done_range(self):
        ids = sorted(
            KnowledgeChunk.objects.exclude(embedding=[]).values_list("id", flat=True)
        )
        midpoint = ids[3]
        # 模拟中断：只搬运了前半段
        from apps.knowledge.models import KnowledgeChunk as KC

        from apps.ai.vector_backends import get_qdrant_backend

        backend = get_qdrant_backend()
        backend.ensure_ready()
        backend.upsert(
            list(
                KC.objects.filter(id__lte=midpoint).select_related(
                    "material", "material__catalog", "ppt", "ppt__catalog",
                    "video", "video__catalog",
                )
            )
        )
        with open(self.state, "w", encoding="utf-8") as fh:
            json.dump({"scope": "all", "last_id": midpoint, "written": 4}, fh)

        output = self._run(batch_size=2)
        self.assertIn("续跑", output)
        self.assertEqual(self._count(), len(ids))  # 不丢：后半段补齐
        with self.assertRaises(FileNotFoundError):
            open(self.state, encoding="utf-8")  # 跑完清 checkpoint

    def test_course_scope_only_writes_that_course(self):
        self._run(course=self.course.id)
        mine = KnowledgeChunk.objects.filter(course=self.course).exclude(embedding=[]).count()
        self.assertEqual(self._count(), mine)

    def test_dry_run_writes_nothing(self):
        output = self._run(dry_run=True)
        self.assertIn("dry-run", output)
        self.assertEqual(self._count(), 0)


@unittest.skipUnless(HAS_QDRANT, "qdrant-client 未安装")
class CascadeSyncTests(GraphMixin, TestCase):
    """验收项：删课件/删课程后，两套后端都查不到对应片段。"""

    def setUp(self):
        super().setUp()
        from apps.ai.vector_backends import reset_backend_cache

        self.tmpdir = tempfile.mkdtemp(prefix="qdrant-cascade-")
        self.override = override_settings(
            QDRANT_URL=f"local:{self.tmpdir}",
            QDRANT_COLLECTION="t_cascade",
            RAG_QDRANT_VECTOR_SIZE=DIM,
            RAG_VECTOR_BACKEND="qdrant",
        )
        self.override.enable()
        reset_backend_cache()
        self.build_graph()
        from apps.ai.vector_backends import get_qdrant_backend

        self.backend = get_qdrant_backend()
        self.backend.upsert(
            list(
                KnowledgeChunk.objects.select_related(
                    "material", "material__catalog", "ppt", "ppt__catalog",
                    "video", "video__catalog",
                )
            )
        )

    def tearDown(self):
        from apps.ai.vector_backends import reset_backend_cache

        reset_backend_cache()
        self.override.disable()
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        super().tearDown()

    def _point_ids(self, ids):
        from apps.ai.vector_backends.qdrant_backend import get_client

        return [p.id for p in get_client().retrieve(self.backend.collection, ids=ids)]

    def _both_backends_ids(self):
        flt = ChunkFilter.build(self.course.id)
        json_ids = {c.id for c, _ in get_json_backend().search(flt, _vec(3), 20)}
        qdrant_ids = {c.id for c, _ in self.backend.search(flt, _vec(3), 20)}
        return json_ids, qdrant_ids

    def test_delete_ppt_cascades_to_qdrant(self):
        chunk_id = self.chunk_ppt.id
        self.assertEqual(self._point_ids([chunk_id]), [chunk_id])
        with self.captureOnCommitCallbacks(execute=True):
            self.ppt_active.delete()
        self.assertEqual(self._point_ids([chunk_id]), [])
        json_ids, qdrant_ids = self._both_backends_ids()
        self.assertNotIn(chunk_id, json_ids)
        self.assertNotIn(chunk_id, qdrant_ids)

    def test_delete_course_cascades_to_qdrant(self):
        chunk_id = self.other_chunk.id
        course_id = self.other_course.id  # delete() 后实例主键被置空，先存
        self.assertEqual(self._point_ids([chunk_id]), [chunk_id])
        with self.captureOnCommitCallbacks(execute=True):
            self.other_course.delete()
        self.assertEqual(self._point_ids([chunk_id]), [])
        flt = ChunkFilter.build(course_id)
        self.assertEqual(self.backend.search(flt, _vec(3), 20), [])
        self.assertEqual(get_json_backend().search(flt, _vec(3), 20), [])

    def test_delete_material_syncs(self):
        chunk_id = self.chunk_ch1.id
        with self.captureOnCommitCallbacks(execute=True):
            self.mat_ch1.delete()
        self.assertEqual(self._point_ids([chunk_id]), [])


@unittest.skipUnless(HAS_QDRANT, "qdrant-client 未安装")
class CompareCommandTests(GraphMixin, TestCase):
    """比对命令：两套后端在测试图上应 100% 重合，并落一份报告。"""

    def setUp(self):
        super().setUp()
        from apps.ai.vector_backends import reset_backend_cache

        self.tmpdir = tempfile.mkdtemp(prefix="qdrant-compare-")
        self.override = override_settings(
            QDRANT_URL=f"local:{self.tmpdir}",
            QDRANT_COLLECTION="t_compare",
            RAG_QDRANT_VECTOR_SIZE=DIM,
            RAG_VECTOR_BACKEND="qdrant",
        )
        self.override.enable()
        reset_backend_cache()
        self.build_graph()
        from apps.ai.vector_backends import get_qdrant_backend

        self.backend = get_qdrant_backend()
        self.backend.upsert(
            list(
                KnowledgeChunk.objects.select_related(
                    "material", "material__catalog", "ppt", "ppt__catalog",
                    "video", "video__catalog",
                )
            )
        )

    def tearDown(self):
        from apps.ai.vector_backends import reset_backend_cache

        reset_backend_cache()
        self.override.disable()
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        super().tearDown()

    def _fake_embed_provider(self):
        class FakeEmbed:
            name = "fake"
            embed_model = "fake-8"

            def embed(self, texts, allow_fallback=True):
                return [_vec(len(t) % 10 + 1) for t in texts]

        return FakeEmbed()

    def test_compare_reports_full_overlap(self):
        report_md = f"{self.tmpdir}/report.md"
        with patch(
            "apps.ai.providers.factory.get_provider",
            return_value=self._fake_embed_provider(),
        ):
            call_command(
                "compare_retrieval",
                course=self.course.id,
                queries="数组怎么声明;讲稿讲了什么",
                top_k=5,
                out=report_md,
                stdout=StringIO(),
            )
        self.assertTrue(report_md.endswith(".md"))
        with open(report_md, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("平均重合率", content)
        self.assertIn("100.00%", content)
        with open(report_md.replace(".md", ".json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertTrue(data["summary"]["pass"])
        self.assertEqual(data["summary"]["only_json_ids"], [])

    def test_compare_detects_missing_backfill(self):
        """少搬一个片段时，比对必须报出来（切换前的兜底检查）。"""
        self.backend.delete([self.chunk_ch1.id])
        report_md = f"{self.tmpdir}/report_missing.md"
        with patch(
            "apps.ai.providers.factory.get_provider",
            return_value=self._fake_embed_provider(),
        ):
            with self.assertRaises(CommandError):
                # 有查询重合率不达标 → 命令以 CommandError 收尾（CI 里能拦住切换）
                call_command(
                    "compare_retrieval",
                    course=self.course.id,
                    queries="讲义里有什么;班级专属资料",
                    top_k=8,
                    out=report_md,
                    stdout=StringIO(),
                )
        with open(report_md, encoding="utf-8") as fh:
            content = fh.read()
        self.assertTrue("平均重合率" in content)
