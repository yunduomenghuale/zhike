"""课程扩展资源门控：签名 URL 签发/校验 + 预置静态页读出（base 注入）。

背景：思维导图/交互演示为平台预置静态页（deploy/resources 只读资产）。
每条 CourseResource 持有独立 access_token，对外链接唯一；
页面与资产不经过 nginx 公开目录，一律由本模块验签后读出：

- 入口页  GET /api/course-resources/page/{token}/?sig=&exp=
- 资产    GET /api/course-resources/asset/{token}/{sig}/{exp}/{rest}
- 预置预览（教师添加资源前试看，无需资源行）
  签发 POST /api/course-resources/preset-sign/  →  GET /api/course-resources/preset/{sig}/{exp}/{path}
  资产    GET /api/course-resources/preset-asset/{sig}/{exp}/{rest}

签名为 HMAC-SHA256（密钥 SECRET_KEY），2 小时有效；签名消息带发布状态，
教师下架资源后旧链接立即失效。资产与入口页共用同一 token 级签名：
持有某资源有效链接的用户在 2 小时内可读取同教材预置资产（如 vendor 库），
已评估可接受（同课程参考内容，短时效）。
"""
import hashlib
import hmac
import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

SIGN_TTL = timedelta(hours=2)

PAGE_URL = "/api/course-resources/page/{token}/"
FILE_URL = "/api/course-resources/file/{token}/"
ASSET_URL = "/api/course-resources/asset/{token}/{sig}/{exp}/{parent}/"
PRESET_PAGE_URL = "/api/course-resources/preset/{sig}/{exp}/{path}"
PRESET_ASSET_URL = "/api/course-resources/preset-asset/{sig}/{exp}/"

# 与 CourseResourceSerializer.validate_path 保持一致：仅平台预置单层页面
PRESET_PATH_RE = re.compile(r"(mindmap|demos)/[A-Za-z0-9_\-]+\.html")

_MIME_MAP = {
    ".html": "text/html", ".htm": "text/html", ".js": "text/javascript",
    ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".ico": "image/x-icon", ".woff": "font/woff", ".woff2": "font/woff2",
    ".ttf": "font/ttf", ".map": "application/json", ".txt": "text/plain",
    ".pdf": "application/pdf", ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_CHARSET_TYPES = {"text/html", "text/javascript", "text/css", "application/json", "image/svg+xml", "text/plain"}

_BASE_TAG_RE = re.compile(r"<head[^>]*>", re.IGNORECASE)


def _hmac(message: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()


def _expires_ts() -> int:
    return int((timezone.now() + SIGN_TTL).timestamp())


# ---------------------------------------------------------------------------
# 资源（按行）签名
# ---------------------------------------------------------------------------

def sign_resource(resource) -> dict:
    """为资源签发带时效的访问 URL（教师预览/学生学习统一入口）。

    文档类签文件流地址（PDF 内联/doc 下载由输出端点按扩展名决定），
    预置类签入口页地址；verify_resource 同口径校验（签名含发布状态）。
    """
    expires_ts = _expires_ts()
    sig = _hmac(f"{resource.access_token}.{expires_ts}.{1 if resource.is_published else 0}")
    template = FILE_URL if resource.kind == "document" else PAGE_URL
    return {
        "url": f"{template.format(token=resource.access_token)}?sig={sig}&exp={expires_ts}",
        "expires_at": timezone.now() + SIGN_TTL,
    }


def verify_resource(resource, sig: str, exp: str) -> bool:
    """校验入口页/资产签名：存在、未过期、且发布状态与签名时一致。"""
    try:
        expires_ts = int(exp)
    except (TypeError, ValueError):
        return False
    if expires_ts <= int(timezone.now().timestamp()):
        return False
    expected = _hmac(f"{resource.access_token}.{expires_ts}.{1 if resource.is_published else 0}")
    return hmac.compare_digest(expected, sig or "")


def asset_base(resource, sig: str, exp: str) -> str:
    """入口页 <base>：让页内相对引用（../vendor、image/、章节互链）落到签名资产路由。"""
    parent = resource.path.rsplit("/", 1)[0] if "/" in resource.path else ""
    return ASSET_URL.format(token=resource.access_token, sig=sig, exp=exp, parent=parent)


# ---------------------------------------------------------------------------
# 预置页（无资源行，教师添加前预览）签名
# ---------------------------------------------------------------------------

def sign_preset(path: str) -> dict:
    """为平台预置页路径签发预览 URL（仅教师可调用，见视图层权限）。"""
    expires_ts = _expires_ts()
    sig = _hmac(f"preset.{expires_ts}")
    return {
        "url": f"{PRESET_PAGE_URL.format(sig=sig, exp=expires_ts, path=path)}",
        "expires_at": timezone.now() + SIGN_TTL,
    }


def verify_preset(sig: str, exp: str) -> bool:
    try:
        expires_ts = int(exp)
    except (TypeError, ValueError):
        return False
    if expires_ts <= int(timezone.now().timestamp()):
        return False
    return hmac.compare_digest(_hmac(f"preset.{expires_ts}"), sig or "")


def preset_asset_base(sig: str, exp: str, parent: str) -> str:
    return f"{PRESET_ASSET_URL.format(sig=sig, exp=exp)}{parent}/"


# ---------------------------------------------------------------------------
# 文件读出与 HTML 注入
# ---------------------------------------------------------------------------

def _safe_join(rest: str):
    """把站内相对路径解析到 RESOURCES_ROOT 内，防目录穿越；非文件返回 None。"""
    rest = (rest or "").lstrip("/")
    if not rest or "\\" in rest or ".." in rest.split("/"):
        return None
    try:
        root = Path(settings.RESOURCES_ROOT).resolve()
        candidate = (root / rest).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate if candidate.is_file() else None


def read_page(resource) -> str | None:
    # 自定义 HTML（导图/演示上传，path 为空）从上传存储读；预置页从 RESOURCES_ROOT 读
    if not resource.path and resource.file:
        try:
            return resource.file.open("rb").read().decode("utf-8", errors="replace")
        except OSError:
            return None
    path = _safe_join(resource.path)
    return None if path is None else path.read_text(encoding="utf-8", errors="replace")


def read_asset(rest: str):
    return _safe_join(rest)


def inject_base(html: str, base_href: str) -> str:
    """在 <head> 后注入 <base>，使页内相对引用走签名资产路由。"""
    tag = f'<base href="{base_href}">'
    match = _BASE_TAG_RE.search(html)
    if match:
        return html[: match.end()] + tag + html[match.end():]
    return tag + html


def guess_content_type(path: Path) -> str:
    ctype = _MIME_MAP.get(path.suffix.lower())
    if not ctype:
        import mimetypes

        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if ctype in _CHARSET_TYPES:
        ctype += "; charset=utf-8"
    return ctype


def guess_content_type_name(filename: str) -> str:
    """按文件名猜 Content-Type（文档文件端点用，上传文件不在 RESOURCES_ROOT）。"""
    import mimetypes

    suffix = Path(filename).suffix.lower()
    ctype = _MIME_MAP.get(suffix) or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if ctype in _CHARSET_TYPES:
        ctype += "; charset=utf-8"
    return ctype
