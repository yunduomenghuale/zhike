"""AI Provider 抽象接口。

统一三类能力，业务层只依赖此接口，不感知具体厂商：
- chat  文本生成（目录识别 / 讲解稿 / 出题 / RAG 回答 / 批改）
- embed 文本向量化（知识库入库与检索）
- tts   文本转语音（AI 配音）

新增厂商只需实现 BaseAIProvider 并在 factory 注册。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseAIProvider(ABC):
    name = "base"

    @abstractmethod
    def chat(self, messages: list[dict], **kwargs) -> str:
        """messages: [{"role": "system|user|assistant", "content": "..."}]，返回文本。"""

    def chat_stream(self, messages: list[dict], **kwargs):
        """流式生成，逐段产出文本片段。

        默认实现回退为「一次性返回整段」，子类可覆盖为真正的 SSE 流式。
        """
        yield self.chat(messages, **kwargs)

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """返回与 texts 等长的向量列表。"""

    def tts(self, text: str, voice: str = "default", speed: float = 1.0) -> str:
        """文本转语音，返回音频可访问地址（或本地路径）。默认未实现。"""
        raise NotImplementedError(f"{self.name} 暂不支持 TTS")
