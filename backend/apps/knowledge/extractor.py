"""教辅资料文本抽取（需求 T-K-02 / 7.2 第 2 步）。

按文件后缀选择解析器，抽取纯文本用于后续切分与向量化。
缺少对应解析库时优雅降级为空串，不影响主流程。

旧版 .doc（OLE2 复合文档，魔数 D0CF11E0A1B11AE1）python-docx 不支持：
Windows 优先用本机 Word COM 抽取，Linux（生产容器）用 LibreOffice
headless 转成 docx 后再抽，二者都不可用才降级为空。
"""
from __future__ import annotations

import logging
import mimetypes
import os

logger = logging.getLogger(__name__)

# 题库导入题图占位行：抽取时在图片的原文位置插入，import_parser 识别后挂到
# 当前题目（题干一张图）。序号与返回 images 列表的 index 一一对应。
QUESTION_IMAGE_PLACEHOLDER = "[[QUESTION_IMAGE:{n}]]"

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


def extract_text_with_tables(file_path: str) -> str:
    """按文档顺序抽取 Word 文本（段落 + 表格）。

    题库/试卷类文档常用表格排布题目，extract_text 的 _read_docx 只读
    doc.paragraphs 会整体丢失表格内容；本函数按 body 顺序遍历块级元素，
    表格单元格以制表符连接、行间换行。非 Word 类型直接复用 extract_text。
    """
    if not file_path or not os.path.exists(file_path):
        return ""
    ftype = detect_file_type(file_path)
    try:
        if ftype == "word":
            if os.path.splitext(file_path)[1].lower() == ".doc" and is_legacy_doc(file_path):
                return _read_legacy_doc_with_tables(file_path)
            return _read_docx_with_tables(file_path)
        return extract_text(file_path)
    except Exception:
        logger.exception("文本抽取失败(含表格): %s", file_path)
        return ""


def _read_legacy_doc_with_tables(path: str) -> str:
    """旧版 .doc 含表格抽取：COM 全文（单元格分隔符已归一）优先，LibreOffice 转 docx 兜底。"""
    text = _read_doc_via_com(path)
    if text:
        return text
    return _read_doc_via_libreoffice(path, reader=_read_docx_with_tables)


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


def _read_docx_with_tables(path: str) -> str:
    """docx 按文档顺序读取段落与表格（题库文档表格排布硬前提）。

    表格行以制表符连接单元格；合并单元格会重复取值，由上层解析器容忍。
    """
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(path)
    lines: list[str] = []
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = Paragraph(child, doc).text.strip()
            if text:
                lines.append(text)
        elif child.tag == qn("w:tbl"):
            for row in Table(child, doc).rows:
                cells = [c.text.strip() for c in row.cells]
                # 合并单元格去重（连续相同值只留一个）
                deduped = [v for i, v in enumerate(cells) if i == 0 or v != cells[i - 1]]
                line = "\t".join(deduped).strip()
                if line:
                    lines.append(line)
    return "\n".join(lines)


def _read_doc_via_libreoffice(path: str, reader=_read_docx) -> str:
    """Linux/生产容器：soffice 把 .doc 转成 docx 后用 reader 抽取。

    reader 默认 _read_docx（纯段落）；含表格场景传 _read_docx_with_tables。
    """
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
            return reader(docx_path)
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


def extract_text_with_images(file_path: str) -> tuple[str, list[dict]]:
    """题库导入专用：抽取文本并在图片原文位置插入占位行（QUESTION_IMAGE_PLACEHOLDER）。

    返回 (text, images)；images = [{"index": n, "ext": ".png", "data": bytes}]，
    与占位行序号一一对应。仅 docx/pdf 提取内嵌图，其余类型退回纯文本（images=[]）。
    - docx：沿用 _read_docx_with_tables 的块级遍历（表格行保持制表符连接），
      段落/表格行内的内嵌图（a:blip）紧随其文本之后登记占位行；
    - pdf：pypdf 无图片位置能力，改用 PyMuPDF 按页内 bbox 与文本块纵向交错定位；
    - 旧版 .doc 经 LibreOffice 转 docx 后按 docx 路径提取（COM 全文模式无位置信息）。
    任何失败都退回纯文本抽取，不阻断导入主流程。
    """
    if not file_path or not os.path.exists(file_path):
        return "", []
    ftype = detect_file_type(file_path)
    try:
        if ftype == "word":
            if os.path.splitext(file_path)[1].lower() == ".doc" and is_legacy_doc(file_path):
                converted = _convert_legacy_doc_to_docx(file_path)
                if not converted:
                    return extract_text_with_tables(file_path), []
                try:
                    return _read_docx_with_images(converted)
                finally:
                    try:
                        os.remove(converted)
                    except OSError:
                        pass
            return _read_docx_with_images(file_path)
        if ftype == "pdf":
            return _read_pdf_with_images(file_path)
        return extract_text(file_path), []
    except Exception:
        logger.exception("题图抽取失败，退回纯文本: %s", file_path)
        try:
            return extract_text_with_tables(file_path), []
        except Exception:
            return "", []


def _convert_legacy_doc_to_docx(path: str) -> str:
    """旧版 .doc → 临时 docx（LibreOffice）；不可用返回 ''。"""
    import shutil
    import subprocess
    import tempfile

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return ""
    try:
        tmp = tempfile.mkdtemp()
        subprocess.run(
            [soffice, "--headless", "--convert-to", "docx", "--outdir", tmp, path],
            timeout=300, check=True, capture_output=True,
        )
        docx_path = os.path.join(tmp, f"{os.path.splitext(os.path.basename(path))[0]}.docx")
        return docx_path if os.path.exists(docx_path) else ""
    except Exception:
        logger.exception("LibreOffice 转换旧版 .doc 提取题图失败: %s", path)
        return ""


def _read_docx_with_images(path: str) -> tuple[str, list[dict]]:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(path)
    lines: list[str] = []
    images: list[dict] = []

    def _register(ext: str, blob: bytes) -> None:
        images.append({"index": len(images), "ext": ext, "data": blob})
        lines.append(QUESTION_IMAGE_PLACEHOLDER.format(n=len(images) - 1))

    def _collect_images(element, seen_rids: set) -> None:
        """元素内所有内嵌图（a:blip r:embed），按文档序登记；seen_rids 防合并单元格重复。"""
        for blip in element.findall(".//" + qn("a:blip")):
            rid = blip.get(qn("r:embed"))
            if not rid or rid in seen_rids:
                continue
            seen_rids.add(rid)
            part = doc.part.related_parts.get(rid)
            blob = getattr(part, "blob", None) if part is not None else None
            if not blob:
                continue
            ctype = getattr(part, "content_type", "") or ""
            ext = mimetypes.guess_extension(ctype) or ".png"
            _register(ext, blob)

    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = Paragraph(child, doc).text.strip()
            if text:
                lines.append(text)
            _collect_images(child, set())
        elif child.tag == qn("w:tbl"):
            for row in Table(child, doc).rows:
                cells = [c.text.strip() for c in row.cells]
                # 合并单元格去重（连续相同值只留一个）
                deduped = [v for i, v in enumerate(cells) if i == 0 or v != cells[i - 1]]
                line = "\t".join(deduped).strip()
                if line:
                    lines.append(line)
                # 表格行内图片（题干配图常见排法）：占位行紧随该行之后，
                # 解析时正挂在刚由该行开启的题目上
                seen: set = set()
                for cell in row.cells:
                    _collect_images(cell._tc, seen)

    return "\n".join(lines), images


def _read_pdf_with_images(path: str) -> tuple[str, list[dict]]:
    import pymupdf

    doc = pymupdf.open(path)
    lines: list[str] = []
    images: list[dict] = []
    try:
        for page in doc:
            # 文本块与图片按页内纵向位置（y0, x0）交错排序，占位行落在图片实际位置
            entries: list[tuple] = []
            for block in page.get_text("blocks"):
                x0, y0, _x1, _y1, text = block[:5]
                if text and str(text).strip():
                    entries.append((float(y0), float(x0), "text", str(text)))
            for info in page.get_image_info(xrefs=True):
                bbox = info.get("bbox")
                xref = info.get("xref")
                if not bbox or not xref:
                    continue
                entries.append((float(bbox[1]), float(bbox[0]), "img", xref))
            entries.sort(key=lambda e: (round(e[0], 1), e[1]))
            for _y, _x, kind, payload in entries:
                if kind == "text":
                    lines.extend(l for l in payload.splitlines() if l.strip())
                    continue
                try:
                    img = doc.extract_image(payload)
                except Exception:
                    continue
                data = img.get("image")
                if not data:
                    continue
                ext = "." + (img.get("ext") or "png")
                images.append({"index": len(images), "ext": ext, "data": data})
                lines.append(QUESTION_IMAGE_PLACEHOLDER.format(n=len(images) - 1))
    finally:
        doc.close()
    return "\n".join(lines), images
