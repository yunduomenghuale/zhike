"""批量导入接口：模板下载 / 预览 / 确认（班级、教师、学生三类共用）。

接口约定（方案 §3.2）：

    GET  /api/admin-panel/imports/template/?kind=class|teacher|student   → xlsx
    POST /api/admin-panel/imports/preview/   multipart: file, kind       → 逐行校验结果
    POST /api/admin-panel/imports/commit/    json: kind, rows, options   → 结果汇总

预览与确认都不信任前端：`commit` 会用服务端校验结果重算一遍，
前端传来的 `row_status` / `message` 一律忽略。
"""

from __future__ import annotations

import base64

from django.http import HttpResponse
from rest_framework import status
from rest_framework.views import APIView

from apps.common.permissions import IsPlatformAdmin
from apps.common.response import api_response

from .imports import (
    KIND_CLASS,
    KIND_STUDENT,
    MAX_FILE_SIZE,
    ImportFileError,
    ImportValidationError,
    annotate_rows,
    build_template,
    commit,
    get_spec,
    parse_excel,
)
from .throttles import AdminScopedThrottle

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _file_payload(filename: str, content: bytes) -> dict:
    """把生成的 xlsx 以 base64 带回响应，前端转 Blob 下载（无状态，不落临时文件）。"""
    return {
        "filename": filename,
        "content_base64": base64.b64encode(content).decode("ascii"),
        "size": len(content),
    }


class AdminImportTemplateView(APIView):
    """下载某一类的导入模板（含填写说明页）。"""

    permission_classes = [IsPlatformAdmin]
    throttle_classes = [AdminScopedThrottle]
    method_scopes = {"GET": "admin_read"}

    def get(self, request):
        kind = request.query_params.get("kind", "")
        try:
            spec = get_spec(kind)
        except ImportFileError as exc:
            return api_response(message=str(exc), code=400, status=400)
        response = HttpResponse(build_template(kind), content_type=XLSX_CONTENT_TYPE)
        response["Content-Disposition"] = f"attachment; filename=import_template_{spec.kind}.xlsx"
        return response


class AdminImportPreviewView(APIView):
    """上传 Excel 解析 + 逐行校验，返回预览页需要的全部信息。"""

    permission_classes = [IsPlatformAdmin]
    throttle_classes = [AdminScopedThrottle]
    method_scopes = {"POST": "admin_heavy"}

    def post(self, request):
        kind = request.data.get("kind", "")
        try:
            get_spec(kind)
        except ImportFileError as exc:
            return api_response(message=str(exc), code=400, status=400)

        upload = request.FILES.get("file")
        if not upload:
            return api_response(message="请上传 Excel 文件", code=400, status=400)
        if not str(upload.name).lower().endswith(".xlsx"):
            return api_response(message="仅支持 .xlsx 文件，请使用系统模板", code=400, status=400)
        if upload.size > MAX_FILE_SIZE:
            return api_response(message="文件大小不能超过 5MB", code=400, status=400)

        # 预览阶段就带上「自动建班」开关与默认届别，让待建班级清单能算出届别/人数
        options = {
            "create_missing_classes": _as_bool(request.data.get("create_missing_classes"), True),
            "default_enrollment_year": _as_int(request.data.get("default_enrollment_year")),
            "default_duration_years": _as_int(request.data.get("default_duration_years")),
            "approved_classes": [],
        }
        try:
            rows = parse_excel(upload, kind)
        except ImportFileError as exc:
            return api_response(message=str(exc), code=400, status=400)

        result = annotate_rows(kind, rows, options)
        return api_response({
            "kind": kind,
            "file_name": upload.name,
            **result,
        })


class AdminImportCommitView(APIView):
    """确认导入：服务端重新校验 → 单事务写入 → 返回结果汇总与可下载文件。"""

    permission_classes = [IsPlatformAdmin]
    throttle_classes = [AdminScopedThrottle]
    method_scopes = {"POST": "admin_heavy"}

    def post(self, request):
        kind = request.data.get("kind", "")
        try:
            spec = get_spec(kind)
        except ImportFileError as exc:
            return api_response(message=str(exc), code=400, status=400)

        rows = request.data.get("rows")
        if not isinstance(rows, list) or not rows:
            return api_response(message="没有可导入的数据", code=400, status=400)

        raw_options = request.data.get("options") or {}
        options = {
            "skip_invalid": _as_bool(raw_options.get("skip_invalid"), False),
            "create_missing_classes": _as_bool(raw_options.get("create_missing_classes"), True),
            "default_enrollment_year": _as_int(raw_options.get("default_enrollment_year")),
            "default_duration_years": _as_int(raw_options.get("default_duration_years")),
            "approved_classes": raw_options.get("approved_classes") or [],
        }

        try:
            result = commit(kind, rows, options, operator=request.user)
        except ImportFileError as exc:
            return api_response(message=str(exc), code=400, status=400)
        except ImportValidationError as exc:
            return api_response(
                {"rows": exc.rows},
                message=exc.message,
                code=400,
                status=400,
            )

        payload = {
            "kind": result["kind"],
            "created_users": result["created_users"],
            "created_classes": result["created_classes"],
            "created_members": result["created_members"],
            "skipped": result["skipped"],
            "failed": result["failed"],
            "failures": result["failures"],
            # 结果页下载项：失败行（改完可直接重传）与初始密码表
            "failure_file": _file_payload(
                f"import_failures_{kind}.xlsx", result["failure_file"]
            ) if result.get("failure_file") else None,
            "password_file": _file_payload(
                f"initial_passwords_{kind}.xlsx", result["password_file"]
            ) if result.get("password_file") else None,
        }
        message = _result_message(kind, result)
        return api_response(payload, message=message,
                            status=status.HTTP_201_CREATED)


def _result_message(kind: str, result: dict) -> str:
    parts = []
    if result["created_users"]:
        parts.append(f"导入 {result['created_users']} 个账号")
    if result["created_classes"]:
        parts.append(f"新建 {len(result['created_classes'])} 个班级")
    if result["created_members"]:
        parts.append(f"入班 {result['created_members']} 人")
    if result["skipped"]:
        parts.append(f"跳过 {result['skipped']} 行")
    if result["failed"]:
        parts.append(f"失败 {result['failed']} 行")
    if not parts:
        return "没有需要导入的数据"
    if kind == KIND_CLASS and not result["created_users"] and not result["created_classes"]:
        return "；".join(parts) + "（编码均已存在，未做修改）"
    if kind == KIND_STUDENT and not result["created_users"]:
        return "；".join(parts)
    return "；".join(parts)


def _as_bool(value, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes", "on")


def _as_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
