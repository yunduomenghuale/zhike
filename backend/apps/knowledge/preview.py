"""教辅资料在线预览：Office → PDF → 逐页 PNG，按存储文件名哈希缓存。

与作业附件预览（homework/views.preview_attachment）同一模式：
- PDF 直接 pypdfium2 逐页出图（版式已固化，零偏移）；
- Word/PPT 先 LibreOffice headless 转 PDF（老 .ppt 先预转 .pptx 提升保真度，
  与 ppt_parser 的渲染链路一致）再出图；
- txt 不出图，由视图直接回文本给前端展示；
- 文件名 uuid 化后内容不可变，渲染产物按 sha256(存储名)[:16] 目录缓存复用。

缓存目录结构：material_preview/<digest>/{source.pdf, pages/slide-*.png}
渲染先落到 pages.staging-<rand> 再整体换名，避免并发/中途失败留下半套页图。
"""
import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.files.storage import default_storage

from apps.courses.ppt_parser import render_pdf_to_images

logger = logging.getLogger(__name__)

# 支持在线预览（出图）的扩展；txt 由视图单独处理，其余类型提示下载
PREVIEWABLE_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx"}
# 单次预览最多渲染页数（超出提示下载查看，避免超大文件长时间占用 worker）
MAX_PREVIEW_PAGES = 100
# txt 预览最多读取字节数
MAX_TEXT_PREVIEW_BYTES = 512 * 1024


def material_media_url(rel_path: Path) -> str:
    """相对 media 的路径 → URL（as_posix 保证 Windows 下也是正斜杠）。"""
    return settings.MEDIA_URL + rel_path.as_posix()


def soffice_cmd() -> str:
    """定位 LibreOffice 可执行文件：PATH 优先；Windows 开发机回退常见安装目录。"""
    found = shutil.which("soffice")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ):
        if os.path.exists(candidate):
            return candidate
    return "soffice"  # 找不到时交给系统报错，走异常分支提示下载


def material_preview_paths(file_name: str) -> tuple[Path, Path]:
    """存储文件名 → (rel_root, abs_root) 预览缓存根目录。"""
    digest = hashlib.sha256(file_name.encode()).hexdigest()[:16]
    rel_root = Path("material_preview") / digest
    return rel_root, Path(settings.MEDIA_ROOT) / rel_root


def convert_office_to_pdf(file_path: str, cache_root: Path) -> Path | None:
    """Word/PPT → PDF（LibreOffice headless），产物缓存为 cache_root/source.pdf。

    转换耗时几十秒级，缓存后重复预览不再转换；失败返回 None 由调用方提示下载。
    """
    cached = cache_root / "source.pdf"
    if cached.exists():
        return cached
    cache_root.mkdir(parents=True, exist_ok=True)
    soffice = soffice_cmd()
    with tempfile.TemporaryDirectory() as tmp:
        # 每次转换用独立 UserInstallation profile：LibreOffice 默认 profile 同时只允许
        # 一个进程，不隔离的话与 PPT 课件渲染（ppt_parser）并发时会互相失败
        lo_profile = f"-env:UserInstallation={Path(tmp, 'lo-profile').as_uri()}"
        source = file_path
        if file_path.lower().endswith(".ppt"):
            # 老格式 .ppt 先预转 .pptx：LibreOffice 对 OOXML 的排版保真度更好（同 ppt_parser）
            try:
                subprocess.run(
                    [soffice, "--headless", lo_profile, "--convert-to", "pptx", "--outdir", tmp, file_path],
                    timeout=300,
                    check=True,
                    capture_output=True,
                )
                pptx_path = Path(tmp) / f"{Path(file_path).stem}.pptx"
                if pptx_path.exists():
                    source = str(pptx_path)
            except Exception:
                logger.warning("资料预览 .ppt 预转 .pptx 失败，退回直接转 PDF: %s", file_path)
        try:
            subprocess.run(
                [soffice, "--headless", lo_profile, "--convert-to", "pdf", "--outdir", tmp, source],
                timeout=300,
                check=True,
                capture_output=True,
            )
        except Exception:
            logger.exception("资料预览 LibreOffice 转 PDF 失败: %s", file_path)
            return None
        pdf_path = Path(tmp) / f"{Path(source).stem}.pdf"
        if not pdf_path.exists():
            logger.warning("资料预览 LibreOffice 未产出 PDF: %s", file_path)
            return None
        # 经临时文件 os.replace 落位，避免并发请求写同一 source.pdf 产生残文件
        staging_pdf = cache_root / f"source.pdf.tmp-{uuid4().hex[:8]}"
        staging_pdf.write_bytes(pdf_path.read_bytes())
        staging_pdf.replace(cached)
    return cached


def render_material_pages(pdf_path: str | Path, rel_root: Path, cache_root: Path) -> list[str]:
    """把 PDF 渲染为逐页 PNG 并返回页图 URL 列表；渲染失败返回空列表。

    先渲染到 staging 目录再整体换名：并发请求各自渲染、先到先得，
    不会在缓存目录里留下半套页图。
    """
    rel_pages = rel_root / "pages"
    pages_dir = cache_root / "pages"
    staging = cache_root / f"pages.staging-{uuid4().hex[:8]}"
    staging.mkdir(parents=True, exist_ok=True)
    try:
        rendered = render_pdf_to_images(str(pdf_path), staging, rel_pages)
        if not rendered:
            return []
        try:
            staging.rename(pages_dir)
        except OSError:
            # 并发渲染先到先得：目标已存在时丢弃自己的产物，页面内容相同
            pass
        return [material_media_url(rel_pages / f"slide-{page:03d}.png") for page in sorted(rendered)]
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def read_material_text(file_name: str) -> str:
    """读取 txt 资料文本（utf-8 优先，回退 gbk；超大文件截断）。"""
    with default_storage.open(file_name, "rb") as fh:
        raw = fh.read(MAX_TEXT_PREVIEW_BYTES)
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")
