"""analytics 服务层（build_class_stats 平移）一致性测试。

平移验收标准：教师端班级学情统计接口行为不变（services 化不改口径）。
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.courses.models import Catalog, Course, TeachingVideo, VideoWatchProgress
from apps.classroom.models import ClassRoom, ClassStudent
from apps.knowledge.models import QARecord
from apps.questions.models import AnswerRecord, Question, WrongNote, WrongMastery
from apps.homework.models import (
    Homework,
    HomeworkAnswer,
    HomeworkQuestion,
    HomeworkSubmission,
)
from apps.exams.models import Exam, ExamSubmission, Paper
from apps.labs.models import Lab, LabSubmission, LabTemplate

from .services import (
    WRONG_TOP_N,
    build_chapter_profile,
    build_class_stats,
    build_class_stats_v2,
)

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


class BuildChapterProfileTests(TestCase):
    """build_chapter_profile（章节学习总结画像）测试。

    覆盖：练习证据链 / F1 成绩可见性门控（作业 RETURNED、考试 score_released）/
    F8 考试乱序映射（复用 resolver）/ 实验·问答·错题本 / for_student 双口径。
    """

    def setUp(self):
        self.teacher = User.objects.create_user(
            username="t_ch", password="pw123456!", role=User.Role.TEACHER
        )
        self.student = User.objects.create_user(
            username="s_ch", password="pw123456!", role=User.Role.STUDENT
        )
        self.course = Course.objects.create(name="章节课程", teacher=self.teacher)
        self.classroom = ClassRoom.objects.create(name="章节班级", teacher=self.teacher)
        self.classroom.courses.add(self.course)
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        self.catalog = Catalog.objects.create(
            course=self.course, title="第三章", order=3, is_published=True
        )
        self.other_catalog = Catalog.objects.create(
            course=self.course, title="第四章", order=4, is_published=True
        )
        # 单选题：原始选项 A/B，正确答案 B（用于构造乱序映射）
        self.question = Question.objects.create(
            course=self.course,
            catalog=self.catalog,
            qtype=Question.QType.SINGLE,
            stem="VLAN 隔离的是什么",
            options=[{"key": "A", "text": "广播域"}, {"key": "B", "text": "冲突域"}],
            answer={"key": "B"},
            analysis="VLAN 隔离广播域，冲突域由交换机端口隔离",
            knowledge_tags=["VLAN"],
            status=Question.Status.PUBLISHED,
        )
        AnswerRecord.objects.create(
            student=self.student,
            question=self.question,
            scene=AnswerRecord.Scene.PRACTICE,
            student_answer={"key": "A"},  # 原始空间：选 A = 错
            is_correct=False,
        )
        AnswerRecord.objects.create(
            student=self.student,
            question=self.question,
            scene=AnswerRecord.Scene.PRACTICE,
            student_answer={"key": "B"},
            is_correct=True,
        )
        # 作业（题库选题模式）：一道本章错题（先建题目后发布，规避「已发布不能新增题目」校验）
        self.homework = Homework.objects.create(
            classroom=self.classroom,
            course=self.course,
            title="章节作业",
            mode=Homework.Mode.QUESTIONS,
            status=Homework.Status.DRAFT,
            total_score=20,
        )
        hq = HomeworkQuestion.objects.create(homework=self.homework, question=self.question, score=10)
        self.homework.status = Homework.Status.PUBLISHED
        self.homework.save(update_fields=["status"])
        self.hw_submission = HomeworkSubmission.objects.create(
            homework=self.homework,
            student=self.student,
            score=10,
            correct_status=HomeworkSubmission.CorrectStatus.SUBMITTED,
        )
        HomeworkAnswer.objects.create(
            submission=self.hw_submission, homework_question=hq, is_correct=False
        )
        # 考试：试卷含本章题目；答卷开选项乱序 perm=[1,0]（展示位0=原始B）
        self.exam = Exam.objects.create(
            course=self.course, classroom=self.classroom, name="章节考试",
            status=Exam.Status.PUBLISHED, shuffle_options=True,
        )
        self.paper = Paper.objects.create(
            course=self.course, exam=self.exam,
            question_items=[{"question_id": self.question.id, "score": 10, "order": 1}],
            total_score=10,
        )
        self.exam_submission = ExamSubmission.objects.create(
            exam=self.exam,
            paper=self.paper,
            student=self.student,
            answers={str(self.question.id): {"key": "B"}},  # 展示空间：选展示位B=原始A=错
            question_layout={"order": [self.question.id], "options": {str(self.question.id): [1, 0]}},
            status=ExamSubmission.Status.SUBMITTED,
            total_score=0,
            score_released=False,
        )
        # 实验（挂本章，提交即出分无门控）
        template = LabTemplate.objects.create(code="ch-lab", title="章节实验模板")
        lab = Lab.objects.create(
            template=template, course=self.course, catalog=self.catalog,
            title="章节实验", status=Lab.Status.PUBLISHED, total_score=100,
        )
        LabSubmission.objects.create(
            lab=lab, student=self.student, status=LabSubmission.Status.SUBMITTED,
            total_score=88, passed_steps=4, total_steps=5,
        )
        # 问答：一条被点「无用」
        QARecord.objects.create(
            course=self.course, catalog=self.catalog, student=self.student,
            question="VLAN 和子网有什么区别", answer="", feedback=-1,
        )
        # 手动错题：一条已巩固、一条未巩固（按 catalog 归属）
        note_mastered = WrongNote.objects.create(
            student=self.student, course=self.course, catalog=self.catalog, stem="错题1"
        )
        WrongNote.objects.create(
            student=self.student, course=self.course, catalog=self.catalog, stem="错题2"
        )
        WrongMastery.objects.create(student=self.student, note=note_mastered)
        # 视频进度（完成）
        video = TeachingVideo.objects.create(
            course=self.course, catalog=self.catalog, is_published=True
        )
        VideoWatchProgress.objects.create(
            student=self.student, video=video,
            status=VideoWatchProgress.Status.COMPLETED, watch_seconds=600,
            last_page=7, page_count=10,
        )

    def test_practice_evidence_and_knowledge_agg(self):
        profile = build_chapter_profile(self.student, self.catalog, for_student=True)
        practice = profile["practice"]
        self.assertEqual(practice["total"], 2)
        self.assertEqual(practice["correct"], 1)
        self.assertEqual(practice["accuracy"], 50)
        self.assertEqual(len(practice["wrong"]), 1)
        wrong = practice["wrong"][0]
        self.assertEqual(wrong["my_answer"], "A")
        self.assertEqual(wrong["correct_answer"], "B")
        self.assertEqual(wrong["knowledge_tags"], ["VLAN"])
        agg = {item["tag"]: item for item in profile["knowledge_agg"]}
        self.assertEqual(agg["VLAN"]["wrong"], 1)
        self.assertEqual(agg["VLAN"]["rate"], 50)

    def test_learning_dimension(self):
        profile = build_chapter_profile(self.student, self.catalog, for_student=True)
        learning = profile["learning"]
        self.assertTrue(learning["completed"])
        self.assertEqual(learning["watch_seconds"], 600)
        self.assertEqual(learning["pages_watched"], "8/10")

    def test_homework_visibility_gate(self):
        """F1：作业未发布成绩（SUBMITTED）时学生口径不出分，只进 visibility 计数。"""
        profile = build_chapter_profile(self.student, self.catalog, for_student=True)
        hw = profile["homework"]
        self.assertEqual(len(hw), 1)
        self.assertIsNone(hw[0]["score"])
        self.assertEqual(len(hw[0]["wrong_points"]), 1)  # 客观题错题证据不受门控
        self.assertEqual(profile["visibility"]["homework_pending_release"], 1)

        self.hw_submission.correct_status = HomeworkSubmission.CorrectStatus.RETURNED
        self.hw_submission.save(update_fields=["correct_status"])
        profile = build_chapter_profile(self.student, self.catalog, for_student=True)
        self.assertEqual(profile["homework"][0]["score"], 10)
        self.assertEqual(profile["homework"][0]["rate"], 50)
        self.assertEqual(profile["visibility"]["homework_pending_release"], 0)

    def test_exam_visibility_and_shuffle_mapping(self):
        """F1+F8：未发布成绩不出分（计数）；乱序答卷经 resolver 归回原始选项空间。"""
        profile = build_chapter_profile(self.student, self.catalog, for_student=True)
        exam = profile["exams"]
        self.assertEqual(len(exam), 1)
        self.assertIsNone(exam[0]["score"])  # score_released=False → 不出分
        self.assertEqual(profile["visibility"]["exam_pending_release"], 1)
        wp = exam[0]["wrong_points"]
        self.assertEqual(len(wp), 1)
        # 展示空间选「B」（=原始 A），unmap 后必须回到原始 key「A」才是错答
        self.assertEqual(wp[0]["my_answer"], "A")
        self.assertEqual(wp[0]["correct_answer"], "B")

        self.exam_submission.score_released = True
        self.exam_submission.save(update_fields=["score_released"])
        profile = build_chapter_profile(self.student, self.catalog, for_student=True)
        self.assertEqual(profile["exams"][0]["score"], 0)
        self.assertEqual(profile["visibility"]["exam_pending_release"], 0)

    def test_teacher_scope_sees_all(self):
        """for_student=False（教师口径）：不受成绩门控限制。"""
        profile = build_chapter_profile(self.student, self.catalog, for_student=False)
        self.assertEqual(profile["homework"][0]["score"], 10)
        self.assertEqual(profile["exams"][0]["score"], 0)
        self.assertEqual(profile["visibility"], {})

    def test_labs_qa_wrong_book(self):
        profile = build_chapter_profile(self.student, self.catalog, for_student=True)
        self.assertEqual(len(profile["labs"]), 1)
        self.assertEqual(profile["labs"][0]["total_score"], 88)
        self.assertEqual(profile["qa"]["count"], 1)
        self.assertEqual(len(profile["qa"]["disliked"]), 1)
        self.assertEqual(profile["wrong_book"], {"mastered": 1, "pending": 1})
        self.assertEqual(profile["chapter"]["title"], "第三章")

    def test_other_chapter_isolated(self):
        """其它章节的数据不混入本章画像。"""
        AnswerRecord.objects.create(
            student=self.student,
            question=Question.objects.create(
                course=self.course, catalog=self.other_catalog, qtype=Question.QType.SINGLE,
                stem="别章题", options=[{"key": "A", "text": "x"}, {"key": "B", "text": "y"}],
                answer={"key": "A"}, status=Question.Status.PUBLISHED,
            ),
            scene=AnswerRecord.Scene.PRACTICE,
            student_answer={"key": "B"},
            is_correct=False,
        )
        profile = build_chapter_profile(self.student, self.catalog, for_student=True)
        self.assertEqual(profile["practice"]["total"], 2)
        self.assertEqual(profile["practice"]["wrong"][0]["stem"], "VLAN 隔离的是什么")


class TeacherChapterSummaryApiTests(TestCase):
    """教师端章节总结列表 / 班级报告历史（P3）测试。"""

    def setUp(self):
        from apps.ai.models import AITask

        self.AITask = AITask
        self.teacher = User.objects.create_user(
            username="t_p3", password="pw123456!", role=User.Role.TEACHER
        )
        self.outsider = User.objects.create_user(
            username="t_p3_out", password="pw123456!", role=User.Role.TEACHER
        )
        self.student = User.objects.create_user(
            username="s_p3", password="pw123456!", role=User.Role.STUDENT
        )
        self.other_student = User.objects.create_user(
            username="s_p3_other", password="pw123456!", role=User.Role.STUDENT
        )
        self.course = Course.objects.create(name="P3课程", teacher=self.teacher)
        self.classroom = ClassRoom.objects.create(name="P3班级", teacher=self.teacher)
        self.classroom.courses.add(self.course)
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        self.catalog = Catalog.objects.create(
            course=self.course, title="第五章", order=5, is_published=True
        )
        self.other_catalog = Catalog.objects.create(
            course=self.course, title="第六章", order=6, is_published=True
        )
        self.client = APIClient()

    def _summary_task(self, student, catalog, version, **kw):
        defaults = dict(
            task_type=self.AITask.TaskType.CHAPTER_SUMMARY,
            student=student,
            catalog=catalog,
            course=catalog.course,
            version=version,
            status=self.AITask.Status.SUCCESS,
            triggered_by=student,
            result={
                "overview": f"第{version}版总结",
                "weak_points": ["递归"],
                "generated_at": "2026-10-22 10:00:00",
            },
        )
        defaults.update(kw)
        return self.AITask.objects.create(**defaults)

    def test_teacher_sees_class_students_latest_version(self):
        """教师看本班学生本章总结：每生取最大版本，全量口径原样返回 result。"""
        self._summary_task(self.student, self.catalog, version=1, result={"overview": "旧版"})
        self._summary_task(
            self.student,
            self.catalog,
            version=2,
            result={"overview": "新版", "generated_at": "2026-10-22 10:00:00"},
        )
        # 非本班学生 / 别章总结不应出现
        self._summary_task(self.other_student, self.catalog, version=1)
        self._summary_task(self.student, self.other_catalog, version=1)

        self.client.force_authenticate(user=self.teacher)
        resp = self.client.get(
            f"/api/analytics/class/{self.classroom.id}/chapter-summaries/",
            {"catalog_id": self.catalog.id},
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.data["data"]
        self.assertEqual(data["total"], 1)
        item = data["summaries"][0]
        self.assertEqual(item["student_id"], self.student.id)
        self.assertEqual(item["student_name"], "s_p3")
        self.assertEqual(item["version"], 2)
        self.assertEqual(item["result"]["overview"], "新版")
        self.assertEqual(item["generated_at"], "2026-10-22 10:00:00")

    def test_teacher_sees_unreleased_scores_full_caliber(self):
        """for_student=False 全量口径：未发布成绩的总结内容也返回（无门控）。"""
        self._summary_task(
            self.student,
            self.catalog,
            version=1,
            result={"overview": "含未发布作业分", "homework": [{"title": "作业1", "score": 18}]},
        )
        self.client.force_authenticate(user=self.teacher)
        resp = self.client.get(
            f"/api/analytics/class/{self.classroom.id}/chapter-summaries/",
            {"catalog_id": self.catalog.id},
        )
        item = resp.data["data"]["summaries"][0]
        self.assertEqual(item["result"]["homework"][0]["score"], 18)

    def test_non_class_teacher_forbidden(self):
        """非本班教师 404（不暴露存在性）。"""
        self._summary_task(self.student, self.catalog, version=1)
        self.client.force_authenticate(user=self.outsider)
        resp = self.client.get(
            f"/api/analytics/class/{self.classroom.id}/chapter-summaries/",
            {"catalog_id": self.catalog.id},
        )
        self.assertEqual(resp.status_code, 404, resp.data)

    def test_catalog_not_in_course_404(self):
        """章节不属于该班级课程时 404。"""
        other_course = Course.objects.create(name="别校课程", teacher=self.teacher)
        foreign_catalog = Catalog.objects.create(course=other_course, title="外章", order=1)
        self.client.force_authenticate(user=self.teacher)
        resp = self.client.get(
            f"/api/analytics/class/{self.classroom.id}/chapter-summaries/",
            {"catalog_id": foreign_catalog.id},
        )
        self.assertEqual(resp.status_code, 404, resp.data)

    def test_missing_catalog_id_400(self):
        self.client.force_authenticate(user=self.teacher)
        resp = self.client.get(
            f"/api/analytics/class/{self.classroom.id}/chapter-summaries/"
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_report_history_lists_recent_first(self):
        """班级报告历史：按 id 倒序，含状态/摘要/简评数。"""
        self.AITask.objects.create(
            task_type=self.AITask.TaskType.CLASS_ANALYTICS,
            classroom=self.classroom,
            course=self.course,
            triggered_by=self.teacher,
            status=self.AITask.Status.SUCCESS,
            result={
                "report": "## 整体学情\n报告正文……",
                "comments": {"1": "简评甲", "2": "简评乙"},
                "stats_snapshot": {"analyzed_count": 2},
                "generated_at": "2026-10-22 09:00:00",
            },
        )
        self.AITask.objects.create(
            task_type=self.AITask.TaskType.CLASS_ANALYTICS,
            classroom=self.classroom,
            course=self.course,
            triggered_by=self.teacher,
            status=self.AITask.Status.FAILED,
            error="provider timeout",
        )
        self.client.force_authenticate(user=self.teacher)
        resp = self.client.get(f"/api/analytics/class/{self.classroom.id}/ai-reports/")
        self.assertEqual(resp.status_code, 200, resp.data)
        reports = resp.data["data"]["reports"]
        self.assertEqual(len(reports), 2)
        self.assertEqual(reports[0]["status"], "failed")
        self.assertEqual(reports[0]["error"], "provider timeout")
        self.assertEqual(reports[1]["status"], "success")
        self.assertEqual(reports[1]["analyzed_count"], 2)
        self.assertEqual(reports[1]["comment_count"], 2)
        self.assertIn("整体学情", reports[1]["report_excerpt"])
        self.assertEqual(reports[1]["generated_at"], "2026-10-22 09:00:00")

    def test_report_history_outsider_404(self):
        self.client.force_authenticate(user=self.outsider)
        resp = self.client.get(f"/api/analytics/class/{self.classroom.id}/ai-reports/")
        self.assertEqual(resp.status_code, 404, resp.data)

    def test_multi_course_class_needs_course_param(self):
        """多课程班级：章节属于课程 B 时必须显式传 course=B。

        回归：教师端学生详情页曾漏传 course，后端回退解析为班级下 id 最小的
        课程 A，导致 B 课章节 404「章节不存在或不属于该课程」。
        """
        course_b = Course.objects.create(name="P3课程B", teacher=self.teacher)
        self.classroom.courses.add(course_b)
        catalog_b = Catalog.objects.create(
            course=course_b, title="B课第一章", order=1, is_published=True
        )
        self._summary_task(self.student, catalog_b, version=1)

        self.client.force_authenticate(user=self.teacher)
        # 不传 course：回退到 id 较小的课程 A（setUp 创建），B 课章节 → 404
        resp = self.client.get(
            f"/api/analytics/class/{self.classroom.id}/chapter-summaries/",
            {"catalog_id": catalog_b.id},
        )
        self.assertEqual(resp.status_code, 404, resp.data)

        # 传 course=B：正常返回该生总结
        resp = self.client.get(
            f"/api/analytics/class/{self.classroom.id}/chapter-summaries/",
            {"catalog_id": catalog_b.id, "course": course_b.id},
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.data["data"]
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["summaries"][0]["result"]["overview"], "第1版总结")
