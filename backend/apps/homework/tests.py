"""作业模块冒烟测试：多附件（含图片）提交、成绩发布后答案/解析可见、
纯客观题自动出分、已发布成绩不被误收回、考试选项顺序不打乱，
以及教师附件即传（上传/替换/移除、原文件名保留、权限与格式校验）。
"""
import json
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from apps.classroom.models import ClassCourse, ClassRoom, ClassStudent
from apps.courses.models import Catalog, Course
from apps.exams.models import Exam, Paper
from apps.exams.resolver import build_for_taking
from apps.homework.models import Homework, HomeworkQuestion, HomeworkSubmission
from apps.questions.models import Question
from apps.users.models import User

TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="zhike_hw_test_")


def fake_image(name="photo.png"):
    """伪造的图片文件（后端仅校验扩展名与大小，不解析内容）。"""
    return SimpleUploadedFile(name, b"fake-image-bytes", content_type="image/png")


def fake_pdf(name="第一章.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 fake-bytes", content_type="application/pdf")


def fake_pdf_document(name="课件.pdf", pages=2):
    """用 pypdfium2 生成 pages 页空白 PDF（预览渲染同引擎，保证可被解析渲染）。"""
    import io

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(240, 320)
    buffer = io.BytesIO()
    pdf.save(buffer)
    pdf.close()
    buffer.seek(0)
    return SimpleUploadedFile(name, buffer.read(), content_type="application/pdf")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class HomeworkFlowTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_hw", password="pw123456!", role=User.Role.TEACHER)
        cls.student = User.objects.create_user(username="s_hw", password="pw123456!", role=User.Role.STUDENT)
        cls.course = Course.objects.create(name="高等数学", teacher=cls.teacher)
        cls.classroom = ClassRoom.objects.create(name="计科1班", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第一章")
        cls.single = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.SINGLE,
            stem="1+1=?", options=[{"key": "A", "text": "2"}, {"key": "B", "text": "3"}],
            answer={"key": "A"}, analysis="1+1 等于 2", score=Decimal("5"),
            status=Question.Status.PUBLISHED,
        )
        cls.short = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.SHORT,
            stem="请简述函数的奇偶性", answer={"text": "奇函数满足 f(-x)=-f(x)"},
            analysis="奇偶性是函数的基本性质", score=Decimal("10"),
            status=Question.Status.PUBLISHED,
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def _publish_questions_homework(self, *questions):
        hw = Homework.objects.create(
            classroom=self.classroom, course=self.course, title="题库作业",
            mode=Homework.Mode.QUESTIONS, status=Homework.Status.DRAFT,
            total_score=Decimal("15"),
        )
        for order, q in enumerate(questions):
            HomeworkQuestion.objects.create(homework=hw, question=q, score=q.score, order=order)
        hw.status = Homework.Status.PUBLISHED
        hw.save(update_fields=["status", "updated_at"])
        return hw

    def _publish_attachment_homework(self, title="附件作业"):
        return Homework.objects.create(
            classroom=self.classroom, course=self.course, title=title,
            mode=Homework.Mode.ATTACHMENT, status=Homework.Status.PUBLISHED,
            total_score=Decimal("100"),
        )

    def test_submit_images_with_questions_homework(self):
        """学生提交图片附件；纯客观题作业提交即出分并发布，学生可见答案/解析。"""
        hw = self._publish_questions_homework(self.single)
        item = hw.questions.first()
        client = APIClient()
        client.force_authenticate(user=self.student)
        resp = client.post(
            "/api/homework-submissions/",
            {
                "homework": hw.id,
                "answers": json.dumps({str(item.id): {"key": "A"}}),
                "attachments": [fake_image("ans1.png"), fake_image("ans2.jpg")],
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        submission = HomeworkSubmission.objects.get(homework=hw, student=self.student)
        self.assertEqual(submission.correct_status, HomeworkSubmission.CorrectStatus.RETURNED)
        self.assertEqual(submission.score, Decimal("5"))
        self.assertEqual(len(submission.attachments), 2)
        self.assertEqual(submission.attachments[0]["name"], "ans1.png")
        self.assertTrue(submission.attachments[0]["url"].startswith("/media/homework_submit/"))
        self.assertGreater(submission.attachments[0]["size"], 0)

        detail = client.get(f"/api/homework-submissions/{submission.id}/")
        snapshot = detail.data["data"]["answer_items"][0]["snapshot"]
        self.assertEqual(snapshot["answer"], {"key": "A"})
        self.assertEqual(snapshot["analysis"], "1+1 等于 2")

    def test_attachment_homework_multiple_images(self):
        """附件作业支持一次提交多张图片，元数据完整。"""
        hw = self._publish_attachment_homework("图片作业")
        client = APIClient()
        client.force_authenticate(user=self.student)
        resp = client.post(
            "/api/homework-submissions/",
            {"homework": hw.id, "content": "手写作答见图片", "attachments": [fake_image("p1.png"), fake_image("p2.png")]},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        submission = HomeworkSubmission.objects.get(homework=hw)
        self.assertEqual(len(submission.attachments), 2)
        self.assertTrue(all(a["url"].startswith("/media/") for a in submission.attachments))

    def test_reject_disallowed_extension(self):
        """HTML 等可造成存储型 XSS 的格式被拒绝。"""
        hw = self._publish_attachment_homework()
        client = APIClient()
        client.force_authenticate(user=self.student)
        resp = client.post(
            "/api/homework-submissions/",
            {"homework": hw.id, "content": "x", "attachments": [SimpleUploadedFile("evil.html", b"<script>")]},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(HomeworkSubmission.objects.filter(homework=hw).exists())

    def test_mixed_homework_answer_visible_after_release(self):
        """含简答题作业：提交后即可学习（答案/解析即时放行、客观题得分即时出）；
        主观题得分与总分待教师批改，批改即发布后可见。"""
        hw = self._publish_questions_homework(self.single, self.short)
        items = list(hw.questions.order_by("order", "id"))
        client = APIClient()
        client.force_authenticate(user=self.student)
        resp = client.post(
            "/api/homework-submissions/",
            {
                "homework": hw.id,
                "answers": json.dumps({
                    str(items[0].id): {"key": "A"},
                    str(items[1].id): {"text": "奇函数满足 f(-x)=-f(x)"},
                }),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        submission = HomeworkSubmission.objects.get(homework=hw)
        self.assertEqual(submission.correct_status, HomeworkSubmission.CorrectStatus.SUBMITTED)

        detail = client.get(f"/api/homework-submissions/{submission.id}/")
        payload = detail.data["data"]
        # 提交后即可学习：答案/解析对学生即时放行（第六轮需求）
        self.assertEqual(payload["answer_items"][0]["snapshot"]["answer"], {"key": "A"})
        self.assertEqual(payload["answer_items"][1]["snapshot"]["analysis"], "奇偶性是函数的基本性质")
        # 客观题得分即时可见；主观题得分与总分仍等教师批改发布
        self.assertEqual(Decimal(str(payload["answer_items"][0]["score"])), Decimal("5"))
        self.assertIsNone(payload["answer_items"][1]["score"])
        self.assertIsNone(payload["score"])

        teacher_client = APIClient()
        teacher_client.force_authenticate(user=self.teacher)
        short_answer_id = payload["answer_items"][1]["id"]
        grade_resp = teacher_client.post(
            f"/api/homework-submissions/{submission.id}/grade/",
            {"answer_scores": {str(short_answer_id): {"score": 8, "comment": "不错"}}},
            format="json",
        )
        self.assertEqual(grade_resp.status_code, 200, grade_resp.data)
        # 批改即发布：无需再调 release（保留调用验证幂等）
        self.assertEqual(
            HomeworkSubmission.objects.get(id=submission.id).correct_status,
            HomeworkSubmission.CorrectStatus.RETURNED,
        )
        release_resp = teacher_client.post(f"/api/homework-submissions/{submission.id}/release/")
        self.assertEqual(release_resp.status_code, 200)

        detail = client.get(f"/api/homework-submissions/{submission.id}/")
        payload = detail.data["data"]
        self.assertEqual(payload["correct_status"], "returned")
        self.assertEqual(Decimal(str(payload["score"])), Decimal("13"))
        self.assertEqual(payload["answer_items"][0]["snapshot"]["answer"], {"key": "A"})
        self.assertEqual(payload["answer_items"][1]["snapshot"]["analysis"], "奇偶性是函数的基本性质")

    def test_grade_keeps_returned_status(self):
        """已发布成绩的提交再次批改后仍保持已发布（纯客观题自动出分不被收回）。"""
        hw = self._publish_questions_homework(self.single)
        item = hw.questions.first()
        client = APIClient()
        client.force_authenticate(user=self.student)
        client.post(
            "/api/homework-submissions/",
            {"homework": hw.id, "answers": json.dumps({str(item.id): {"key": "A"}})},
            format="json",
        )
        submission = HomeworkSubmission.objects.get(homework=hw)
        self.assertEqual(submission.correct_status, "returned")

        teacher_client = APIClient()
        teacher_client.force_authenticate(user=self.teacher)
        resp = teacher_client.post(f"/api/homework-submissions/{submission.id}/grade/", {}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        submission.refresh_from_db()
        self.assertEqual(submission.correct_status, "returned")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class HomeworkAttachmentUploadTests(APITestCase):
    """教师作业附件即传：多文件追加、按 url 移除、PDF 页图预览、格式/数量校验、权限。"""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_hw_att", password="pw123456!", role=User.Role.TEACHER)
        cls.other_teacher = User.objects.create_user(username="t_hw_other", password="pw123456!", role=User.Role.TEACHER)
        cls.student = User.objects.create_user(username="s_hw_att", password="pw123456!", role=User.Role.STUDENT)
        cls.course = Course.objects.create(name="线性代数", teacher=cls.teacher)
        cls.classroom = ClassRoom.objects.create(name="信科1班", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)
        cls.homework = Homework.objects.create(
            classroom=cls.classroom, course=cls.course, title="附件作业",
            mode=Homework.Mode.ATTACHMENT, status=Homework.Status.DRAFT,
            total_score=Decimal("100"),
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def _upload(self, client, homework, uploaded):
        return client.post(
            f"/api/homeworks/{homework.id}/attachments/",
            {"attachments": uploaded},
            format="multipart",
        )

    def _fake_docx(self, name="第二章.docx"):
        return SimpleUploadedFile(
            name, b"PK\x03\x04 fake-docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_upload_appends_and_remove_by_url(self):
        """多次上传为追加而非替换；按 url 移除单个附件并删除存储文件。"""
        client = APIClient()
        client.force_authenticate(user=self.teacher)

        resp = self._upload(client, self.homework, fake_pdf("第一章.pdf"))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.homework.refresh_from_db()
        self.assertEqual(len(self.homework.attachments), 1)
        self.assertEqual(self.homework.attachments[0]["name"], "第一章.pdf")
        self.assertTrue(self.homework.attachments[0]["url"].startswith("/media/homework/"))
        first_path = default_storage.path(self.homework.attachments[0]["url"][len("/media/"):])

        # 再次上传：追加，原附件保留
        resp = self._upload(client, self.homework, self._fake_docx())
        self.assertEqual(resp.status_code, 200, resp.data)
        self.homework.refresh_from_db()
        self.assertEqual([a["name"] for a in self.homework.attachments], ["第一章.pdf", "第二章.docx"])

        # 列表序列化带出附件列表
        list_resp = client.get(f"/api/homeworks/?classroom={self.classroom.id}")
        payload = list_resp.data["data"]
        rows = payload["results"] if isinstance(payload, dict) else payload
        row = next(item for item in rows if item["id"] == self.homework.id)
        self.assertEqual([a["name"] for a in row["attachments"]], ["第一章.pdf", "第二章.docx"])

        # 按 url 移除第一个：文件一并删除，第二个保留
        resp = client.delete(
            f"/api/homeworks/{self.homework.id}/attachments/",
            {"url": self.homework.attachments[0]["url"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.homework.refresh_from_db()
        self.assertEqual([a["name"] for a in self.homework.attachments], ["第二章.docx"])
        self.assertFalse(default_storage.exists(first_path))

        # 移除不存在的 url → 400
        resp = client.delete(
            f"/api/homeworks/{self.homework.id}/attachments/",
            {"url": "/media/homework/not-exist.pdf"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_upload_allows_multiple_files_in_one_request(self):
        """一次选择多个文件全部落盘并追加。"""
        client = APIClient()
        client.force_authenticate(user=self.teacher)
        resp = self._upload(client, self.homework, [fake_pdf("a.pdf"), self._fake_docx("b.docx")])
        self.assertEqual(resp.status_code, 200, resp.data)
        self.homework.refresh_from_db()
        self.assertEqual([a["name"] for a in self.homework.attachments], ["a.pdf", "b.docx"])

    def test_upload_rejects_bad_extension_oversize_and_overcount(self):
        """HTML 等可造成存储型 XSS 的格式、超 20MB、超过数量上限均被拒绝。"""
        client = APIClient()
        client.force_authenticate(user=self.teacher)
        resp = self._upload(client, self.homework, SimpleUploadedFile("evil.html", b"<script>"))
        self.assertEqual(resp.status_code, 400)

        resp = self._upload(client, self.homework, SimpleUploadedFile("big.pdf", b"x" * (20 * 1024 * 1024 + 1)))
        self.assertEqual(resp.status_code, 400)

        resp = self._upload(client, self.homework, [fake_pdf(f"f{i}.pdf") for i in range(10)])
        self.assertEqual(resp.status_code, 400)
        self.homework.refresh_from_db()
        self.assertEqual(self.homework.attachments, [])

    def test_upload_on_published_homework(self):
        """已发布作业仍可追加附件（标题/模式/题目冻结不涉及附件）。"""
        self.homework.status = Homework.Status.PUBLISHED
        self.homework.save(update_fields=["status"])
        client = APIClient()
        client.force_authenticate(user=self.teacher)
        resp = self._upload(client, self.homework, fake_pdf("补充资料.pdf"))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.homework.refresh_from_db()
        self.assertEqual(len(self.homework.attachments), 1)

    def test_student_and_other_teacher_cannot_upload(self):
        """学生不可上传；非任课教师被行级过滤（404）。"""
        student_client = APIClient()
        student_client.force_authenticate(user=self.student)
        resp = self._upload(student_client, self.homework, fake_pdf())
        self.assertEqual(resp.status_code, 403)

        other_client = APIClient()
        other_client.force_authenticate(user=self.other_teacher)
        resp = self._upload(other_client, self.homework, fake_pdf())
        self.assertEqual(resp.status_code, 404)

    def test_preview_pdf_pages(self):
        """PDF 附件渲染为页图列表（无工具栏连续滚动），带缓存复用；非 PDF/外来 url 被拒。"""
        client = APIClient()
        client.force_authenticate(user=self.teacher)
        resp = self._upload(client, self.homework, fake_pdf_document("课件.pdf", pages=2))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.homework.refresh_from_db()
        pdf_url = self.homework.attachments[0]["url"]

        resp = client.get(f"/api/homeworks/{self.homework.id}/attachments/preview/", {"url": pdf_url})
        self.assertEqual(resp.status_code, 200, resp.data)
        pages = resp.data["data"]["pages"]
        self.assertEqual(len(pages), 2)
        self.assertTrue(all(p.startswith("/media/homework_preview/") for p in pages))
        self.assertTrue(all(default_storage.exists(p[len("/media/"):]) for p in pages))

        # 二次请求命中缓存，页数一致
        resp2 = client.get(f"/api/homeworks/{self.homework.id}/attachments/preview/", {"url": pdf_url})
        self.assertEqual(resp2.status_code, 200, resp2.data)
        self.assertEqual(resp2.data["data"]["pages"], pages)

        # 非本作业的附件 url 被拒
        resp = client.get(
            f"/api/homeworks/{self.homework.id}/attachments/preview/",
            {"url": "/media/homework/other.pdf"},
        )
        self.assertEqual(resp.status_code, 400)

        # 非 PDF 附件不给预览
        resp = self._upload(client, self.homework, self._fake_docx("笔记.docx"))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.homework.refresh_from_db()
        docx_url = next(a["url"] for a in self.homework.attachments if a["name"] == "笔记.docx")
        resp = client.get(f"/api/homeworks/{self.homework.id}/attachments/preview/", {"url": docx_url})
        self.assertEqual(resp.status_code, 400)

    def test_student_can_preview_published_homework_attachment(self):
        """学生可预览所属班级已发布作业的 PDF 附件；未发布不可见（404）。"""
        client = APIClient()
        client.force_authenticate(user=self.teacher)
        resp = self._upload(client, self.homework, fake_pdf_document("资料.pdf", pages=1))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.homework.refresh_from_db()
        pdf_url = self.homework.attachments[0]["url"]

        student_client = APIClient()
        student_client.force_authenticate(user=self.student)
        resp = student_client.get(f"/api/homeworks/{self.homework.id}/attachments/preview/", {"url": pdf_url})
        self.assertEqual(resp.status_code, 404)  # 草稿对学生不可见

        self.homework.status = Homework.Status.PUBLISHED
        self.homework.save(update_fields=["status"])
        resp = student_client.get(f"/api/homeworks/{self.homework.id}/attachments/preview/", {"url": pdf_url})
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(len(resp.data["data"]["pages"]), 1)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class HomeworkSubmissionStagingTests(APITestCase):
    """学生提交前附件即传（暂存目录）+ 提交时引用；非法引用被拒。"""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_hw_stage", password="pw123456!", role=User.Role.TEACHER)
        cls.student = User.objects.create_user(username="s_hw_stage", password="pw123456!", role=User.Role.STUDENT)
        cls.course = Course.objects.create(name="数据结构", teacher=cls.teacher)
        cls.classroom = ClassRoom.objects.create(name="软工1班", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)
        cls.homework = Homework.objects.create(
            classroom=cls.classroom, course=cls.course, title="附件作业",
            mode=Homework.Mode.ATTACHMENT, status=Homework.Status.PUBLISHED,
            total_score=Decimal("100"),
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def test_stage_then_submit_with_uploaded(self):
        """暂存上传 → 提交引用 → 附件元数据完整入库。"""
        client = APIClient()
        client.force_authenticate(user=self.student)
        resp = client.post(
            "/api/homework-submissions/attachments/",
            {"attachments": [fake_image("ans1.png"), fake_image("ans2.jpg")]},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        staged = resp.data["data"]["added"]
        self.assertEqual(len(staged), 2)
        self.assertEqual(staged[0]["name"], "ans1.png")
        self.assertTrue(all(s["url"].startswith("/media/homework_submit/") for s in staged))
        self.assertGreater(staged[0]["size"], 0)

        resp = client.post(
            "/api/homework-submissions/",
            {
                "homework": self.homework.id,
                "content": "见附件",
                "uploaded": json.dumps(staged),
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        submission = HomeworkSubmission.objects.get(homework=self.homework, student=self.student)
        self.assertEqual(len(submission.attachments), 2)
        self.assertEqual(submission.attachments[0]["name"], "ans1.png")
        self.assertTrue(submission.attachments[0]["url"].startswith("/media/homework_submit/"))

    def test_stage_rejects_bad_file(self):
        """暂存上传同样拒绝 HTML 等危险格式与超限文件。"""
        client = APIClient()
        client.force_authenticate(user=self.student)
        resp = client.post(
            "/api/homework-submissions/attachments/",
            {"attachments": SimpleUploadedFile("evil.html", b"<script>")},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(list((Path(TEST_MEDIA_ROOT) / "homework_submit").glob("*")))

    def test_submit_rejects_foreign_uploaded_url(self):
        """提交时引用非暂存目录的 url 被拒（防任意文件冒名）。"""
        client = APIClient()
        client.force_authenticate(user=self.student)
        resp = client.post(
            "/api/homework-submissions/",
            {
                "homework": self.homework.id,
                "content": "x",
                "uploaded": json.dumps([{"name": "evil.pdf", "size": 1, "type": "", "url": "/media/homework/evil.pdf"}]),
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(HomeworkSubmission.objects.filter(homework=self.homework).exists())

    def test_teacher_cannot_stage(self):
        """暂存上传仅学生可用。"""
        client = APIClient()
        client.force_authenticate(user=self.teacher)
        resp = client.post(
            "/api/homework-submissions/attachments/",
            {"attachments": fake_image()},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 403)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ExamOptionOrderTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_ex", password="pw123456!", role=User.Role.TEACHER)
        cls.course = Course.objects.create(name="物理", teacher=cls.teacher)
        cls.classroom = ClassRoom.objects.create(name="物理班", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        cls.catalog = Catalog.objects.create(course=cls.course, title="运动学")
        cls.question = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.SINGLE,
            stem="下面哪个是矢量？",
            options=[{"key": "A", "text": "质量"}, {"key": "B", "text": "速度"}, {"key": "C", "text": "时间"}],
            answer={"key": "B"}, analysis="速度有方向", score=Decimal("5"),
            status=Question.Status.PUBLISHED,
        )
        cls.exam = Exam.objects.create(
            course=cls.course, classroom=cls.classroom, name="单元测",
            shuffle_options=True, shuffle_questions=False,
        )
        cls.paper = Paper.objects.create(
            course=cls.course, exam=cls.exam, mode=Paper.Mode.MANUAL,
            question_items=[{"question_id": cls.question.id, "score": 5, "order": 0}],
            total_score=Decimal("5"),
        )

    def test_options_keep_original_order(self):
        """选项乱序已停用：无论历史数据如何，选项始终按原始 A/B/C 顺序与内容下发。"""
        for _ in range(5):
            result = build_for_taking(self.paper, self.exam)
            self.assertEqual([o["key"] for o in result[0]["options"]], ["A", "B", "C"])
            self.assertEqual([o["text"] for o in result[0]["options"]], ["质量", "速度", "时间"])


class HomeworkStatsTests(APITestCase):
    """作业统计：总览/分段/逐题/排名/权限（对齐考试统计口径）。"""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(username="t_hw_stats", password="pw123456!", role=User.Role.TEACHER)
        cls.other_teacher = User.objects.create_user(username="t_hw_stats_other", password="pw123456!", role=User.Role.TEACHER)
        cls.s1 = User.objects.create_user(username="s_hw_z", password="pw123456!", role=User.Role.STUDENT, real_name="张三")
        cls.s2 = User.objects.create_user(username="s_hw_l", password="pw123456!", role=User.Role.STUDENT, real_name="李四")
        cls.s3 = User.objects.create_user(username="s_hw_w", password="pw123456!", role=User.Role.STUDENT, real_name="王五")
        cls.course = Course.objects.create(name="大学英语", teacher=cls.teacher)
        cls.classroom = ClassRoom.objects.create(name="英语1班", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        for s in (cls.s1, cls.s2, cls.s3):
            ClassStudent.objects.create(classroom=cls.classroom, student=s)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第一单元")
        cls.single = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.SINGLE,
            stem="How are you?",
            options=[{"key": "A", "text": "Fine"}, {"key": "B", "text": "Bad"}, {"key": "C", "text": "Sad"}],
            answer={"key": "A"}, analysis="日常问候", score=Decimal("5"),
            status=Question.Status.PUBLISHED,
        )
        cls.short = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype=Question.QType.SHORT,
            stem="请用英语自我介绍", answer={"text": "My name is..."},
            analysis="注意时态", score=Decimal("10"),
            status=Question.Status.PUBLISHED,
        )
        cls.teacher_client = APIClient()
        cls.teacher_client.force_authenticate(user=cls.teacher)
        cls.other_client = APIClient()
        cls.other_client.force_authenticate(user=cls.other_teacher)
        cls.student_client = APIClient()
        cls.student_client.force_authenticate(user=cls.s1)

    def _publish_questions_homework(self, *questions):
        hw = Homework.objects.create(
            classroom=self.classroom, course=self.course, title="题库作业",
            mode=Homework.Mode.QUESTIONS, status=Homework.Status.DRAFT,
            total_score=Decimal("15"),
        )
        for order, q in enumerate(questions):
            HomeworkQuestion.objects.create(homework=hw, question=q, score=q.score, order=order)
        hw.status = Homework.Status.PUBLISHED
        hw.save(update_fields=["status", "updated_at"])
        return hw

    def _submit(self, student, homework_id, answers):
        client = APIClient()
        client.force_authenticate(user=student)
        return client.post(
            "/api/homework-submissions/",
            {"homework": homework_id, "content": "我的作答", "answers": json.dumps(answers)},
            format="json",
        )

    def test_stats_overview_and_rankings(self):
        """附件作业：应交 3 / 已交 2 / 未交 1 / 逾期 1 / 待批改 1 / 已发布 1；
        已出分者排名在前，待批改次之，未提交排后。"""
        from django.utils import timezone
        from datetime import timedelta

        hw = Homework.objects.create(
            classroom=self.classroom, course=self.course, title="附件作业",
            mode=Homework.Mode.ATTACHMENT, status=Homework.Status.PUBLISHED,
            total_score=Decimal("100"),
            deadline=timezone.now() - timedelta(days=1),
        )
        self._submit(self.s1, hw.id, {}).data  # 逾期提交
        self._submit(self.s2, hw.id, {})
        sub1 = HomeworkSubmission.objects.get(homework=hw, student=self.s1)
        # s1 批改并发布（90 分）；s2 待批改
        resp = self.teacher_client.post(
            f"/api/homework-submissions/{sub1.id}/grade/",
            {"score": 90, "comment": "很好"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        d = self.teacher_client.get(f"/api/homeworks/{hw.id}/stats/").data["data"]
        ov = d["overview"]
        self.assertEqual(ov["student_count"], 3)
        self.assertEqual(ov["submitted"], 2)
        self.assertEqual(ov["unsubmitted"], 1)
        self.assertEqual(ov["late_count"], 2)
        self.assertEqual(ov["pending_count"], 1)
        self.assertEqual(ov["released_count"], 1)
        # 仅 s1 出分：90 分；及格线 60、优秀线 85
        self.assertEqual(ov["avg_score"], 90.0)
        self.assertEqual(ov["max_score"], 90.0)
        self.assertEqual(ov["min_score"], 90.0)
        self.assertEqual(ov["pass_rate"], 100.0)
        self.assertEqual(ov["excellent_rate"], 100.0)

        rows = d["rankings"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["student_name"], "张三")
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[0]["score"], 90.0)
        self.assertEqual(rows[0]["status"], "returned")
        self.assertTrue(rows[0]["is_late"])
        # 待批改：无最终分与排名，客观分 0
        self.assertEqual(rows[1]["student_name"], "李四")
        self.assertIsNone(rows[1]["rank"])
        self.assertIsNone(rows[1]["score"])
        self.assertEqual(rows[1]["status"], "submitted")
        # 未提交排最后
        self.assertEqual(rows[2]["student_name"], "王五")
        self.assertEqual(rows[2]["status"], "unsubmitted")

        dist = {item["range"]: item["count"] for item in d["score_distribution"]}
        self.assertEqual(dist["90-100"], 1)
        self.assertEqual(dist["未出分"], 1)

    def test_stats_question_and_distribution(self):
        """题库作业（单选+简答）：逐题正确率/选项分布/平均分；
        待批改行只计入未出分，分段按最终分。"""
        hw = self._publish_questions_homework(self.single, self.short)
        items = list(hw.questions.order_by("order", "id"))
        single_item, short_item = items[0], items[1]
        # 张三：单选对、简答待批 → 客观 5 分，提交后总分 5（部分分）
        self._submit(self.s1, hw.id, {
            str(single_item.id): {"key": "A"},
            str(short_item.id): {"text": "My name is Zhangsan."},
        })
        # 李四：单选错 → 客观 0 分
        self._submit(self.s2, hw.id, {
            str(single_item.id): {"key": "B"},
            str(short_item.id): {"text": "My name is Lisi."},
        })
        # 教师批改张三简答 8 分 → 总分 13，已发布
        sub1 = HomeworkSubmission.objects.get(homework=hw, student=self.s1)
        short_answer = sub1.answer_items.get(homework_question=short_item)
        resp = self.teacher_client.post(
            f"/api/homework-submissions/{sub1.id}/grade/",
            {"answer_scores": {str(short_answer.id): {"score": 8}}},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        d = self.teacher_client.get(f"/api/homeworks/{hw.id}/stats/").data["data"]

        ov = d["overview"]
        self.assertEqual(ov["submitted"], 2)
        self.assertEqual(ov["unsubmitted"], 1)
        self.assertEqual(ov["pending_count"], 1)
        self.assertEqual(ov["released_count"], 1)
        # 仅张三出分 13：及格线 15×60%=9、优秀线 12.75
        self.assertEqual(ov["avg_score"], 13.0)
        self.assertEqual(ov["pass_rate"], 100.0)
        self.assertEqual(ov["excellent_rate"], 100.0)

        qs = {q["question_id"]: q for q in d["question_stats"]}
        single = qs[single_item.id]
        self.assertEqual(single["correct_rate"], 50.0)
        self.assertEqual(single["avg_score"], 2.5)
        self.assertEqual(single["unanswered"], 0)
        counts = {o["key"]: o["count"] for o in single["options"]}
        self.assertEqual(counts, {"A": 1, "B": 1, "C": 0})
        self.assertTrue(next(o for o in single["options"] if o["key"] == "A")["is_correct"])
        # 简答：主观题无正确率；仅张三批改出分 8
        short = qs[short_item.id]
        self.assertIsNone(short["correct_rate"])
        self.assertEqual(short["avg_score"], 8.0)

        rows = d["rankings"]
        self.assertEqual(rows[0]["student_name"], "张三")
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[0]["score"], 13.0)
        # 李四待批改：最终分不入统计，排名无分数
        self.assertEqual(rows[1]["student_name"], "李四")
        self.assertIsNone(rows[1]["rank"])
        self.assertIsNone(rows[1]["score"])
        self.assertEqual(rows[1]["objective_score"], 0.0)
        self.assertEqual(rows[2]["student_name"], "王五")

        dist = {item["range"]: item["count"] for item in d["score_distribution"]}
        # 总分 15：张三 13 → 86.7% 落 80-89；李四未出分
        self.assertEqual(dist["80-89"], 1)
        self.assertEqual(dist["未出分"], 1)

    def test_stats_attachment_mode_has_no_question_stats(self):
        """附件作业无题目维度数据，question_stats 为空列表。"""
        hw = Homework.objects.create(
            classroom=self.classroom, course=self.course, title="附件作业",
            mode=Homework.Mode.ATTACHMENT, status=Homework.Status.PUBLISHED,
            total_score=Decimal("100"),
        )
        d = self.teacher_client.get(f"/api/homeworks/{hw.id}/stats/").data["data"]
        self.assertEqual(d["question_stats"], [])
        self.assertEqual(d["homework"]["title"], "附件作业")
        self.assertEqual(d["homework"]["class_name"], "英语1班")
        self.assertEqual(d["homework"]["course_name"], "大学英语")

    def test_stats_same_score_same_rank(self):
        """同分同名次：两人均 90 分 → 并列第 1。"""
        hw = Homework.objects.create(
            classroom=self.classroom, course=self.course, title="附件作业",
            mode=Homework.Mode.ATTACHMENT, status=Homework.Status.PUBLISHED,
            total_score=Decimal("100"),
        )
        for s in (self.s1, self.s2):
            self._submit(s, hw.id, {})
            sub = HomeworkSubmission.objects.get(homework=hw, student=s)
            self.teacher_client.post(
                f"/api/homework-submissions/{sub.id}/grade/", {"score": 90}, format="json"
            )
        rows = self.teacher_client.get(f"/api/homeworks/{hw.id}/stats/").data["data"]["rankings"]
        self.assertEqual([r["rank"] for r in rows[:2]], [1, 1])

    def test_stats_permission(self):
        """权限：仅本班授课教师可查看；其他教师 404，学生 403。"""
        hw = Homework.objects.create(
            classroom=self.classroom, course=self.course, title="附件作业",
            mode=Homework.Mode.ATTACHMENT, status=Homework.Status.PUBLISHED,
            total_score=Decimal("100"),
        )
        self.assertEqual(self.other_client.get(f"/api/homeworks/{hw.id}/stats/").status_code, 404)
        self.assertEqual(self.student_client.get(f"/api/homeworks/{hw.id}/stats/").status_code, 403)
