# 手册 Markdown -> Word(.docx) 排版脚本
# 特性：封面 / 目录域 / 篇章节三级标题 / 图片自动编号图注 / 表格带表头底色 / 中文字体 / 页眉页脚页码
import os, re, sys
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.section import WD_SECTION
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # docs/manual
OUT_DOCX = os.path.join(BASE, '智课系统V2用户使用手册.docx')
FILES = ['01-入门篇.md', '02-教师篇.md', '03-学生篇.md', '04-管理员篇.md', '05-FAQ与附录.md']

BODY_FONT = '宋体'
HEAD_FONT = '黑体'
ACCENT = RGBColor(0x1F, 0x4E, 0x8C)   # 深蓝
GRAY = RGBColor(0x59, 0x59, 0x59)
CONTENT_W = Cm(16.0)                  # A4 2.5cm 边距下的可用宽度


def set_font(run, name=BODY_FONT, size=10.5, bold=False, color=None, italic=False):
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color
    run._element.rPr.rFonts.set(qn('w:eastAsia'), name)


def set_para_spacing(p, before=0, after=4, line=1.5):
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line


def add_field(paragraph, instr, placeholder):
    run = paragraph.add_run()
    fld_begin = OxmlElement('w:fldChar'); fld_begin.set(qn('w:fldCharType'), 'begin')
    instr_el = OxmlElement('w:instrText'); instr_el.set(qn('xml:space'), 'preserve'); instr_el.text = instr
    fld_sep = OxmlElement('w:fldChar'); fld_sep.set(qn('w:fldCharType'), 'separate')
    t = OxmlElement('w:t'); t.text = placeholder
    fld_end = OxmlElement('w:fldChar'); fld_end.set(qn('w:fldCharType'), 'end')
    for el in (fld_begin, instr_el, fld_sep, t, fld_end):
        run._r.append(el)


def shade_cell(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), hexcolor)
    tcPr.append(shd)


def add_bottom_border(paragraph, color='1F4E8C', sz=6):
    pPr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single'); bottom.set(qn('w:sz'), str(sz))
    bottom.set(qn('w:space'), '2'); bottom.set(qn('w:color'), color)
    borders.append(bottom)
    pPr.append(borders)


INLINE_BOLD = re.compile(r'\*\*(.+?)\*\*')
INLINE_CODE = re.compile(r'`([^`]+)`')


def add_rich_text(p, text, size=10.5, color=None, base_bold=False):
    """处理 **粗体** 与 `代码` 行内格式"""
    pos = 0
    pattern = re.compile(r'(\*\*.+?\*\*|`[^`]+`)')
    for m in pattern.finditer(text):
        if m.start() > pos:
            set_font(p.add_run(text[pos:m.start()]), size=size, color=color, bold=base_bold)
        seg = m.group(0)
        if seg.startswith('**'):
            set_font(p.add_run(seg[2:-2]), size=size, color=color, bold=True)
        else:
            r = p.add_run(seg[1:-1])
            set_font(r, name='Consolas', size=size - 0.5, color=RGBColor(0xB0, 0x30, 0x30), bold=base_bold)
        pos = m.end()
    if pos < len(text):
        set_font(p.add_run(text[pos:]), size=size, color=color, bold=base_bold)


class Builder:
    def __init__(self):
        self.doc = Document()
        self.part_no = 0          # 篇序号（图注编号用）
        self.fig_no = 0           # 篇内图序号
        self.fig_total = 0
        self._setup_styles()
        self._setup_page()

    def _setup_styles(self):
        st = self.doc.styles['Normal']
        st.font.name = BODY_FONT
        st.font.size = Pt(10.5)
        st.element.rPr.rFonts.set(qn('w:eastAsia'), BODY_FONT)

    def _setup_page(self):
        sec = self.doc.sections[0]
        sec.page_height = Cm(29.7); sec.page_width = Cm(21.0)
        sec.top_margin = Cm(2.4); sec.bottom_margin = Cm(2.2)
        sec.left_margin = Cm(2.5); sec.right_margin = Cm(2.5)

    # ---------- 封面 ----------
    def cover(self):
        doc = self.doc
        for _ in range(3):
            doc.add_paragraph()
        p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(p.add_run('智课系统 V2'), name=HEAD_FONT, size=30, bold=True, color=ACCENT)

        p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_para_spacing(p, before=10, after=6, line=1.2)
        set_font(p.add_run('用户使用手册'), name=HEAD_FONT, size=40, bold=True, color=RGBColor(0x22, 0x22, 0x22))

        p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(p.add_run('教师 · 学生 · 管理员'), size=13, color=GRAY)

        for _ in range(6):
            doc.add_paragraph()

        info = [('适用系统版本', '智课系统 V2（Web 端）'),
                ('手册版本', 'v1.0'),
                ('发布日期', '2026 年 10 月 26 日'),
                ('编制', '智课平台项目组')]
        tbl = doc.add_table(rows=len(info), cols=2)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, (k, v) in enumerate(info):
            c0, c1 = tbl.rows[i].cells
            c0.width = Cm(4.5); c1.width = Cm(8.0)
            p0 = c0.paragraphs[0]; p0.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            set_font(p0.add_run(k + '：'), size=11, color=GRAY)
            set_font(c1.paragraphs[0].add_run(v), size=11)
        doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ---------- 目录 ----------
    def toc(self):
        doc = self.doc
        p = doc.add_paragraph()
        set_font(p.add_run('目  录'), name=HEAD_FONT, size=20, bold=True, color=ACCENT)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_para_spacing(p, after=14)
        add_bottom_border(p, 'BFBFBF', 4)

        tip = doc.add_paragraph(); tip.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(tip.add_run('（若页码未显示：全选目录后按 F9，或在目录上右键选择「更新域」）'), size=9, color=GRAY)

        p = doc.add_paragraph()
        add_field(p, 'TOC \\o "1-2" \\h \\z \\u', '目录将在打开文档时自动生成，或按 F9 更新。')
        doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ---------- 标题 ----------
    def h1(self, text):
        self.part_no += 1
        self.fig_no = 0
        doc = self.doc
        if self.part_no > 1:
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        p = doc.add_paragraph(style='Heading 1')
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        set_para_spacing(p, before=0, after=16, line=1.3)
        set_font(p.add_run(text), name=HEAD_FONT, size=24, bold=True, color=ACCENT)
        add_bottom_border(p, '1F4E8C', 10)

    def h2(self, text):
        p = self.doc.add_paragraph(style='Heading 2')
        set_para_spacing(p, before=14, after=6, line=1.3)
        set_font(p.add_run(text), name=HEAD_FONT, size=15, bold=True, color=RGBColor(0x1A, 0x1A, 0x1A))

    def h3(self, text):
        p = self.doc.add_paragraph(style='Heading 3')
        set_para_spacing(p, before=10, after=4, line=1.3)
        set_font(p.add_run(text), name=HEAD_FONT, size=12, bold=True, color=RGBColor(0x33, 0x33, 0x33))

    # ---------- 正文元素 ----------
    def para(self, text):
        p = self.doc.add_paragraph()
        set_para_spacing(p, after=5, line=1.55)
        p.paragraph_format.first_line_indent = Cm(0)
        add_rich_text(p, text)

    def bullet(self, text, ordered=False, idx=None):
        p = self.doc.add_paragraph()
        set_para_spacing(p, after=3, line=1.5)
        p.paragraph_format.left_indent = Cm(0.9)
        p.paragraph_format.first_line_indent = Cm(-0.55)
        mark = f'{idx}. ' if ordered else '·  '
        set_font(p.add_run(mark), size=10.5, bold=ordered)
        add_rich_text(p, text)

    def note(self, text):
        """引用块：浅灰底 + 左侧提示"""
        p = self.doc.add_paragraph()
        set_para_spacing(p, before=4, after=8, line=1.45)
        p.paragraph_format.left_indent = Cm(0.3)
        pPr = p._p.get_or_add_pPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), 'F2F5FA')
        pPr.append(shd)
        set_font(p.add_run('说明  '), size=9.5, bold=True, color=ACCENT)
        add_rich_text(p, text, size=9.5, color=RGBColor(0x33, 0x33, 0x33))

    def image(self, path, alt):
        full = os.path.join(BASE, path)
        if not os.path.exists(full):
            self.para(f'（图片缺失：{path}）')
            return
        self.fig_no += 1
        self.fig_total += 1
        with Image.open(full) as im:
            w_px, h_px = im.size
        width = CONTENT_W
        # 过高图片按高度上限缩放（<= 15cm），避免整页只剩一张图
        max_h = Cm(15.5)
        if h_px / w_px * width > max_h:
            width = max_h * w_px / h_px
        p = self.doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_para_spacing(p, before=6, after=2, line=1.0)
        p.add_run().add_picture(full, width=width)
        cap = self.doc.add_paragraph(); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_para_spacing(cap, before=0, after=10, line=1.2)
        set_font(cap.add_run(f'图 {self.part_no}-{self.fig_no}  {alt}'), size=9, color=GRAY)

    def table(self, rows):
        header, body = rows[0], rows[1:]
        ncol = len(header)
        tbl = self.doc.add_table(rows=1 + len(body), cols=ncol)
        tbl.style = 'Table Grid'
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, h in enumerate(header):
            cell = tbl.rows[0].cells[j]
            shade_cell(cell, '1F4E8C')
            p = cell.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            set_font(p.add_run(h), name=HEAD_FONT, size=9.5, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
        for i, row in enumerate(body, start=1):
            for j in range(ncol):
                cell = tbl.rows[i].cells[j]
                if i % 2 == 0:
                    shade_cell(cell, 'F5F7FB')
                p = cell.paragraphs[0]
                add_rich_text(p, row[j] if j < len(row) else '', size=9.5)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)


MD_FILE = re.compile(r'^(!\[[^\]]*\]\([^)]+\))\s*$')
IMG = re.compile(r'^!\[([^\]]*)\]\(([^)]+)\)$')


def parse_table(lines, i):
    rows = []
    while i < len(lines) and lines[i].strip().startswith('|'):
        raw = lines[i].strip().strip('|')
        cells = [c.strip() for c in raw.split('|')]
        if not all(re.fullmatch(r':?-{2,}:?', c) for c in cells):
            rows.append(cells)
        i += 1
    return rows, i


def build():
    b = Builder()
    b.cover()
    b.toc()

    for fname in FILES:
        path = os.path.join(BASE, fname)
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            s = line.strip()
            if not s:
                i += 1; continue
            if s.startswith('# '):
                b.h1(s[2:].strip()); i += 1; continue
            if s.startswith('## '):
                b.h2(s[3:].strip()); i += 1; continue
            if s.startswith('### '):
                b.h3(s[4:].strip()); i += 1; continue
            m = IMG.match(s)
            if m:
                b.image(m.group(2).strip(), m.group(1).strip()); i += 1; continue
            if s.startswith('|'):
                rows, i = parse_table(lines, i)
                if rows:
                    b.table(rows)
                continue
            if s.startswith('> '):
                b.note(s[2:].strip()); i += 1; continue
            m = re.match(r'^[-*]\s+(.*)$', s)
            if m:
                b.bullet(m.group(1)); i += 1; continue
            m = re.match(r'^(\d+)\.\s+(.*)$', s)
            if m:
                b.bullet(m.group(2), ordered=True, idx=m.group(1)); i += 1; continue
            if re.fullmatch(r'-{3,}', s):
                i += 1; continue
            b.para(s); i += 1

    # 页脚页码 + 页眉
    sec = b.doc.sections[0]
    hp = sec.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    set_font(hp.add_run('智课系统 V2 用户使用手册'), size=9, color=GRAY)
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run('第 '); set_font(r, size=9, color=GRAY)
    add_field(fp, 'PAGE', '1')
    r = fp.add_run(' 页'); set_font(r, size=9, color=GRAY)

    b.doc.save(OUT_DOCX)
    print(f'SAVED {OUT_DOCX}')
    print(f'images embedded: {b.fig_total}')


if __name__ == '__main__':
    build()
