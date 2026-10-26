# -*- coding: utf-8 -*-
"""题库填空题按空赋分 + 文档导入规则解析 + AI 多类型生题测试（2026-10）。

覆盖：
- Question.save() 答案规范化：旧版纯字符串数组均分补分、score=Σ空分、非填空题不受影响
- grade_objective 按空判分：全对满分 / 部分对给部分分 / 缺答按错 / 大小写与空白不敏感 /
  旧版字符串数组保持全对满分否则 0 分
- QuestionSerializer 按空校验：每空 text 非空、分值必须为 >0 的数字、空题拒绝；
  仅 PATCH status 等字段时不触发答案校验（不破坏旧题操作）
- import_parser.parse_questions 规则解析：五种题型各 ≥3 种格式变体、
  残缺输入告警、特殊格式（甲乙丙丁/圈号/括号选项归一、表格列兜底、
  尾部分值、卷末速查行跳过、跨页续接、选项换行、无标题结构推断、表格题目行）
- 导入 API / 草稿批次 API：安全校验、行级隔离、save 入库管道（查重/留批/入库即删）
- AI 多类型生题（阶段 4）：generate 端点 groups 校验与防重复提交、
  run_question_gen 流水线（mock 建批次 / 部分失败 degraded / 全失败）、
  ai-tasks/active 恢复入口、教师端 AI 限流分档
"""
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache as django_cache
from django.test import SimpleTestCase, override_settings

from rest_framework.test import APIClient, APITestCase, APIRequestFactory
from rest_framework.test import force_authenticate

from apps.ai.models import AITask
from apps.ai.providers.base import BaseAIProvider
from apps.ai.providers.mock import MockProvider
from apps.ai.tests_ai_task import _FakeThreading
from apps.courses.models import Catalog, Course
from apps.questions.grading import blank_items, grade_objective
from apps.questions.import_parser import parse_questions
from apps.questions.models import Question, QuestionDraftBatch
from apps.questions.question_gen_ai import run_question_gen
from apps.questions.serializers import QuestionSerializer
from apps.users.models import User


def _blank_question(**kwargs):
    """构造填空题（经 save() 规范化，模拟旧版字符串答案的常见入口）。"""
    defaults = dict(
        qtype=Question.QType.BLANK,
        stem="Java 三大特征：____、____、____。",
        answer={"blanks": ["封装", "继承", "多态"]},
        score=Decimal("6"),
        status=Question.Status.PUBLISHED,
    )
    defaults.update(kwargs)
    return Question.objects.create(**defaults)


class BlankAnswerNormalizeTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_qbank", password="pw123456!", role=User.Role.TEACHER)
        cls.course = Course.objects.create(name="Java程序设计", teacher=cls.teacher)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第一章")

    def test_legacy_string_blanks_get_even_scores(self):
        """旧版纯字符串数组：按原总分均分补分，Σ 不变，结构升级为对象数组。"""
        q = _blank_question(course=self.course, catalog=self.catalog)
        q.refresh_from_db()
        self.assertEqual(
            q.answer["blanks"],
            [
                {"text": "封装", "score": 2.0},
                {"text": "继承", "score": 2.0},
                {"text": "多态", "score": 2.0},
            ],
        )
        self.assertEqual(q.score, Decimal("6"))

    def test_uneven_total_distributes_remainder_to_first_blanks(self):
        """总分无法整除时余数依次补给前几个空，保证 Σ=原分值。"""
        q = _blank_question(course=self.course, catalog=self.catalog, score=Decimal("5"))
        q.refresh_from_db()
        scores = [b["score"] for b in q.answer["blanks"]]
        self.assertEqual(scores, [1.7, 1.7, 1.6])
        self.assertEqual(sum(scores), 5.0)
        self.assertEqual(q.score, Decimal("5"))

    def test_score_recomputed_from_blank_scores(self):
        """对象数组：总分以 Σ空分为准，忽略传入的旧总分。"""
        q = _blank_question(
            course=self.course, catalog=self.catalog,
            answer={"blanks": [{"text": "封装", "score": 3}, {"text": "继承", "score": 4}]},
            score=Decimal("100"),
        )
        q.refresh_from_db()
        self.assertEqual(q.score, Decimal("7"))

    def test_edit_existing_blank_recomputes_total(self):
        """编辑既有填空题：按新空分重算总分（删空/改分即时生效）。"""
        q = _blank_question(course=self.course, catalog=self.catalog)
        q.answer = {"blanks": [{"text": "封装", "score": 5}, {"text": "继承", "score": 2}]}
        q.save()
        q.refresh_from_db()
        self.assertEqual(q.score, Decimal("7"))
        self.assertEqual(len(q.answer["blanks"]), 2)

    def test_non_blank_question_untouched(self):
        """非填空题的 answer/score 不受规范化影响。"""
        q = Question.objects.create(
            course=self.course, catalog=self.catalog, qtype=Question.QType.SINGLE,
            stem="1+1=?", options=[{"key": "A", "text": "2"}],
            answer={"key": "A"}, score=Decimal("5"),
        )
        q.refresh_from_db()
        self.assertEqual(q.score, Decimal("5"))
        self.assertEqual(q.answer, {"key": "A"})


class BlankGradingTests(APITestCase):
    @staticmethod
    def _q(blanks, score="6"):
        return SimpleNamespace(qtype="blank", answer={"blanks": blanks}, score=Decimal(score))

    def test_full_correct_gets_full_score(self):
        q = self._q([
            {"text": "封装", "score": 2}, {"text": "继承", "score": 2}, {"text": "多态", "score": 2},
        ])
        ok, score = grade_objective(q, {"blanks": ["封装", "继承", "多态"]})
        self.assertTrue(ok)
        self.assertEqual(score, Decimal("6"))

    def test_partial_gets_partial_score(self):
        q = self._q([
            {"text": "封装", "score": 2}, {"text": "继承", "score": 2}, {"text": "多态", "score": 2},
        ])
        ok, score = grade_objective(q, {"blanks": ["封装", "继承", "答错"]})
        self.assertFalse(ok)
        self.assertEqual(score, Decimal("4"))

    def test_missing_blank_counts_as_wrong(self):
        """学生漏答某一空：按错处理，只拿命中空的分。"""
        q = self._q([{"text": "封装", "score": 2}, {"text": "继承", "score": 3}])
        ok, score = grade_objective(q, {"blanks": ["封装"]})
        self.assertFalse(ok)
        self.assertEqual(score, Decimal("2"))

    def test_extra_answers_ignored(self):
        q = self._q([{"text": "封装", "score": 2}])
        ok, score = grade_objective(q, {"blanks": ["封装", "多写"]})
        self.assertTrue(ok)
        self.assertEqual(score, Decimal("2"))

    def test_case_and_whitespace_insensitive(self):
        q = self._q([{"text": "Encapsulation", "score": 3}])
        ok, score = grade_objective(q, {"blanks": [" encapsulation "]})
        self.assertTrue(ok)
        self.assertEqual(score, Decimal("3"))

    def test_legacy_string_blanks_all_or_nothing(self):
        """旧版纯字符串数组（无按空分值）：保持全对满分、否则 0 分。"""
        q = self._q(["封装", "继承", "多态"])
        ok, score = grade_objective(q, {"blanks": ["封装", "继承", "多态"]})
        self.assertTrue(ok)
        self.assertEqual(score, Decimal("6"))
        ok, score = grade_objective(q, {"blanks": ["封装", "继承", "答错"]})
        self.assertFalse(ok)
        self.assertEqual(score, Decimal("0"))

    def test_blank_items_helper_compat(self):
        items = blank_items({"blanks": [{"text": "a", "score": 1}, "b", {"text": "c"}]})
        self.assertEqual(items[0], {"text": "a", "score": Decimal("1")})
        self.assertEqual(items[1], {"text": "b", "score": None})
        self.assertEqual(items[2], {"text": "c", "score": None})


class BlankSerializerValidationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_qval", password="pw123456!", role=User.Role.TEACHER)
        cls.course = Course.objects.create(name="Java程序设计", teacher=cls.teacher)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第一章")

    def _validate(self, data, instance=None, partial=False):
        request = APIRequestFactory().post("/")
        force_authenticate(request, user=self.teacher)
        serializer = QuestionSerializer(
            instance=instance, data=data, partial=partial, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        return serializer

    def _expect_error(self, data, message, instance=None, partial=False):
        request = APIRequestFactory().post("/")
        force_authenticate(request, user=self.teacher)
        serializer = QuestionSerializer(
            instance=instance, data=data, partial=partial, context={"request": request}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn(message, str(serializer.errors))

    def _base_payload(self, blanks):
        return {
            "course": self.course.id, "catalog": self.catalog.id,
            "qtype": "blank", "stem": "Java 三大特征：____、____、____。",
            "answer": {"blanks": blanks},
        }

    def test_valid_per_blank_payload_saves_sum_as_score(self):
        blanks = [{"text": "封装", "score": 3}, {"text": "继承", "score": 4}]
        serializer = self._validate(self._base_payload(blanks))
        q = serializer.save(creator=self.teacher)
        q.refresh_from_db()
        self.assertEqual(q.score, Decimal("7"))
        self.assertEqual([b["score"] for b in q.answer["blanks"]], [3.0, 4.0])

    def test_reject_blank_without_score(self):
        self._expect_error(
            self._base_payload([{"text": "封装"}, {"text": "继承", "score": 2}]),
            "第1空的分值不能为空",
        )

    def test_reject_zero_or_negative_score(self):
        self._expect_error(
            self._base_payload([{"text": "封装", "score": 0}]),
            "第1空的分值必须大于 0",
        )

    def test_reject_non_numeric_score(self):
        self._expect_error(
            self._base_payload([{"text": "封装", "score": "两分"}]),
            "第1空的分值必须是数字",
        )

    def test_reject_empty_blank_text(self):
        self._expect_error(
            self._base_payload([{"text": "  ", "score": 2}]),
            "第1空的答案不能为空",
        )

    def test_reject_empty_blanks_list(self):
        self._expect_error(self._base_payload([]), "填空题至少需要设置一个空")

    def test_status_only_patch_skips_answer_validation(self):
        """只改 status 的 PATCH 不触发答案校验（旧题运维操作不受影响）。"""
        q = _blank_question(course=self.course, catalog=self.catalog)
        serializer = self._validate({"status": "disabled"}, instance=q, partial=True)
        serializer.save()
        q.refresh_from_db()
        self.assertEqual(q.status, Question.Status.DISABLED)

    def test_answer_patch_still_validated(self):
        """PATCH answer 时同样按空校验。"""
        q = _blank_question(course=self.course, catalog=self.catalog)
        self._expect_error(
            {"answer": {"blanks": [{"text": "封装", "score": -1}]}},
            "第1空的分值必须大于 0",
            instance=q, partial=True,
        )


class ImportParserTests(SimpleTestCase):
    """import_parser.parse_questions：纯函数规则解析（无 IO，不落库）。"""

    # ------------------------------------------------------------------ 单选
    def test_single_choice_standard_dot_labels(self):
        """标准格式：一、单选题 + A. 选项 + 答案：B + 解析：xxx。"""
        text = (
            "一、单选题\n"
            "1. Java 中 int 占用的字节数是？\n"
            "A. 2\nB. 4\nC. 8\nD. 16\n"
            "答案：B\n"
            "解析：int 为 4 字节。"
        )
        drafts = parse_questions(text)
        self.assertEqual(len(drafts), 1)
        d = drafts[0]
        self.assertEqual(d["qtype"], "single")
        self.assertEqual(d["stem"], "Java 中 int 占用的字节数是？")
        self.assertEqual([o["key"] for o in d["options"]], ["A", "B", "C", "D"])
        self.assertEqual([o["text"] for o in d["options"]], ["2", "4", "8", "16"])
        self.assertEqual(d["answer"], {"key": "B"})
        self.assertEqual(d["analysis"], "int 为 4 字节。")
        self.assertEqual(d["score"], 2)
        self.assertEqual(d["difficulty"], "medium")
        self.assertEqual(d["knowledge_tags"], [])
        self.assertEqual(d["_warnings"], [])

    def test_single_choice_cn_punct_and_bracket_answer(self):
        """全角变体：一、单项选择题 + 1、+ A、 + 【答案】C（无冒号）。"""
        text = (
            "一、单项选择题\n"
            "1、下列哪个是 Java 的关键字？\n"
            "A、static\nB、final\nC、hello\nD、world\n"
            "【答案】C"
        )
        drafts = parse_questions(text)
        self.assertEqual(len(drafts), 1)
        d = drafts[0]
        self.assertEqual(d["qtype"], "single")
        self.assertEqual(d["stem"], "下列哪个是 Java 的关键字？")
        self.assertEqual(d["answer"], {"key": "C"})
        self.assertEqual(d["_warnings"], [])

    def test_single_choice_inline_options_pdf_style(self):
        """PDF 行内粘连选项：A.xxx B.xxx C.xxx D.xxx 需二次切分。"""
        text = (
            "一、单选题\n"
            "3. 下列哪项不属于面向对象特征？\n"
            "A.封装 B.继承 C.多态 D.函数\n"
            "答案：D"
        )
        drafts = parse_questions(text)
        self.assertEqual(len(drafts), 1)
        d = drafts[0]
        self.assertEqual(d["stem"], "下列哪项不属于面向对象特征？")
        self.assertEqual([o["text"] for o in d["options"]], ["封装", "继承", "多态", "函数"])
        self.assertEqual(d["answer"], {"key": "D"})

    def test_single_choice_digit_leading_stem_not_blocked(self):
        """数字开头题干（1. 1+1=?）必须放行——小数防护只挡 1.5 这类真小数。"""
        text = "一、单选题\n1. 1+1=?\nA. 2\nB. 3\nC. 4\nD. 5\n答案：A"
        drafts = parse_questions(text)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["stem"], "1+1=?")
        self.assertEqual(drafts[0]["answer"], {"key": "A"})

    def test_single_choice_score_tail_extracted(self):
        """题干尾部「（2分）」摘为分值，题干不留残尾。"""
        text = (
            "一、单选题\n"
            "1. Java 中 int 占用的字节数是？（2分）\n"
            "A. 2\nB. 4\nC. 8\nD. 16\n"
            "答案：B"
        )
        d = parse_questions(text)[0]
        self.assertEqual(d["stem"], "Java 中 int 占用的字节数是？")
        self.assertEqual(d["score"], 2.0)

    def test_single_choice_cn_labels_remapped(self):
        """甲乙丙丁选项归一为 A/B/C/D，答案「甲」同步重映射为 A。"""
        text = (
            "一、单选题\n"
            "1. 中国的首都是？\n"
            "甲. 北京\n乙. 上海\n丙. 广州\n丁. 深圳\n"
            "答案：甲"
        )
        d = parse_questions(text)[0]
        self.assertEqual([o["key"] for o in d["options"]], ["A", "B", "C", "D"])
        self.assertEqual([o["text"] for o in d["options"]], ["北京", "上海", "广州", "深圳"])
        self.assertEqual(d["answer"], {"key": "A"})

    def test_single_choice_paren_letter_labels(self):
        """（A）北京 括号字母选项：标签取括号内字母，答案按 A 归一。"""
        text = (
            "一、单选题\n"
            "1. 中国的首都是？\n"
            "（A）北京\n（B）上海\n（C）广州\n（D）深圳\n"
            "答案：A"
        )
        d = parse_questions(text)[0]
        self.assertEqual([o["key"] for o in d["options"]], ["A", "B", "C", "D"])
        self.assertEqual(d["answer"], {"key": "A"})
        self.assertEqual(d["_warnings"], [])

    def test_single_choice_table_row_options(self):
        """docx 无标签表格列兜底：制表符行首列题干、其余按序编号并告警。"""
        text = "一、单选题\n1. 中国的首都\t北京\t上海\t广州\t深圳\n答案：A"
        d = parse_questions(text)[0]
        self.assertEqual(d["stem"], "中国的首都")
        self.assertEqual([o["text"] for o in d["options"]], ["北京", "上海", "广州", "深圳"])
        self.assertEqual(d["answer"], {"key": "A"})
        self.assertIn("选项来自无标签表格列", "".join(d["_warnings"]))

    def test_table_header_row_skipped(self):
        """docx 表头行（题号/题干/选项/答案）被跳过，不起题。"""
        text = "题号\t题干\tA\tB\tC\tD\t答案\n1\t中国的首都\t北京\t上海\t广州\t深圳\tA"
        d = parse_questions(text)
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["stem"], "中国的首都")
        self.assertEqual([o["text"] for o in d[0]["options"]], ["北京", "上海", "广州", "深圳"])
        self.assertEqual(d[0]["answer"], {"key": "A"})

    def test_table_row_number_cell_starts_question(self):
        """表格题目行：题号列起新题，末列答案样式摘出为 answer。"""
        text = "1\tJava 中 int 占用的字节数是？\t2\t4\t8\t16\tB"
        d = parse_questions(text)
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["stem"], "Java 中 int 占用的字节数是？")
        self.assertEqual([o["text"] for o in d[0]["options"]], ["2", "4", "8", "16"])
        self.assertEqual(d[0]["answer"], {"key": "B"})
        self.assertEqual(d[0]["qtype"], "single")

    def test_table_row_judge_answer_cell(self):
        """表格判断题行：末列「对」摘出 → 题型判 judge、答案归一 A。"""
        text = "1\tJava 是编译型语言。\t对"
        d = parse_questions(text)
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["qtype"], "judge")
        self.assertEqual(d[0]["answer"], {"key": "A"})
        self.assertEqual(d[0]["options"], [])

    def test_table_row_without_answer_column_warns(self):
        """表格题目行无答案列：末列按选项处理，缺答案与无标签列双告警。"""
        text = "1\t中国的首都\t北京\t上海\t广州\t深圳"
        d = parse_questions(text)
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["qtype"], "single")
        self.assertEqual([o["text"] for o in d[0]["options"]], ["北京", "上海", "广州", "深圳"])
        self.assertIn("未识别到答案，请核对", d[0]["_warnings"])
        self.assertIn("选项来自无标签表格列", "".join(d[0]["_warnings"]))

    def test_single_choice_combined_marker_feeds_both(self):
        """「答案与解析：」合并标记：答案与解析都入账（不丢半截信息）。"""
        text = (
            "一、单选题\n"
            "1. 2+2=?\n"
            "A. 4\nB. 5\nC. 6\nD. 7\n"
            "答案与解析：选A，因为 2+2 等于 4。"
        )
        d = parse_questions(text)[0]
        self.assertEqual(d["answer"], {"key": "A"})
        self.assertEqual(d["analysis"], "选A，因为 2+2 等于 4。")
        self.assertEqual(d["_warnings"], [])

    def test_single_choice_paren_wrapped_marker(self):
        """「（答案：A）」整行括号包裹：残留「（」不污染题干。"""
        text = "一、单选题\n1. 1+1=?\nA. 2\nB. 3\nC. 4\nD. 5\n（答案：A）"
        d = parse_questions(text)[0]
        self.assertEqual(d["stem"], "1+1=?")
        self.assertEqual(d["answer"], {"key": "A"})
        self.assertEqual(d["_warnings"], [])

    # ------------------------------------------------------------------ 多选
    def test_multi_choice_dunhao_separated(self):
        """多选：答案「A、C」顿号分隔 → keys 列表。"""
        text = (
            "二、多选题\n"
            "1. 以下属于 Java 基本数据类型的有？\n"
            "A. int\nB. String\nC. double\nD. Object\n"
            "答案：A、C"
        )
        d = parse_questions(text)[0]
        self.assertEqual(d["qtype"], "multi")
        self.assertEqual(d["answer"], {"keys": ["A", "C"]})
        self.assertEqual(d["score"], 3)
        self.assertEqual(d["_warnings"], [])

    def test_multi_choice_concatenated(self):
        """多选：答案「AC」无分隔粘连 → keys 列表。"""
        text = (
            "二、多项选择题\n"
            "1. 以下属于 Java 基本数据类型的有？\n"
            "A. int\nB. String\nC. double\nD. Object\n"
            "答案：AC"
        )
        d = parse_questions(text)[0]
        self.assertEqual(d["qtype"], "multi")
        self.assertEqual(d["answer"], {"keys": ["A", "C"]})

    def test_multi_choice_circled_labels(self):
        """多选：① int 圈号+空白分隔选项；答案「①③」重映射为 A、C。"""
        text = (
            "一、多选题\n"
            "1. 以下属于 Java 基本数据类型的有？\n"
            "① int\n② String\n③ double\n④ Object\n"
            "答案：①③"
        )
        d = parse_questions(text)[0]
        self.assertEqual([o["key"] for o in d["options"]], ["A", "B", "C", "D"])
        self.assertEqual([o["text"] for o in d["options"]], ["int", "String", "double", "Object"])
        self.assertEqual(d["answer"], {"keys": ["A", "C"]})
        self.assertEqual(d["_warnings"], [])

    def test_single_section_multi_answer_autoconvert(self):
        """章节标注单选但答案含多个字母 → 转多选并告警（qtype 与 answer 结构一致）。"""
        text = (
            "一、单选题\n"
            "1. 以下哪些是 Java 基本类型？\n"
            "A. int\nB. String\nC. double\nD. Object\n"
            "答案：AC"
        )
        d = parse_questions(text)[0]
        self.assertEqual(d["qtype"], "multi")
        self.assertEqual(d["answer"], {"keys": ["A", "C"]})
        self.assertIn("原题型为单选但答案含多个选项", "".join(d["_warnings"]))

    def test_multi_answer_single_letter_warns(self):
        """多选答案不足两个选项 → 告警待修正。"""
        text = (
            "二、多选题\n"
            "1. 以下属于 Java 基本数据类型的有？\n"
            "A. int\nB. String\nC. double\nD. Object\n"
            "答案：A"
        )
        d = parse_questions(text)[0]
        self.assertEqual(d["answer"], {"keys": ["A"]})
        self.assertIn("多选题答案不足两个选项", "".join(d["_warnings"]))

    # ------------------------------------------------------------------ 判断
    def test_judge_correct_wrong_words(self):
        """判断：对 → A、错 → B。"""
        text = (
            "五、判断题\n"
            "1. Java 是编译型语言。\n答案：对\n"
            "2. Python 是纯编译型语言。\n答案：错"
        )
        drafts = parse_questions(text)
        self.assertEqual(len(drafts), 2)
        self.assertEqual([d["answer"]["key"] for d in drafts], ["A", "B"])
        self.assertEqual([d["qtype"] for d in drafts], ["judge", "judge"])
        self.assertEqual([d["_warnings"] for d in drafts], [[], []])

    def test_judge_symbols(self):
        """判断：√ → A、× → B。"""
        text = (
            "五、判断题\n"
            "1. Java 支持多继承。\n答案：×\n"
            "2. Java 支持单继承。\n答案：√"
        )
        drafts = parse_questions(text)
        self.assertEqual([d["answer"]["key"] for d in drafts], ["B", "A"])

    def test_judge_tf_letters(self):
        """判断：T → A、F → B。"""
        text = (
            "五、判断题\n"
            "1. Java 是编译型语言。\n答案：T\n"
            "2. Python 是解释型语言。\n答案：F"
        )
        drafts = parse_questions(text)
        self.assertEqual([d["answer"]["key"] for d in drafts], ["A", "B"])

    def test_judge_unrecognized_answer_warns(self):
        """判断答案无法归一（「不确定」）→ 双重告警。"""
        text = "五、判断题\n1. Java 是编译型语言。\n答案：不确定"
        d = parse_questions(text)[0]
        self.assertEqual(d["answer"], {})
        joined = "".join(d["_warnings"])
        self.assertIn("未能识别判断答案", joined)
        self.assertIn("未识别到答案", joined)

    # ------------------------------------------------------------------ 填空
    def test_blank_underscore_semicolon(self):
        """填空：____ 空位 + 分号分隔答案。"""
        text = (
            "六、填空题\n"
            "1. Java 三大特征是____、____、____。\n"
            "答案：封装；继承；多态"
        )
        d = parse_questions(text)[0]
        self.assertEqual(d["qtype"], "blank")
        self.assertEqual(d["answer"], {"blanks": [{"text": "封装"}, {"text": "继承"}, {"text": "多态"}]})
        self.assertEqual(d["score"], 4)
        self.assertEqual(d["_warnings"], [])

    def test_blank_parenthesis_dunhao(self):
        """填空：全角空括号（ ）+ 顿号分隔答案。"""
        text = (
            "六、填空题\n"
            "1. HTTP 默认端口是（ ），HTTPS 默认端口是（ ）。\n"
            "答案：80、443"
        )
        d = parse_questions(text)[0]
        self.assertEqual(d["answer"], {"blanks": [{"text": "80"}, {"text": "443"}]})
        self.assertEqual(d["_warnings"], [])

    def test_blank_annotations_stripped(self):
        """填空：①封装（2分）②继承（2分）——序号环切 + 分值注释剥除。"""
        text = (
            "六、填空题\n"
            "1. Java 三大特征是____、____。\n"
            "答案：①封装（2分）②继承（2分）"
        )
        d = parse_questions(text)[0]
        self.assertEqual(d["answer"], {"blanks": [{"text": "封装"}, {"text": "继承"}]})
        self.assertEqual(d["_warnings"], [])

    def test_blank_count_mismatch_warns(self):
        """空位数与答案数不一致 → 告警。"""
        text = (
            "六、填空题\n"
            "1. Java 三大特征是____、____、____。\n"
            "答案：封装；继承"
        )
        d = parse_questions(text)[0]
        self.assertEqual(len(d["answer"]["blanks"]), 2)
        self.assertIn("空位数（3）与答案数（2）不一致", "".join(d["_warnings"]))

    # ------------------------------------------------------------------ 简答
    def test_short_answer_reference(self):
        """简答：无选项无空位，取「参考答案」原文。"""
        text = (
            "七、简答题\n"
            "1. 简述 Java 平台无关性的实现原理。\n"
            "参考答案：Java 源码经编译器生成与平台无关的字节码，由 JVM 解释执行。"
        )
        d = parse_questions(text)[0]
        self.assertEqual(d["qtype"], "short")
        self.assertEqual(d["answer"], {"text": "Java 源码经编译器生成与平台无关的字节码，由 JVM 解释执行。"})
        self.assertEqual(d["score"], 10)
        self.assertEqual(d["_warnings"], [])

    def test_short_answer_score_tail(self):
        """简答：题干尾部「（10分）」覆盖默认分值。"""
        text = (
            "七、简答题\n"
            "1. 简述 Java 平台无关性的实现原理。（10分）\n"
            "参考答案：Java 源码经编译器生成字节码。"
        )
        d = parse_questions(text)[0]
        self.assertEqual(d["stem"], "简述 Java 平台无关性的实现原理。")
        self.assertEqual(d["score"], 10.0)

    # ------------------------------------------------------------ 结构与边界
    def test_section_title_variants(self):
        """题型标题变体：第一部分 判断题 / 裸标题「单选题（每题2分）」。"""
        text = (
            "第一部分 判断题\n"
            "1. Java 是编译型语言。\n答案：对\n"
            "单选题（每题2分）\n"
            "2. 1+1=?\nA. 2\nB. 3\nC. 4\nD. 5\n答案：A"
        )
        drafts = parse_questions(text)
        self.assertEqual(len(drafts), 2)
        self.assertEqual(drafts[0]["qtype"], "judge")
        self.assertEqual(drafts[1]["qtype"], "single")
        self.assertEqual([d["_warnings"] for d in drafts], [[], []])

    def test_no_section_infers_type(self):
        """无题型标题 → 按结构推断（有选项→单选/多选、有空位→填空、其余→简答）并告警。"""
        text = (
            "1. 1+1=?\nA. 2\nB. 3\n答案：A\n"
            "2. Java 三大特征是____、____、____。\n答案：封装；继承；多态\n"
            "3. 请简述进程与线程的区别。\n参考答案：进程是资源分配的最小单位。"
        )
        drafts = parse_questions(text)
        self.assertEqual([d["qtype"] for d in drafts], ["single", "blank", "short"])
        for d in drafts:
            self.assertIn("未识别到题型标题，已按结构推断", d["_warnings"])

    def test_stem_wrap_across_lines(self):
        """跨页续接：题干折行直接相连，中文间不留空格。"""
        text = (
            "一、单选题\n"
            "1. 下列关于 Java 虚拟机\n的说法正确的是？\n"
            "A. 一次编译到处运行\nB. 跨平台\nC. 需要手动内存管理\nD. 以上都不对\n"
            "答案：A"
        )
        d = parse_questions(text)[0]
        self.assertEqual(d["stem"], "下列关于 Java 虚拟机的说法正确的是？")
        self.assertEqual(d["answer"], {"key": "A"})

    def test_option_wrap_continues_option(self):
        """选项换行续接并入最后一个选项，不污染题干。"""
        text = (
            "一、单选题\n"
            "1. 下列关于 Java 平台无关性的说法正确的是？\n"
            "A. 一次编译，\n到处运行\n"
            "B. 依赖 JVM 解释执行\nC. 需要为每个平台重新编译\nD. 代码在操作系统上直接运行\n"
            "答案：A"
        )
        d = parse_questions(text)[0]
        self.assertEqual(d["options"][0]["text"], "一次编译，到处运行")
        self.assertEqual(d["stem"], "下列关于 Java 平台无关性的说法正确的是？")

    def test_answer_summary_lines_skipped(self):
        """卷末答案速查行（1.A / 2.B）跳过，不计入题干、不产生额外题目。"""
        text = (
            "一、单选题\n"
            "1. 1+1=?\nA. 2\nB. 3\nC. 4\nD. 5\n答案：A\n"
            "2. 2+2=?\nA. 4\nB. 5\nC. 6\nD. 7\n答案：B\n"
            "参考答案：\n1.A\n2.B"
        )
        drafts = parse_questions(text)
        self.assertEqual(len(drafts), 2)
        self.assertEqual([d["answer"]["key"] for d in drafts], ["A", "B"])

    def test_decimal_number_not_question_start(self):
        """「1.5 是 Java 的版本号吗？」是真小数不是题号 → 不成题。"""
        text = "一、单选题\n1.5 是 Java 的版本号吗？\nA. 是\nB. 否"
        self.assertEqual(parse_questions(text), [])

    def test_preamble_and_symbol_lines_skipped(self):
        """卷首说明/分值行/空行跳过，前导内容不成题。"""
        text = (
            "Java 程序设计试题\n"
            "（满分 100 分）\n\n"
            "一、单选题\n"
            "1. 1+1=?\nA. 2\nB. 3\nC. 4\nD. 5\n答案：A"
        )
        drafts = parse_questions(text)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["stem"], "1+1=?")

    def test_crlf_normalized(self):
        """Windows 换行 \\r\\n 归一化，题干不留 \\r。"""
        text = "一、单选题\r\n1. 1+1=?\r\nA. 2\r\nB. 3\r\nC. 4\r\nD. 5\r\n答案：A"
        d = parse_questions(text)[0]
        self.assertEqual(d["stem"], "1+1=?")
        self.assertNotIn("\r", d["stem"])

    def test_empty_text(self):
        """空文本/纯空白 → []。"""
        self.assertEqual(parse_questions(""), [])
        self.assertEqual(parse_questions("\n\n   \n"), [])

    # ------------------------------------------------------------------ 告警
    def test_warning_missing_answer(self):
        """缺答案 → 告警「未识别到答案」。"""
        text = "一、单选题\n1. 下列哪个是 Java 关键字？\nA. static\nB. final"
        d = parse_questions(text)[0]
        self.assertEqual(d["answer"], {})
        self.assertIn("未识别到答案", "".join(d["_warnings"]))

    def test_warning_insufficient_options(self):
        """选项不足 → 告警（选项数入文案）。"""
        text = "一、单选题\n1. 下列哪个是 Java 关键字？\n答案：A"
        d = parse_questions(text)[0]
        self.assertEqual(d["options"], [])
        self.assertIn("选项不足（识别到 0 个）", "".join(d["_warnings"]))


# ---------------------------------------------------------------------------
# 文档导入 API（设计方案 §2.4）
# ---------------------------------------------------------------------------

_IMPORT_TXT = (
    "一、单选题\n"
    "1. Java 中 int 占用的字节数是？\n"
    "A. 2\nB. 4\nC. 8\nD. 16\n"
    "答案：B\n"
    "解析：int 为 4 字节。\n"
    "二、判断题\n"
    "1. Java 是编译型语言。\n"
    "答案：对"
)


class QuestionImportApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_import", password="pw123456!", role=User.Role.TEACHER)
        cls.outsider = User.objects.create_user(username="t_import2", password="pw123456!", role=User.Role.TEACHER)
        cls.student = User.objects.create_user(username="s_import", password="pw123456!", role=User.Role.STUDENT)
        cls.course = Course.objects.create(name="Java程序设计", teacher=cls.teacher)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第一章")
        cls.outsider_course = Course.objects.create(name="他人课程", teacher=cls.outsider)

    def _upload(self, content, filename="题库.txt", course=None, catalog=None):
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile(filename, content.encode("utf-8"), content_type="text/plain")
        return self.client.post(
            "/api/questions/import/",
            {
                "file": upload,
                "course": course or self.course.id,
                "catalog": self.catalog.id if catalog is None else catalog,
            },
            format="multipart",
        )

    def test_import_txt_creates_batch_with_drafts(self):
        self.client.force_authenticate(user=self.teacher)
        response = self._upload(_IMPORT_TXT)
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        self.assertEqual(data["origin"], "import")
        self.assertEqual(data["status"], "parsed")
        self.assertEqual(data["file_name"], "题库.txt")
        self.assertEqual(len(data["drafts"]), 2)
        self.assertEqual(data["stats"]["total"], 2)
        self.assertEqual(data["stats"]["warned"], 0)
        batch = QuestionDraftBatch.objects.get(pk=data["id"])
        self.assertTrue(batch.file.name.startswith("question_imports/"))
        self.assertEqual(batch.catalog_id, self.catalog.id)
        self.assertIn("int 为 4 字节", batch.raw_text)

    def test_import_without_catalog_allowed(self):
        """catalog 可选：导入时不选章节，后续 PATCH 补（决策：一篇文档一个目标章节）。"""
        self.client.force_authenticate(user=self.teacher)
        response = self._upload(_IMPORT_TXT, catalog="")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["data"]["catalog"])

    def test_import_rejects_unsupported_extension(self):
        self.client.force_authenticate(user=self.teacher)
        response = self._upload(_IMPORT_TXT, filename="题库.exe")
        self.assertEqual(response.status_code, 400)
        self.assertIn("暂不支持该文件格式", response.data["message"])

    def test_import_rejects_magic_mismatch(self):
        """扩展名 .pdf 但内容是文本 → 魔数复检拒绝（附录 B-5 防伪造/损坏）。"""
        self.client.force_authenticate(user=self.teacher)
        response = self._upload(_IMPORT_TXT, filename="题库.pdf")
        self.assertEqual(response.status_code, 400)
        self.assertIn("文件内容与扩展名不符", response.data["message"])

    def test_import_rejects_oversize(self):
        self.client.force_authenticate(user=self.teacher)
        from django.core.files.uploadedfile import SimpleUploadedFile

        big = SimpleUploadedFile("大文件.txt", b"x" * (10 * 1024 * 1024 + 1), content_type="text/plain")
        response = self.client.post(
            "/api/questions/import/", {"file": big, "course": self.course.id}, format="multipart"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("10MB", response.data["message"])

    def test_import_rejects_no_questions(self):
        self.client.force_authenticate(user=self.teacher)
        response = self._upload("这是一段没有任何题目结构的说明文字。")
        self.assertEqual(response.status_code, 400)
        self.assertIn("未能识别出题目", response.data["message"])

    def test_import_rejects_empty_text(self):
        self.client.force_authenticate(user=self.teacher)
        response = self._upload("   \n\n  ")
        self.assertEqual(response.status_code, 400)
        self.assertIn("未能提取到文本内容", response.data["message"])

    def test_import_rejects_other_teacher_course(self):
        self.client.force_authenticate(user=self.outsider)
        response = self._upload(_IMPORT_TXT, course=self.course.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("只能导入到自己负责课程", response.data["message"])

    def test_import_rejects_catalog_of_other_course(self):
        self.client.force_authenticate(user=self.teacher)
        other_catalog = Catalog.objects.create(course=self.outsider_course, title="外课程章节")
        response = self._upload(_IMPORT_TXT, catalog=other_catalog.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("所选章节不属于当前课程", response.data["message"])

    def test_import_student_forbidden(self):
        """学生不可见导入端点（批次含答案解析，附录 B-2）。"""
        self.client.force_authenticate(user=self.student)
        response = self._upload(_IMPORT_TXT)
        self.assertEqual(response.status_code, 403)

    def test_import_platform_admin_allowed(self):
        admin = User.objects.create_user(username="admin_imp", password="pw123456!", role=User.Role.ADMIN)
        self.client.force_authenticate(user=admin)
        response = self._upload(_IMPORT_TXT, course=self.course.id)
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# 草稿批次 API + 入库管道（设计方案 §2.4 / 附录 B-2/B-3/B-4）
# ---------------------------------------------------------------------------


def _draft(qtype="single", stem="1+1=?", **kw):
    base = {
        "qtype": qtype, "stem": stem, "options": [], "answer": {}, "analysis": "",
        "score": 2, "difficulty": "medium", "knowledge_tags": [], "_warnings": [],
    }
    base.update(kw)
    return base


class QuestionDraftBatchApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_batch", password="pw123456!", role=User.Role.TEACHER)
        cls.outsider = User.objects.create_user(username="t_batch2", password="pw123456!", role=User.Role.TEACHER)
        cls.student = User.objects.create_user(username="s_batch", password="pw123456!", role=User.Role.STUDENT)
        cls.course = Course.objects.create(name="Java程序设计", teacher=cls.teacher)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第一章")
        cls.catalog2 = Catalog.objects.create(course=cls.course, title="第二章")
        cls.outsider_course = Course.objects.create(name="他人课程", teacher=cls.outsider)

    def _make_batch(self, drafts=None, catalog="__default__", with_file=False, **kw):
        batch = QuestionDraftBatch.objects.create(
            origin=kw.pop("origin", QuestionDraftBatch.Origin.IMPORT),
            course=kw.pop("course", self.course),
            catalog=self.catalog if catalog == "__default__" else catalog,
            creator=kw.pop("creator", self.teacher),
            drafts=drafts if drafts is not None else [],
            **kw,
        )
        if with_file:
            from django.core.files.base import ContentFile

            batch.file.save("question_imports/test.txt", ContentFile(b"raw"), save=True)
        return batch

    def _full_drafts(self):
        return [
            _draft(qtype="single", stem="1+1=?",
                   options=[{"key": "A", "text": "2"}, {"key": "B", "text": "3"}],
                   answer={"key": "A"}),
            _draft(qtype="judge", stem="Java 是编译型语言。", answer={"key": "对"}),
            _draft(qtype="blank", stem="三大特征是____、____、____。", score=4,
                   answer={"blanks": [{"text": "封装"}, {"text": "继承"}, {"text": "多态"}]}),
            _draft(qtype="multi", stem="哪些是基本类型？", score=3,
                   options=[{"key": "A", "text": "int"}, {"key": "B", "text": "String"},
                            {"key": "C", "text": "double"}, {"key": "D", "text": "Object"}],
                   answer={"keys": ["A", "C"]}),
            _draft(qtype="short", stem="简述进程与线程的区别。", score=10,
                   answer={"text": "进程是资源分配单位，线程是调度单位。"}),
        ]

    # ------------------------------------------------------------- 列表/详情
    def test_list_scoped_to_own_courses(self):
        mine = self._make_batch()
        self._make_batch(course=self.outsider_course, creator=self.outsider)
        self.client.force_authenticate(user=self.teacher)
        response = self.client.get("/api/question-draft-batches/")
        self.assertEqual(response.status_code, 200)
        ids = [b["id"] for b in response.data["data"]["results"]]
        self.assertIn(mine.id, ids)
        self.assertEqual(len(ids), 1)

    def test_list_filters_by_course_and_status(self):
        batch = self._make_batch()
        self.client.force_authenticate(user=self.teacher)
        response = self.client.get(f"/api/question-draft-batches/?course={self.course.id}&status=parsed")
        self.assertEqual([b["id"] for b in response.data["data"]["results"]], [batch.id])
        response = self.client.get("/api/question-draft-batches/?status=saved")
        self.assertEqual(response.data["data"]["results"], [])

    def test_student_forbidden_on_batch_endpoints(self):
        batch = self._make_batch(self._full_drafts())
        self.client.force_authenticate(user=self.student)
        self.assertEqual(self.client.get("/api/question-draft-batches/").status_code, 403)
        self.assertEqual(self.client.get(f"/api/question-draft-batches/{batch.id}/").status_code, 403)

    def test_other_teacher_gets_404(self):
        batch = self._make_batch(self._full_drafts())
        self.client.force_authenticate(user=self.outsider)
        response = self.client.get(f"/api/question-draft-batches/{batch.id}/")
        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------- PATCH
    def test_patch_drafts_persisted(self):
        batch = self._make_batch(self._full_drafts())
        drafts = self._full_drafts()
        drafts[0]["stem"] = "1+1 等于几？"
        self.client.force_authenticate(user=self.teacher)
        response = self.client.patch(
            f"/api/question-draft-batches/{batch.id}/", {"drafts": drafts}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        batch.refresh_from_db()
        self.assertEqual(batch.drafts[0]["stem"], "1+1 等于几？")

    def test_patch_catalog_switches_target(self):
        batch = self._make_batch()
        self.client.force_authenticate(user=self.teacher)
        response = self.client.patch(
            f"/api/question-draft-batches/{batch.id}/", {"catalog": self.catalog2.id}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        batch.refresh_from_db()
        self.assertEqual(batch.catalog_id, self.catalog2.id)

    def test_patch_catalog_of_other_course_rejected(self):
        batch = self._make_batch()
        other_catalog = Catalog.objects.create(course=self.outsider_course, title="外课程章节")
        self.client.force_authenticate(user=self.teacher)
        response = self.client.patch(
            f"/api/question-draft-batches/{batch.id}/", {"catalog": other_catalog.id}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("所选章节不属于当前课程", response.data["message"])

    def test_patch_readonly_fields_ignored(self):
        batch = self._make_batch()
        self.client.force_authenticate(user=self.teacher)
        self.client.patch(
            f"/api/question-draft-batches/{batch.id}/",
            {"status": "saved", "origin": "ai_gen"}, format="json",
        )
        batch.refresh_from_db()
        self.assertEqual(batch.status, "parsed")
        self.assertEqual(batch.origin, "import")

    # ------------------------------------------------------------- save 管道
    def test_save_all_drafts_normalizes_and_creates_questions(self):
        batch = self._make_batch(self._full_drafts())
        self.client.force_authenticate(user=self.teacher)
        response = self.client.post(
            f"/api/question-draft-batches/{batch.id}/save/",
            {"items": self._full_drafts()}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        result = response.data["data"]
        self.assertEqual(len(result["saved"]), 5)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["remaining"], 0)

        questions = {q.id: q for q in Question.objects.filter(course=self.course)}
        self.assertEqual(len(questions), 5)
        # 判断题：答案归一 A/B + 补对错选项
        judge = next(q for q in questions.values() if q.qtype == "judge")
        self.assertEqual(judge.answer, {"key": "A"})
        self.assertEqual([o["key"] for o in judge.options], ["A", "B"])
        # 填空题：按空均分，Σ=每题总分
        blank = next(q for q in questions.values() if q.qtype == "blank")
        self.assertEqual([b["score"] for b in blank.answer["blanks"]], [1.4, 1.3, 1.3])
        self.assertEqual(blank.score, Decimal("4"))
        # source=文档导入、状态=草稿
        self.assertTrue(all(q.source == "import" and q.status == "draft" for q in questions.values()))

        batch.refresh_from_db()
        self.assertEqual(batch.drafts, [])
        self.assertEqual(batch.status, "saved")
        self.assertFalse(batch.file)  # 入库即删

    def test_save_with_publish_marks_questions_published(self):
        """publish=True：入库题目直接置「已发布」，省去逐题点发布（导入/AI 生题共用）。"""
        batch = self._make_batch(self._full_drafts())
        self.client.force_authenticate(user=self.teacher)
        response = self.client.post(
            f"/api/question-draft-batches/{batch.id}/save/",
            {"items": self._full_drafts(), "publish": True}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        result = response.data["data"]
        self.assertEqual(len(result["saved"]), 5)
        questions = Question.objects.filter(course=self.course)
        self.assertEqual(questions.count(), 5)
        self.assertTrue(all(q.status == "published" for q in questions))
        # 默认路径仍为草稿（回归保护：publish 缺省不改变原口径）
        default_draft = {**self._full_drafts()[0], "stem": "默认路径回归保护题干（不与已发布题重复）"}
        batch2 = self._make_batch([default_draft])
        response = self.client.post(
            f"/api/question-draft-batches/{batch2.id}/save/",
            {"items": [default_draft]}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["data"]["saved"]), 1)
        draft_q = Question.objects.get(id=response.data["data"]["saved"][0])
        self.assertEqual(draft_q.status, "draft")

    def test_save_partial_failure_keeps_failed_draft(self):
        drafts = self._full_drafts()
        drafts[1]["answer"] = {"key": "可能是"}  # 判断题无法归一 → failed
        batch = self._make_batch(drafts)
        self.client.force_authenticate(user=self.teacher)
        response = self.client.post(
            f"/api/question-draft-batches/{batch.id}/save/", {"items": drafts}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        result = response.data["data"]
        self.assertEqual(len(result["saved"]), 4)
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(result["failed"][0]["index"], 1)
        self.assertIn("判断题答案", result["failed"][0]["error"])
        self.assertEqual(result["remaining"], 1)
        batch.refresh_from_db()
        self.assertEqual(len(batch.drafts), 1)  # 失败项留批次内可修正重试
        self.assertEqual(batch.status, "parsed")

    def test_save_dedup_skips_existing_stem(self):
        batch = self._make_batch(self._full_drafts())
        Question.objects.create(
            course=self.course, catalog=self.catalog, qtype="single",
            stem="1+1=?", options=[{"key": "A", "text": "2"}], answer={"key": "A"}, score=2,
        )
        self.client.force_authenticate(user=self.teacher)
        response = self.client.post(
            f"/api/question-draft-batches/{batch.id}/save/",
            {"items": [self._full_drafts()[0]]}, format="json",
        )
        result = response.data["data"]
        self.assertEqual(result["saved"], [])
        self.assertEqual(result["skipped"], 1)
        batch.refresh_from_db()
        self.assertEqual(len(batch.drafts), 5)  # 跳过项保留，可改题干后重试

    def test_save_repeat_submit_no_duplicates(self):
        """响应丢失后重试：精确查重保证不产生重复入库（附录 B-3）。"""
        drafts = self._full_drafts()
        batch = self._make_batch(drafts)
        self.client.force_authenticate(user=self.teacher)
        url = f"/api/question-draft-batches/{batch.id}/save/"
        first = self.client.post(url, {"items": [drafts[0]]}, format="json")
        self.assertEqual(len(first.data["data"]["saved"]), 1)
        second = self.client.post(url, {"items": [drafts[0]]}, format="json")
        self.assertEqual(second.data["data"]["saved"], [])
        self.assertEqual(second.data["data"]["skipped"], 1)
        self.assertEqual(Question.objects.filter(course=self.course, stem="1+1=?").count(), 1)

    def test_save_requires_catalog(self):
        batch = self._make_batch(self._full_drafts(), catalog=None)
        self.client.force_authenticate(user=self.teacher)
        response = self.client.post(
            f"/api/question-draft-batches/{batch.id}/save/",
            {"items": [self._full_drafts()[0]]}, format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("请先为批次选择目标章节", response.data["message"])

    def test_save_rejects_empty_items(self):
        batch = self._make_batch(self._full_drafts())
        self.client.force_authenticate(user=self.teacher)
        response = self.client.post(
            f"/api/question-draft-batches/{batch.id}/save/", {"items": []}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("提交内容不能为空", response.data["message"])

    def test_save_saved_batch_rejected(self):
        batch = self._make_batch(self._full_drafts())
        batch.status = QuestionDraftBatch.Status.SAVED
        batch.save()
        self.client.force_authenticate(user=self.teacher)
        response = self.client.post(
            f"/api/question-draft-batches/{batch.id}/save/",
            {"items": [self._full_drafts()[0]]}, format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("已全部入库", response.data["message"])

    def test_save_single_missing_options_failed(self):
        drafts = [_draft(stem="没有选项的题", answer={"key": "A"})]
        batch = self._make_batch(drafts)
        self.client.force_authenticate(user=self.teacher)
        response = self.client.post(
            f"/api/question-draft-batches/{batch.id}/save/", {"items": drafts}, format="json"
        )
        result = response.data["data"]
        self.assertEqual(result["saved"], [])
        self.assertIn("至少需要 2 个选项", result["failed"][0]["error"])

    def test_save_multi_answer_not_in_options_failed(self):
        drafts = [_draft(
            qtype="multi", stem="越界答案",
            options=[{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
            answer={"keys": ["A", "Z"]},
        )]
        batch = self._make_batch(drafts)
        self.client.force_authenticate(user=self.teacher)
        response = self.client.post(
            f"/api/question-draft-batches/{batch.id}/save/", {"items": drafts}, format="json"
        )
        self.assertIn("不在选项中", response.data["data"]["failed"][0]["error"])

    def test_save_ai_gen_batch_marks_source_ai(self):
        batch = QuestionDraftBatch.objects.create(
            origin=QuestionDraftBatch.Origin.AI_GEN, course=self.course,
            catalog=self.catalog, creator=self.teacher, drafts=self._full_drafts(),
        )
        self.client.force_authenticate(user=self.teacher)
        self.client.post(
            f"/api/question-draft-batches/{batch.id}/save/",
            {"items": [self._full_drafts()[0]]}, format="json",
        )
        q = Question.objects.get(course=self.course, stem="1+1=?")
        self.assertEqual(q.source, "ai")

    # ------------------------------------------------------------- DELETE
    def test_destroy_deletes_file_then_row(self):
        batch = self._make_batch(self._full_drafts(), with_file=True)
        name = batch.file.name
        self.assertTrue(batch.file.storage.exists(name))
        self.client.force_authenticate(user=self.teacher)
        response = self.client.delete(f"/api/question-draft-batches/{batch.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(QuestionDraftBatch.objects.filter(pk=batch.id).exists())
        self.assertFalse(batch.file.storage.exists(name))


# ---------------------------------------------------------------------------
# AI 多类型生题（阶段 4）
# ---------------------------------------------------------------------------
_QGEN_LABELS = (
    ("single", "单选题"),
    ("multi", "多选题"),
    ("judge", "判断题"),
    ("blank", "填空题"),
    ("short", "简答题"),
)


def _qgen_items(qtype: str, n: int = 2) -> list[dict]:
    """按题型契约生成确定性合规题（供 _QGenProvider 脚本化返回）。"""
    items = []
    for i in range(1, n + 1):
        base = {
            "qtype": qtype,
            "stem": f"测试{qtype}第{i}题",
            "analysis": "本题考查核心概念。",
            "difficulty": "medium",
            "knowledge_tags": ["标签甲"],
        }
        if qtype in ("single", "multi"):
            base["options"] = [
                {"key": "A", "text": "甲"}, {"key": "B", "text": "乙"},
                {"key": "C", "text": "丙"}, {"key": "D", "text": "丁"},
            ]
            base["answer"] = {"key": "AB"[(i - 1) % 2]} if qtype == "single" else {"keys": ["A", "C"]}
        elif qtype == "judge":
            base["answer"] = {"key": "A" if i % 2 else "B"}
        elif qtype == "blank":
            base["options"] = []
            base["answer"] = {"blanks": [{"text": f"答案{i}"}]}
        else:  # short
            base["options"] = []
            base["answer"] = {"text": "参考答案"}
        items.append(base)
    return items


class _QGenProvider(BaseAIProvider):
    """生题测试替身：按 prompt 中的题型返回确定性 JSON；fail_qtypes 中的题型调用抛错。

    dirty=True 时额外混入 2 条不合规题（缺选项 / 空题干），验证丢弃与告警。
    """

    name = "stub"

    def __init__(self, fail_qtypes=(), dirty=False):
        self.fail_qtypes = set(fail_qtypes)
        self.dirty = dirty
        self.calls: list[str] = []

    def chat(self, messages, **kwargs):
        content = messages[-1]["content"] if messages else ""
        for qtype, label in _QGEN_LABELS:
            if f"题型={label}" in content:
                self.calls.append(qtype)
                if qtype in self.fail_qtypes:
                    raise RuntimeError(f"模拟{label}生成失败")
                items = _qgen_items(qtype)
                if self.dirty and qtype == "single":
                    items = items + [
                        {"qtype": "single", "stem": "缺选项",
                         "options": [{"key": "A", "text": "甲"}], "answer": {"key": "A"}},
                        {"qtype": "single", "stem": "",
                         "options": [{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
                         "answer": {"key": "A"}},
                    ]
                return json.dumps(items, ensure_ascii=False)
        return "[]"

    def embed(self, texts):
        raise NotImplementedError


def _patch_pipeline_provider(provider):
    """patch 生题流水线的 Provider 并保活到测试结束（同步线程模式下随请求同步执行）。"""
    patcher = patch("apps.questions.question_gen_ai.get_provider", return_value=provider)
    patcher.start()
    return patcher


class QuestionAiGenApiTests(APITestCase):
    """generate 端点：groups 校验 / 课程章节归属 / 防重复提交 / 学生禁入。"""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_aigen", password="pw123456!", role=User.Role.TEACHER)
        cls.outsider = User.objects.create_user(username="t_aigen2", password="pw123456!", role=User.Role.TEACHER)
        cls.student = User.objects.create_user(username="s_aigen", password="pw123456!", role=User.Role.STUDENT)
        cls.course = Course.objects.create(name="Java程序设计", teacher=cls.teacher)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第一章")
        cls.outsider_course = Course.objects.create(name="他人课程", teacher=cls.outsider)
        cls.outsider_catalog = Catalog.objects.create(course=cls.outsider_course, title="第一章")

    def setUp(self):
        # daemon 线程改同步执行 + mock provider：提交即完整跑完，断言确定性
        thread_patcher = patch("apps.ai.tasks.threading", _FakeThreading)
        thread_patcher.start()
        self.addCleanup(thread_patcher.stop)
        provider_patcher = _patch_pipeline_provider(MockProvider())
        self.addCleanup(provider_patcher.stop)

    def _post(self, payload, user=None):
        self.client.force_authenticate(user=user or self.teacher)
        return self.client.post("/api/questions/generate/", payload, format="json")

    def _groups(self):
        return [
            {"qtype": "single", "count": 2, "score": 2},
            {"qtype": "judge", "count": 1, "score": 2},
        ]

    def test_generate_requires_catalog(self):
        response = self._post({"course": self.course.id, "groups": self._groups()})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "请先选择题目所属章节")

    def test_generate_rejects_foreign_catalog(self):
        response = self._post({
            "course": self.outsider_course.id, "catalog": self.outsider_catalog.id,
            "groups": self._groups(),
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "所选章节不属于当前课程")

    def test_generate_rejects_empty_groups(self):
        response = self._post({"course": self.course.id, "catalog": self.catalog.id, "groups": []})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "请至少选择一个题型并设置数量")

    def test_generate_rejects_missing_groups(self):
        response = self._post({"course": self.course.id, "catalog": self.catalog.id})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "请至少选择一个题型并设置数量")

    def test_generate_rejects_unknown_qtype(self):
        response = self._post({
            "course": self.course.id, "catalog": self.catalog.id,
            "groups": [{"qtype": "essay", "count": 2, "score": 2}],
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "不支持的题型：essay")

    def test_generate_rejects_count_out_of_range(self):
        response = self._post({
            "course": self.course.id, "catalog": self.catalog.id,
            "groups": [{"qtype": "single", "count": 21, "score": 2}],
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "每种题型数量需在 1-20 之间")

    def test_generate_rejects_score_out_of_range(self):
        response = self._post({
            "course": self.course.id, "catalog": self.catalog.id,
            "groups": [{"qtype": "single", "count": 2, "score": 0}],
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "每题分值需在 0.5-100 之间")

    def test_generate_rejects_too_many_groups(self):
        groups = [{"qtype": q, "count": 1, "score": 2} for q, _ in Question.QType.choices] + [
            {"qtype": "single", "count": 1, "score": 2}
        ]
        response = self._post({"course": self.course.id, "catalog": self.catalog.id, "groups": groups})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "一次最多同时生成 5 种题型")

    def test_generate_rejects_total_over_limit(self):
        # 单组合法（20），3 组合计 60 > 50 → 总数上限拦截
        response = self._post({
            "course": self.course.id, "catalog": self.catalog.id,
            "groups": [
                {"qtype": "single", "count": 20, "score": 2},
                {"qtype": "multi", "count": 20, "score": 3},
                {"qtype": "judge", "count": 20, "score": 2},
            ],
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "一次生成题目总数不可超过 50")

    def test_generate_rejects_non_numeric_count(self):
        response = self._post({
            "course": self.course.id, "catalog": self.catalog.id,
            "groups": [{"qtype": "single", "count": "两份", "score": 2}],
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "题型数量与分值必须是数字")

    def test_generate_submits_task_and_builds_batch(self):
        response = self._post({
            "course": self.course.id, "catalog": self.catalog.id,
            "objective": "覆盖核心知识点", "groups": self._groups(),
        })
        self.assertEqual(response.status_code, 200)
        task_id = response.data["data"]["task_id"]
        task = AITask.objects.get(id=task_id)
        # 同步线程模式下任务已跑完（mock provider）
        self.assertEqual(task.status, AITask.Status.SUCCESS, task.error)
        self.assertEqual(task.triggered_by, self.teacher)
        self.assertEqual(task.course_id, self.course.id)
        self.assertEqual(task.catalog_id, self.catalog.id)
        self.assertEqual(task.progress["groups"], [
            {"qtype": "single", "count": 2, "score": 2.0},
            {"qtype": "judge", "count": 1, "score": 2.0},
        ])
        batch = QuestionDraftBatch.objects.get(id=task.result["batch_id"])
        self.assertEqual(batch.origin, "ai_gen")
        self.assertEqual(batch.catalog_id, self.catalog.id)
        self.assertEqual(batch.creator, self.teacher)
        self.assertEqual(len(batch.drafts), 3)  # 单选 2 + 判断 1

    def test_generate_rejects_duplicate_submit(self):
        # 同教师同课程已有一条 pending 任务（模型层部分唯一索引）→ 友好文案
        AITask.objects.create(
            task_type=AITask.TaskType.QUESTION_GEN, status=AITask.Status.PENDING,
            triggered_by=self.teacher, course=self.course, catalog=self.catalog,
        )
        response = self._post({
            "course": self.course.id, "catalog": self.catalog.id, "groups": self._groups(),
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "已有进行中的生题任务，请等待完成后再试")

    def test_generate_rejects_student(self):
        response = self._post(
            {"course": self.course.id, "catalog": self.catalog.id, "groups": self._groups()},
            user=self.student,
        )
        self.assertEqual(response.status_code, 403)

    def test_generate_after_finished_allows_new_task(self):
        """上一任务终态（success）后约束解除，可再次提交。"""
        first = AITask.objects.create(
            task_type=AITask.TaskType.QUESTION_GEN, status=AITask.Status.SUCCESS,
            triggered_by=self.teacher, course=self.course, catalog=self.catalog,
        )
        response = self._post({
            "course": self.course.id, "catalog": self.catalog.id, "groups": self._groups(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data["data"]["task_id"], first.id)


class QuestionGenPipelineTests(APITestCase):
    """run_question_gen 流水线：mock 建批次 / 部分失败 degraded / 全失败抛错 / 不合规丢弃。"""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_qgen", password="pw123456!", role=User.Role.TEACHER)
        cls.course = Course.objects.create(name="Java程序设计", teacher=cls.teacher)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第一章")

    def _task(self, groups, **kwargs):
        return AITask.objects.create(
            task_type=AITask.TaskType.QUESTION_GEN,
            status=AITask.Status.PENDING,
            triggered_by=self.teacher,
            course=self.course,
            catalog=self.catalog,
            progress={"stage": "queued", "groups": groups, "objective": "覆盖核心知识点"},
            **kwargs,
        )

    def test_mock_groups_build_batch(self):
        """provider=mock：按组确定性出题，全部落 AI 草稿批次，分值按组指定。"""
        task = self._task([
            {"qtype": "single", "count": 2, "score": 2},
            {"qtype": "blank", "count": 2, "score": 4},
        ])
        with patch("apps.questions.question_gen_ai.get_provider", return_value=MockProvider()):
            run_question_gen(task)
        task.refresh_from_db()
        self.assertEqual(task.status, AITask.Status.SUCCESS)
        self.assertFalse(task.result["degraded"])
        self.assertEqual(task.result["failed_groups"], [])
        batch = QuestionDraftBatch.objects.get(id=task.result["batch_id"])
        self.assertEqual(batch.origin, "ai_gen")
        self.assertEqual(batch.task_id, task.id)
        self.assertEqual(len(batch.drafts), 4)
        by_type = {d["qtype"]: d for d in batch.drafts}
        self.assertEqual(by_type["single"]["score"], 2)
        self.assertEqual(by_type["blank"]["score"], 4)
        # 填空未逐空赋分：留待入库管道按每题总分均分
        self.assertNotIn("score", by_type["blank"]["answer"]["blanks"][0])
        self.assertEqual(task.progress["stage"], "done")

    def test_partial_group_failure_marks_degraded(self):
        """单组失败不整批失败：成功组照常建批次，failed_groups 记原因。"""
        provider = _QGenProvider(fail_qtypes={"judge"})
        task = self._task([
            {"qtype": "single", "count": 2, "score": 2},
            {"qtype": "judge", "count": 1, "score": 2},
        ])
        with patch("apps.questions.question_gen_ai.get_provider", return_value=provider):
            run_question_gen(task)
        task.refresh_from_db()
        self.assertEqual(task.status, AITask.Status.SUCCESS)
        self.assertTrue(task.result["degraded"])
        self.assertEqual(len(task.result["failed_groups"]), 1)
        self.assertEqual(task.result["failed_groups"][0]["qtype"], "judge")
        self.assertIn("RuntimeError", task.result["failed_groups"][0]["error"])
        self.assertEqual(task.result["total"], 2)  # 仅单选 2 题
        batch = QuestionDraftBatch.objects.get(id=task.result["batch_id"])
        self.assertEqual(len(batch.drafts), 2)
        self.assertTrue(batch.stats["degraded"])

    def test_all_groups_failed_raises(self):
        """全部组失败：抛 ValueError（上层 _execute 捕获后标 FAILED + error）。"""
        task = self._task([{"qtype": "single", "count": 1, "score": 2}])
        with patch("apps.questions.question_gen_ai.get_provider", return_value=_QGenProvider(fail_qtypes={"single"})):
            with self.assertRaises(ValueError):
                run_question_gen(task)

    def test_all_groups_failed_marks_task_failed_via_executor(self):
        """经 _execute 的全失败路径：任务落 FAILED，error 带组失败原因。"""
        import contextvars

        from apps.ai.tasks import _execute

        task = self._task([{"qtype": "judge", "count": 1, "score": 2}])
        with patch("apps.questions.question_gen_ai.get_provider", return_value=_QGenProvider(fail_qtypes={"judge"})):
            _execute(task.id, contextvars.copy_context())
        task.refresh_from_db()
        self.assertEqual(task.status, AITask.Status.FAILED)
        self.assertIn("判断题", task.error)
        self.assertIsNotNone(task.finished_at)

    def test_invalid_items_dropped_with_group_note(self):
        """LLM 混入不合规题（缺选项/空题干）：丢弃并计入 failed_groups，合规题保留。"""
        provider = _QGenProvider(dirty=True)
        task = self._task([{"qtype": "single", "count": 2, "score": 2}])
        with patch("apps.questions.question_gen_ai.get_provider", return_value=provider):
            run_question_gen(task)
        task.refresh_from_db()
        self.assertEqual(task.status, AITask.Status.SUCCESS)
        batch = QuestionDraftBatch.objects.get(id=task.result["batch_id"])
        self.assertEqual(len(batch.drafts), 2)
        self.assertTrue(task.result["degraded"])
        self.assertEqual(task.result["failed_groups"][0]["qtype"], "single")
        self.assertIn("2 条生成结果不合规已丢弃", task.result["failed_groups"][0]["error"])

    def test_generated_batch_flows_into_save_pipeline(self):
        """生题批次可直接走 save 入库管道（与文档导入共用），查重/分值均分生效。"""
        from apps.questions.draft_pipeline import save_batch_drafts

        task = self._task([
            {"qtype": "single", "count": 1, "score": 2},
            {"qtype": "blank", "count": 1, "score": 4},
        ])
        with patch("apps.questions.question_gen_ai.get_provider", return_value=MockProvider()):
            run_question_gen(task)
        task.refresh_from_db()
        batch = QuestionDraftBatch.objects.get(id=task.result["batch_id"])
        result = save_batch_drafts(batch, batch.drafts, self.teacher)
        self.assertEqual(len(result["saved"]), 2)
        self.assertEqual(result["failed"], [])
        questions = Question.objects.filter(course=self.course).order_by("id")
        self.assertEqual(questions.count(), 2)
        blank_q = questions.get(qtype="blank")
        # 每题 4 分按 2 空均分（mock 填空题 2 空），Σ=4
        self.assertEqual([b["score"] for b in blank_q.answer["blanks"]], [2.0, 2.0])
        self.assertEqual(blank_q.score, 4)
        self.assertEqual(blank_q.source, "ai")
        batch.refresh_from_db()
        self.assertEqual(batch.status, "saved")


class AITaskActiveApiTests(APITestCase):
    """ai-tasks/active：恢复入口只列本人进行中的生题任务。"""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_active", password="pw123456!", role=User.Role.TEACHER)
        cls.outsider = User.objects.create_user(username="t_active2", password="pw123456!", role=User.Role.TEACHER)
        cls.course = Course.objects.create(name="Java程序设计", teacher=cls.teacher)

    def test_active_lists_own_pending_question_gen_only(self):
        mine = AITask.objects.create(
            task_type=AITask.TaskType.QUESTION_GEN, status=AITask.Status.RUNNING,
            triggered_by=self.teacher, course=self.course,
        )
        mine_chapter = AITask.objects.create(
            task_type=AITask.TaskType.CHAPTER_SUMMARY, status=AITask.Status.PENDING,
            triggered_by=self.teacher,
        )
        mine_done = AITask.objects.create(
            task_type=AITask.TaskType.QUESTION_GEN, status=AITask.Status.SUCCESS,
            triggered_by=self.teacher, course=self.course,
        )
        outsider_task = AITask.objects.create(
            task_type=AITask.TaskType.QUESTION_GEN, status=AITask.Status.PENDING,
            triggered_by=self.outsider,
        )
        self.client.force_authenticate(user=self.teacher)
        response = self.client.get("/api/ai-tasks/active/")
        self.assertEqual(response.status_code, 200)
        ids = [t["id"] for t in response.data["data"]]
        self.assertIn(mine.id, ids)
        self.assertNotIn(mine_chapter.id, ids)   # 默认只 question_gen
        self.assertNotIn(mine_done.id, ids)      # 终态不列
        self.assertNotIn(outsider_task.id, ids)  # 只列本人
        row = next(t for t in response.data["data"] if t["id"] == mine.id)
        self.assertEqual(row["course"], self.course.id)
        self.assertEqual(row["course_name"], self.course.name)
        self.assertEqual(row["status"], "running")

    def test_active_all_type_includes_other_task_types(self):
        mine_chapter = AITask.objects.create(
            task_type=AITask.TaskType.CHAPTER_SUMMARY, status=AITask.Status.PENDING,
            triggered_by=self.teacher,
        )
        self.client.force_authenticate(user=self.teacher)
        response = self.client.get("/api/ai-tasks/active/?task_type=all")
        ids = [t["id"] for t in response.data["data"]]
        self.assertIn(mine_chapter.id, ids)

    def test_active_requires_auth(self):
        response = self.client.get("/api/ai-tasks/active/")
        self.assertEqual(response.status_code, 401)


# 本类用 override_settings 重新开启小额度进行验证（默认 test 运行整体关闭）。
@override_settings(TEACHER_AI_THROTTLE_RATES={"teacher_ai_generate": "1/min", "teacher_ai_import": None})
class TeacherAiThrottleTests(APITestCase):
    """教师端 AI 限流：generate 挂 teacher_ai_generate 档；未声明动作（列表）放行。"""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_throttle", password="pw123456!", role=User.Role.TEACHER)
        cls.course = Course.objects.create(name="Java程序设计", teacher=cls.teacher)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第一章")

    def setUp(self):
        self.client.force_authenticate(user=self.teacher)
        django_cache.clear()  # 清掉历史计数，保证用例间独立

    def test_generate_throttled_after_first_request(self):
        url = "/api/questions/generate/"
        # 限流先于业务校验：第一次计入配额（业务 400），第二次 429
        first = self.client.post(url, {}, format="json")
        second = self.client.post(url, {}, format="json")
        self.assertEqual(first.status_code, 400)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.data["code"], 429)
        self.assertIn("操作过于频繁", second.data["message"])
        self.assertIn("Retry-After", second.headers)

    def test_list_action_not_throttled(self):
        # list 未声明 action_scopes → 放行（连续多次均 200）
        for _ in range(3):
            response = self.client.get("/api/questions/")
            self.assertEqual(response.status_code, 200)
