"""虚拟实验页门控：签名 URL 签发/校验 + 静态页读出（与课程资源门控同构）。

背景：实验本体是 deploy/labs 下的静态 HTML（原由 nginx /labs/ 公开直出，
下线后直链仍可访问、链接地址可猜测）。现与课程资源统一：
- 每条 Lab 持有独立 access_token，对外链接 /api/lab-gate/page/{token}/?sig=&exp=
- 签名为 HMAC-SHA256（密钥 SECRET_KEY），2 小时有效，消息带发布状态——
  教师下线后旧链接立即失效；重新上线后需从课程实验页重新进入（重新签发）
- 入口页注入 <base>，页内相对引用（lab-bridge.js 等）走签名资产路由
- 双层防护：门控管「页面可读」，页内 bridge 仍需一次性 attempt_token
  才能取随机种子/提交成绩（数据层不受页面层影响）

v3.2 / L2（custom 实验）三分流：
- template → 原逻辑（预置 HTML + lab-bridge.js，票据在页面 URL）
- custom 父页面 /api/lab-gate/page/{token}/ → 平台父页面（持票据，唯一代发上报）
- custom iframe  /api/lab-gate/frame/{token}/{sig}/{exp}/ → 教师 HTML + 无票据 shim
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.courses import resource_gate

PAGE_URL = "/api/lab-gate/page/{token}/"
ASSET_URL = "/api/lab-gate/asset/{token}/{sig}/{exp}/"
FRAME_URL = "/api/lab-gate/frame/{token}/{sig}/{exp}/"
PARENT_TEMPLATE = "lab-gate-parent.html"

# 注入前先剥掉教师 HTML 里已有的 <base>（两个 <base> 时浏览器取第一个，签名 base 会失效）
_BASE_STRIP_RE = re.compile(r"<base\b[^>]*>", re.IGNORECASE)
# <head ...> 开口标签后紧跟 <base> 与桥接脚本
_HEAD_OPEN_RE = re.compile(r"<head\b[^>]*>", re.IGNORECASE)


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


def sign_preview(lab) -> dict:
    """教师预览签名：消息 lab.{token}.{exp}.preview，与正式签名不可互换，不绑定发布状态。"""
    expires_ts = resource_gate._expires_ts()
    sig = resource_gate._hmac(f"lab.{lab.access_token}.{expires_ts}.preview")
    return {
        "url": f"{PAGE_URL.format(token=lab.access_token)}?sig={sig}&exp={expires_ts}&preview=1",
        "expires_at": timezone.now() + resource_gate.SIGN_TTL,
    }


def verify_preview(lab, sig: str, exp: str) -> bool:
    """校验预览签名：只验时效与签名本身（草稿也可预览），与发布状态无关。"""
    try:
        expires_ts = int(exp)
    except (TypeError, ValueError):
        return False
    if expires_ts <= int(timezone.now().timestamp()):
        return False
    expected = resource_gate._hmac(f"lab.{lab.access_token}.{expires_ts}.preview")
    from hmac import compare_digest

    return compare_digest(expected, sig or "")


def frame_url(lab, sig: str, exp: str, preview: bool = False) -> str:
    """iframe 内容页绝对路径（C45：必须绝对路径，否则被父页面 <base> 改写到资产路由）。

    预览时 sig/exp 是预览签名并带 preview=1（frame 视图据此走 verify_preview）。
    """
    url = FRAME_URL.format(token=lab.access_token, sig=sig, exp=exp)
    return f"{url}?preview=1" if preview else url


def _asset_sig_exp(lab, sig: str, exp: str, preview: bool) -> tuple:
    """资产路由只认正式签名（lab_gate_asset → verify_lab）。

    预览页的 URL 签名是 preview 消息，不能直接拿去当 <base>：否则
    lab-bridge-parent.js / lab-bridge-shim.js 全部 403。预览时另签一对正式 sig/exp
    （签名绑定当前发布状态，草稿同样有效），URL 本身仍用预览签名。
    """
    if not preview:
        return sig, exp
    from urllib.parse import parse_qs, urlparse

    query = parse_qs(urlparse(sign_lab(lab)["url"]).query)
    return query["sig"][0], query["exp"][0]


def asset_base(lab, sig: str, exp: str) -> str:
    """入口页 <base>：lab-bridge.js 等相对引用落到签名资产路由。"""
    return ASSET_URL.format(token=lab.access_token, sig=sig, exp=exp)


def _lab_page_relpath(lab) -> str | None:
    """模板静态页相对 LABS_ROOT 的路径：static_path（/labs/x.html）或缺省 {code}.html。

    page_source=custom 的实验没有模板静态页（页面走 LabPage/L2 沙箱链路），返回 None。
    """
    if lab.template_id is None:
        return None
    raw = (lab.template.static_path or "").strip() or f"/labs/{lab.template.code}.html"
    name = raw.rsplit("/labs/", 1)[-1] if "/labs/" in raw else raw.lstrip("/")
    return name


def read_page(lab) -> str | None:
    """读实验入口 HTML；分流：custom → LabPage 文件文本；template → LABS_ROOT 静态页。"""
    if lab.page_source == lab.PageSource.CUSTOM and getattr(lab, "custom_page", None):
        try:
            with lab.custom_page.file.open("rb") as f:
                return f.read().decode("utf-8", errors="replace")
        except (OSError, ValueError):
            return None
    relpath = _lab_page_relpath(lab)
    if relpath is None:
        return None
    root = Path(settings.LABS_ROOT).resolve()
    try:
        candidate = (root / relpath).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate.read_text(encoding="utf-8", errors="replace") if candidate.is_file() else None


def _read_static(name: str) -> str | None:
    root = Path(settings.LABS_ROOT).resolve()
    try:
        candidate = (root / name).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate.read_text(encoding="utf-8", errors="replace") if candidate.is_file() else None


def _strip_base(html: str) -> str:
    """剥离 HTML 中已有的 <base>，避免双 base 时浏览器取第一个导致签名 base 失效。"""
    return _BASE_STRIP_RE.sub("", html)


def _inject_after_head(html: str, snippet: str) -> str:
    """把 snippet 注入到 <head> 开口标签之后；无 <head> 时退到 <html> 后或文首。"""
    match = _HEAD_OPEN_RE.search(html)
    if match:
        return html[: match.end()] + snippet + html[match.end():]
    lowered = html.lower()
    idx = lowered.find("<html")
    if idx >= 0:
        end = lowered.find(">", idx)
        if end > 0:
            return html[: end + 1] + snippet + html[end + 1:]
    return snippet + html


def inject_bridge(html: str, mode: str, base: str, preview: bool = False) -> str:
    """S7 三分流注入（mode=template|frame）：<base> 紧跟桥接脚本。

    - template：只注入 <base>（预置页本体已引用 lab-bridge.js，跳过不重复注入）；
    - frame（custom iframe 内容页）：先剥已有 <base>，再注入签名 <base> + 预览引导
      变量 + 无票据 shim（shim 据此设置 LabBridge.preview）。
    - parent 页面由 render_parent() 整体渲染（模板自带脚本），不走本函数。
    """
    if mode == "frame":
        html = _strip_base(html)
        snippet = (
            f'<base href="{base}">'
            f"<script>window.__LAB_PREVIEW__ = {'true' if preview else 'false'};</script>"
            '<script src="lab-bridge-shim.js"></script>'
        )
        return _inject_after_head(html, snippet)
    # template：保持原行为（inject_base 只插不去重，预置页无自带 base）
    return resource_gate.inject_base(html, base)


def render_parent(lab, sig: str, exp: str, attempt_token: str | None, preview: bool) -> str | None:
    """custom 平台父页面：读模板 → 替换四占位符 → 注入 <base>（C45）。

    - __FRAME_URL__：iframe 绝对路径（frame_url()，绝不拼 attempt_token，C45）；
    - __LAB_BOOT_TOKEN__：票据 JSON 字面量（仅正式模式；父页面 IIFE 读完即删）；
    - __LAB_CONTEXT__：预览模式给 mock context（四字段），正式模式给 null（由父页面
      用票据取 bridge-validate 后映射四字段写入）；
    - __LAB_PREVIEW__：true/false 字面量。
    """
    template = _read_static(PARENT_TEMPLATE)
    if template is None:
        return None
    context = (
        {
            "labId": lab.id,
            "submissionId": None,
            "totalScore": float(lab.total_score) if lab.total_score is not None else None,
            "gradeEndpoint": "/api/lab-gate/grade/",
        }
        if preview
        else None
    )
    # 用 /*__X__*/ 注释形态占位，避免朴素 replace 误伤 window.__X__ 变量名
    a_sig, a_exp = _asset_sig_exp(lab, sig, exp, preview)
    html = (
        template
        .replace("/*__FRAME_URL__*/", frame_url(lab, sig, exp, preview=preview))
        .replace("/*__LAB_BOOT_TOKEN__*/", json.dumps(attempt_token))
        .replace("/*__LAB_CONTEXT__*/", json.dumps(context, ensure_ascii=False))
        .replace("/*__LAB_PREVIEW__*/", "true" if preview else "false")
    )
    return resource_gate.inject_base(html, asset_base(lab, a_sig, a_exp))


def render_frame(lab, sig: str, exp: str, preview: bool) -> str | None:
    """custom iframe 内容页：教师 HTML + 签名 <base> + 预览引导变量 + 无票据 shim。"""
    html = read_page(lab)
    if html is None:
        return None
    a_sig, a_exp = _asset_sig_exp(lab, sig, exp, preview)
    return inject_bridge(html, "frame", asset_base(lab, a_sig, a_exp), preview=preview)


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
