"""系统内置本地模型 Provider（name="local"）。

与「本地模型服务」（openai，OpenAI 兼容的外部端点）不同：local 是系统自带推理——
权重在 backend/data/models（生产为数据卷 /app/data/models），CPU 直接跑：

- embed  向量化：BGE-M3（sentence-transformers，dense 1024 维、L2 归一化）
- rerank 重排序：Qwen3-Reranker-0.6B（yes/no logits softmax 概率分）

无需 API Key / 接口地址；权重缺失时经 ModelScope 惰性下载（部署期可由
Dockerfile PRELOAD_MODELS=true 预置 + entrypoint 拷入数据卷）。
权重加载与推理实现见 apps/ai/local_models.py（进程内单例 + 推理串行锁）。
chat / tts 本地无内置实现，走白名单限制不可选。
"""
from __future__ import annotations

from ..calllog import record_ai_call
from .base import BaseAIProvider


class LocalModelsProvider(BaseAIProvider):
    name = "local"

    def __init__(self, config: dict, capability: str = ""):
        from apps.ai.local_models import default_model

        self.config = dict(config or {})
        self.capability = capability
        # 模型名：管理端按能力配置（config["model"]）> 环境变量/内置默认
        self.model = self.config.get("model") or (
            default_model(capability) if capability in ("embed", "rerank") else ""
        )
        self.timeout = self.config.get("timeout")  # 本地无 HTTP 超时语义，仅记录展示

    def chat(self, messages: list[dict], **kwargs) -> str:
        raise NotImplementedError("系统内置本地模型暂不支持对话生成，请选择线上服务商")

    def embed(self, texts: list[str], *, allow_fallback: bool = True) -> list[list[float]]:
        # allow_fallback 对 local 无意义（本地没有可回退的 Mock——真失败必须上抛，
        # 杜绝假向量污染向量空间），形参仅为与调用方契约一致
        if not texts:
            return []
        with record_ai_call(
            "embed", self.name, self.model, input_text=texts, item_count=len(texts)
        ) as rec:
            from apps.ai.local_models import embed_texts

            vectors = embed_texts(self.model, texts)
            rec.set_output(vectors)
            return vectors

    def rerank(self, query: str, documents: list[str], top_n: int | None = None) -> list[dict]:
        if not documents:
            return []
        with record_ai_call(
            "rerank", self.name, self.model, input_text=query, item_count=len(documents)
        ) as rec:
            from apps.ai.local_models import rerank_scores

            scores = rerank_scores(self.model, query, documents)
            ranked = [
                {"index": i, "score": float(score)} for i, score in enumerate(scores)
            ]
            ranked.sort(key=lambda item: item["score"], reverse=True)
            rec.set_output(ranked)
            return ranked[:top_n] if top_n else ranked

    def tts(self, text: str, voice: str = "default", speed: float = 1.0) -> str:
        raise NotImplementedError("系统内置本地模型暂不支持语音合成，请选择线上服务商")
