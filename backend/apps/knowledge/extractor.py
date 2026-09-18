"""教辅资料文本抽取（需求 T-K-02 / 7.2 第 2 步）。

按文件后缀选择解析器，抽取纯文本用于后续切分与向量化。
老格式 .doc/.ppt 先转 OOXML 再解析：Windows 用 Office COM，
Linux 用 LibreOffice（与 courses.ppt_parser 同一套路）。
缺少对应解析库时优雅降级为空串，不影响主流程。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile


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
            return _read_ppt(file_path)
    except Exception:
        # 解析失败不阻断流程，交由上层标记失败或用占位
        return ""
    return ""


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


def _read_word(path: str) -> str:
    if path.lower().endswith(".docx"):
        return _read_docx(path)
    # 老格式 .doc：先转 .docx 再解析
    converted = _convert_to_ooxml(path, "docx")
    if not converted:
        return ""
    try:
        return _read_docx(converted)
    finally:
        shutil.rmtree(os.path.dirname(converted), ignore_errors=True)


def _read_ppt(path: str) -> str:
    if path.lower().endswith(".pptx"):
        return _read_pptx(path)
    # 老格式 .ppt：先转 .pptx 再解析
    converted = _convert_to_ooxml(path, "pptx")
    if not converted:
        return ""
    try:
        return _read_pptx(converted)
    finally:
        shutil.rmtree(os.path.dirname(converted), ignore_errors=True)


def _convert_to_ooxml(file_path: str, target_ext: str) -> str:
    """老格式 Office 文件转 OOXML，返回转换后的路径（失败返回空串）。

    Windows 用 Office COM（Word/PowerPoint），Linux 用 LibreOffice headless。
    """
    tmp_dir = tempfile.mkdtemp(prefix="ooxml-")
    stem = os.path.splitext(os.path.basename(file_path))[0]
    out_path = os.path.join(tmp_dir, f"{stem}.{target_ext}")
    if os.name == "nt":
        _convert_with_office_com(file_path, out_path)
    else:
        try:
            subprocess.run(
                ["soffice", "--headless", "--convert-to", target_ext, "--outdir", tmp_dir, file_path],
                timeout=300,
                check=True,
                capture_output=True,
            )
        except Exception:
            pass
    return out_path if os.path.exists(out_path) else ""


def _convert_with_office_com(file_path: str, out_path: str) -> None:
    """Windows Microsoft Office COM 转换：.doc→.docx / .ppt→.pptx。"""
    try:
        import pythoncom
        import win32com.client
    except Exception:
        return

    is_word = out_path.lower().endswith(".docx")
    app = None
    doc = None
    pythoncom.CoInitialize()
    try:
        app = win32com.client.Dispatch("Word.Application" if is_word else "PowerPoint.Application")
        try:
            app.DisplayAlerts = 0
        except Exception:
            pass
        if is_word:
            doc = app.Documents.Open(os.path.abspath(file_path), ReadOnly=True)
            # wdFormatDocumentDefault = 16 (.docx)
            doc.SaveAs2(os.path.abspath(out_path), FileFormat=16)
        else:
            doc = app.Presentations.Open(os.path.abspath(file_path), True, False, False)
            # ppSaveAsOpenXMLPresentation = 24 (.pptx)
            doc.SaveAs(os.path.abspath(out_path), 24)
    except Exception:
        pass
    finally:
        if doc is not None:
            try:
                doc.Close()
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def _read_docx(path: str) -> str:
    from docx import Document

    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _read_pptx(path: str) -> str:
    from pptx import Presentation

    prs = Presentation(path)
    parts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
    return "\n".join(p for p in parts if p.strip())
