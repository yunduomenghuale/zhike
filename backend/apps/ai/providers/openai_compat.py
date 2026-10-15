"""通用 OpenAI 兼容 Provider。

适配任何提供 OpenAI 兼容接口的服务（DeepSeek、阿里 MaaS、本地 vLLM 等）：
- chat  POST {base_url}/chat/completions
- embed POST {base_url}/embeddings（未配置 embed_model 或调用失败时回退到 Mock 向量，
        保证知识库检索仍可用；DeepSeek 无 embedding 接口即走此回退）
- rerank  DashScope 原生端点 /services/rerank/text-rerank/text-rerank
        （OpenAI 兼容生态无统一 /rerank 规范，仅 DashScope 可用）
"""
from __future__ import annotations

import json
import os
import uuid

import requests
from django.conf import settings

from .base import BaseAIProvider
from .mock import MockProvider


class _Http4xxError(RuntimeError):
    """4xx 客户端错误（含上下文超限）：不重试，直接上抛给上层识别降级。"""


# 向量接口批量上限（DashScope text-embedding-v3 为 10 条/批，超限整批 400）。
# 保守取 10：对上限更高的服务只是多两次往返，不会失败。
_EMBED_BATCH_SIZE = 10


def _http_error_detail(resp) -> str:
    """把错误响应体转成可读信息。

    requests 的 HTTPError 只带 URL 不带响应体，而真正的错误原因在 body 里
    （DashScope 404 实为 {"code":"InvalidParameter","message":"Model not exist."}，
     即模型名不存在/已下线；连接测试需要看到它才能定位）。
    错误字段有两种形态：顶层 code/message（DashScope 原生）与
    error.code/error.message（OpenAI 兼容网关），都要解析。
    """
    try:
        body = resp.json()
    except Exception:
        return f"HTTP {resp.status_code}: {resp.text[:200]}"
    if not isinstance(body, dict):
        return f"HTTP {resp.status_code}: {resp.text[:200]}"
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = body.get("code") or err.get("code") or ""
    message = body.get("message") or err.get("message") or ""
    detail = f"HTTP {resp.status_code}"
    if code:
        detail += f" {code}"
    if message:
        detail += f": {message}"
    return detail


def _tts_error_detail(resp) -> str:
    """提取 TTS 错误响应体里的真实原因（兼容 OpenAI 与 DashScope 两种错误结构）。

    OpenAI 兼容服务（含本地 localai/AllTalk）错误体为 {"error": {"message", "code"}}；
    DashScope 原生端点错误体为顶层 {"code", "message"}。
    """
    try:
        body = resp.json()
    except Exception:
        return f"HTTP {resp.status_code}: {resp.text[:200]}"
    if not isinstance(body, dict):
        return f"HTTP {resp.status_code}: {resp.text[:200]}"
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = err.get("code") or body.get("code") or ""
    message = err.get("message") or body.get("message") or ""
    detail = f"HTTP {resp.status_code}"
    if code:
        detail += f" {code}"
    if message:
        detail += f": {message}"
    return detail


class OpenAICompatProvider(BaseAIProvider):
    def __init__(self, config: dict, name: str = "openai-compat"):
        self.name = name
        self.api_key = config.get("api_key", "")
        self.base_url = config.get("base_url", "").rstrip("/")
        self.chat_model = config.get("chat_model", "")
        self.embed_model = config.get("embed_model", "")  # 为空则走 mock 向量
        self.rerank_model = config.get("rerank_model", "")  # 为空则不支持重排序
        self.tts_model = config.get("tts_model", "")      # 为空则不支持 TTS
        # 管理端可配的超时(秒)/发音人；为空时回退 settings 默认值（AI_TTS_TIMEOUT / AI_TTS_VOICE）
        try:
            self.timeout = int(config.get("timeout")) if config.get("timeout") else None
        except (TypeError, ValueError):
            self.timeout = None
        self.voice = (config.get("voice") or "").strip()
        self._mock = MockProvider()
        # 记录最近一次 TTS 失败原因（连接测试/配音失败时展示）；空字符串=无失败记录
        self.last_tts_error = ""
        # 记录最近一次 chat 是否回退到 Mock：空字符串=真实模型返回，非空=真实调用失败已回退。
        # 调用方（如目录识别）可据此判断返回内容是否可信。
        self.last_chat_error = ""

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def chat(self, messages: list[dict], **kwargs) -> str:
        # 每次调用先清零，保证 last_chat_error 反映的是「本次」而非历史调用的结果。
        self.last_chat_error = ""
        last_error = None
        for _ in range(kwargs.get("retries", 2)):
            try:
                payload = {
                    "model": kwargs.get("model", self.chat_model),
                    "messages": messages,
                    "temperature": kwargs.get("temperature", 0.6),
                }
                if "enable_thinking" in kwargs:
                    payload["enable_thinking"] = kwargs["enable_thinking"]
                if "max_tokens" in kwargs:
                    payload["max_tokens"] = kwargs["max_tokens"]
                resp = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                    timeout=kwargs.get("timeout", 180),
                )
                if 400 <= resp.status_code < 500:
                    # 4xx（含上下文超限）重试无意义：带错误体上抛给上层识别降级，
                    # 不能当成普通失败吞掉后静默回退 Mock。
                    hint = ""
                    try:
                        hint = str(resp.json().get("error", {}).get("message", ""))
                    except Exception:
                        hint = resp.text[:500]
                    raise _Http4xxError(f"HTTP {resp.status_code}: {hint}")
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except _Http4xxError:
                raise
            except Exception as exc:
                last_error = exc
        self.last_chat_error = str(last_error) if last_error else ""
        # 目录识别等场景要求「真模型或明确失败」，不接受静默回退到 Mock 的占位内容。
        if not kwargs.get("fallback_to_mock", True):
            raise last_error or RuntimeError("AI chat 调用失败")
        return self._mock.chat(messages, **kwargs)

    def chat_stream(self, messages: list[dict], **kwargs):
        """真流式：OpenAI 兼容 stream=True，逐 token 产出 delta.content。

        请求失败时回退到 Mock 的分片流式，保证前端始终能拿到内容。
        """
        payload = {
            "model": kwargs.get("model", self.chat_model),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.6),
            "stream": True,
        }
        if "enable_thinking" in kwargs:
            payload["enable_thinking"] = kwargs["enable_thinking"]
        if "max_tokens" in kwargs:
            payload["max_tokens"] = kwargs["max_tokens"]
        try:
            with requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                stream=True,
                timeout=kwargs.get("timeout", 120),
            ) as resp:
                if 400 <= resp.status_code < 500:
                    # 4xx（含上下文超限）不能静默回退 Mock——上抛给上层识别降级
                    hint = ""
                    try:
                        hint = str(resp.json().get("error", {}).get("message", ""))
                    except Exception:
                        hint = resp.text[:500]
                    raise _Http4xxError(f"HTTP {resp.status_code}: {hint}")
                resp.raise_for_status()
                for raw in resp.iter_lines(decode_unicode=True):
                    if not raw:
                        continue
                    line = raw.strip()
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    choices = obj.get("choices") or [{}]
                    piece = (choices[0].get("delta") or {}).get("content")
                    if piece:
                        yield piece
        except _Http4xxError:
            raise
        except Exception:
            # 回退：分片产出 Mock 结果，前端仍表现为流式
            yield from self._mock.chat_stream(messages, **kwargs)

    def embed(self, texts: list[str], *, allow_fallback: bool = True) -> list[list[float]]:
        # 未配置嵌入模型 -> 直接用 mock（如 DeepSeek 无 embedding 接口）
        if not self.embed_model:
            if allow_fallback:
                return self._mock.embed(texts)
            raise NotImplementedError(f"{self.name} 未配置向量模型")
        # 向量服务普遍有批量上限：DashScope text-embedding-v3 为 10 条/批，
        # 超限整批 400（batch size is invalid）。课件逐页入库/长资料切分很容易
        # 超过 10 条，这里统一分批请求再按顺序拼接，调用方无感。
        if len(texts) <= _EMBED_BATCH_SIZE:
            return self._embed_batch(texts, allow_fallback)
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(texts), _EMBED_BATCH_SIZE):
                vectors.extend(
                    self._embed_batch(texts[start : start + _EMBED_BATCH_SIZE], allow_fallback=False)
                )
        except Exception:
            # 与不分批时语义一致：允许回退则整批换 mock（不混杂真实/假向量），
            # 否则上抛真实错误（重建/连接测试要求「真模型或明确失败」）
            if not allow_fallback:
                raise
            return self._mock.embed(texts)
        return vectors

    def _embed_batch(self, texts: list[str], allow_fallback: bool) -> list[list[float]]:
        resp = None
        try:
            resp = requests.post(
                f"{self.base_url}/embeddings",
                headers=self._headers(),
                json={"model": self.embed_model, "input": texts},
                # 管理端可配超时；未配则 60s。本地 embed 服务冷启动/CPU 推理慢，易整批超时
                timeout=self.timeout or 60,
            )
            resp.raise_for_status()
            return [item["embedding"] for item in resp.json()["data"]]
        except Exception as exc:
            # 嵌入不可用时回退，保证知识库入库/检索不中断；
            # allow_fallback=False（连接测试）时上抛真实错误，避免误报成功
            if allow_fallback:
                return self._mock.embed(texts)
            if resp is not None and resp.status_code >= 400:
                raise RuntimeError(_http_error_detail(resp)) from exc
            raise

    def _rerank_uses_dashscope_native(self) -> bool:
        """判断重排序是否走 DashScope 原生端点。

        OpenAI 兼容生态没有统一的 /rerank 端点规范（DashScope 的
        compatible-mode 也没有，实测 404），仅 DashScope 原生端点
        /api/v1/services/rerank/text-rerank/text-rerank 可用（gte-rerank-v2 等）。
        """
        base = (self.base_url or "").lower()
        return "dashscope" in base or "compatible-mode" in base

    def rerank(self, query: str, documents: list[str], top_n: int | None = None) -> list[dict]:
        """DashScope 原生重排序（gte-rerank-v2）：对检索候选按 query 相关性重新打分。

        向量检索是纯余弦相似度，关键词面重合但语义不相关的片段也会拿高分；
        重排模型按 query-document 语义相关性打分，可把噪声片段压到低分段。

        请求体必须包 input/parameters（少了会 400 Field required）；
        响应在 output.results[]，每项含 index（documents 下标）与 relevance_score。
        返回 [{"index": int, "score": float}]，按分数降序；失败原样上抛，
        由上层（检索编排）回退纯向量结果——重排是增强项，不能拖垮问答主链路。
        """
        if not self.rerank_model:
            raise NotImplementedError(f"{self.name} 未配置重排序模型")
        if not self._rerank_uses_dashscope_native():
            raise NotImplementedError(f"{self.name} 暂不支持重排序（仅 DashScope 原生端点）")
        if not documents:
            return []

        # compatible-mode/v1 -> api/v1（rerank 走原生接口）
        native = self.base_url.replace("/compatible-mode/v1", "/api/v1")
        limit = min(top_n or len(documents), len(documents))
        resp = requests.post(
            f"{native}/services/rerank/text-rerank/text-rerank",
            headers=self._headers(),
            json={
                "model": self.rerank_model,
                "input": {"query": query, "documents": documents},
                "parameters": {"top_n": limit, "return_documents": False},
            },
            # 重排是单次轻量请求，取管理端超时，未配则 60s
            timeout=self.timeout or 60,
        )
        if resp.status_code >= 400:
            # 透出响应体里的真实原因（模型不存在/输入超限等），连接测试需要它定位
            raise RuntimeError(_http_error_detail(resp))
        resp.raise_for_status()

        results = (resp.json().get("output") or {}).get("results") or []
        ranked = [
            {"index": int(item["index"]), "score": float(item.get("relevance_score") or 0.0)}
            for item in results
            if isinstance(item, dict) and "index" in item
        ]
        if not ranked:
            # 200 但无结果属于协议异常（不是「全不相关」）：上抛让上层回退纯向量，
            # 而不是把候选全部丢弃导致问答无资料可用
            raise RuntimeError("重排序接口未返回结果")
        ranked.sort(key=lambda x: x["score"], reverse=True)
        # top_n 限定返回条数（DashScope 按 parameters.top_n 收敛，这里再兜底一次）
        return ranked[:limit] if top_n else ranked

    def _tts_uses_dashscope_native(self) -> bool:
        """判断 TTS 是否走 DashScope 原生多模态端点。

        DashScope（含 compatible-mode）的 TTS 仅提供原生端点
        /api/v1/services/aigc/multimodal-generation/generation；
        其余 OpenAI 兼容服务（OpenAI 官方、本地 localai/AllTalk 等）
        统一走 /audio/speech。
        """
        base = (self.base_url or "").lower()
        return "dashscope" in base or "compatible-mode" in base

    def tts(self, text: str, voice: str | None = None, speed: float = 1.0) -> str:
        """文本转语音，返回落地到本地 media 的音频可访问路径（避免临时 URL 过期）。

        两条分支：
        - DashScope 原生端点（base_url 含 dashscope / compatible-mode）：
          模型如 qwen3-tts-flash，返回音频 URL 后下载落盘（_tts_dashscope）；
        - 其余 OpenAI 兼容服务（OpenAI 官方、本地 localai/AllTalk 等）：
          POST {base_url}/audio/speech，音频二进制直接落盘（_tts_openai_compatible）。

        发音人优先级：调用参数 > 管理端配置(voice) > settings.AI_TTS_VOICE > Cherry。
        超时取管理端配置(timeout)，未配则 settings.AI_TTS_TIMEOUT（默认 120s，
        AI_TTS_TIMEOUT 环境变量可调大）——本地 TTS（尤其 CPU 推理）合成慢，不调大易超时。
        """
        if not self.tts_model:
            raise NotImplementedError(f"{self.name} 未配置 TTS 模型")
        voice = voice or self.voice or getattr(settings, "AI_TTS_VOICE", "Cherry")
        if self._tts_uses_dashscope_native():
            return self._tts_dashscope(text, voice)
        return self._tts_openai_compatible(text, voice, speed)

    def _tts_timeout(self) -> int:
        return self.timeout or getattr(settings, "AI_TTS_TIMEOUT", 120)

    def _tts_dashscope(self, text: str, voice: str) -> str:
        """DashScope 原生多模态端点 TTS（qwen3-tts-flash 等）。

        注意：旧模型 qwen-tts 已被 DashScope 下线（404 Model not exist），
        当前可用模型为 qwen3-tts-flash / qwen3-tts-instruct-flash。
        """
        timeout = self._tts_timeout()
        # compatible-mode/v1 -> api/v1（TTS 走原生接口）
        native = self.base_url.replace("/compatible-mode/v1", "/api/v1")
        last_error = None
        resp = None
        for _ in range(3):
            try:
                resp = requests.post(
                    f"{native}/services/aigc/multimodal-generation/generation",
                    headers=self._headers(),
                    json={"model": self.tts_model, "input": {"text": text, "voice": voice}},
                    timeout=timeout,
                )
                resp.raise_for_status()
                audio = resp.json()["output"]["audio"]
                break
            except Exception as exc:
                # 4xx/5xx 时提取响应体里的真实原因（如模型不存在），
                # 连接测试/配音失败时能看到「Model not exist」而不是一串 URL
                last_error = (
                    RuntimeError(_http_error_detail(resp))
                    if resp is not None and resp.status_code >= 400
                    else exc
                )
        else:
            self.last_tts_error = str(last_error) if last_error else ""
            raise last_error or RuntimeError("TTS 请求失败")

        url = audio.get("url")
        if not url:
            raise RuntimeError("TTS 未返回音频地址")

        last_error = None
        for _ in range(3):
            try:
                download = requests.get(url, timeout=timeout)
                download.raise_for_status()
                content = download.content
                break
            except Exception as exc:
                last_error = exc
        else:
            self.last_tts_error = str(last_error) if last_error else ""
            raise last_error or RuntimeError("TTS 音频下载失败")

        ext = ".wav" if ".wav" in url.lower() else ".mp3" if ".mp3" in url.lower() else ".wav"
        rel = f"tts/{uuid.uuid4().hex}{ext}"
        dest = os.path.join(settings.MEDIA_ROOT, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(content)
        return f"{settings.MEDIA_URL}{rel}"

    def _tts_openai_compatible(self, text: str, voice: str, speed: float) -> str:
        """OpenAI 兼容 TTS：POST {base_url}/audio/speech，音频二进制直接落盘。

        适用于本地 TTS 服务（localai / AllTalk / 其他 OpenAI audio 兼容实现）
        与 OpenAI 官方语音接口。发音人 voice 由服务端自行解释（本地服务多为
        说话人 ID）；response_format 请求 mp3，最终扩展名按 Content-Type 判定。
        """
        timeout = self._tts_timeout()
        payload = {
            "model": self.tts_model,
            "input": text,
            "voice": voice,
            "speed": speed,
            "response_format": "mp3",
        }
        last_error = None
        resp = None
        for _ in range(3):
            resp = None
            try:
                resp = requests.post(
                    f"{self.base_url}/audio/speech",
                    headers=self._headers(),
                    json=payload,
                    timeout=timeout,
                )
                if 400 <= resp.status_code < 500:
                    # 4xx（模型不存在/发音人不支持/端点缺失）重试无意义：提取错误体上抛
                    raise _Http4xxError(
                        f"{_tts_error_detail(resp)}（端点 {self.base_url}/audio/speech）"
                    )
                resp.raise_for_status()
                content = resp.content
                if not content:
                    raise RuntimeError("TTS 接口返回空音频")
                break
            except _Http4xxError as exc:
                self.last_tts_error = str(exc)[:300]
                raise
            except Exception as exc:
                last_error = exc
        else:
            self.last_tts_error = str(last_error)[:300] if last_error else ""
            raise last_error or RuntimeError("TTS 请求失败")

        # 扩展名按 Content-Type 判定（各本地服务默认格式不一：mp3/wav/ogg/flac/m4a）
        ctype = (resp.headers.get("Content-Type") or "").lower()
        ext = ".mp3"
        if "wav" in ctype:
            ext = ".wav"
        elif "ogg" in ctype:
            ext = ".ogg"
        elif "flac" in ctype:
            ext = ".flac"
        elif "aac" in ctype or "m4a" in ctype or "mp4" in ctype:
            ext = ".m4a"

        rel = f"tts/{uuid.uuid4().hex}{ext}"
        dest = os.path.join(settings.MEDIA_ROOT, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(content)
        return f"{settings.MEDIA_URL}{rel}"
