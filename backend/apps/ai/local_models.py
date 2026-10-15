"""系统内置本地模型：权重下载与进程内推理缓存。

两个内置能力：
- 向量化 embed：BGE-M3（BAAI，dense 1024 维，sentence-transformers 加载）
- 重排序 rerank：Qwen3-Reranker-0.6B（阿里开源，transformers 加载，
  causal-LM yes/no 打分——取 "yes"/"no" token 的 logits 做 softmax 得相关性概率）

设计约定：
- 权重放 settings.AI_MODELS_DIR（默认 backend/data/models；生产容器内经
  /app/data bind mount 持久化，重建容器不丢）。
- 下载源 ModelScope（国内可达）；首次使用惰性下载，manage.py download_models
  可预热，镜像构建 PRELOAD_MODELS=true 可预置（entrypoint 拷入数据卷）。
- 模型对象进程内单例（懒加载 + 双检锁）；推理加锁串行——torch CPU 下并发
  推理无收益且可能互相踩踏。gunicorn 每 worker 各持一份（内存随加载增长：
  BGE-M3 FP32 约 2.3GB、Qwen3-Reranker 约 1.2GB，仅实际启用时才加载）。
"""
from __future__ import annotations

import threading
from pathlib import Path

from django.conf import settings

# 能力 -> 默认模型（settings.AI_SETTINGS["local"] 可经环境变量覆盖；
# 管理端按能力配置的 model_name 优先于这里的默认值）
DEFAULT_MODELS = {
    "embed": "BAAI/bge-m3",
    "rerank": "Qwen/Qwen3-Reranker-0.6B",
}

_load_lock = threading.Lock()
_infer_lock = threading.Lock()
_embedder_cache: dict[str, object] = {}
_reranker_cache: dict[str, tuple] = {}


def default_model(kind: str) -> str:
    """能力默认模型名：环境变量 > 内置默认。"""
    conf = getattr(settings, "AI_SETTINGS", {}).get("local", {})
    key = "embed_model" if kind == "embed" else "rerank_model"
    return conf.get(key) or DEFAULT_MODELS[kind]


def model_path(name: str) -> Path:
    """模型本地路径：绝对路径直用，否则解析到 AI_MODELS_DIR/<namespace>/<name>。"""
    p = Path(str(name or "").strip())
    if p.is_absolute():
        return p
    return Path(settings.AI_MODELS_DIR) / str(name).strip()


def is_downloaded(name: str) -> bool:
    """粗略判定权重已就绪：目录存在且含 config.json。"""
    path = model_path(name)
    return path.is_dir() and (path / "config.json").exists()


def ensure_downloaded(name: str) -> Path:
    """确保权重在本地：缺失则经 ModelScope 下载（snapshot_download 原子落盘）。"""
    path = model_path(name)
    if is_downloaded(name):
        return path
    try:
        from modelscope import snapshot_download
    except ImportError as exc:  # 依赖未安装（如裁剪环境）时给出可操作的指引
        raise RuntimeError("缺少 modelscope 依赖，请先 pip install modelscope") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # 新版 modelscope 支持 local_dir（落盘位置即加载位置，免二次搬运）
        snapshot_download(str(name), local_dir=str(path))
    except TypeError:
        # 旧版仅支持 cache_dir，落点为 cache_dir/<namespace>/<name>，与 model_path 一致
        snapshot_download(str(name), cache_dir=str(Path(settings.AI_MODELS_DIR)))
    if not is_downloaded(name):
        raise RuntimeError(f"模型 {name} 下载后校验失败（缺少 config.json）")
    return path


def get_embedder(name: str):
    """加载（并缓存）BGE-M3 向量模型（sentence-transformers，CPU）。"""
    path = ensure_downloaded(name)
    key = str(path)
    model = _embedder_cache.get(key)
    if model is None:
        with _load_lock:
            model = _embedder_cache.get(key)
            if model is None:
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer(str(path), device="cpu")
                _embedder_cache[key] = model
    return model


def embed_texts(name: str, texts: list[str]) -> list[list[float]]:
    """BGE-M3 dense 向量（L2 归一化，检索侧余弦等价点积）。推理串行。"""
    model = get_embedder(name)
    with _infer_lock:
        vectors = model.encode(
            list(texts), normalize_embeddings=True, show_progress_bar=False
        )
    return [list(map(float, row)) for row in vectors]


_RERANK_PREFIX = (
    "<|im_start|>system\nJudge whether the Document meets the requirements based on "
    "the Query and the Instruct provided. Note that the answer can only be \"yes\" or "
    "\"no\".<|im_end|>\n<|im_start|>user\n"
)
_RERANK_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
_RERANK_INSTRUCTION = (
    "Given a web search query, retrieve relevant passages that answer the query"
)
_RERANK_MAX_LEN = 1024  # 单候选 query+doc 的 token 上限（课件片段约 500 字，足够）


def get_reranker(name: str) -> tuple:
    """加载（并缓存）Qwen3-Reranker：返回 (tokenizer, model, yes_id, no_id)。"""
    path = ensure_downloaded(name)
    key = str(path)
    bundle = _reranker_cache.get(key)
    if bundle is None:
        with _load_lock:
            bundle = _reranker_cache.get(key)
            if bundle is None:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer

                tokenizer = AutoTokenizer.from_pretrained(str(path), padding_side="left")
                model = AutoModelForCausalLM.from_pretrained(
                    str(path), torch_dtype=torch.float32
                )
                model.eval()
                bundle = (
                    tokenizer,
                    model,
                    tokenizer.convert_tokens_to_ids("yes"),
                    tokenizer.convert_tokens_to_ids("no"),
                )
                _reranker_cache[key] = bundle
    return bundle


def rerank_scores(name: str, query: str, documents: list[str]) -> list[float]:
    """Qwen3-Reranker 官方打分：yes/no 双 token logits softmax，取 P(yes)。

    返回与 documents 等长的 0~1 相关性分。推理串行。
    """
    import torch

    tokenizer, model, yes_id, no_id = get_reranker(name)
    prefix_ids = tokenizer.encode(_RERANK_PREFIX, add_special_tokens=False)
    suffix_ids = tokenizer.encode(_RERANK_SUFFIX, add_special_tokens=False)
    budget = _RERANK_MAX_LEN - len(prefix_ids) - len(suffix_ids)
    pairs = [
        f"<Instruct>: {_RERANK_INSTRUCTION}\n<Query>: {query}\n<Document>: {doc}"
        for doc in documents
    ]
    inputs = tokenizer(
        pairs,
        padding=False,
        truncation="longest_first",
        return_attention_mask=False,
        max_length=budget,
    )
    for i, ids in enumerate(inputs["input_ids"]):
        inputs["input_ids"][i] = prefix_ids + ids + suffix_ids
    inputs = tokenizer.pad(
        inputs, padding=True, return_tensors="pt", max_length=_RERANK_MAX_LEN
    )
    with _infer_lock, torch.no_grad():
        logits = model(**inputs).logits[:, -1, :]
        pair_logits = torch.stack([logits[:, no_id], logits[:, yes_id]], dim=1)
        probs = torch.nn.functional.softmax(pair_logits, dim=1)
    return [float(s) for s in probs[:, 1].tolist()]
