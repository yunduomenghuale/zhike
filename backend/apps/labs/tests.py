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

    def test_schedule_empty_time_means_open(self):
        """排课时间留空（空字符串）按“立即开放/不限制”保存，不再 400；
        之后补截止时间可正常更新窗口。"""
        lab_id = self._create_lab()
        # 前端日期选择器清空后提交空字符串（el-date-picker 的空值形态）
        res = self.tc.post("/api/lab-schedules/", {
            "lab": lab_id, "classroom": self.classroom.id, "open_at": "", "close_at": "",
        }, format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        schedule = LabSchedule.objects.get(lab_id=lab_id, classroom=self.classroom)
        self.assertIsNone(schedule.open_at)
        self.assertIsNone(schedule.close_at)
        self.assertTrue(schedule.is_open())  # 空时间 = 始终开放

        # 同班重排：只更新截止时间，开放时间保持为空（不被误清）
        from django.utils import timezone
        from datetime import timedelta

        close_at = timezone.now() + timedelta(days=3)
        res = self.tc.post("/api/lab-schedules/", {
            "lab": lab_id, "classroom": self.classroom.id, "close_at": close_at.isoformat(),
        }, format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        schedule.refresh_from_db()
        self.assertIsNone(schedule.open_at)
        self.assertIsNotNone(schedule.close_at)

    def test_other_teacher_cannot_access(self):
        other = User.objects.create_user("t002", password="pass1234", role="teacher", real_name="王老师")
        client = APIClient()
        client.force_authenticate(other)
        res = client.post("/api/labs/", {
            "template": self.template.id, "course": self.course.id,
        }, format="json")
        self.assertEqual(res.status_code, 400)  # 非自己课程被序列化器拒绝


class LabGateTest(TestCase):
    """实验门控：随机令牌 + 签名含发布状态（下线即失效）+ 可再上线。"""

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
        cls.lab = Lab.objects.create(template=cls.template, course=cls.course, title="ARP实验")
        LabSchedule.objects.create(lab=cls.lab, classroom=cls.classroom)

    def setUp(self):
        self.tc = APIClient()
        self.tc.force_authenticate(self.teacher)
        self.sc = APIClient()
        self.sc.force_authenticate(self.student)
        self.lab.refresh_from_db()

    def _publish(self):
        res = self.tc.post(f"/api/labs/{self.lab.id}/publish/", format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        self.lab.refresh_from_db()

    def _gate(self):
        from apps.labs import gate
        return gate.sign_lab(self.lab)["url"]

    def _asset_base(self):
        """门控资产路由基址（sig/exp 在路径段，非 query）。"""
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self._gate())
        qs = parse_qs(parsed.query)
        return f"/api/lab-gate/asset/{self.lab.access_token}/{qs['sig'][0]}/{qs['exp'][0]}/"

    def test_access_token_random_unique(self):
        """每条 Lab 持有不可猜测的随机 access_token（与课程资源同构）。"""
        other = Lab.objects.create(template=self.template, course=self.course, title="另一个实验")
        self.assertNotEqual(self.lab.access_token, other.access_token)
        self.assertTrue(self.lab.access_token)

    def test_gate_page_and_asset_ok_when_published(self):
        """发布态：门控页 200（注入 <base> + SAMEORIGIN），资产可读。"""
        self._publish()
        url = self._gate()  # /api/lab-gate/page/{token}/?sig=&exp=
        res = self.sc.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'<script src="lab-bridge.js">', res.content)  # 实验页本体
        self.assertIn(b'<base href="/api/lab-gate/asset/', res.content)  # <base> 注入
        self.assertEqual(res["X-Frame-Options"], "SAMEORIGIN")
        self.assertEqual(res["Cache-Control"], "no-store")
        # 资产路由：同签名可读 lab-bridge.js
        res = self.sc.get(self._asset_base() + "lab-bridge.js")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"LabBridge", res.content)

    def test_gate_invalid_signature_blocked(self):
        """签名缺失/篡改/过期一律 403 友好页（不泄露实验存在性以外的信息）。"""
        self._publish()
        res = self.sc.get(f"/api/lab-gate/page/{self.lab.access_token}/")
        self.assertEqual(res.status_code, 403)
        self.assertIn("实验链接无效", res.content.decode())
        res = self.sc.get(f"/api/lab-gate/page/{self.lab.access_token}/?sig=bad&exp=9999999999")
        self.assertEqual(res.status_code, 403)
        res = self.sc.get(f"/api/lab-gate/page/{self.lab.access_token}/?sig=bad&exp=1")
        self.assertEqual(res.status_code, 403)  # 过期

    def test_close_invalidates_signed_url(self):
        """下线后旧签名立即失效；重新上线后（closed→published）可再次签发进入。"""
        self._publish()
        url = self._gate()
        self.assertEqual(self.sc.get(url).status_code, 200)

        # 教师下线
        res = self.tc.post(f"/api/labs/{self.lab.id}/close/", format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        self.lab.refresh_from_db()
        self.assertEqual(self.lab.status, Lab.Status.CLOSED)
        # 旧门控链接失效（签名含发布状态）
        res = self.sc.get(url)
        self.assertEqual(res.status_code, 403)

        # 票据层同步拦截：有效 attempt_token 在实验下线后也拿不到 seed
        start = self.sc.post("/api/lab-submissions/start/", {"lab": self.lab.id}, format="json")
        # start 本身对 closed 实验拒绝（先于票据）
        self.assertEqual(start.status_code, 400)

        # 重新上线：closed → published（可控上下线）
        self._publish()
        self.assertEqual(self.lab.status, Lab.Status.PUBLISHED)
        new_url = self._gate()
        self.assertEqual(self.sc.get(new_url).status_code, 200)
        # 学生可重新 start 拿新票据
        start = self.sc.post("/api/lab-submissions/start/", {"lab": self.lab.id}, format="json")
        self.assertEqual(start.status_code, 200, start.data)
        token = start.data["data"]["attempt_token"]
        res = self.sc.get(f"/api/lab-submissions/bridge-validate/?token={token}")
        self.assertEqual(res.status_code, 200, res.data)

    def test_bridge_validate_blocked_after_close(self):
        """票据有效期内实验被下线：bridge-validate 403（页内桥接同步拒绝）。"""
        self._publish()
        start = self.sc.post("/api/lab-submissions/start/", {"lab": self.lab.id}, format="json")
        token = start.data["data"]["attempt_token"]
        # 下线前可用
        self.assertEqual(self.sc.get(f"/api/lab-submissions/bridge-validate/?token={token}").status_code, 200)
        self.tc.post(f"/api/labs/{self.lab.id}/close/", format="json")
        res = self.sc.get(f"/api/lab-submissions/bridge-validate/?token={token}")
        self.assertEqual(res.status_code, 403)
        self.assertIn("下线", res.data.get("message", ""))

    def test_asset_path_traversal_blocked(self):
        """资产路由防目录穿越：.. 段与非 LABS_ROOT 路径拒绝。"""
        self._publish()
        base = self._asset_base()
        res = self.sc.get(base + "../../settings.py")
        self.assertIn(res.status_code, (403, 404))
        res = self.sc.get(base + "nonexistent.js")
        self.assertEqual(res.status_code, 404)


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
