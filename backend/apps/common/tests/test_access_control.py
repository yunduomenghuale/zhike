from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.ai.vectorstore import search_chunks
from apps.classroom.models import ClassCourse, ClassRoom, ClassStudent
from apps.courses.models import Catalog, Course
from apps.exams.models import Exam, ExamSubmission, Paper
from apps.knowledge.models import KnowledgeChunk, Material
from apps.questions.models import Question, WrongMastery


User = get_user_model()


class PlatformFixtureMixin:
    def setUp(self):
        self.teacher1 = User.objects.create_user(
            username="teacher-one", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.teacher2 = User.objects.create_user(
            username="teacher-two", password="StrongPass!123", role=User.Role.TEACHER
        )
        self.student1 = User.objects.create_user(
            username="student-one", password="StrongPass!123", role=User.Role.STUDENT
        )
        self.student2 = User.objects.create_user(
            username="student-two", password="StrongPass!123", role=User.Role.STUDENT
        )
        self.course1 = Course.objects.create(name="Course 1", teacher=self.teacher1)
        self.course2 = Course.objects.create(name="Course 2", teacher=self.teacher2)
        self.catalog1 = Catalog.objects.create(
            course=self.course1, title="Chapter 1", is_published=True
        )
        self.catalog2 = Catalog.objects.create(
            course=self.course2, title="Chapter 2", is_published=True
        )
        self.class1 = ClassRoom.objects.create(name="Class 1", teacher=self.teacher1)
        self.class2 = ClassRoom.objects.create(name="Class 2", teacher=self.teacher2)
        ClassCourse.objects.create(classroom=self.class1, course=self.course1)
        ClassCourse.objects.create(classroom=self.class2, course=self.course2)
        self.member1 = ClassStudent.objects.create(
            classroom=self.class1, student=self.student1
        )
        self.member2 = ClassStudent.objects.create(
            classroom=self.class2, student=self.student2
        )
        self.question1 = Question.objects.create(
            course=self.course1,
            catalog=self.catalog1,
            qtype=Question.QType.SINGLE,
            stem="Q1",
            options=[{"key": "A", "text": "yes"}, {"key": "B", "text": "no"}],
            answer={"key": "A"},
            status=Question.Status.PUBLISHED,
            creator=self.teacher1,
        )
        self.question2 = Question.objects.create(
            course=self.course2,
            catalog=self.catalog2,
            qtype=Question.QType.SINGLE,
            stem="Q2",
            options=[{"key": "A", "text": "yes"}, {"key": "B", "text": "no"}],
            answer={"key": "A"},
            status=Question.Status.PUBLISHED,
            creator=self.teacher2,
        )

    def login_as(self, user):
        self.client.force_authenticate(user=user)

    def result_ids(self, response):
        return {item["id"] for item in response.data["data"]["results"]}


class AccessControlTests(PlatformFixtureMixin, APITestCase):

    def test_wrong_question_mastery_can_be_marked_and_unmarked(self):
        self.login_as(self.student1)

        marked = self.client.post(
            "/api/wrong-mastery/",
            {"question": self.question1.id},
            format="json",
        )

        self.assertEqual(marked.status_code, 200)
        self.assertTrue(marked.data["data"]["mastered"])
        self.assertTrue(
            WrongMastery.objects.filter(
                student=self.student1,
                question=self.question1,
                removed=False,
            ).exists()
        )

        unmarked = self.client.post(
            "/api/wrong-mastery/",
            {"question": self.question1.id},
            format="json",
        )

        self.assertEqual(unmarked.status_code, 200)
        self.assertFalse(unmarked.data["data"]["mastered"])
        self.assertFalse(
            WrongMastery.objects.filter(
                student=self.student1,
                question=self.question1,
            ).exists()
        )

    def test_student_must_complete_profile_before_joining_class(self):
        self.login_as(self.student1)

        denied = self.client.post(
            "/api/classes/join/",
            {"invite_code": self.class2.invite_code},
            format="json",
        )
        self.assertEqual(denied.status_code, 400)
        self.assertFalse(
            ClassStudent.objects.filter(
                classroom=self.class2,
                student=self.student1,
            ).exists()
        )

        self.student1.real_name = "Student One"
        self.student1.phone = "13800000001"
        self.student1.save(update_fields=["real_name", "phone"])
        joined = self.client.post(
            "/api/classes/join/",
            {"invite_code": self.class2.invite_code},
            format="json",
        )

        self.assertEqual(joined.status_code, 200)
        self.assertTrue(
            ClassStudent.objects.filter(
                classroom=self.class2,
                student=self.student1,
            ).exists()
        )

    def test_teacher_cannot_add_student_with_incomplete_profile(self):
        self.login_as(self.teacher1)

        response = self.client.post(
            f"/api/classes/{self.class1.id}/add-student/",
            {"username": self.student2.username},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            ClassStudent.objects.filter(
                classroom=self.class1,
                student=self.student2,
            ).exists()
        )

    def test_student_only_sees_enrolled_courses_and_questions(self):
        self.login_as(self.student1)

        courses = self.client.get("/api/courses/")
        questions = self.client.get("/api/questions/")

        self.assertEqual(courses.status_code, 200)
        self.assertEqual(self.result_ids(courses), {self.course1.id})
        self.assertEqual(self.result_ids(questions), {self.question1.id})

    def test_student_cannot_enumerate_other_class_members(self):
        self.login_as(self.student1)

        response = self.client.get("/api/class-students/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.result_ids(response), {self.member1.id})

    def test_teacher_cannot_modify_another_teachers_catalog(self):
        self.login_as(self.teacher1)

        response = self.client.patch(
            f"/api/catalogs/{self.catalog2.id}/", {"title": "stolen"}, format="json"
        )

        self.assertEqual(response.status_code, 404)
        self.catalog2.refresh_from_db()
        self.assertEqual(self.catalog2.title, "Chapter 2")

    def test_material_lists_respect_course_and_class_scope(self):
        global_material = Material.objects.create(
            course=self.course1, file_name="global.txt", qa_open=True
        )
        own_class_material = Material.objects.create(
            course=self.course1,
            classroom=self.class1,
            file_name="own.txt",
            qa_open=True,
        )
        other_material = Material.objects.create(
            course=self.course2,
            classroom=self.class2,
            file_name="other.txt",
            qa_open=True,
        )
        self.login_as(self.student1)

        response = self.client.get("/api/materials/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.result_ids(response), {global_material.id, own_class_material.id}
        )
        self.assertNotIn(other_material.id, self.result_ids(response))

    def test_student_rag_search_excludes_closed_and_other_class_materials(self):
        open_material = Material.objects.create(
            course=self.course1, classroom=self.class1, file_name="open", qa_open=True
        )
        closed_material = Material.objects.create(
            course=self.course1, classroom=self.class1, file_name="closed", qa_open=False
        )
        other_class = ClassRoom.objects.create(name="Other class", teacher=self.teacher1)
        ClassCourse.objects.create(classroom=other_class, course=self.course1)
        other_material = Material.objects.create(
            course=self.course1, classroom=other_class, file_name="other", qa_open=True
        )
        visible = KnowledgeChunk.objects.create(
            material=open_material, course=self.course1, content="visible", embedding=[1.0, 0.0]
        )
        KnowledgeChunk.objects.create(
            material=closed_material, course=self.course1, content="closed", embedding=[1.0, 0.0]
        )
        KnowledgeChunk.objects.create(
            material=other_material, course=self.course1, content="other", embedding=[1.0, 0.0]
        )

        results = search_chunks(
            self.course1.id,
            [1.0, 0.0],
            student_access=True,
            classroom_id=self.class1.id,
        )

        self.assertEqual([chunk.id for chunk, _ in results], [visible.id])


class ExamFlowTests(PlatformFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.exam = Exam.objects.create(
            course=self.course1,
            classroom=self.class1,
            name="Published exam",
            status=Exam.Status.PUBLISHED,
            start_at=now - timedelta(minutes=5),
            end_at=now + timedelta(hours=1),
            duration=30,
        )
        self.paper = Paper.objects.create(
            course=self.course1,
            exam=self.exam,
            question_items=[{"question_id": self.question1.id, "score": 5, "order": 0}],
            total_score=5,
        )
        self.other_exam = Exam.objects.create(
            course=self.course2,
            classroom=self.class2,
            name="Other exam",
            status=Exam.Status.PUBLISHED,
            start_at=now - timedelta(minutes=5),
            end_at=now + timedelta(hours=1),
        )

    def test_only_enrolled_student_can_start_published_exam(self):
        self.login_as(self.student1)
        denied = self.client.post(
            "/api/exam-submissions/start/", {"exam": self.other_exam.id}, format="json"
        )
        self.assertEqual(denied.status_code, 404)

        self.login_as(self.teacher1)
        teacher_denied = self.client.post(
            "/api/exam-submissions/start/", {"exam": self.exam.id}, format="json"
        )
        self.assertEqual(teacher_denied.status_code, 403)

    def test_client_cannot_fake_timeout_or_submit_twice(self):
        self.login_as(self.student1)
        started = self.client.post(
            "/api/exam-submissions/start/", {"exam": self.exam.id}, format="json"
        )
        self.assertEqual(started.status_code, 200)
        submission_id = started.data["data"]["submission"]["id"]

        submitted = self.client.post(
            f"/api/exam-submissions/{submission_id}/submit/",
            {"answers": {str(self.question1.id): {"key": "A"}}, "timeout": True},
            format="json",
        )
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.data["data"]["status"], ExamSubmission.Status.SUBMITTED)
        self.assertIsNone(submitted.data["data"]["objective_score"])
        self.assertIsNone(submitted.data["data"]["total_score"])
        self.assertEqual(submitted.data["data"]["subjective_scores"], {})

        repeated = self.client.post(
            f"/api/exam-submissions/{submission_id}/submit/",
            {"answers": {}},
            format="json",
        )
        self.assertEqual(repeated.status_code, 400)

    def test_server_marks_submission_timed_out(self):
        sub = ExamSubmission.objects.create(
            exam=self.exam,
            paper=self.paper,
            student=self.student1,
            status=ExamSubmission.Status.IN_PROGRESS,
            started_at=timezone.now() - timedelta(hours=1),
        )
        self.login_as(self.student1)

        response = self.client.post(
            f"/api/exam-submissions/{sub.id}/submit/", {"answers": {}}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], ExamSubmission.Status.TIMEOUT)

    def test_analysis_stays_hidden_until_exam_finishes(self):
        sub = ExamSubmission.objects.create(
            exam=self.exam,
            paper=self.paper,
            student=self.student1,
            status=ExamSubmission.Status.SUBMITTED,
            started_at=timezone.now() - timedelta(minutes=2),
            submitted_at=timezone.now(),
        )
        self.login_as(self.student1)

        response = self.client.get(f"/api/exam-submissions/{sub.id}/review/")

        self.assertEqual(response.status_code, 403)


class PasswordPolicyTests(APITestCase):
    def test_registration_rejects_weak_password(self):
        response = self.client.post(
            "/api/auth/register/",
            {
                "username": "weak-user",
                "password": "123456",
                "real_name": "Weak",
                "role": "student",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
