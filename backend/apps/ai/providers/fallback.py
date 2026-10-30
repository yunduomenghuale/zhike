"""AI Provider 静默回退的显性化标记（P5-B7）。

回退（真实 provider 失败/未配置 → Mock）发生时打标，请求收口处消费并写进
响应体 `provider_fallback=true` + `fallback_reason`，前端展示「当前为模拟数据」
角标；管理端按 AICallLog.is_mock 聚合可见回退告警。

用 contextvars 而非实例属性：provider 可能被单例复用（多请求共享），实例属性
会串号；contextvar 天然按请求上下文隔离。显式配置 provider=mock 不算回退，不打标。
"""
import contextvars

_fallback_reason: contextvars.ContextVar = contextvars.ContextVar("ai_provider_fallback", default=None)


def mark_fallback(reason: str) -> None:
    """标记本次请求上下文发生过 Mock 回退（保留首个原因，不覆盖）。"""
    if reason and not _fallback_reason.get():
        _fallback_reason.set(str(reason)[:300])


def current_fallback() -> str:
    """读取当前上下文的回退原因（未回退为空串）。"""
    return _fallback_reason.get() or ""


def consume_fallback() -> str:
    """读取并清空回退标记（响应收口处用，避免同一请求多次响应重复携带）。"""
    val = _fallback_reason.get() or ""
    if val:
        _fallback_reason.set(None)
    return val
