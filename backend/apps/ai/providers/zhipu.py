"""智谱 GLM Provider（OpenAI 兼容风格调用）。

Chat:  POST https://open.bigmodel.cn/api/paas/v4/chat/completions
Embed: POST https://open.bigmodel.cn/api/paas/v4/embeddings
仅在 AI_PROVIDER=zhipu 且配置了 ZHIPU_API_KEY 时启用。
"""
from __future__ import annotations

import requests

from .base import BaseAIProvider

BASE = "https://open.bigmodel.cn/api/paas/v4"


class ZhipuProvider(BaseAIProvider):
    name = "zhipu"

    def __init__(self, config: dict):
        self.api_key = config.get("api_key", "")
        self.base_url = config.get("base_url", BASE).rstrip("/") or BASE
        self.chat_model = config.get("chat_model", "glm-4-flash")
        self.embed_model = config.get("embed_model", "embedding-3")

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def chat(self, messages: list[dict], **kwargs) -> str:
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": kwargs.get("model", self.chat_model),
                "messages": messages,
                "temperature": kwargs.get("temperature", 0.6),
            },
            timeout=kwargs.get("timeout", 60),
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = requests.post(
            f"{self.base_url}/embeddings",
            headers=self._headers(),
            json={"model": self.embed_model, "input": texts},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return [item["embedding"] for item in data]
