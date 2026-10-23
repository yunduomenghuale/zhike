# -*- coding: utf-8 -*-
"""题库填空题按空赋分 + 文档导入规则解析测试（2026-10）。

覆盖：
- Question.save() 答案规范化：旧版纯字符串数组均分补分、score=Σ空分、非填空题不受影响
- grade_objective 按空判分：全对满分 / 部分对给部分分 / 缺答按错 / 大小写与空白不敏感 /
  旧版字符串数组保持全对满分否则 0 分
- QuestionSerializer 按空校验：每空 text 非空、分值必须为 >0 的数字、空题拒绝；
  仅 PATCH status 等字段时不触发答案校验（不破坏旧题操作）
- import_parser.parse_questions 规则解析：五种题型各 ≥3 种格式变体、
  残缺输入告警、特殊格式（甲乙丙丁/圈号/括号选项归一、表格列兜底、
  尾部分值、卷末速查行跳过、跨页续接、选项换行、无标题结构推断）
"""
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from rest_framework.test import APIClient, APITestCase, APIRequestFactory
from rest_framework.test import force_authenticate

from apps.courses.models import Catalog, Course
from apps.questions.grading import blank_items, grade_objective
from apps.questions.import_parser import parse_questions
from apps.questions.models import Question
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
