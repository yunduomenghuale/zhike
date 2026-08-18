from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase
from pptx import Presentation
from pptx.util import Inches

from apps.ai.services import (
    _dedupe_page_body,
    _local_script_for_page,
    _polish_script_text,
)
from apps.courses.ppt_parser import _read_presentation


class TeachingScriptCleanupTests(SimpleTestCase):
    def test_page_body_removes_numbered_and_exact_duplicate_lines(self):
        body = "1. Application\n2. Application\nApplet\nApplet"

        self.assertEqual(_dedupe_page_body(body), "1. Application\nApplet")

    def test_polish_removes_repeated_generated_clause(self):
        sentence = "Application 是普通 Java 应用程序，通常从 main 方法开始运行"
        script = f"{sentence}；{sentence}；Applet 是早期嵌入网页运行的 Java 程序。"

        polished = _polish_script_text(script)

        self.assertEqual(polished.count(sentence), 1)
        self.assertIn("Applet 是早期嵌入网页运行的 Java 程序", polished)

    def test_local_script_deduplicates_equivalent_explanations_and_has_no_fixed_filler(self):
        result = _local_script_for_page(
            {
                "page": 6,
                "title": "Application 和 Applet",
                "body": "Application\nApplication 程序\nApplet",
            }
        )

        script = result["script"]
        self.assertEqual(script.count("通常从 main 方法开始运行"), 1)
        self.assertNotIn("学习时先把这些要点按顺序串起来", script)

    def test_ppt_parser_ignores_duplicate_text_boxes(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate-text.pptx"
            presentation = Presentation()
            slide = presentation.slides.add_slide(presentation.slide_layouts[1])
            slide.shapes.title.text = "Application 和 Applet"
            slide.placeholders[1].text = "Application\nApplet"
            duplicate = slide.shapes.add_textbox(Inches(1), Inches(4), Inches(5), Inches(1))
            duplicate.text_frame.text = "Application\nApplet"
            presentation.save(path)

            pages = _read_presentation(str(path))

        self.assertEqual(pages[0]["body"], "Application\nApplet")
