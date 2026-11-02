"""AI 调用闸门：限制同时在飞的 provider 调用数（三层并发之第三层）。

设计见 docs/AI长任务队列化改造方案.md §5.1：
- chat / tts 各一把进程级 BoundedSemaphore，包在任务流水线的**单次调用**外层
  （挂点：讲稿块、配音页、分析分批、生题分组、ingest embed，共 5 处）；
- **不要挂在 factory.get_provider() 上**——那会把学生 RAG 的 SSE 流式问答也
  罩进来，一条流持锁 30s，等于把交互功能拖到后台任务的节奏上；
- 闸门持锁期间必须是纯 HTTP 等待，不得再进 DB 事务（否则行锁持到秒级）。

worker 单副本下进程级信号量即全局真相；未来扩副本需改 DB 计数（方案 §5.1）。
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

from django.conf import settings

_LOCK = threading.Lock()
_GATES: dict[str, threading.BoundedSemaphore | None] = {}


def _gate(capability: str) -> threading.BoundedSemaphore | None:
    with _LOCK:
        if capability not in _GATES:
            limit = {
                "chat": settings.AI_MAX_CONCURRENT_CHAT,
                "tts": settings.AI_MAX_CONCURRENT_TTS,
            }.get(capability)
            _GATES[capability] = (
                threading.BoundedSemaphore(limit) if limit and limit > 0 else None
            )
        return _GATES[capability]


@contextmanager
def gated(capability: str):
    """在闸门内执行一次 provider 调用。未配置的能力（如 embed 走远程不限）直接放行。"""
    gate = _gate(capability)
    if gate is None:
        yield
        return
    gate.acquire()
    try:
        yield
    finally:
        gate.release()


def in_flight(capability: str) -> int:
    """当前在飞数（健康检查/测试用）：信号量没有内置计数，用虚拟占用探测。"""
    gate = _gate(capability)
    if gate is None:
        return 0
    n = 0
    while gate.acquire(blocking=False):
        n += 1
    for _ in range(n):
        gate.release()
    return n


def reset_gates() -> None:
    """测试专用：重建全部闸门（settings 被测试覆盖后旧信号量容量失效）。"""
    with _LOCK:
        _GATES.clear()
