"""通用 OpenAI 兼容 Provider。

适配任何提供 OpenAI 兼容接口的服务（DeepSeek、阿里 MaaS、本地 vLLM 等）：
- chat  POST {base_url}/chat/completions
- embed POST {base_url}/embeddings（未配置 embed_model 或调用失败时回退到 Mock 向量，
        保证知识库检索仍可用；DeepSeek 无 embedding 接口即走此回退）
"""
from __future__ import annotations

import json

import requests

from .base import BaseAIProvider
from .mock import MockProvider


class OpenAICompatProvider(BaseAIProvider):
    def __init__(self, config: dict, name: str = "openai-compat"):
        self.name = name
        self.api_key = config.get("api_key", "")
        self.base_url = config.get("base_url", "").rstrip("/")
        self.chat_model = config.get("chat_model", "")
        self.embed_model = config.get("embed_model", "")  # 为空则走 mock 向量
        self.tts_model = config.get("tts_model", "")      # 为空则不支持 TTS
        self._mock = MockProvider()
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
                    timeout=kwargs.get("timeout", 90),
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
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
        except Exception:
            # 回退：分片产出 Mock 结果，前端仍表现为流式
            yield from self._mock.chat_stream(messages, **kwargs)

    def embed(self, texts: list[str]) -> list[list[float]]:
        # 未配置嵌入模型 -> 直接用 mock（如 DeepSeek 无 embedding 接口）
        if not self.embed_model:
            return self._mock.embed(texts)
        try:
            resp = requests.post(
                f"{self.base_url}/embeddings",
                headers=self._headers(),
                json={"model": self.embed_model, "input": texts},
                timeout=60,
            )
            resp.raise_for_status()
            return [item["embedding"] for item in resp.json()["data"]]
        except Exception:
            # 嵌入不可用时回退，保证知识库入库/检索不中断
            return self._mock.embed(texts)

    def tts(self, text: str, voice: str = "Cherry", speed: float = 1.0) -> str:
        """文本转语音（DashScope 原生 qwen-tts）。

        返回落地到本地 media 的音频可访问路径（避免临时 OSS URL 过期）。
        """
        if not self.tts_model:
            raise NotImplementedError(f"{self.name} 未配置 TTS 模型")

        import os
        import uuid

        from django.conf import settings

        # compatible-mode/v1 -> api/v1（TTS 走原生接口）
        native = self.base_url.replace("/compatible-mode/v1", "/api/v1")
        last_error = None
        for _ in range(3):
            try:
                resp = requests.post(
                    f"{native}/services/aigc/multimodal-generation/generation",
                    headers=self._headers(),
                    json={"model": self.tts_model, "input": {"text": text, "voice": voice}},
                    timeout=120,
                )
                resp.raise_for_status()
                audio = resp.json()["output"]["audio"]
                break
            except Exception as exc:
                last_error = exc
        else:
            self.last_tts_error = str(last_error) if last_error else ""
            raise last_error or RuntimeError("TTS 请求失败")

        url = audio.get("url")
        if not url:
            raise RuntimeError("TTS 未返回音频地址")

        last_error = None
        for _ in range(3):
            try:
                download = requests.get(url, timeout=90)
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
