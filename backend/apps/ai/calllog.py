"""AI 调用埋点：统一记录每次 Provider 调用的流水（AICallLog）。

设计要点：
- Provider 层（openai_compat / local / mock）是全部 AI 调用的唯一收口，
  在这里埋点即可同时覆盖外部服务、本地 OpenAI 兼容服务与系统内置本地模型；
- 业务上下文（场景 scene / 关联课程 / trace_id）经 contextvars 传递，
  由 services.py 等调用方用 ai_scene() 声明，触发人由中间件写入；
- 计量口径分两类：HTTP 类服务解析响应 usage 得 token；进程内本地模型
  无 token，以条数/字符数计量；
- 内容留痕只存输入指纹（sha256）与截断摘要，不落 prompt/响应全文；
- 写库失败只记日志，绝不影响主业务；高频场景可按 settings 采样。

典型用法（Provider 内）：

    with record_ai_call("chat", self.name, self.chat_model, input_text=messages) as rec:
        ...  # 发起请求
        rec.set_usage(resp_json.get("usage"))
        rec.set_output(text)

流式（chat_stream）：

    yield from record_stream("chat", self.name, model, gen(), input_text=messages)
"""
from __future__ import annotations

import contextvars
import functools
import hashlib
import inspect
import logging
import random
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings

logger = logging.getLogger(__name__)

# 业务上下文：由 ai_scene() 设置，同一业务请求内的多次调用共享
_scene_ctx: ContextVar[dict] = ContextVar("ai_call_scene", default=None)

# 当前请求用户：由 AiCallJWTAuthentication 写入（管理命令等无请求场景为 None）
_current_user: ContextVar[dict] = ContextVar("ai_call_user", default=None)

# 当前请求对象引用：由中间件暂存，落库时兜底解析触发人（DRF 认证在视图内完成）
_request_ref: ContextVar = ContextVar("ai_call_request", default=None)

# 嵌套抑制：OpenAICompatProvider 回退 Mock 时置位，避免 Mock 内部重复记一条流水
_nested_suppress: ContextVar[bool] = ContextVar("ai_call_nested_suppress", default=False)

_PREVIEW_LIMIT = 200  # 输入摘要截断长度


@contextmanager
def suppress_recording():
    """抑制区域内的埋点落库（供「真实调用失败回退 Mock」的嵌套调用使用）。"""
    token = _nested_suppress.set(True)
    try:
        yield
    finally:
        _nested_suppress.reset(token)


def _sample_rate(scene: str) -> float:
    """高频场景采样率：settings.AI_CALL_LOG_SAMPLE = {"qa": 0.2}，未配置的场景全记。"""
    rates = getattr(settings, "AI_CALL_LOG_SAMPLE", {}) or {}
    try:
        return max(0.0, min(1.0, float(rates.get(scene, 1.0))))
    except (TypeError, ValueError):
        return 1.0


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()


def _flatten_input(input_text) -> str:
    """把 messages / 字符串 / 列表统一成可哈希的文本表示。"""
    if input_text is None:
        return ""
    if isinstance(input_text, str):
        return input_text
    try:
        import json

        return json.dumps(input_text, ensure_ascii=False, default=str)
    except Exception:
        return str(input_text)


@contextmanager
def ai_scene(scene: str, *, course_id: int | None = None):
    """声明业务场景：进入即生成 trace_id，退出恢复。

    一次业务请求（如学生问答）内的 embed/rerank/chat 多次调用共享同一
    trace_id，管理端可据此串联成一条调用链。嵌套调用沿用外层场景。
    """
    current = _scene_ctx.get()
    if current is not None and current.get("scene") == scene:
        # 同场景重复进入（如分批讲稿的多次批次）：沿用既有 trace_id
        yield current
        return
    token = _scene_ctx.set(
        {
            "scene": scene,
            "course_id": course_id,
            "trace_id": uuid.uuid4().hex,
        }
    )
    try:
        yield _scene_ctx.get()
    finally:
        _scene_ctx.reset(token)


def set_current_user(user):
    """中间件入口：记录当前请求用户（只存 id 与用户名，触发时再取）。"""
    if user is not None and getattr(user, "is_authenticated", False):
        _current_user.set({"id": user.id, "username": user.username})
    else:
        _current_user.set(None)


def clear_current_user():
    _current_user.set(None)


def set_request_ref(request):
    """中间件入口：暂存请求对象（返回 contextvar token 供重置）。"""
    return _request_ref.set(request)


def reset_request_ref(token):
    _request_ref.reset(token)


def scene_decorator(scene: str, course_getter=None):
    """业务函数装饰器：进入函数即声明 AI 调用场景（见 ai_scene）。

    对普通函数与生成器函数均生效（生成器在迭代期间保持场景）。
    course_getter: (args, kwargs) -> course_id | None，从参数提取关联课程。

    用法：
        @scene_decorator(AICallLog.Scene.QA, course_getter=lambda a, kw: a[0])
        def knowledge_qa(course_id, ...): ...
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            course_id = None
            if course_getter is not None:
                try:
                    course_id = course_getter(args, kwargs)
                except Exception:
                    course_id = None
            if inspect.isgeneratorfunction(fn):
                # 生成器函数：调用仅创建生成器（不执行函数体），迭代期间保持场景
                return _scene_generator(fn(*args, **kwargs), scene, course_id)
            # 普通函数：必须先进入场景再执行，否则函数体内的调用记不到场景
            with ai_scene(scene, course_id=course_id):
                result = fn(*args, **kwargs)
            if inspect.isgenerator(result):
                # 普通函数返回生成器（如返回生成器表达式）：迭代期间同样保持场景
                return _scene_generator(result, scene, course_id)
            return result

        return wrapper

    return decorator


def _scene_generator(gen, scene: str, course_id):
    with ai_scene(scene, course_id=course_id):
        yield from gen


def copy_call_context():
    """复制当前调用上下文（场景/trace_id/触发人/抑制标记）快照。

    线程池不会把 contextvars 带进工作线程，提交任务时需显式复制、
    在 worker 内经 run_in_context 恢复，否则并发批次的调用流水会丢场景归属。
    """
    return contextvars.copy_context()


def run_in_context(ctx, fn, *args, **kwargs):
    """在复制的上下文中执行函数（配合 copy_call_context 用于线程池任务）。"""
    return ctx.run(fn, *args, **kwargs)


def _resolve_user():
    """触发人解析优先级：认证类显式写入 > 场景上下文手动注入 > 暂存请求的 user。

    第三级兜底覆盖 session 认证与测试 force_authenticate——DRF 认证通过
    Request.user setter 把用户回写到 Django request 上，落库时（视图执行中）
    读取即可拿到。
    """
    current = _current_user.get()
    if current:
        return current
    scene = _scene_ctx.get() or {}
    if scene.get("user"):
        return scene["user"]
    request = _request_ref.get()
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return {"id": user.id, "username": user.username}
    return None


class _CallRecord:
    """单次调用的记录 accumulator，退出 with 时落库。"""

    def __init__(self, capability: str, provider: str, model: str, input_text=None, item_count=None):
        self.capability = capability
        self.provider = provider or ""
        self.model = model or ""
        self.scene_ctx = _scene_ctx.get() or {}
        self.item_count = item_count
        self.input_chars = None
        self.output_chars = None
        self.input_digest = ""
        self.input_preview = ""
        if input_text is not None:
            flat = _flatten_input(input_text)
            self.input_chars = len(flat)
            self.input_digest = _digest(flat)
            self.input_preview = flat[:_PREVIEW_LIMIT]
        self.usage = None
        self.is_mock = False
        self.attempts = 1
        self.error = ""
        self.latency_ms = 0

    def set_usage(self, usage):
        """记录 HTTP 类服务响应的 usage（prompt/completion/total tokens）。"""
        if isinstance(usage, dict):
            self.usage = usage

    def set_output(self, output):
        if isinstance(output, str):
            self.output_chars = len(output)
        elif isinstance(output, (list, tuple)):
            self.output_chars = len(output)
            if self.item_count is None:
                self.item_count = len(output)

    def mark_mock(self):
        self.is_mock = True

    def _build(self, success: bool) -> dict:
        user = _resolve_user()
        prompt_tokens = completion_tokens = total_tokens = None
        if self.usage:
            try:
                prompt_tokens = int(self.usage.get("prompt_tokens") or 0) or None
                completion_tokens = int(self.usage.get("completion_tokens") or 0) or None
                total_tokens = int(
                    self.usage.get("total_tokens")
                    or (prompt_tokens or 0) + (completion_tokens or 0)
                ) or None
            except (TypeError, ValueError):
                prompt_tokens = completion_tokens = total_tokens = None
        return {
            "capability": self.capability,
            "provider": self.provider,
            "model_name": self.model[:120],
            "scene": self.scene_ctx.get("scene") or "other",
            "success": success,
            "is_mock": self.is_mock,
            "error": self.error[:300],
            "latency_ms": self.latency_ms,
            "attempts": self.attempts,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "item_count": self.item_count,
            "input_chars": self.input_chars,
            "output_chars": self.output_chars,
            "input_digest": self.input_digest,
            "input_preview": self.input_preview,
            "trace_id": self.scene_ctx.get("trace_id") or "",
            "triggered_by_id": user.get("id") if user else None,
            "course_id": self.scene_ctx.get("course_id"),
        }

    def flush(self, success: bool):
        if _nested_suppress.get():
            return
        scene = self.scene_ctx.get("scene") or "other"
        if not success and _sample_rate(scene) < 1.0:
            # 失败调用永远记录（排障需要），采样只作用于成功调用
            pass
        elif random.random() >= _sample_rate(scene):
            return
        try:
            from .models import AICallLog

            AICallLog.objects.create(**self._build(success))
        except Exception:
            # 埋点是旁路观测：DB 不可用/字段异常都不能影响主业务流程
            logger.exception("写入 AI 调用流水失败（%s/%s）", self.capability, self.provider)


@contextmanager
def record_ai_call(capability: str, provider: str, model: str, *, input_text=None, item_count=None):
    """记录一次调用：进入计时，正常退出记成功，异常退出记失败后原样上抛。"""
    import time

    rec = _CallRecord(capability, provider, model, input_text=input_text, item_count=item_count)
    started = time.monotonic()
    try:
        yield rec
    except Exception as exc:
        rec.latency_ms = int((time.monotonic() - started) * 1000)
        rec.error = str(exc)
        rec.flush(success=False)
        raise
    rec.latency_ms = int((time.monotonic() - started) * 1000)
    rec.flush(success=True)


def record_stream(
    capability: str,
    provider: str,
    model: str,
    generator,
    *,
    input_text=None,
    is_mock: bool = False,
    state=None,
):
    """包装流式生成器：逐段转发，累计输出字符数，结束后落库。

    生成器惰性执行：计时从首个 next()（真正发起请求）开始。
    失败时记录错误摘要并原样上抛，保证上层降级逻辑不受影响。
    is_mock：调用方预先知道是 Mock 直连时传 True；
    state：调用方可变的 dict，迭代中置 state["mock"]=True 表示发生了
    Mock 回退（流式路径拿不到内部的 rec，经它转标 is_mock）。
    """
    import time

    rec = _CallRecord(capability, provider, model, input_text=input_text)
    if is_mock:
        rec.mark_mock()
    started = None
    success = True
    try:
        for piece in generator:
            if started is None:
                started = time.monotonic()
            if piece:
                rec.output_chars = (rec.output_chars or 0) + len(piece)
            yield piece
    except Exception as exc:
        success = False
        rec.error = str(exc)
        raise
    finally:
        if state and state.get("mock"):
            rec.mark_mock()
        rec.latency_ms = int(((time.monotonic() - (started or time.monotonic())) * 1000))
        rec.flush(success=success)
