"""rerank 能力测试：Provider 层（DashScope 原生端点）+ 检索编排（向量召回→重排→阈值）。

覆盖：
- Provider：原生端点请求格式/响应解析、4xx 错误透出、未配模型与非 DashScope
  端点明确不支持、空文档短路、空结果按协议异常上抛、top_n 收敛；
- 编排：阈值按重排模型解析（gte-rerank 分数尺度低、qwen3 系高）、相对截断
  滤掉弱相关噪声、重排失败/协议异常回退纯向量 top_k、全部低于阈值返回空、
  召回数取 settings 且不小于 top_k。
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from apps.ai.providers.mock import MockProvider
from apps.ai.services import _search_relevant_chunks
from apps.knowledge.models import KnowledgeChunk

User = get_user_model()


class _FakeResponse:
    """假 HTTP 响应：status_code + json 体，4xx 时 raise_for_status 抛错。"""

    def __init__(self, *, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._json_body is None:
            raise ValueError("响应体不是 JSON")
        return self._json_body


def _rerank_provider(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", model="gte-rerank-v2"):
    from apps.ai.providers.openai_compat import OpenAICompatProvider

    return OpenAICompatProvider(
        {"api_key": "sk-test", "base_url": base_url, "rerank_model": model}
    )


def _rerank_body(scores):
    """构造 DashScope 原生 rerank 响应体：scores 为按 documents 顺序的相关性分。"""
    return {
        "output": {
            "results": [
                {"index": i, "relevance_score": s, "document": None}
                for i, s in enumerate(scores)
            ]
        },
        "usage": {"total_tokens": 100},
    }


class RerankProviderTests(SimpleTestCase):
    """OpenAICompatProvider.rerank：DashScope 原生端点行为。"""

    def test_native_endpoint_payload_and_parsed_scores(self):
        provider = _rerank_provider()
        seen = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            seen.update(url=url, json=json, timeout=timeout)
            return _FakeResponse(json_body=_rerank_body([0.2, 0.9, 0.5]))

        with patch("apps.ai.providers.openai_compat.requests.post", side_effect=fake_post):
            ranked = provider.rerank("考核方式是什么？", ["噪声页", "目标页", "相关页"], top_n=2)

        # 端点：compatible-mode/v1 -> api/v1 原生 rerank
        self.assertEqual(
            seen["url"],
            "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
        )
        # 请求体必须包 input/parameters（少了会 400 Field required）
        self.assertEqual(seen["json"]["model"], "gte-rerank-v2")
        self.assertEqual(seen["json"]["input"]["query"], "考核方式是什么？")
        self.assertEqual(seen["json"]["input"]["documents"], ["噪声页", "目标页", "相关页"])
        self.assertEqual(seen["json"]["parameters"], {"top_n": 2, "return_documents": False})
        # 响应解析：按 relevance_score 降序，保留 documents 原始下标
        self.assertEqual(ranked, [{"index": 1, "score": 0.9}, {"index": 2, "score": 0.5}])

    def test_top_n_clamped_to_documents_length(self):
        provider = _rerank_provider()
        seen = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            seen["json"] = json
            return _FakeResponse(json_body=_rerank_body([0.9, 0.1]))

        with patch("apps.ai.providers.openai_compat.requests.post", side_effect=fake_post):
            provider.rerank("问题", ["甲", "乙"], top_n=99)

        self.assertEqual(seen["json"]["parameters"]["top_n"], 2)

    def test_4xx_raises_with_error_detail(self):
        provider = _rerank_provider()
        calls = []

        def fake_post(url, headers=None, json=None, timeout=None):
            calls.append(url)
            return _FakeResponse(
                status_code=400,
                text='{"code":"InvalidParameter","message":"Model not exist."}',
                json_body={"code": "InvalidParameter", "message": "Model not exist."},
            )

        with patch("apps.ai.providers.openai_compat.requests.post", side_effect=fake_post):
            with self.assertRaises(RuntimeError) as ctx:
                provider.rerank("问题", ["甲"])

        # 错误体透出（模型名不存在时能直接看出原因）
        self.assertIn("InvalidParameter", str(ctx.exception))
        self.assertIn("Model not exist.", str(ctx.exception))
        self.assertEqual(len(calls), 1)

    def test_empty_results_raises_as_protocol_anomaly(self):
        """200 但无结果 = 协议异常（不是「全不相关」）：上抛让上层回退纯向量。"""
        provider = _rerank_provider()

        def fake_post(url, headers=None, json=None, timeout=None):
            return _FakeResponse(json_body={"output": {}})

        with patch("apps.ai.providers.openai_compat.requests.post", side_effect=fake_post):
            with self.assertRaises(RuntimeError) as ctx:
                provider.rerank("问题", ["甲"])
        self.assertIn("未返回结果", str(ctx.exception))

    def test_empty_documents_short_circuits_without_http(self):
        provider = _rerank_provider()
        with patch("apps.ai.providers.openai_compat.requests.post") as post:
            self.assertEqual(provider.rerank("问题", []), [])
        post.assert_not_called()

    def test_missing_model_raises_not_implemented(self):
        provider = _rerank_provider(model="")
        with self.assertRaises(NotImplementedError):
            provider.rerank("问题", ["甲"])

    def test_non_dashscope_endpoint_raises_not_implemented(self):
        """OpenAI 兼容生态无统一 /rerank 规范（compatible-mode 实测 404）：明确不支持。"""
        provider = _rerank_provider(base_url="https://api.openai.com/v1")
        with self.assertRaises(NotImplementedError):
            provider.rerank("问题", ["甲"])

    def test_mock_provider_rerank_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            MockProvider().rerank("问题", ["甲"])


# ---------------------------------------------------------------------------
# 检索编排（_search_relevant_chunks）
# ---------------------------------------------------------------------------
class _FakeEmbed:
    """假 embed：对任意输入返回固定查询向量。"""

    name = "fake-embed"

    def __init__(self, vec):
        self.vec = list(vec)

    def embed(self, texts, **kwargs):
        return [list(self.vec) for _ in texts]


class _FakeRerank:
    """假 rerank：按预设分数表打分（下标对齐候选顺序），可配置抛错。

    model：模拟 provider.rerank_model（阈值按模型解析，见 _resolve_rerank_threshold）。
    """

    name = "fake-rerank"

    def __init__(self, scores=None, raise_exc=None, model=""):
        self.scores = scores
        self.raise_exc = raise_exc
        self.rerank_model = model
        self.calls = []

    def rerank(self, query, documents, top_n=None):
        self.calls.append({"query": query, "documents": list(documents), "top_n": top_n})
        if self.raise_exc is not None:
            raise self.raise_exc
        ranked = [{"index": i, "score": s} for i, s in enumerate(self.scores)]
        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked[: top_n or len(ranked)]


def _patch_providers(embed, rerank):
    """按能力分发假 provider（embed / rerank 分开取，与生产一致）。"""

    def factory(capability):
        return {"embed": embed, "rerank": rerank}[capability]

    return patch("apps.ai.services.get_provider", side_effect=factory)


class RetrievalOrchestrationTests(TestCase):
    """_search_relevant_chunks：向量召回 -> 重排 -> 阈值过滤 -> top_k。"""

    def setUp(self):
        from apps.courses.models import Course

        self.teacher = User.objects.create_user(
            username="rerank-teacher", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.course = Course.objects.create(name="Java", teacher=self.teacher)
        # 查询向量 [1,0]；第 i 个片段 embedding=[1, i+1] -> 余弦随 i 递减，
        # 向量检索顺序恒为 chunk0 > chunk1 > ...（与重排顺序可区分）
        for i in range(5):
            KnowledgeChunk.objects.create(
                course_id=self.course.id,
                content=f"片段{i}",
                page=i + 1,
                embedding=[1.0, float(i + 1)],
            )

    def _run(self, rerank_scores=None, raise_exc=None, rerank_model="", **overrides):
        embed = _FakeEmbed([1.0, 0.0])
        rerank = _FakeRerank(scores=rerank_scores, raise_exc=raise_exc, model=rerank_model)
        with _patch_providers(embed, rerank), override_settings(**overrides):
            result = _search_relevant_chunks(self.course.id, "考核方式是什么？")
        return result, rerank

    def test_rerank_filters_noise_below_threshold(self):
        """核心场景：只有目标页过阈值，噪声页（向量高分但语义不相关）被滤掉。"""
        result, rerank = self._run(rerank_scores=[0.9, 0.1, 0.05, 0.02, 0.01])
        self.assertEqual([c.page for c, _ in result], [1])
        self.assertEqual(result[0][1], 0.9)  # score 为重排分
        self.assertEqual(rerank.calls[0]["query"], "考核方式是什么？")
        self.assertEqual(rerank.calls[0]["top_n"], 5)

    def test_rerank_reorders_candidates_and_keeps_close_scores(self):
        """重排分覆盖向量顺序：分数接近（无 2 倍落差）的多个相关片段都保留。"""
        result, _ = self._run(rerank_scores=[0.8, 0.9, 0.7, 0.1, 0.05])
        self.assertEqual([c.page for c, _ in result], [2, 1, 3])
        self.assertEqual([round(s, 4) for _, s in result], [0.9, 0.8, 0.7])

    def test_fallback_to_vector_when_rerank_unconfigured(self):
        """未配置重排（Mock 抛 NotImplementedError）：回退纯向量 top_k，问答可用。"""
        result, _ = self._run(raise_exc=NotImplementedError("mock 暂不支持重排序"))
        self.assertEqual([c.page for c, _ in result], [1, 2, 3, 4, 5])

    def test_fallback_to_vector_when_rerank_errors(self):
        """重排调用失败（网络/5xx/协议异常）：同样回退纯向量 top_k。"""
        result, _ = self._run(raise_exc=RuntimeError("HTTP 503"))
        self.assertEqual([c.page for c, _ in result], [1, 2, 3, 4, 5])

    def test_all_below_threshold_returns_empty(self):
        """全部低于阈值：判定资料未覆盖该问题，返回空（上层走「无相关内容」话术）。"""
        result, _ = self._run(rerank_scores=[0.1, 0.1, 0.1, 0.1, 0.1])
        self.assertEqual(result, [])

    def test_recall_count_from_settings(self):
        """召回数取 settings.AI_RERANK_RECALL：只把前 N 个候选交给重排。"""
        result, rerank = self._run(
            rerank_scores=[0.9, 0.2, 0.1],
            AI_RERANK_RECALL=3,
        )
        self.assertEqual(len(rerank.calls[0]["documents"]), 3)
        self.assertEqual([c.page for c, _ in result], [1])

    def test_recall_respects_explicit_small_value(self):
        """召回数显式配小（2 < top_k）：只把 2 个候选交给重排，结果不超过 2 条。"""
        result, rerank = self._run(rerank_scores=[0.9, 0.8], AI_RERANK_RECALL=2)
        self.assertEqual(len(rerank.calls[0]["documents"]), 2)
        self.assertEqual([c.page for c, _ in result], [1, 2])

    def test_threshold_from_settings(self):
        """阈值取 settings.AI_RERANK_THRESHOLD：调高后原能过阈值的片段被滤掉。"""
        result, _ = self._run(rerank_scores=[0.9, 0.4, 0.1, 0.05, 0.02], AI_RERANK_THRESHOLD=0.5)
        self.assertEqual([c.page for c, _ in result], [1])

    def test_gte_rerank_low_scores_kept_by_model_threshold(self):
        """回归（2026-10-15）：gte-rerank-v2 相关片段只有 0.09~0.9，按 qwen3 量级
        的 0.3 阈值会把目标页（实测 0.288）也滤掉、参考来源全空。分模型阈值下
        目标页必须保留，且相对截断把弱相关噪声（0.13 及以下）切掉。"""
        result, rerank = self._run(
            rerank_scores=[0.288, 0.132, 0.112, 0.086, 0.058],
            rerank_model="gte-rerank-v2",
        )
        self.assertEqual(rerank.calls[0]["top_n"], 5)
        self.assertEqual([c.page for c, _ in result], [1])
        self.assertEqual(result[0][1], 0.288)

    def test_gte_rerank_offtopic_scores_still_filtered(self):
        """gte-rerank 对无关问题的最高分仅 ~0.006：低于该模型阈值，仍返回空。"""
        result, _ = self._run(
            rerank_scores=[0.006, 0.006, 0.006, 0.006, 0.006],
            rerank_model="gte-rerank-v2",
        )
        self.assertEqual(result, [])

    def test_relative_cutoff_drops_weak_noise(self):
        """相对截断：与最高分存在 2 倍以上落差的多为同课程弱相关噪声，不进引用。"""
        # 最高分 0.9，截断线 max(0.3, 0.45)=0.45：0.44 恰好在线下被滤掉
        result, _ = self._run(rerank_scores=[0.9, 0.44, 0.2, 0.1, 0.05])
        self.assertEqual([c.page for c, _ in result], [1])

    def test_keep_ratio_zero_disables_relative_cutoff(self):
        """AI_RERANK_KEEP_RATIO=0 退回纯阈值过滤：过阈值的片段全部保留。"""
        result, _ = self._run(
            rerank_scores=[0.9, 0.4, 0.35, 0.1, 0.05], AI_RERANK_KEEP_RATIO=0
        )
        self.assertEqual([c.page for c, _ in result], [1, 2, 3])

    def test_empty_ranked_falls_back_to_vector(self):
        """协议异常（重排返回空列表）：回退纯向量 top_k，不把候选全部丢弃。"""
        result, _ = self._run(rerank_scores=[])
        self.assertEqual([c.page for c, _ in result], [1, 2, 3, 4, 5])


class RerankThresholdResolutionTests(SimpleTestCase):
    """_resolve_rerank_threshold：显式环境变量 > 按模型名匹配 > 默认值。"""

    def test_resolve_by_model_name(self):
        from apps.ai.services import _resolve_rerank_threshold

        self.assertEqual(_resolve_rerank_threshold("gte-rerank-v2"), 0.05)
        self.assertEqual(_resolve_rerank_threshold("qwen3-rerank"), 0.3)
        # 本地 Qwen3-Reranker 的完整 ModelScope ID 也命中 qwen3-reranker 子串
        self.assertEqual(_resolve_rerank_threshold("Qwen/Qwen3-Reranker-0.6B"), 0.3)
        # 未配置/未知模型回退默认阈值
        self.assertEqual(_resolve_rerank_threshold(""), 0.3)
        self.assertEqual(_resolve_rerank_threshold("some-unknown-rerank"), 0.3)

    def test_explicit_env_threshold_wins_over_model_table(self):
        from apps.ai.services import _resolve_rerank_threshold

        with override_settings(AI_RERANK_THRESHOLD=0.42):
            self.assertEqual(_resolve_rerank_threshold("gte-rerank-v2"), 0.42)
        # 未显式配置（None）时回到分模型阈值
        with override_settings(AI_RERANK_THRESHOLD=None):
            self.assertEqual(_resolve_rerank_threshold("gte-rerank-v2"), 0.05)
