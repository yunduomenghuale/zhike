"""labs 一期冒烟测试：模板库 → 建实验 → 附题 → 排课发布 → start/bridge → 提交评分 → 复核/重置 → 统计。"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.classroom.models import ClassCourse, ClassRoom, ClassStudent
from apps.courses.models import Catalog, Course
from apps.labs.models import Lab, LabSchedule, LabSubmission, LabTemplate
from apps.questions.models import Question
from apps.users.models import User


class LabFlowTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user("t001", password="pass1234", role="teacher", real_name="张老师")
        cls.student = User.objects.create_user("20240001", password="pass1234", role="student", real_name="李同学")
        cls.course = Course.objects.create(name="计算机网络", teacher=cls.teacher)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第3章 数据链路层", is_published=True)
        cls.classroom = ClassRoom.objects.create(name="网络2401", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)
        cls.template = LabTemplate.objects.create(
            code="arp-ip-lab", title="ARP实验", default_standard_minutes=30,
            random_config={"ranges": {"s1": [1, 9], "s2": [1, 9]}},
        )
        cls.short_q = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype="short",
            stem="简述ARP的工作过程", answer={"text": "ARP请求广播，目标主机单播回应，建立IP到MAC映射缓存"},
            analysis="ARP 通过广播请求与单播应答完成地址解析", score=10, status="published",
        )
        cls.single_q = Question.objects.create(
            course=cls.course, catalog=cls.catalog, qtype="single",
            stem="ARP 的作用是", options=[{"key": "A", "text": "IP到MAC"}, {"key": "B", "text": "MAC到IP"}],
            answer={"key": "A"}, score=10, status="published",
        )

    def setUp(self):
        self.tc = APIClient()
        self.tc.force_authenticate(self.teacher)
        self.sc = APIClient()
        self.sc.force_authenticate(self.student)

    def _create_lab(self):
        res = self.tc.post("/api/labs/", {
            "template": self.template.id, "course": self.course.id,
            "catalog": self.catalog.id, "total_score": "100",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        return res.data["data"]["id"] if isinstance(res.data.get("data"), dict) else res.data["data"]

    def _publish(self, lab_id):
        res = self.tc.post(f"/api/labs/{lab_id}/questions/", {"question_ids": [self.short_q.id, self.single_q.id]}, format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        res = self.tc.post("/api/lab-schedules/", {"lab": lab_id, "classroom": self.classroom.id}, format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        res = self.tc.post(f"/api/labs/{lab_id}/publish/", format="json")
        self.assertIn(res.status_code, (200, 201), res.data)

    def test_full_flow(self):
        # 学生发布前不可见
        self.assertEqual(self.sc.get("/api/labs/").data["data"]["total"], 0)

        lab_id = self._create_lab()
        self._publish(lab_id)

        # 学生可见
        res = self.sc.get("/api/labs/")
        self.assertEqual(res.data["data"]["total"], 1)

        # 开始实验：拿票据+seed
        res = self.sc.post("/api/lab-submissions/start/", {"lab": lab_id}, format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        data = res.data["data"]
        token = data["attempt_token"]
        seed = data["random_seed"]
        self.assertIn("s1", seed)
        sub_id = data["submission"]["id"]

        # 桥接校验
        res = self.sc.get(f"/api/lab-submissions/bridge-validate/?token={token}")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["data"]["random_seed"], seed)

        # 提交：全步骤通过、耗时 20 分钟、2 次错误、主观题答对关键词
        res = self.sc.post(f"/api/lab-submissions/{sub_id}/submit/", {
            "attempt_token": token,
            "steps_result": {"1": "pass", "2": "pass", "3": "pass", "4": "pass", "5": "pass"},
            "error_log": [{"step": 1, "cmd": "xx"}, {"step": 2, "cmd": "yy"}],
            "elapsed_seconds": 1200,
            "answers": {
                str(self.single_q.id): {"key": "A"},
                str(self.short_q.id): {"text": "ARP请求以广播形式发出，目标主机以单播回应，并建立IP与MAC的映射缓存"},
            },
        }, format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        sub = res.data["data"]
        self.assertEqual(sub["status"], "submitted")
        self.assertIsNotNone(sub["total_score"])
        # 基础分 100*0.8=80；准确性 5-2=3；效率 5；完成度 10 → 步骤分 98；题目 20 分
        self.assertEqual(Decimal(sub["score_breakdown"]["base"]), Decimal("80.0"))
        self.assertEqual(Decimal(sub["base_score"]), Decimal("80.0"))
        self.assertEqual(Decimal(sub["accuracy_score"]), Decimal("3"))
        self.assertGreater(Decimal(sub["total_score"]), Decimal("0"))

        # 训练型：提交后可直接重开新一轮（allow_resubmit 默认 True）
        res = self.sc.post("/api/lab-submissions/start/", {"lab": lab_id}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["data"]["submission"]["status"], "in_progress")

        # 教师复核改分 + 学生收到通知
        res = self.tc.post(f"/api/lab-submissions/{sub_id}/review/", {"total_score": "88", "comment": "不错"}, format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        self.assertEqual(Decimal(res.data["data"]["total_score"]), Decimal("88.0"))
        self.assertTrue(self.student.notifications.filter(ntype="lab").exists())

        # 教师重置接口仍可用（后端保留）
        res = self.tc.post(f"/api/lab-submissions/{sub_id}/reset/", format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        res = self.sc.post("/api/lab-submissions/start/", {"lab": lab_id}, format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        # 训练型：学生可自主重做（attempt+1），教师 reset 再 +1
        self.assertEqual(res.data["data"]["submission"]["attempt"], 3)

        # 学情统计含实验维度
        res = self.tc.get(f"/api/analytics/class/{self.classroom.id}/?course={self.course.id}")
        self.assertEqual(res.status_code, 200, res.data)
        row = res.data["data"]["students"][0]
        self.assertIn("experiment_done", row)
        self.assertIn("avg_experiment_score", row)
        self.assertEqual(row["experiment_total"], 1)

        # 相似度评分单元验证
        from apps.questions.grading import grade_subjective, subjective_similarity

        sim = subjective_similarity(
            "ARP请求以广播形式发出，目标主机以单播回应",
            "ARP请求广播，目标主机单播回应，建立IP到MAC映射",
        )
        self.assertGreater(sim, 0.5)
        verdict, score, _ = grade_subjective(self.short_q, {"text": "完全无关的内容哈哈哈哈"})
        self.assertEqual(verdict, "wrong")

    def test_question_weight_validation(self):
        """question_weight>0 时不强制附题（允许先建后附），但权重越界报错。"""
        res = self.tc.post("/api/labs/", {
            "template": self.template.id, "course": self.course.id, "question_weight": "1.5",
        }, format="json")
        self.assertEqual(res.status_code, 400)

    def test_other_teacher_cannot_access(self):
        other = User.objects.create_user("t002", password="pass1234", role="teacher", real_name="王老师")
        client = APIClient()
        client.force_authenticate(other)
        res = client.post("/api/labs/", {
            "template": self.template.id, "course": self.course.id,
        }, format="json")
        self.assertEqual(res.status_code, 400)  # 非自己课程被序列化器拒绝


class LabReportTest(TestCase):
    """二期报告生成/下载冒烟。"""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user("t101", password="pass1234", role="teacher", real_name="张老师")
        cls.student = User.objects.create_user("20249999", password="pass1234", role="student", real_name="李同学")
        cls.course = Course.objects.create(name="计算机网络", teacher=cls.teacher)
        cls.classroom = ClassRoom.objects.create(name="网络2402", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)
        cls.template = LabTemplate.objects.create(
            code="arp-ip-lab", title="ARP实验", default_standard_minutes=30,
            random_config={"ranges": {"s1": [1, 9]}},
        )
        cls.lab = Lab.objects.create(
            template=cls.template, course=cls.course, title="ARP实验",
            status=Lab.Status.PUBLISHED,
        )
        cls.schedule = LabSchedule.objects.create(lab=cls.lab, classroom=cls.classroom)

    def setUp(self):
        self.sc = APIClient()
        self.sc.force_authenticate(self.student)

    def _submit(self):
        res = self.sc.post("/api/lab-submissions/start/", {"lab": self.lab.id}, format="json")
        data = res.data["data"]
        sub_id = data["submission"]["id"]
        res = self.sc.post(f"/api/lab-submissions/{sub_id}/submit/", {
            "attempt_token": data["attempt_token"],
            "steps_result": {"1": "pass", "2": "pass", "3": "pass"},
            "error_log": [],
            "elapsed_seconds": 600,
        }, format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        return sub_id

    def test_report_generate_and_download(self):
        sub_id = self._submit()
        # 未填结论不能生成
        res = self.sc.post(f"/api/lab-submissions/{sub_id}/generate-report/")
        self.assertEqual(res.status_code, 400)
        # 写结论 → 生成
        res = self.sc.post(f"/api/lab-submissions/{sub_id}/conclusion/", {"conclusion": "掌握了 ARP 广播与单播应答机制。"}, format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        res = self.sc.post(f"/api/lab-submissions/{sub_id}/generate-report/")
        self.assertIn(res.status_code, (200, 201), res.data)
        report = res.data["data"]
        self.assertTrue(report["file_docx"])
        self.assertTrue(report["file_pdf"])
        # 下载 PDF / DOCX（注意：查询参数用 type，format 是 DRF 内容协商保留字）
        res = self.sc.get(f"/api/lab-submissions/{sub_id}/download-report/?type=pdf")
        self.assertEqual(res.status_code, 200, getattr(res, "data", None))
        self.assertEqual(res["Content-Type"], "application/pdf")
        self.assertGreater(len(b"".join(res.streaming_content)), 1000)
        res = self.sc.get(f"/api/lab-submissions/{sub_id}/download-report/?type=docx")
        self.assertEqual(res.status_code, 200, getattr(res, "data", None))
        # 其他学生不可下载（行级过滤 404 或权限 403 均可，不泄露存在性）
        other = User.objects.create_user("20248888", password="pass1234", role="student")
        oc = APIClient()
        oc.force_authenticate(other)
        res = oc.get(f"/api/lab-submissions/{sub_id}/download-report/?type=pdf")
        self.assertIn(res.status_code, (403, 404))
