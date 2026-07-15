"""通义千问 Provider（阿里 DashScope OpenAI 兼容模式）。

Base: https://dashscope.aliyuncs.com/compatible-mode/v1
Chat / Embeddings 走 OpenAI 兼容接口；TTS(CosyVoice) 走 DashScope 原生接口。
仅在 AI_PROVIDER=tongyi 且配置了 TONGYI_API_KEY 时启用。
"""
from __future__ import annotations

import requests

from .base import BaseAIProvider

BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class TongyiProvider(BaseAIProvider):
    name = "tongyi"

    def __init__(self, config: dict):
        self.api_key = config.get("api_key", "")
        self.chat_model = config.get("chat_model", "qwen-plus")
        self.embed_model = config.get("embed_model", "text-embedding-v3")
        self.tts_model = config.get("tts_model", "cosyvoice-v1")

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def chat(self, messages: list[dict], **kwargs) -> str:
        resp = requests.post(
            f"{BASE}/chat/completions",
            headers=self._headers(),
            json={
                "model": kwargs.get("model", self.chat_model),
                "messages": messages,
                "temperature": kwargs.get("temperature", 0.6),
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = requests.post(
            f"{BASE}/embeddings",
            headers=self._headers(),
            json={"model": self.embed_model, "input": texts},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return [item["embedding"] for item in data]

    def tts(self, text: str, voice: str = "longxiaochun", speed: float = 1.0) -> str:
        # TODO: 接入 DashScope CosyVoice 语音合成接口，返回音频 URL。
        # 需异步任务落地音频文件后回写地址（见 services.synthesize_video）。
        raise NotImplementedError("通义 TTS 待接入 CosyVoice")
