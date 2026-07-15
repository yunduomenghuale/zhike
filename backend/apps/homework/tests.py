from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.classroom.models import ClassCourse, ClassRoom, ClassStudent
from apps.courses.models import Catalog, Course
from apps.questions.models import AnswerRecord, Question
from apps.users.models import User

from .models import Homework, HomeworkAnswer, HomeworkQuestion, HomeworkSubmission


class HomeworkQuestionFlowTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username="teacher", password="pass", role=User.Role.TEACHER, real_name="教师"
        )
        self.student = User.objects.create_user(
            username="student", password="pass", role=User.Role.STUDENT, real_name="学生"
        )
        self.course = Course.objects.create(name="测试课程", teacher=self.teacher)
        self.classroom = ClassRoom.objects.create(name="测试班", teacher=self.teacher)
        ClassCourse.objects.create(classroom=self.classroom, course=self.course)
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        self.catalog = Catalog.objects.create(course=self.course, title="第一章")
        self.single = Question.objects.create(
            course=self.course,
            catalog=self.catalog,
            qtype=Question.QType.SINGLE,
            stem="选择 A",
            options=[{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}],
            answer={"key": "A"},
            score=5,
            status=Question.Status.PUBLISHED,
            creator=self.teacher,
        )
        self.short = Question.objects.create(
            course=self.course,
            catalog=self.catalog,
            qtype=Question.QType.SHORT,
            stem="请简述",
            answer={"text": "参考答案"},
            score=10,
            status=Question.Status.PUBLISHED,
            creator=self.teacher,
        )
        self.client = APIClient()

    def create_homework(self):
        self.client.force_authenticate(self.teacher)
        response = self.client.post(
            "/api/homeworks/",
            {
                "course": self.course.id,
                "classroom": self.classroom.id,
                "title": "题库作业",
                "mode": Homework.Mode.QUESTIONS,
                "status": Homework.Status.PUBLISHED,
                "question_items": [
                    {"question": self.single.id, "score": "5.0"},
                    {"question": self.short.id, "score": "10.0"},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return Homework.objects.get(pk=response.data["data"]["id"])

    def test_snapshot_auto_grading_and_subjective_grading(self):
        homework = self.create_homework()
        self.assertEqual(homework.total_score, Decimal("15.0"))
        items = list(homework.questions.order_by("order"))
        self.assertEqual(items[0].snapshot["answer"], {"key": "A"})

        # 发布后题库答案发生变化，作业仍按冻结快照判分。
        self.single.answer = {"key": "B"}
        self.single.save(update_fields=["answer", "updated_at"])

        self.client.force_authenticate(self.student)
        response = self.client.post(
            "/api/homework-submissions/",
            {
                "homework": homework.id,
                "answers": {
                    str(items[0].id): {"key": "A"},
                    str(items[1].id): {"text": "我的回答"},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        submission = HomeworkSubmission.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(submission.objective_score, Decimal("5.0"))
        self.assertEqual(submission.correct_status, HomeworkSubmission.CorrectStatus.SUBMITTED)
        self.assertEqual(HomeworkAnswer.objects.filter(submission=submission).count(), 2)
        self.assertEqual(AnswerRecord.objects.filter(scene=AnswerRecord.Scene.HOMEWORK).count(), 2)

        subjective = submission.answer_items.get(homework_question=items[1])
        self.client.force_authenticate(self.teacher)
        response = self.client.post(
            f"/api/homework-submissions/{submission.id}/grade/",
            {"answer_scores": {str(subjective.id): {"score": "8.0", "comment": "要点完整"}}},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        submission.refresh_from_db()
        self.assertEqual(submission.score, Decimal("13.0"))
        self.assertEqual(submission.correct_status, HomeworkSubmission.CorrectStatus.GRADED)

    def test_published_question_list_is_frozen(self):
        homework = self.create_homework()
        self.client.force_authenticate(self.teacher)
        response = self.client.patch(
            f"/api/homeworks/{homework.id}/",
            {"question_items": [{"question": self.single.id, "score": "3.0"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(HomeworkQuestion.objects.filter(homework=homework).count(), 2)

        self.client.force_authenticate(self.student)
        response = self.client.get(f"/api/homeworks/{homework.id}/")
        self.assertEqual(response.status_code, 200)
        snapshot = response.data["data"]["questions"][0]["snapshot"]
        self.assertNotIn("answer", snapshot)
        self.assertNotIn("analysis", snapshot)

    def test_attachment_homework_remains_supported(self):
        homework = Homework.objects.create(
            course=self.course,
            classroom=self.classroom,
            title="附件型作业",
            mode=Homework.Mode.ATTACHMENT,
            total_score=100,
            status=Homework.Status.PUBLISHED,
        )
        self.client.force_authenticate(self.student)
        response = self.client.post(
            "/api/homework-submissions/",
            {"homework": homework.id, "content": "文本作业内容"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["correct_status"], HomeworkSubmission.CorrectStatus.SUBMITTED)
