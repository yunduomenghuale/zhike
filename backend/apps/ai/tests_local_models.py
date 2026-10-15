"""系统内置本地模型（local provider）单测。

原则：不打真实模型、不下载权重——加载/推理函数全部 patch 掉；
真实链路由冒烟脚本（smoke_local_models.py）与 E2E 覆盖。
"""
from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from apps.ai.local_models import (
    default_model,
    ensure_downloaded,
    is_downloaded,
    model_path,
)
from apps.ai.providers.factory import build_provider
from apps.ai.providers.local import LocalModelsProvider


class LocalProviderFactoryTests(SimpleTestCase):
    """factory：local 无 API Key 也必须构建成功（不得回落 Mock）。"""

    def test_build_without_api_key(self):
        provider = build_provider("local", {"model": ""}, "embed")
        self.assertIsInstance(provider, LocalModelsProvider)
        self.assertEqual(provider.name, "local")

    def test_default_models_per_capability(self):
        embed = build_provider("local", {"model": ""}, "embed")
        rerank = build_provider("local", {"model": ""}, "rerank")
        self.assertEqual(embed.model, "BAAI/bge-m3")
        self.assertEqual(rerank.model, "Qwen/Qwen3-Reranker-0.6B")

    def test_explicit_model_overrides_default(self):
        provider = build_provider("local", {"model": "BAAI/bge-large-zh"}, "embed")
        self.assertEqual(provider.model, "BAAI/bge-large-zh")

    def test_chat_and_tts_not_implemented(self):
        provider = build_provider("local", {"model": ""}, "chat")
        with self.assertRaises(NotImplementedError):
            provider.chat([{"role": "user", "content": "hi"}])
        with self.assertRaises(NotImplementedError):
            provider.tts("hi")


class LocalProviderContractTests(SimpleTestCase):
    """Provider 与 local_models 推理函数的契约：透传、排序、top_n、空输入。"""

    def test_embed_delegates_and_accepts_allow_fallback(self):
        provider = LocalModelsProvider({"model": "BAAI/bge-m3"}, capability="embed")
        with patch("apps.ai.local_models.embed_texts", return_value=[[0.1, 0.2]]) as fake:
            vectors = provider.embed(["连接测试"], allow_fallback=False)
        self.assertEqual(vectors, [[0.1, 0.2]])
        fake.assert_called_once_with("BAAI/bge-m3", ["连接测试"])

    def test_embed_empty_short_circuits(self):
        provider = LocalModelsProvider({"model": "BAAI/bge-m3"}, capability="embed")
        with patch("apps.ai.local_models.embed_texts") as fake:
            self.assertEqual(provider.embed([]), [])
        fake.assert_not_called()

    def test_rerank_sorted_desc_with_original_index(self):
        provider = LocalModelsProvider({"model": "Qwen/Qwen3-Reranker-0.6B"}, capability="rerank")
        # 第 2 条最相关、第 0 条次之、第 1 条最低——index 必须保持原始下标
        with patch(
            "apps.ai.local_models.rerank_scores", return_value=[0.6, 0.1, 0.9]
        ) as fake:
            ranked = provider.rerank("q", ["d0", "d1", "d2"])
        self.assertEqual(
            ranked,
            [
                {"index": 2, "score": 0.9},
                {"index": 0, "score": 0.6},
                {"index": 1, "score": 0.1},
            ],
        )
        fake.assert_called_once_with("Qwen/Qwen3-Reranker-0.6B", "q", ["d0", "d1", "d2"])

    def test_rerank_top_n_and_empty(self):
        provider = LocalModelsProvider({"model": "Qwen/Qwen3-Reranker-0.6B"}, capability="rerank")
        with patch("apps.ai.local_models.rerank_scores", return_value=[0.3, 0.9, 0.6]):
            ranked = provider.rerank("q", ["a", "b", "c"], top_n=2)
        self.assertEqual([item["index"] for item in ranked], [1, 2])
        self.assertEqual(provider.rerank("q", []), [])


@override_settings(AI_MODELS_DIR="X:/ai-models-test")
class LocalModelsRegistryTests(SimpleTestCase):
    """路径解析 / 就绪判定 / 下载触发（modelscope 用假模块注入，不走网络）。"""

    def test_relative_name_resolves_under_models_dir(self):
        self.assertEqual(
            model_path("BAAI/bge-m3"), Path("X:/ai-models-test") / "BAAI/bge-m3"
        )

    def test_absolute_path_passthrough(self):
        self.assertEqual(model_path("D:/mymodel"), Path("D:/mymodel"))

    def test_is_downloaded_requires_config_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(AI_MODELS_DIR=tmp):
                self.assertFalse(is_downloaded("BAAI/bge-m3"))
                target = Path(tmp) / "BAAI" / "bge-m3"
                target.mkdir(parents=True)
                self.assertFalse(is_downloaded("BAAI/bge-m3"))  # 空目录不算就绪
                (target / "config.json").write_text("{}")
                self.assertTrue(is_downloaded("BAAI/bge-m3"))

    def test_ensure_downloaded_skips_when_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "BAAI" / "bge-m3"
            target.mkdir(parents=True)
            (target / "config.json").write_text("{}")
            with override_settings(AI_MODELS_DIR=tmp):
                path = ensure_downloaded("BAAI/bge-m3")
            self.assertEqual(path, target)

    def test_ensure_downloaded_invokes_modelscope(self):
        calls = []
        fake_module = types.SimpleNamespace(
            snapshot_download=lambda name, local_dir=None, cache_dir=None: calls.append(
                (name, local_dir, cache_dir)
            )
            or self._seed(target_holder[0])
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Qwen" / "Qwen3-Reranker-0.6B"
            target_holder = [target]
            with override_settings(AI_MODELS_DIR=tmp):
                with patch.dict(sys.modules, {"modelscope": fake_module}):
                    path = ensure_downloaded("Qwen/Qwen3-Reranker-0.6B")
            self.assertEqual(path, target)
            self.assertEqual(calls[0][0], "Qwen/Qwen3-Reranker-0.6B")

    @staticmethod
    def _seed(target: Path):
        target.mkdir(parents=True, exist_ok=True)
        (target / "config.json").write_text("{}")

    def test_ensure_downloaded_post_check_failure(self):
        fake_module = types.SimpleNamespace(snapshot_download=lambda *a, **k: None)
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(AI_MODELS_DIR=tmp):
                with patch.dict(sys.modules, {"modelscope": fake_module}):
                    with self.assertRaises(RuntimeError):
                        ensure_downloaded("BAAI/bge-m3")

    def test_default_model_reads_settings(self):
        with override_settings(
            AI_SETTINGS={"local": {"embed_model": "BAAI/bge-m3", "rerank_model": "X/r"}}
        ):
            self.assertEqual(default_model("embed"), "BAAI/bge-m3")
            self.assertEqual(default_model("rerank"), "X/r")


class LocalEmbedInferTests(SimpleTestCase):
    """embed_texts：加载走缓存入口、归一化参数、推理串行锁。"""

    def test_embed_texts_uses_cached_embedder(self):
        fake_model = MagicMock()
        fake_model.encode.return_value = [[0.5, 0.5], [0.1, 0.9]]
        with patch("apps.ai.local_models.get_embedder", return_value=fake_model):
            from apps.ai.local_models import embed_texts

            vectors = embed_texts("BAAI/bge-m3", ["甲", "乙"])
        self.assertEqual(len(vectors), 2)
        self.assertAlmostEqual(vectors[0][0], 0.5)
        _, kwargs = fake_model.encode.call_args
        self.assertTrue(kwargs.get("normalize_embeddings"))


if __name__ == "__main__":
    unittest.main()
