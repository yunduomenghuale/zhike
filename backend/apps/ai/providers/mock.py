"""Mock AI provider for local development."""
from __future__ import annotations

import hashlib
import json
import math

from .base import BaseAIProvider

_DIM = 64


class MockProvider(BaseAIProvider):
    name = "mock"

    def chat_stream(self, messages: list[dict], **kwargs):
        """把整段回答切成小片段产出，模拟打字机式流式输出。"""
        text = self.chat(messages, **kwargs)
        for i in range(0, len(text), 3):
            yield text[i : i + 3]

    def chat(self, messages: list[dict], **kwargs) -> str:
        content = messages[-1]["content"] if messages else ""

        if "CATALOG_EXTRACT" in content:
            return json.dumps(
                [
                    {
                        "title": "第一章 Java语言基础",
                        "children": [
                            {"title": "1.1 Java开发环境与程序结构"},
                            {"title": "1.2 数据类型、变量与运算符"},
                        ],
                    },
                    {
                        "title": "第二章 面向对象程序设计",
                        "children": [
                            {"title": "2.1 类与对象"},
                            {"title": "2.2 继承、多态与接口"},
                        ],
                    },
                    {
                        "title": "第三章 综合课程设计实践",
                        "children": [
                            {"title": "3.1 项目需求分析与设计"},
                            {"title": "3.2 编码实现、测试与答辩"},
                        ],
                    },
                ],
                ensure_ascii=False,
            )

        if "识别章节" in content or "授课计划" in content:
            return json.dumps(
                [
                    {
                        "title": "第一章 绪论",
                        "children": [{"title": "1.1 课程简介"}, {"title": "1.2 学习目标"}],
                    },
                    {
                        "title": "第二章 基础知识",
                        "children": [{"title": "2.1 基本概念"}, {"title": "2.2 核心原理"}],
                    },
                ],
                ensure_ascii=False,
            )

        if "生成题目" in content:
            return json.dumps(
                [
                    {
                        "qtype": "single",
                        "stem": "以下关于本章核心概念的说法，正确的是？",
                        "options": [
                            {"key": "A", "text": "选项一"},
                            {"key": "B", "text": "选项二"},
                            {"key": "C", "text": "选项三"},
                            {"key": "D", "text": "选项四"},
                        ],
                        "answer": {"key": "B"},
                        "analysis": "（Mock）B 项符合章节定义。",
                        "difficulty": "medium",
                        "knowledge_tags": ["核心概念"],
                    }
                ],
                ensure_ascii=False,
            )

        if "讲解稿" in content:
            return "（Mock 讲解稿）本页介绍了核心知识点，请结合课件内容理解要点。"

        if "知识库" in content or "参考资料" in content:
            return "（Mock 回答）根据课程资料，该问题的要点如下；如需精确内容请查看对应章节。"

        return f"（Mock）已收到：{content[:60]}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._fake_vector(t) for t in texts]

    def _fake_vector(self, text: str) -> list[float]:
        vec = [0.0] * _DIM
        for token in text:
            h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            vec[h % _DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def tts(self, text: str, voice: str = "default", speed: float = 1.0) -> str:
        return "/media/mock/tts_placeholder.mp3"
