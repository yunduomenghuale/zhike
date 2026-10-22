"""analytics 服务层（build_class_stats 平移）一致性测试。

平移验收标准：教师端班级学情统计接口行为不变（services 化不改口径）。
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.courses.models import Catalog, Course, TeachingVideo, VideoWatchProgress
from apps.classroom.models import ClassRoom, ClassStudent
from apps.knowledge.models import QARecord
from apps.questions.models import AnswerRecord, Question

from .services import WRONG_TOP_N, build_class_stats, build_class_stats_v2

User = get_user_model()


class BuildClassStatsTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username="t_stats", password="pw123456!", role=User.Role.TEACHER
        )
        self.student = User.objects.create_user(
            username="s_stats", password="pw123456!", role=User.Role.STUDENT
        )
        self.course = Course.objects.create(name="统计课程", teacher=self.teacher)
        self.classroom = ClassRoom.objects.create(name="统计班级", teacher=self.teacher)
        self.classroom.courses.add(self.course)
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)

    def test_service_direct_call(self):
        stats = build_class_stats(self.classroom, self.course.id)
        self.assertEqual(stats["class_name"], "统计班级")
        self.assertEqual(stats["summary"]["student_count"], 1)
        self.assertEqual(len(stats["students"]), 1)
        self.assertEqual(stats["students"][0]["username"], "s_stats")

    def test_teacher_endpoint_matches_service(self):
        """教师端接口与服务函数输出一致（平移不改口径）。"""
        client = APIClient()
        client.force_authenticate(user=self.teacher)
        resp = client.get(f"/api/analytics/class/{self.classroom.id}/")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(
            resp.data["data"], build_class_stats(self.classroom, self.course.id)
        )


class BuildClassStatsV2Tests(TestCase):
    """build_class_stats_v2（AI 学情分析专用聚合）测试。"""

    def setUp(self):
        self.teacher = User.objects.create_user(
            username="t_v2", password="pw123456!", role=User.Role.TEACHER
        )
        self.student_a = User.objects.create_user(
            username="s_v2_a", password="pw123456!", role=User.Role.STUDENT
        )
        self.student_b = User.objects.create_user(
            username="s_v2_b", password="pw123456!", role=User.Role.STUDENT
        )
        self.course = Course.objects.create(name="V2课程", teacher=self.teacher)
        self.classroom = ClassRoom.objects.create(name="V2班级", teacher=self.teacher)
        self.classroom.courses.add(self.course)
        ClassStudent.objects.create(classroom=self.classroom, student=self.student_a)
        ClassStudent.objects.create(classroom=self.classroom, student=self.student_b)
        self.catalog = Catalog.objects.create(
            course=self.course, title="第一章", order=1, is_published=True
        )
        self.question = Question.objects.create(
            course=self.course,
            catalog=self.catalog,
            qtype=Question.QType.SINGLE,
            stem="递归终止条件是什么",
            options=[{"key": "A", "text": "a"}, {"key": "B", "text": "b"}],
            answer={"key": "B"},
            knowledge_tags=["递归"],
            status=Question.Status.PUBLISHED,
        )
        AnswerRecord.objects.create(
            student=self.student_a,
            question=self.question,
            scene=AnswerRecord.Scene.PRACTICE,
            student_answer={"key": "A"},
            is_correct=False,
        )
        AnswerRecord.objects.create(
            student=self.student_a,
            question=self.question,
            scene=AnswerRecord.Scene.PRACTICE,
            student_answer={"key": "B"},
            is_correct=True,
        )
        QARecord.objects.create(
            course=self.course,
            catalog=self.catalog,
            student=self.student_a,
            question="递归什么时候停止",
            answer="当满足基准情形时停止",
        )
        video = TeachingVideo.objects.create(
            course=self.course, catalog=self.catalog, is_published=True
        )
        VideoWatchProgress.objects.create(
            student=self.student_a,
            video=video,
            status=VideoWatchProgress.Status.COMPLETED,
            watch_seconds=600,
        )

    def test_has_data_flags(self):
        """D6：六类行为全无即无数据；汇总带 analyzed/no_data 计数。"""
        stats = build_class_stats_v2(self.classroom, self.course.id)
        rows = {r["student_id"]: r for r in stats["students"]}
        self.assertTrue(rows[self.student_a.id]["has_data"])
        self.assertFalse(rows[self.student_b.id]["has_data"])
        self.assertEqual(stats["summary"]["analyzed_count"], 1)
        self.assertEqual(stats["summary"]["no_data_count"], 1)

    def test_wrong_questions_and_knowledge_agg(self):
        """错题证据链（截断 + 知识点 + 章节归属）与班级级知识点预聚合。"""
        stats = build_class_stats_v2(self.classroom, self.course.id)
        row = next(r for r in stats["students"] if r["student_id"] == self.student_a.id)
        wrong = row["wrong_questions"]
        self.assertEqual(len(wrong), 1)
        self.assertEqual(wrong[0]["knowledge_tags"], ["递归"])
        self.assertEqual(wrong[0]["chapter"], "第一章")
        self.assertEqual(wrong[0]["correct_answer"], "B")
        self.assertEqual(wrong[0]["my_answer"], "A")
        self.assertLessEqual(len(wrong[0]["stem"]), 80)
        self.assertLessEqual(len(wrong[0]["analysis"]), 120)

        agg = {item["tag"]: item for item in stats["knowledge_agg"]}
        self.assertEqual(agg["递归"]["total"], 2)
        self.assertEqual(agg["递归"]["wrong"], 1)
        self.assertEqual(agg["递归"]["rate"], 50)

    def test_dimension_aggregates(self):
        """章节矩阵 / 提问热度 / 视频行为 / 时间趋势等新增维度。"""
        stats = build_class_stats_v2(self.classroom, self.course.id)
        self.assertEqual(len(stats["chapter_matrix"]), 1)
        self.assertEqual(stats["chapter_matrix"][0]["chapter"], "第一章")
        self.assertEqual(stats["chapter_matrix"][0]["accuracy"], 50)
        self.assertEqual(stats["qa_heat"]["total"], 1)
        self.assertTrue(stats["qa_heat"]["top_questions"])
        self.assertEqual(stats["video_behavior"]["completed_chapters"], 1)
        self.assertEqual(stats["video_behavior"]["students_with_progress"], 1)
        self.assertEqual(stats["time_trend"]["practice_last_30d"], 2)
        row = next(r for r in stats["students"] if r["student_id"] == self.student_a.id)
        self.assertEqual(row["qa"]["count"], 1)
        self.assertEqual(row["video"]["completed_chapters"], 1)
        self.assertTrue(row["chapter_coverage"])

    def test_wrong_questions_capped(self):
        """错题条数上限（WRONG_TOP_N）：超量时只取最近 N 条。"""
        for _ in range(WRONG_TOP_N + 3):
            AnswerRecord.objects.create(
                student=self.student_a,
                question=self.question,
                scene=AnswerRecord.Scene.PRACTICE,
                student_answer={"key": "A"},
                is_correct=False,
            )
        stats = build_class_stats_v2(self.classroom, self.course.id)
        row = next(r for r in stats["students"] if r["student_id"] == self.student_a.id)
        self.assertEqual(len(row["wrong_questions"]), WRONG_TOP_N)
