"""虚拟实验页门控：签名 URL 签发/校验 + 静态页读出（与课程资源门控同构）。

背景：实验本体是 deploy/labs 下的静态 HTML（原由 nginx /labs/ 公开直出，
下线后直链仍可访问、链接地址可猜测）。现与课程资源统一：
- 每条 Lab 持有独立 access_token，对外链接 /api/lab-gate/page/{token}/?sig=&exp=
- 签名为 HMAC-SHA256（密钥 SECRET_KEY），2 小时有效，消息带发布状态——
  教师下线后旧链接立即失效；重新上线后需从课程实验页重新进入（重新签发）
- 入口页注入 <base>，页内相对引用（lab-bridge.js 等）走签名资产路由
- 双层防护：门控管「页面可读」，页内 bridge 仍需一次性 attempt_token
  才能取随机种子/提交成绩（数据层不受页面层影响）
"""
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.courses import resource_gate

PAGE_URL = "/api/lab-gate/page/{token}/"
ASSET_URL = "/api/lab-gate/asset/{token}/{sig}/{exp}/"


def sign_lab(lab) -> dict:
    """为实验签发带时效的入口页 URL（学生「进入实验」时由 start 动作返回）。"""
    expires_ts = resource_gate._expires_ts()
    published = 1 if lab.status == lab.Status.PUBLISHED else 0
    sig = resource_gate._hmac(f"lab.{lab.access_token}.{expires_ts}.{published}")
    return {
        "url": f"{PAGE_URL.format(token=lab.access_token)}?sig={sig}&exp={expires_ts}",
        "expires_at": timezone.now() + resource_gate.SIGN_TTL,
    }


def verify_lab(lab, sig: str, exp: str) -> bool:
    """校验实验门控签名：未过期 + 发布状态与签名时一致（下线即失效）。"""
    try:
        expires_ts = int(exp)
    except (TypeError, ValueError):
        return False
    if expires_ts <= int(timezone.now().timestamp()):
        return False
    published = 1 if lab.status == lab.Status.PUBLISHED else 0
    expected = resource_gate._hmac(f"lab.{lab.access_token}.{expires_ts}.{published}")
    from hmac import compare_digest

    return compare_digest(expected, sig or "")


def asset_base(lab, sig: str, exp: str) -> str:
    """入口页 <base>：lab-bridge.js 等相对引用落到签名资产路由。"""
    return ASSET_URL.format(token=lab.access_token, sig=sig, exp=exp)


def _lab_page_relpath(lab) -> str:
    """模板静态页相对 LABS_ROOT 的路径：static_path（/labs/x.html）或缺省 {code}.html。"""
    raw = (lab.template.static_path or "").strip() or f"/labs/{lab.template.code}.html"
    name = raw.rsplit("/labs/", 1)[-1] if "/labs/" in raw else raw.lstrip("/")
    return name


def read_page(lab) -> str | None:
    """读实验入口 HTML；文件不存在返回 None。"""
    root = Path(settings.LABS_ROOT).resolve()
    try:
        candidate = (root / _lab_page_relpath(lab)).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate.read_text(encoding="utf-8", errors="replace") if candidate.is_file() else None


def read_asset(rest: str):
    """实验页资产（lab-bridge.js 等）：限制在 LABS_ROOT 内，防目录穿越。"""
    rest = (rest or "").lstrip("/")
    if not rest or "\\" in rest or ".." in rest.split("/"):
        return None
    try:
        root = Path(settings.LABS_ROOT).resolve()
        candidate = (root / rest).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate if candidate.is_file() else None
