"""教辅资料文本抽取（需求 T-K-02 / 7.2 第 2 步）。

按文件后缀选择解析器，抽取纯文本用于后续切分与向量化。
缺少对应解析库时优雅降级为空串，不影响主流程。

旧版 .doc（OLE2 复合文档，魔数 D0CF11E0A1B11AE1）python-docx 不支持：
Windows 优先用本机 Word COM 抽取，Linux（生产容器）用 LibreOffice
headless 转成 docx 后再抽，二者都不可用才降级为空。
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# OLE2 复合文档魔数（旧版 .doc / .ppt / .xls）
OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def detect_file_type(file_name: str) -> str:
    ext = os.path.splitext(file_name)[1].lower().lstrip(".")
    return {
        "pdf": "pdf",
        "doc": "word",
        "docx": "word",
        "ppt": "ppt",
        "pptx": "ppt",
        "txt": "txt",
        "md": "txt",
    }.get(ext, ext or "unknown")


def is_legacy_doc(file_path: str) -> bool:
    """按文件头判断是否为旧版 .doc（OLE2 复合文档），而非 OOXML。"""
    try:
        with open(file_path, "rb") as f:
            return f.read(8) == OLE2_MAGIC
    except Exception:
        return False


def extract_text(file_path: str) -> str:
    """从本地文件抽取文本。返回可能为空。"""
    if not file_path or not os.path.exists(file_path):
        return ""
    ftype = detect_file_type(file_path)
    try:
        if ftype == "txt":
            return _read_txt(file_path)
        if ftype == "pdf":
            return _read_pdf(file_path)
        if ftype == "word":
            return _read_word(file_path)
        if ftype == "ppt":
            return _read_pptx(file_path)
    except Exception:
        logger.exception("知识库文本抽取失败: %s", file_path)
        # 解析失败不阻断流程，交由上层标记失败或用占位
        return ""
    return ""


def _read_word(path: str) -> str:
    """docx 直接用 python-docx；旧版 .doc（OLE2）走转换兜底。"""
    if os.path.splitext(path)[1].lower() == ".doc" and is_legacy_doc(path):
        return _read_legacy_doc(path)
    return _read_docx(path)


def _read_legacy_doc(path: str) -> str:
    """旧版 .doc 文本抽取：Word COM（Windows）→ LibreOffice 转 docx（Linux）。

    LibreOffice 输出文件名 = 原文件 stem + ".docx"，临时目录转换不污染 media。
    """
    text = _read_doc_via_com(path)
    if text:
        return text
    return _read_doc_via_libreoffice(path)


def _read_doc_via_com(path: str) -> str:
    """Windows：Word COM 打开文档读取全文（与 PPT 渲染的 COM 模式一致）。"""
    try:
        import pythoncom
        import win32com.client
    except Exception:
        return ""

    word = None
    doc = None
    pythoncom.CoInitialize()
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(os.path.abspath(path), ReadOnly=True)
        # COM 全文以 \r 分行、表格单元格以 \x07 结尾，归一化为 \n 并去除控制符
        raw = doc.Content.Text or ""
        return "\n".join(
            line for line in raw.replace("\x07", " ").replace("\r", "\n").split("\n") if line.strip()
        )
    except Exception:
        return ""
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def _read_txt(path: str) -> str:
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    return ""


def _read_pdf(path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _read_docx(path: str) -> str:
    from docx import Document

    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _read_doc_via_libreoffice(path: str) -> str:
    """Linux/生产容器：soffice 把 .doc 转成 docx 后用 python-docx 抽取。"""
    import shutil
    import subprocess
    import tempfile

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        logger.warning("知识库解析旧版 .doc 失败：环境无 Word COM 也无 LibreOffice: %s", path)
        return ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                [soffice, "--headless", "--convert-to", "docx", "--outdir", tmp, path],
                timeout=300,
                check=True,
                capture_output=True,
            )
            docx_path = os.path.join(tmp, f"{os.path.splitext(os.path.basename(path))[0]}.docx")
            if not os.path.exists(docx_path):
                logger.warning("知识库解析旧版 .doc 失败：LibreOffice 未产出 docx: %s", path)
                return ""
            return _read_docx(docx_path)
    except Exception:
        logger.exception("LibreOffice 转换旧版 .doc 失败: %s", path)
        return ""


def _read_pptx(path: str) -> str:
    from pptx import Presentation

    prs = Presentation(path)
    parts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
    return "\n".join(p for p in parts if p.strip())
