# -*- coding: utf-8 -*-
"""题库填空题按空赋分测试（2026-10）。

覆盖：
- Question.save() 答案规范化：旧版纯字符串数组均分补分、score=Σ空分、非填空题不受影响
- grade_objective 按空判分：全对满分 / 部分对给部分分 / 缺答按错 / 大小写与空白不敏感 /
  旧版字符串数组保持全对满分否则 0 分
- QuestionSerializer 按空校验：每空 text 非空、分值必须为 >0 的数字、空题拒绝；
  仅 PATCH status 等字段时不触发答案校验（不破坏旧题操作）
"""
from decimal import Decimal
from types import SimpleNamespace

from rest_framework.test import APIClient, APITestCase, APIRequestFactory
from rest_framework.test import force_authenticate

from apps.courses.models import Catalog, Course
from apps.questions.grading import blank_items, grade_objective
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
