"""统一 API 响应结构：{ code, message, data }。"""
from rest_framework.response import Response
from rest_framework.views import exception_handler


def api_response(data=None, message="ok", code=0, status=200):
    return Response({"code": code, "message": message, "data": data}, status=status)


def custom_exception_handler(exc, context):
    """把 DRF 默认异常包装成统一结构。"""
    response = exception_handler(exc, context)
    if response is None:
        return response

    detail = response.data
    if isinstance(detail, dict) and "detail" in detail:
        message = detail["detail"]
        payload = None
    else:
        message = "请求错误"
        payload = detail

    response.data = {
        "code": response.status_code,
        "message": str(message),
        "data": payload,
    }
    return response
