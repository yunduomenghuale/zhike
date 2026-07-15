from django.db.models.deletion import ProtectedError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.courses.models import Catalog, Course
from apps.users.models import User

from .models import Question


class StrictQuestionCatalogTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username="question_teacher", password="pass", role=User.Role.TEACHER
        )
        self.course = Course.objects.create(name="课程一", teacher=self.teacher)
        self.catalog = Catalog.objects.create(course=self.course, title="第一章")
        self.other_course = Course.objects.create(name="课程二", teacher=self.teacher)
        self.other_catalog = Catalog.objects.create(course=self.other_course, title="第二章")
        self.client = APIClient()
        self.client.force_authenticate(self.teacher)

    def payload(self, **overrides):
        data = {
            "course": self.course.id,
            "catalog": self.catalog.id,
            "qtype": Question.QType.JUDGE,
            "stem": "这是判断题",
            "options": [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}],
            "answer": {"key": "A"},
            "score": "5.0",
            "difficulty": Question.Difficulty.MEDIUM,
        }
        data.update(overrides)
        return data

    def test_question_requires_catalog_from_same_course(self):
        response = self.client.post("/api/questions/", self.payload(catalog=None), format="json")
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/api/questions/", self.payload(catalog=self.other_catalog.id), format="json"
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post("/api/questions/", self.payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["catalog_title"], "第一章")

    def test_catalog_with_questions_cannot_be_deleted(self):
        Question.objects.create(
            course=self.course,
            catalog=self.catalog,
            qtype=Question.QType.JUDGE,
            stem="受保护题目",
            answer={"key": "A"},
            creator=self.teacher,
        )
        with self.assertRaises(ProtectedError):
            self.catalog.delete()
        response = self.client.delete(f"/api/catalogs/{self.catalog.id}/")
        self.assertEqual(response.status_code, 400)

    def test_ai_generation_requires_catalog(self):
        response = self.client.post(
            "/api/questions/generate/",
            {"course": self.course.id, "qtype": Question.QType.SINGLE, "count": 1},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
