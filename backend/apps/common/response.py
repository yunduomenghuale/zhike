"""统一 API 响应结构：{ code, message, data }。"""
from rest_framework import status
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from rest_framework.views import exception_handler


def api_response(data=None, message="ok", code=0, status=200):
    return Response({"code": code, "message": message, "data": data}, status=status)


def _format_error_detail(detail):
    if isinstance(detail, dict):
        parts = []
        for field, value in detail.items():
            msg = _format_error_detail(value)
            if msg:
                # non_field_errors 是对象级校验，字段前缀无意义，直接展示消息本身
                parts.append(msg if field == "non_field_errors" else f"{field}: {msg}")
        return "；".join(parts)
    if isinstance(detail, list):
        return "，".join(str(item) for item in detail)
    return str(detail) if detail is not None else ""


def custom_exception_handler(exc, context):
    """把 DRF 默认异常包装成统一结构。"""
    response = exception_handler(exc, context)
    if response is None:
        return response

    # 限流（429）：DRF 默认英文文案本地化，并透传等待秒数。
    # 配额类限流（P5-B6 check_ai_quota）以自定义 code=ai_quota 标记，透传其业务中文
    # detail（「已达上限/联系管理员」）；普通频控保持泛化提示。不能用 detail 内容
    # 判断——DRF 会把 wait 拼进 detail，默认文案永远不等于 default_detail。
    if isinstance(exc, Throttled):
        wait = int(exc.wait) if exc.wait else 60
        # APIException 不存 self.code，code 编在 ErrorDetail 里，经 get_codes() 取出
        quota_code = None
        try:
            quota_code = exc.get_codes()
        except Exception:
            quota_code = None
        custom = str(exc.detail) if quota_code == "ai_quota" else ""
        response.data = {
            "code": status.HTTP_429_TOO_MANY_REQUESTS,
            "message": custom or f"操作过于频繁，请 {wait} 秒后再试",
            "data": None,
        }
        response["Retry-After"] = str(wait)
        return response

    detail = response.data
    if isinstance(detail, dict) and "detail" in detail:
        message = detail["detail"]
        payload = None
    else:
        message = _format_error_detail(detail) or "请求错误"
        payload = detail

    response.data = {
        "code": response.status_code,
        "message": str(message),
        "data": payload,
    }
    return response
