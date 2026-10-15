# -*- coding: utf-8 -*-
"""重新生成作业 E2E 大文件 fixtures（旧 hw-teacher-big.pdf 是随机字节伪装的损坏 PDF，PDFium 无法解析）。

- hw-teacher-big.pdf：~12MB 有效多页 PDF（PIL 直接内嵌 JPEG，页数 10）
- hw-submit-big.png：~4MB 噪声 PNG（学生端即传流程可见，上传阶段足够长以供采样）

运行：venv/Scripts/python.exe gen_hw_e2e_fixtures.py
"""
import random
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "test" / "e2e" / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)


def noise_image(size, seed, label):
    """随机噪声图（JPEG/PNG 压缩率低 → 体积大），叠加白底标签便于肉眼确认页序。"""
    rng = random.Random(seed)
    w, h = size
    img = Image.frombytes("RGB", (w, h), bytes(rng.getrandbits(8) for _ in range(w * h * 3)))
    draw = ImageDraw.Draw(img)
    draw.rectangle([30, 30, 30 + 14 * len(label), 110], fill=(255, 255, 255))
    draw.text((44, 52), label, fill=(0, 0, 0))
    return img


# 1) ~12MB 有效 PDF：10 页 A4@150dpi 噪声 JPEG
pages = [noise_image((1240, 1754), 100 + i, f"hw-teacher-big page {i + 1}") for i in range(10)]
pdf_path = OUT / "hw-teacher-big.pdf"
pages[0].save(pdf_path, format="PDF", save_all=True, append_images=pages[1:], resolution=150)
print("pdf:", pdf_path, pdf_path.stat().st_size / 1024 / 1024, "MB")

# 2) ~4MB 噪声 PNG（学生提交用，保证上传阶段可被 16ms 采样捕获）
png_path = OUT / "hw-submit-big.png"
noise_image((1100, 1100), 7, "hw-submit-big").save(png_path, format="PNG", optimize=False)
print("png:", png_path, png_path.stat().st_size / 1024 / 1024, "MB")

# 3) 校验 PDF 可被 pypdfium2 解析渲染
import pypdfium2 as pdfium

pdf = pdfium.PdfDocument(str(pdf_path))
print("pdf pages:", len(pdf))
page = pdf[0]
image = page.render(scale=150 / 72).to_pil()
print("first page render:", image.size)
page.close()
pdf.close()
