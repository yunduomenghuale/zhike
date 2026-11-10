"""labs 一期冒烟测试：模板库 → 建实验 → 排课发布 → start/bridge → 提交评分 → 复核/重置 → 统计。"""
from decimal import Decimal

from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.classroom.models import ClassCourse, ClassRoom, ClassStudent
from apps.courses.models import Catalog, Course
from apps.labs.models import Lab, LabSchedule, LabSubmission, LabTemplate
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
        # 附题端点已随「实验附题」功能整体下线：/questions/ 应 404
        res = self.tc.post(f"/api/labs/{lab_id}/questions/", {"question_ids": [1]}, format="json")
        self.assertEqual(res.status_code, 404)
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

        # 提交：全步骤通过、耗时 20 分钟、2 次错误（附题 answers 字段已不再消费）
        res = self.sc.post(f"/api/lab-submissions/{sub_id}/submit/", {
            "attempt_token": token,
            "steps_result": {"1": "pass", "2": "pass", "3": "pass", "4": "pass", "5": "pass"},
            "error_log": [{"step": 1, "cmd": "xx"}, {"step": 2, "cmd": "yy"}],
            "elapsed_seconds": 1200,
        }, format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        sub = res.data["data"]
        self.assertEqual(sub["status"], "submitted")
        self.assertIsNotNone(sub["total_score"])
        # 基础分 100*0.8=80；准确性 5-2=3；效率 5；完成度 10 → 步骤分 98
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


class LabCustomModelTest(TestCase):
    """Stage 1：template=None 的自定义实验——数据层/报告链不崩、报告双分支、grade_raw 角色裁剪。"""

    HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>自定义实验</title>
    <style>body{font-family:sans-serif}</style></head><body><h1>实验操作区</h1>
    <script>window.__custom_lab__ = true;</script></body></html>""".encode("utf-8")

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user("t201", password="pass1234", role="teacher", real_name="赵老师")
        cls.student = User.objects.create_user("20250001", password="pass1234", role="student", real_name="钱同学")
        cls.course = Course.objects.create(name="计算机网络", teacher=cls.teacher)
        cls.classroom = ClassRoom.objects.create(name="网络2501", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)

    def setUp(self):
        self.tc = APIClient()
        self.tc.force_authenticate(self.teacher)
        self.sc = APIClient()
        self.sc.force_authenticate(self.student)

    def _create_custom_lab(self):
        res = self.tc.post("/api/labs/", {
            "page_source": "custom", "course": self.course.id,
            "title": "VLAN 综合自定义实验", "total_score": "100", "pass_score": "60",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        data = res.data["data"]
        self.assertIsNone(data["template"])
        self.assertIsNone(data["template_code"])
        self.assertIsNone(data["template_title"])
        self.assertIsNone(data["page_url"])
        self.assertEqual(data["page_source"], "custom")
        return data["id"]

    def _upload_page(self, lab_id):
        import hashlib

        from django.core.files.base import ContentFile

        from apps.labs.models import LabPage

        page = LabPage(
            lab_id=lab_id, original_name="vlan-lab.html", size=len(self.HTML),
            sha256=hashlib.sha256(self.HTML).hexdigest(), uploaded_by=self.teacher,
        )
        page.file.save("vlan-lab.html", ContentFile(self.HTML), save=True)
        return page

    def test_custom_lab_full_chain_no_template(self):
        """无模板 lab 走完 创建 → 发布 → start → bridge-validate → 生成报告，全链路不崩。"""
        lab_id = self._create_custom_lab()

        # 发布前置校验：custom 无页面必须 400
        res = self.tc.post("/api/lab-schedules/", {"lab": lab_id, "classroom": self.classroom.id}, format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        res = self.tc.post(f"/api/labs/{lab_id}/publish/", format="json")
        self.assertEqual(res.status_code, 400, res.data)
        self.assertIn("上传", res.data.get("message", ""))

        # 上传页面（模型层直建；上传 API 属 Stage 2）→ 发布成功
        self._upload_page(lab_id)
        res = self.tc.post(f"/api/labs/{lab_id}/publish/", format="json")
        self.assertIn(res.status_code, (200, 201), res.data)

        # start → 票据 + 门控 URL（gate 三分流是 Stage 2，这里只验票据/桥接层）
        res = self.sc.post("/api/lab-submissions/start/", {"lab": lab_id}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        data = res.data["data"]
        token = data["attempt_token"]
        self.assertIn("page_url", data)

        # bridge-validate：template=None 不崩，code 兜底 custom-{id}，expected 为空
        res = self.sc.get(f"/api/lab-submissions/bridge-validate/?token={token}")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["data"]["lab"]["code"], f"custom-{lab_id}")
        self.assertEqual(res.data["data"]["lab"]["page_source"], "custom")
        self.assertEqual(res.data["data"]["expected"], {})

        # 模拟 Stage 3 端点将写入的成绩（external 分支数据形态）
        from django.utils import timezone

        from apps.labs.models import LabSubmission

        sub = LabSubmission.objects.get(lab_id=lab_id, student=self.student)
        sub.status = LabSubmission.Status.SUBMITTED
        sub.submitted_at = timezone.now()
        sub.elapsed_seconds = 742
        sub.total_score = "86.5"
        sub.score_breakdown = {"source": "external", "total": 86.5, "elapsed_seconds": 742}
        sub.grading_source = "external"
        sub.grade_raw = {"body": {"total_score": 86.5, "elapsed_seconds": 742}, "server": {"via": "parent"}}
        sub.grade_raw_digest = "ab" * 32
        sub.graded_at = timezone.now()
        sub.save()

        # grade_raw 角色裁剪：教师可见、学生 None（C8）
        res = self.tc.get(f"/api/lab-submissions/{sub.id}/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["data"]["grade_raw"]["body"]["total_score"], 86.5)
        self.assertEqual(res.data["data"]["grading_source"], "external")
        res = self.sc.get(f"/api/lab-submissions/{sub.id}/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIsNone(res.data["data"]["grade_raw"])
        self.assertEqual(res.data["data"]["score_breakdown"]["source"], "external")

        # 报告：写结论 → 生成 → docx/pdf 真实打开检查
        res = self.sc.post(f"/api/lab-submissions/{sub.id}/conclusion/", {"conclusion": "完成了 VLAN 划分与连通性验证。"}, format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        res = self.sc.post(f"/api/lab-submissions/{sub.id}/generate-report/")
        self.assertIn(res.status_code, (200, 201), res.data)

        sub.refresh_from_db()
        self.assertTrue(sub.report.file_docx.name.endswith(".docx"))
        self.assertIn(f"custom-{lab_id}", sub.report.file_name)

        # DOCX：评分明细 = 总分 + 用时，不出现步骤分四项与步骤表
        from docx import Document as DocxDocument

        doc = DocxDocument(sub.report.file_docx.path)
        text = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("总分：86.5 / 100", text)
        self.assertIn("用时：12 分钟", text)
        self.assertNotIn("基础分", text)
        self.assertIn("不适用", text)  # 步骤清单标注不适用
        self.assertNotIn("步骤 1：", text)

        # PDF：魔数正确且可解析出「总分」文本
        import pypdf

        self.assertTrue(sub.report.file_pdf.path.endswith(".pdf"))
        reader = pypdf.PdfReader(sub.report.file_pdf.path)
        pdf_text = "".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("总分", pdf_text)
        self.assertNotIn("基础分", pdf_text)

    def test_template_mode_still_requires_template(self):
        """template 模式不填模板仍被校验拒绝（存量行为不回退）。"""
        res = self.tc.post("/api/labs/", {
            "page_source": "template", "course": self.course.id, "title": "无模板预置",
        }, format="json")
        self.assertEqual(res.status_code, 400, res.data)

    def test_custom_lab_clears_template_on_create(self):
        """custom + 同时带 template：以 custom 为准，template 被清空。"""
        template = LabTemplate.objects.create(code="arp-ip-lab", title="ARP实验")
        res = self.tc.post("/api/labs/", {
            "page_source": "custom", "template": template.id, "course": self.course.id,
            "title": "带模板字段的自定义实验", "total_score": "100",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIsNone(res.data["data"]["template"])


class LabCustomPageTest(TestCase):
    """Stage 2：页面上传/替换/删除/预览 + L2 沙箱门控（父页面/frame 双响应）+ S8 静态扫描。"""

    HTML = """<!DOCTYPE html><html lang="zh-CN"><head>
    <meta charset="utf-8"><base href="https://evil.example/"><title>上传测试</title>
    <style>body{{font-family:sans-serif}}</style></head>
    <body><h1 id="t">教师实验页面</h1><script>var a=1;<\/script></body></html>""".encode("utf-8")

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user("t301", password="pass1234", role="teacher", real_name="孙老师")
        cls.student = User.objects.create_user("20260001", password="pass1234", role="student", real_name="周同学")
        cls.admin = User.objects.create_user("adm1", password="pass1234", role="admin", real_name="管理员")
        cls.course = Course.objects.create(name="计算机网络", teacher=cls.teacher)
        cls.classroom = ClassRoom.objects.create(name="网络2601", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)

    def setUp(self):
        self.tc = APIClient()
        self.tc.force_authenticate(self.teacher)
        self.sc = APIClient()
        self.sc.force_authenticate(self.student)

    def _make_custom_lab(self):
        res = self.tc.post("/api/labs/", {
            "page_source": "custom", "course": self.course.id,
            "title": "沙箱测试实验", "total_score": "100", "pass_score": "60",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        return res.data["data"]["id"]

    def _upload(self, lab_id, content=None, name="page.html", confirm=None):
        from django.core.files.uploadedfile import SimpleUploadedFile

        data = {"file": SimpleUploadedFile(name, content if content is not None else self.HTML, content_type="text/html")}
        if confirm is not None:
            data["confirm"] = confirm
        return self.tc.post(f"/api/labs/{lab_id}/page/", data, format="multipart")

    def _publish_with_page(self, lab_id):
        res = self.tc.post("/api/lab-schedules/", {"lab": lab_id, "classroom": self.classroom.id}, format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        res = self.tc.post(f"/api/labs/{lab_id}/publish/", format="json")
        self.assertIn(res.status_code, (200, 201), res.data)

    def test_upload_replace_delete_page(self):
        """上传 → 发布 → 替换（旧文件清盘）→ 删除（无模板拒绝 / 有模板回退）。"""
        from apps.labs.models import LabPage

        lab_id = self._make_custom_lab()

        # 非 .html / 空文件被拒
        res = self._upload(lab_id, b"hi", name="page.txt")
        self.assertEqual(res.status_code, 400, res.data)
        res = self._upload(lab_id, b"", name="empty.html")
        self.assertEqual(res.status_code, 400, res.data)

        # 正常上传
        res = self._upload(lab_id)
        self.assertIn(res.status_code, (200, 201), res.data)
        page = LabPage.objects.get(lab_id=lab_id)
        first_path = page.file.path
        self.assertEqual(page.original_name, "page.html")
        self.assertEqual(page.sha256, __import__("hashlib").sha256(self.HTML).hexdigest())
        self.assertEqual(page.uploaded_by, self.teacher)
        # 序列化器带页面元信息
        res = self.tc.get(f"/api/labs/{lab_id}/")
        self.assertTrue(res.data["data"]["has_custom_page"])
        self.assertEqual(res.data["data"]["custom_page_name"], "page.html")

        # 替换：旧磁盘文件被清
        res = self._upload(lab_id, self.HTML + b"<!-- v2 -->")
        self.assertIn(res.status_code, (200, 201), res.data)
        page.refresh_from_db()
        self.assertNotEqual(page.file.path, first_path)
        self.assertFalse(__import__("os").path.exists(first_path))

        # 发布前置校验通过
        self._publish_with_page(lab_id)

        # 无模板不可删除页面
        res = self.tc.delete(f"/api/labs/{lab_id}/page/")
        self.assertEqual(res.status_code, 400, res.data)

        # 有模板：删除页面 → 回退 template 模式
        lab = Lab.objects.get(id=lab_id)
        lab.template = LabTemplate.objects.create(code="arp-ip-lab", title="ARP实验")
        lab.save(update_fields=["template"])
        res = self.tc.delete(f"/api/labs/{lab_id}/page/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["data"]["page_source"], "template")
        self.assertFalse(LabPage.objects.filter(lab_id=lab_id).exists())
        lab.refresh_from_db()
        self.assertFalse(__import__("os").path.exists(page.file.path))

        # 删除实验：磁盘无残留（C7/perform_destroy）
        res = self.tc.post("/api/labs/", {
            "page_source": "custom", "course": self.course.id, "title": "待删除实验", "total_score": "100",
        }, format="json")
        lab2 = res.data["data"]["id"]
        res = self._upload(lab2)
        self.assertIn(res.status_code, (200, 201), res.data)
        p2 = LabPage.objects.get(lab_id=lab2)
        p2_path = p2.file.path
        res = self.tc.delete(f"/api/labs/{lab2}/")
        self.assertIn(res.status_code, (200, 204), res.data)
        self.assertFalse(__import__("os").path.exists(p2_path))

    def test_sandbox_parent_and_frame(self):
        """L2 门控：父页面持票据 + sandbox iframe（无 allow-same-origin）；frame 无票据。"""
        import re

        lab_id = self._make_custom_lab()
        self._upload(lab_id)
        self._publish_with_page(lab_id)

        # 学生 start → 父页面 URL（含票据）
        res = self.sc.post("/api/lab-submissions/start/", {"lab": lab_id}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        data = res.data["data"]
        token = data["attempt_token"]
        page_url = data["page_url"]

        # 父页面：200 + 平台父页面特征
        res = self.sc.get(page_url)
        self.assertEqual(res.status_code, 200, res.content[:200])
        html = res.content.decode()
        m = re.search(r'<iframe[^>]*sandbox="([^"]*)"[^>]*src="([^"]*)"', html)
        self.assertIsNotNone(m, "父页面必须含 sandbox iframe")
        sandbox_attr, frame_src = m.group(1), m.group(2)
        # C40：绝不允许 allow-same-origin
        self.assertNotIn("allow-same-origin", sandbox_attr)
        self.assertIn("allow-scripts", sandbox_attr)
        # C45：iframe src 绝对路径、不含票据
        self.assertTrue(frame_src.startswith("/api/lab-gate/frame/"), frame_src)
        self.assertNotIn(token, frame_src)
        self.assertNotIn("token=", frame_src)
        # C45：父页面自带 <base> 与 parent 桥接脚本
        self.assertIn('<base href="/api/lab-gate/asset/', html)
        self.assertIn("lab-bridge-parent.js", html)
        # 票据只以 JSON 字面量进父页面引导变量
        self.assertIn(f'window.__LAB_BOOT_TOKEN__ = "{token}";', html)
        # S6：父页面严格 CSP
        csp = res.get("Content-Security-Policy", "")
        self.assertIn("form-action 'none'", csp)
        self.assertIn("base-uri 'self'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertEqual(res.get("Referrer-Policy"), "no-referrer")

        # frame：教师 HTML + shim，无任何票据/引导变量
        res = self.sc.get(frame_src)
        self.assertEqual(res.status_code, 200, res.content[:200])
        frame_html = res.content.decode()
        self.assertIn("教师实验页面", frame_html)
        self.assertIn("lab-bridge-shim.js", frame_html)
        self.assertIn('<base href="/api/lab-gate/asset/', frame_html)
        self.assertNotIn(token, frame_html)                      # 票据不进 iframe
        self.assertNotIn("__LAB_BOOT_TOKEN__", frame_html)       # 引导变量不进 iframe
        self.assertNotIn("https://evil.example/", frame_html)    # 教师自带 <base> 被剥离
        # frame CSP：sandbox 指令（无 allow-same-origin）+ 严格 CSP
        fcsp = res.get("Content-Security-Policy", "")
        self.assertIn("sandbox allow-scripts allow-forms allow-modals", fcsp)
        self.assertNotIn("allow-same-origin", fcsp)
        self.assertIn("form-action 'none'", fcsp)
        self.assertIn("base-uri 'self'", fcsp)
        self.assertEqual(res.get("X-Frame-Options"), "SAMEORIGIN", "C44：frame 响应须 SAMEORIGIN")

        # 无票据访问父页面 → 403 友好页
        bare = page_url.split("&token=")[0]
        res = self.sc.get(bare)
        self.assertEqual(res.status_code, 403)

    def test_static_scan_and_preview(self):
        """S8 静态扫描（命中→二次确认→管理员告警）+ 教师预览（草稿可预览、不取票据）。"""
        lab_id = self._make_custom_lab()

        # 命中扫描：首次拒绝并给出命中项
        dirty = b"""<html><head><script src="https://cdn.example/x.js"></script>
        <script>eval("1");localStorage.getItem("k");new WebSocket("wss://x");
        navigator.sendBeacon("https://x",{});document.cookie;window.opener;</script>
        </head><body>s</body></html>"""
        res = self._upload(lab_id, dirty, name="dirty.html")
        self.assertEqual(res.status_code, 400, res.data)
        self.assertTrue(res.data["data"]["require_confirm"])
        self.assertIn("eval 动态执行", res.data["data"]["hits"])
        self.assertIn("外链资源引用", res.data["data"]["hits"])
        self.assertGreaterEqual(len(res.data["data"]["hits"]), 6)
        # 未确认不落库
        from apps.labs.models import LabPage
        self.assertFalse(LabPage.objects.filter(lab_id=lab_id).exists())
        self.assertFalse(self.admin.notifications.exists())

        # confirm=1 二次确认 → 落库 + 管理员告警
        res = self._upload(lab_id, dirty, name="dirty.html", confirm="1")
        self.assertIn(res.status_code, (200, 201), res.data)
        self.assertTrue(self.admin.notifications.filter(title__contains="静态扫描命中").exists())

        # 干净文件无告警上传成功
        lab2 = self._make_custom_lab()
        res = self._upload(lab2)
        self.assertIn(res.status_code, (200, 201), res.data)
        self.assertEqual(res.data["data"]["hits"], [])

        # 预览：草稿（未发布）也可预览；父页面 preview=true 且不注入票据
        res = self.tc.get(f"/api/labs/{lab2}/page/preview/")
        self.assertEqual(res.status_code, 200, res.data)
        url = res.data["data"]["url"]
        self.assertIn("preview=1", url)
        res = self.tc.get(url)
        self.assertEqual(res.status_code, 200, res.content[:200])
        html = res.content.decode()
        self.assertIn("window.__LAB_PREVIEW__ = true;", html)
        self.assertIn("window.__LAB_BOOT_TOKEN__ = null;", html)
        import re
        m = re.search(r'<iframe[^>]*src="([^"]*)"', html)
        self.assertIn("preview=1", m.group(1))
        # 预览页 <base> 必须换成正式签名，否则 lab-bridge-parent.js / shim.js 403
        base = re.search(r'<base href="([^"]*)"', html).group(1)
        res = self.tc.get(base + "lab-bridge-parent.js")
        self.assertEqual(res.status_code, 200, b"lib must be readable in preview")
        # 预览 frame 同样可达（草稿，走 verify_preview），且 shim 资产可读
        res = self.tc.get(m.group(1))
        self.assertEqual(res.status_code, 200, res.content[:200])
        frame_base = re.search(r'<base href="([^"]*)"', res.content.decode()).group(1)
        res = self.tc.get(frame_base + "lab-bridge-shim.js")
        self.assertEqual(res.status_code, 200, b"shim must be readable in preview")
        self.assertIn("教师实验页面", self.tc.get(m.group(1)).content.decode())

        # 学生无权限上传/预览（IsTeacher 不含学生；admin 按 C46 也不放行教师 action）
        res = self.sc.post(f"/api/labs/{lab2}/page/", {}, format="multipart")
        self.assertIn(res.status_code, (401, 403), res.data)
        res = self.sc.get(f"/api/labs/{lab2}/page/preview/")
        self.assertIn(res.status_code, (401, 403), res.data)


class LabStaticContractTest(SimpleTestCase):
    """Stage 2：C40/C41/C42/C44/C45/C46 静态契约逐条对照（读真实静态文件与源码，非 mock）。"""

    def _static(self, name):
        from pathlib import Path

        from django.conf import settings

        text = (Path(settings.LABS_ROOT) / name).read_text(encoding="utf-8")
        self.assertTrue(text.strip(), f"{name} 不应为空")
        return text

    def test_c40_c46_static_contract(self):
        import re
        from pathlib import Path

        parent_html = self._static("lab-gate-parent.html")
        parent_js = self._static("lab-bridge-parent.js")
        shim_js = self._static("lab-bridge-shim.js")
        views_src = Path(__file__).with_name("views.py").read_text(encoding="utf-8")

        # C40：三个 L2 静态文件都不出现 allow-same-origin（含注释，避免后续静态扫描误命中）
        for name, text in (("parent.html", parent_html), ("parent.js", parent_js), ("shim.js", shim_js)):
            self.assertNotIn("allow-same-origin", text, f"C40: {name} 出现 allow-same-origin")

        # C44：iframe sandbox 属性与 frame 响应 CSP sandbox 指令取交集且保持一致
        m = re.search(r'<iframe[^>]*sandbox="([^"]*)"', parent_html)
        self.assertIsNotNone(m, "C44：父页面必须显式声明 sandbox 属性")
        sandbox_attr = " ".join(m.group(1).split())
        self.assertEqual(sandbox_attr, "allow-scripts allow-forms allow-modals")
        csp_sandbox = re.search(r'"sandbox ([^;"]+); "', views_src)
        self.assertIsNotNone(csp_sandbox, "C44：frame 响应必须下发 sandbox 指令")
        self.assertEqual(" ".join(csp_sandbox.group(1).split()), sandbox_attr)

        # C41：opaque origin 下 event.origin 恒为 "null"，必须校验 event.source
        self.assertIn("e.source !== frame.contentWindow", parent_js, "C41：必须校验 event.source")

        # C42：shim 内不得出现票据头或同源 API fetch 字面量，分数只走 postMessage
        self.assertNotIn("X-Lab-Token", shim_js, "C42：shim 不得出现票据头字面量")
        self.assertNotIn("fetch('/api", shim_js, "C42：shim 不得出现同源 API fetch")
        self.assertNotIn('fetch("/api', shim_js, "C42：shim 不得出现同源 API fetch")
        self.assertIn("window.parent.postMessage", shim_js, "C42：shim 必须只经 postMessage 通信")

        # C45：四占位符齐全（注释形态，避免替换误伤 window.__LAB_*__ 变量名）
        for ph in (
            "/*__FRAME_URL__*/", "/*__LAB_BOOT_TOKEN__*/",
            "/*__LAB_CONTEXT__*/", "/*__LAB_PREVIEW__*/",
        ):
            self.assertIn(ph, parent_html, f"C45：父页面缺少占位符 {ph}")
        self.assertIn('<script src="lab-bridge-parent.js">', parent_html)
        self.assertIn('src="/*__FRAME_URL__*/"', parent_html)
        for field in ("labId", "submissionId", "totalScore", "gradeEndpoint"):
            self.assertIn(field, parent_js, f"C45：context 缺字段 {field}")
        # 断言「实际取用原响应字段」而非注释里的字面量，避免注释措辞误伤
        for leaked in ("d.random_seed", "d.expected", "d.status", "res.data.status"):
            self.assertNotIn(leaked, parent_js, f"C45：不得透传 {leaked}")

        # C46：新增 action 显式 [IsTeacher]，不得放宽为 IsTeacherOrAdmin
        self.assertIsNotNone(
            re.search(r'@action\([^)]*url_path="page"[^)]*permission_classes=\[IsTeacher\]\)', views_src),
            "C46：page action 必须显式 [IsTeacher]",
        )
        self.assertIsNotNone(
            re.search(r'@action\([^)]*url_path="page/preview"[^)]*permission_classes=\[IsTeacher\]\)', views_src),
            "C46：preview action 必须显式 [IsTeacher]",
        )
        self.assertNotIn("IsTeacherOrAdmin", views_src, "C46：不得使用 IsTeacherOrAdmin 放宽权限")

    def test_stage3_grade_contract(self):
        """Stage 3 静态契约：S2 双行锁 / S4 闸门 / context 四字段 / 限流双写 / 路由顺序。"""
        from pathlib import Path

        parent_js = self._static("lab-bridge-parent.js")
        shim_js = self._static("lab-bridge-shim.js")
        views_src = Path(__file__).with_name("views.py").read_text(encoding="utf-8")
        services_src = Path(__file__).with_name("services.py").read_text(encoding="utf-8")
        urls_src = Path(__file__).with_name("urls.py").read_text(encoding="utf-8")
        settings_src = Path(__file__).parents[2].joinpath("config", "settings.py").read_text(encoding="utf-8")
        throttles_src = Path(__file__).parents[1].joinpath("common", "throttles.py").read_text(encoding="utf-8")

        # C41 / S4：伪造 postMessage（source 不符）被丢弃；失败自动解除闸门
        self.assertIn("e.source !== frame.contentWindow", parent_js)
        self.assertIn("if (m.type !== 'lab:grade' || reported) return;", parent_js)
        self.assertIn("if (!res || res.code !== 0) reported = false;", parent_js)
        self.assertIn("reported = false;", parent_js)
        # 票据只进父页面上报请求头，且引导变量用完即删
        self.assertIn("delete window.__LAB_BOOT_TOKEN__", parent_js)
        self.assertIn("'/api/lab-gate/grade/'", parent_js)
        self.assertIn("'X-Lab-Token': token", parent_js)
        # context / 响应一律不含票据：所有 postMessage 行都不得出现 token
        post_lines = [ln for ln in parent_js.splitlines() if "postMessage(" in ln]
        self.assertTrue(post_lines)
        for ln in post_lines:
            self.assertNotIn("token", ln.lower(), f"C45：postMessage 泄漏票据：{ln.strip()}")

        # C42：shim 无票据、无同源 API 请求；LabBridge.context 只来自父页面应答
        self.assertNotIn("X-Lab-Token", shim_js)
        self.assertNotIn("fetch(", shim_js)
        self.assertNotIn("bootToken", shim_js)
        self.assertIn("m.context || null", shim_js)
        self.assertIn("window.parent.postMessage", shim_js)

        # C45：服务端 context 恰好四字段、不含票据字面量
        start = views_src.index("context = {")
        block = views_src[start:views_src.index("}", start)]
        for field in ("labId", "submissionId", "totalScore", "gradeEndpoint"):
            self.assertIn(f'"{field}"', block)
        self.assertNotIn("token", block.lower())
        self.assertIn("services.finalize_submission", views_src)
        self.assertIn("grade-debug", views_src)

        # S2：同一事务内双行锁 + 事务内消费票据
        self.assertIn("with transaction.atomic():", services_src)
        self.assertEqual(services_src.count(".select_for_update()"), 2)
        self.assertIn("bridge.consume_token(locked_ticket)", services_src)

        # C22/C43：显式 grade path 必须排在 router.urls 之前
        self.assertLess(urls_src.index('path("lab-gate/grade/"'), urls_src.index("+ router.urls"))

        # lab_grade 限流 scope：双写 + 自定义 get_cache_key 按 user.pk
        self.assertGreaterEqual(settings_src.count('"lab_grade": "10/min"'), 2)
        self.assertIn("class LabGradeThrottle", throttles_src)
        self.assertIn('"ident": user.pk', throttles_src)


# ---------------------------------------------------------------------------
# Stage 3：成绩上报端点 / S1–S5 / dry-run / C17·C18 统计分支
# ---------------------------------------------------------------------------


class LabGradeReportTest(TestCase):
    """`POST /api/lab-gate/grade/` 六分支 + S1/S3/S5 + dry-run + 失败重试。"""

    HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
    <title>成绩上报测试页</title></head><body><h1>自定义实验</h1>
    <script>
      window.__custom_lab__ = true;
      // 接入说明要求：运行时读取满分并上报成绩（静态健康检查会查这两个调用）
      (async function () {
        const ctx = await window.LabBridge.validate();
        window.__maxScore__ = ctx.totalScore;
        window.LabBridge.reportGrade({ total_score: 0, elapsed_seconds: 0 });
      })();
    </script></body></html>""".encode("utf-8")

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user("t401", password="pass1234", role="teacher", real_name="吴老师")
        cls.student = User.objects.create_user("20270001", password="pass1234", role="student", real_name="郑同学")
        cls.other_student = User.objects.create_user("20270002", password="pass1234", role="student", real_name="王同学")
        cls.admin = User.objects.create_user("adm401", password="pass1234", role="admin", real_name="管理员")
        cls.course = Course.objects.create(name="计算机网络", teacher=cls.teacher)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第4章 自定义实验", is_published=True)
        cls.classroom = ClassRoom.objects.create(name="网络2701", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.other_student)
        cls.template = LabTemplate.objects.create(
            code="st3-arp", title="ARP实验", default_standard_minutes=30,
            random_config={"ranges": {"s1": [1, 9], "s2": [1, 9]}},
        )

    def setUp(self):
        self.tc = APIClient()
        self.tc.force_authenticate(self.teacher)
        self.sc = APIClient()
        self.sc.force_authenticate(self.student)
        self.adc = APIClient()
        self.adc.force_authenticate(self.admin)
        # 真实浏览器路径：父页面只带 X-Lab-Token 头，不带 JWT、不带 force_authenticate
        self.gc = APIClient()

    def _make_lab(self, title="成绩上报测试实验", page_source="custom"):
        payload = {
            "course": self.course.id, "catalog": self.catalog.id, "title": title,
            "total_score": "100", "pass_score": "60", "page_source": page_source,
        }
        if page_source == "template":
            payload["template"] = self.template.id
        res = self.tc.post("/api/labs/", payload, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        return res.data["data"]["id"]

    def _upload(self, lab_id):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return self.tc.post(f"/api/labs/{lab_id}/page/", {
            "file": SimpleUploadedFile("grade.html", self.HTML, content_type="text/html"),
        }, format="multipart")

    def _publish(self, lab_id):
        res = self.tc.post("/api/lab-schedules/", {"lab": lab_id, "classroom": self.classroom.id}, format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        res = self.tc.post(f"/api/labs/{lab_id}/publish/", format="json")
        self.assertIn(res.status_code, (200, 201), res.data)

    def _setup(self, title="成绩上报测试实验", page_source="custom"):
        lab_id = self._make_lab(title, page_source)
        if page_source == "custom":
            res = self._upload(lab_id)
            self.assertIn(res.status_code, (200, 201), res.data)
        self._publish(lab_id)
        return lab_id

    def _start(self, lab_id):
        res = self.sc.post("/api/lab-submissions/start/", {"lab": lab_id}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        data = res.data["data"]
        return data["attempt_token"], data["submission"]["id"]

    def _grade(self, token, payload, client=None):
        return (client or self.gc).post(
            "/api/lab-gate/grade/", payload, format="json", HTTP_X_LAB_TOKEN=token,
        )

    def _ticket(self, token):
        from apps.labs.models import LabAttemptToken

        return LabAttemptToken.objects.get(token=token)

    def _sub(self, sub_id):
        from apps.labs.models import LabSubmission

        return LabSubmission.objects.get(pk=sub_id)

    def test_grade_debug_detects_page_without_bridge(self):
        """Stage 9 教师反馈：把页面里的 script 删掉后，dry-run 必须能发现页面没接入桥接，
        而不是无论页面长什么样都 PASS。"""
        from django.core.files.uploadedfile import SimpleUploadedFile

        lab_id = self._make_lab("无桥接调用实验")
        bad_html = ("<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
                    "<title>静态页</title></head><body><h1>纯展示页，没有任何脚本</h1></body></html>").encode("utf-8")
        res = self.tc.post(f"/api/labs/{lab_id}/page/", {
            "file": SimpleUploadedFile("bad.html", bad_html, content_type="text/html"),
        }, format="multipart")
        self.assertEqual(res.status_code, 200, res.data)
        self._publish(lab_id)
        res = self.tc.post(f"/api/labs/{lab_id}/grade-debug/", {
            "total_score": "88.5", "elapsed_seconds": 60,
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertFalse(res.data["data"]["passed"], "无桥接调用的页面必须判失败")
        names = {c["name"]: c for c in res.data["data"]["checks"]}
        self.assertFalse(names["页面脚本"]["ok"])
        self.assertFalse(names["读取满分（LabBridge.validate）"]["ok"])
        self.assertFalse(names["成绩上报（LabBridge.reportGrade）"]["ok"])

    def test_invalid_expired_consumed_ticket(self):
        """六分支 1：票据无效 / 过期 / 已消费 / 完全缺失，一律拒绝且不落库。"""
        from datetime import timedelta

        from django.utils import timezone

        lab_id = self._setup()
        token, sub_id = self._start(lab_id)

        res = self._grade("not-a-real-token", {"total_score": "86.5", "elapsed_seconds": 10})
        self.assertEqual(res.status_code, 401, res.data)
        self.assertIn("票据无效", res.data["message"])

        res = self.gc.post("/api/lab-gate/grade/", {"total_score": "86.5"}, format="json")
        self.assertEqual(res.status_code, 401, res.data)
        self.assertEqual(res.data["message"], "实验票据无效")

        t = self._ticket(token)
        t.expires_at = timezone.now() - timedelta(seconds=1)
        t.save(update_fields=["expires_at", "updated_at"])
        res = self._grade(token, {"total_score": "86.5", "elapsed_seconds": 10})
        self.assertEqual(res.status_code, 401, res.data)
        self.assertIn("过期", res.data["message"])

        t.expires_at = timezone.now() + timedelta(hours=2)
        t.save(update_fields=["expires_at", "updated_at"])
        t.consumed = True
        t.save(update_fields=["consumed", "updated_at"])
        res = self._grade(token, {"total_score": "86.5", "elapsed_seconds": 10})
        self.assertEqual(res.status_code, 401, res.data)
        self.assertIn("已使用", res.data["message"])

        sub = self._sub(sub_id)
        self.assertEqual(sub.status, "in_progress")
        self.assertIsNone(sub.submitted_at)
        self.assertIsNone(sub.total_score, "LabSubmission.total_score 是 nullable，未提交时应为 None")
        self.assertEqual(sub.grading_source, "steps")

    def test_cross_lab_ticket_and_body_fields_ignored(self):
        """六分支 2：跨实验票据（预置实验）被拒；票据归属被篡改被拒；请求体不能指定实验/学生。"""
        lab_a = self._setup("自定义实验 A")
        lab_b = self._setup("预置实验 B", page_source="template")
        token_a, sub_a = self._start(lab_a)
        token_b, _ = self._start(lab_b)

        # 预置实验票据不能走 external 端点（custom 来源硬校验）
        res = self._grade(token_b, {"total_score": "90", "elapsed_seconds": 100})
        self.assertEqual(res.status_code, 400, res.data)
        self.assertIn("不支持页面成绩上报", res.data["message"])

        # 票据学生被改成别人 → C32 归属校验（不是自我抵消的 request.user 比较）
        t = self._ticket(token_a)
        t.student = self.other_student
        t.save(update_fields=["student", "updated_at"])
        res = self._grade(token_a, {"total_score": "86.5", "elapsed_seconds": 10})
        self.assertEqual(res.status_code, 400, res.data)
        self.assertIn("票据与作答不匹配", res.data["message"])

        t.student = self.student
        t.save(update_fields=["student", "updated_at"])
        # 请求体伪造 lab / student / submitted_at：一律忽略，只从票据反查
        res = self._grade(token_a, {
            "total_score": "86.5", "elapsed_seconds": 3,
            "lab": lab_b, "student": self.other_student.id,
            "submitted_at": "2000-01-01T00:00:00Z",
        })
        self.assertEqual(res.status_code, 200, res.data)
        sub = self._sub(sub_a)
        self.assertEqual(sub.lab_id, lab_a)
        self.assertEqual(sub.student_id, self.student.id)
        self.assertNotEqual(sub.submitted_at.year, 2000)

    def test_out_of_range_score_and_failed_retry(self):
        """六分支 3：越界/格式错/超大报文返回中文错误；票据不作废，修正后重试成功。"""
        lab_id = self._setup()
        token, sub_id = self._start(lab_id)
        cases = [
            ({}, "缺少总成绩"),
            ({"total_score": "abc"}, "总成绩格式不正确"),
            ({"total_score": "-1", "elapsed_seconds": 10}, "成绩超出实验总分范围"),
            ({"total_score": "100.1", "elapsed_seconds": 10}, "成绩超出实验总分范围"),
            ({"total_score": "86.55", "elapsed_seconds": 10}, "最多保留 1 位小数"),
            ({"total_score": "86.5", "elapsed_seconds": -1}, "用时不能为负"),
            ({"total_score": "86.5", "elapsed_seconds": 10, "pad": "x" * 70000}, "上报内容过大"),
        ]
        for payload, expected in cases:
            res = self._grade(token, payload)
            self.assertEqual(res.status_code, 400, (payload.get("total_score"), res.data))
            self.assertIn(expected, res.data["message"], res.data)
            self.assertFalse(self._ticket(token).consumed, "失败不得作废票据")
            self.assertEqual(self._sub(sub_id).status, "in_progress")

        # 修正后重试成功（S4 父页面失败自动解除闸门的服务端前提）
        res = self._grade(token, {"total_score": "86.5", "elapsed_seconds": 10})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertTrue(self._ticket(token).consumed)
        self.assertEqual(self._sub(sub_id).status, "submitted")

    def test_success_uses_server_time_and_raw_digest(self):
        """六分支 4 + S1：正常入库、票据消费、submitted_at 与用时均由服务端生成。"""
        from datetime import timedelta
        import hashlib
        import json

        from django.utils import timezone

        lab_id = self._setup()
        token, sub_id = self._start(lab_id)
        LabSubmission.objects.filter(pk=sub_id).update(
            started_at=timezone.now() - timedelta(seconds=742)
        )

        # 客户端谎报 3 秒 + 伪造 submitted_at
        res = self._grade(token, {
            "total_score": "86.5", "elapsed_seconds": 3,
            "submitted_at": "2000-01-01T00:00:00Z",
        })
        self.assertEqual(res.status_code, 200, res.data)
        data = res.data["data"]
        self.assertEqual(
            {"submission_id", "total_score", "status", "submitted_at", "graded_at"},
            set(data.keys()),
        )
        self.assertEqual(data["status"], "submitted")
        self.assertEqual(Decimal(str(data["total_score"])), Decimal("86.5"))

        sub = self._sub(sub_id)
        delta = int((sub.submitted_at - sub.started_at).total_seconds())
        self.assertEqual(sub.elapsed_seconds, delta, "S1：用时必须是 submitted_at - started_at")
        self.assertGreaterEqual(delta, 742)
        self.assertNotEqual(sub.elapsed_seconds, 3, "S1：客户端用时不得采信")
        self.assertLess(abs((sub.submitted_at - timezone.now()).total_seconds()), 60)
        self.assertEqual(sub.grading_source, "external")
        self.assertEqual(Decimal(str(sub.total_score)), Decimal("86.5"))
        self.assertEqual(sub.score_breakdown["source"], "external")
        self.assertEqual(sub.score_breakdown["total"], 86.5)
        self.assertEqual(sub.score_breakdown["elapsed_seconds"], delta)
        self.assertEqual(sub.graded_at, sub.submitted_at)
        self.assertEqual(sub.passed_steps, 0)
        self.assertEqual(sub.total_steps, 0)
        # C8：grade_raw 原文 + 摘要，教师可见、学生不可见
        self.assertEqual(sub.grade_raw["request"]["elapsed_seconds"], 3)
        self.assertEqual(sub.grade_raw["server"]["client_elapsed_seconds"], 3)
        self.assertEqual(sub.grade_raw["server"]["elapsed_seconds"], delta)
        self.assertEqual(
            sub.grade_raw_digest,
            hashlib.sha256(json.dumps(
                sub.grade_raw, sort_keys=True, ensure_ascii=False, default=str
            ).encode("utf-8")).hexdigest(),
        )
        self.assertTrue(self._ticket(token).consumed)
        self.assertEqual(
            self.tc.get(f"/api/lab-submissions/{sub_id}/").data["data"]["grade_raw"]["request"]["elapsed_seconds"], 3
        )
        self.assertIsNone(
            self.sc.get(f"/api/lab-submissions/{sub_id}/").data["data"]["grade_raw"]
        )

    def test_window_closed_and_unpublished_rejected(self):
        """S3：窗口关闭 / 实验下线后，持有效票据仍被拒；票据与作答状态不变。"""
        from datetime import timedelta

        from django.utils import timezone

        lab_id = self._setup()
        token, sub_id = self._start(lab_id)
        LabSchedule.objects.filter(lab_id=lab_id).update(
            close_at=timezone.now() - timedelta(minutes=1)
        )

        res = self._grade(token, {"total_score": "86.5", "elapsed_seconds": 10})
        self.assertEqual(res.status_code, 400, res.data)
        self.assertIn("实验已截止", res.data["message"])
        res = self.sc.get(f"/api/lab-submissions/bridge-validate/?token={token}")
        self.assertEqual(res.status_code, 403, res.data)
        self.assertIn("实验已截止", res.data["message"])

        LabSchedule.objects.filter(lab_id=lab_id).update(close_at=None)
        Lab.objects.filter(id=lab_id).update(status=Lab.Status.CLOSED)
        res = self._grade(token, {"total_score": "86.5", "elapsed_seconds": 10})
        self.assertEqual(res.status_code, 400, res.data)
        self.assertIn("实验已下线", res.data["message"])

        self.assertFalse(self._ticket(token).consumed)
        self.assertEqual(self._sub(sub_id).status, "in_progress")

    def test_perfect_instant_submit_marked_abnormal(self):
        """S5：满分 + 极短用时置 abnormal=True，只标记不拒答；非满分不误标。"""
        lab_a = self._setup("满分秒交实验")
        token_a, sub_a = self._start(lab_a)
        res = self._grade(token_a, {"total_score": "100", "elapsed_seconds": 1})
        self.assertEqual(res.status_code, 200, res.data)
        sub = self._sub(sub_a)
        self.assertEqual(sub.status, "submitted", "S5 只标记，不拒答")
        self.assertTrue(sub.abnormal)
        self.assertIn("满分", sub.grade_raw["server"]["abnormal_reason"])

        lab_b = self._setup("非满分秒交实验")
        token_b, sub_b = self._start(lab_b)
        res = self._grade(token_b, {"total_score": "99.5", "elapsed_seconds": 1})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertFalse(self._sub(sub_b).abnormal)

    def test_grade_debug_dry_run_three_payloads(self):
        """在线调试：满分/零分/部分分三种模拟报文均通过，last_debug 正确、不产生真实提交。"""
        # 草稿态（未发布）也必须能 dry-run：Stage 4 的 UI 顺序是 创建 → 调试 → 发布
        draft_id = self._make_lab("草稿态调试实验")
        res = self._upload(draft_id)
        self.assertIn(res.status_code, (200, 201), res.data)
        res = self.tc.post(f"/api/labs/{draft_id}/grade-debug/", {
            "total_score": "86.5", "elapsed_seconds": 742,
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertTrue(res.data["data"]["passed"], "草稿态 dry-run 不应被发布状态拦下")
        # Stage 9：环境提示项已移除；页面静态健康检查为 blocking（草稿+已上传页面应全 PASS）
        names = {c["name"] for c in res.data["data"]["checks"]}
        self.assertNotIn("票据模拟", names)
        self.assertNotIn("发布状态", names)
        self.assertIn("成绩上报（LabBridge.reportGrade）", names)
        self.assertTrue(all(c["ok"] for c in res.data["data"]["checks"] if c["blocking"]),
                        "已上传页面的静态健康检查应全部通过")

        lab_id = self._setup()
        for score in ("100", "0", "86.5"):
            res = self.tc.post(f"/api/labs/{lab_id}/grade-debug/", {
                "total_score": score, "elapsed_seconds": 742,
            }, format="json")
            self.assertEqual(res.status_code, 200, res.data)
            payload = res.data["data"]
            self.assertTrue(payload["passed"], res.data)
            self.assertTrue(payload["dry_run"])
            self.assertIsNotNone(payload["preview"])
            self.assertEqual(payload["preview"]["grading_source"], "external")
            self.assertIn("未入库", res.data["message"])
            lab = Lab.objects.get(pk=lab_id)
            self.assertTrue(lab.last_debug["passed"])
            self.assertEqual(lab.last_debug["payload"]["total_score"], score)

        # 模拟失败报文 → 徽标变红，仍不入库
        res = self.tc.post(f"/api/labs/{lab_id}/grade-debug/", {
            "total_score": "101", "elapsed_seconds": 1,
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertFalse(res.data["data"]["passed"])
        self.assertTrue(any(not c["ok"] for c in res.data["data"]["checks"]))
        self.assertIsNone(res.data["data"]["preview"])
        self.assertFalse(Lab.objects.get(pk=lab_id).last_debug["passed"])

        self.assertFalse(LabSubmission.objects.filter(
            lab_id=lab_id, status=LabSubmission.Status.SUBMITTED
        ).exists())
        # C46：dry-run 只对教师开放，学生与平台管理员均不可调用
        for client in (self.sc, self.adc, self.gc):
            res = client.post(f"/api/labs/{lab_id}/grade-debug/", {
                "total_score": "86.5", "elapsed_seconds": 1,
            }, format="json")
            self.assertIn(res.status_code, (401, 403), res.data)

    def test_context_contract_has_four_fields_only(self):
        """C45：bridge-validate 的 context 只有四字段，绝不含票据。"""
        import json

        lab_id = self._setup()
        token, sub_id = self._start(lab_id)
        res = self.sc.get(f"/api/lab-submissions/bridge-validate/?token={token}")
        self.assertEqual(res.status_code, 200, res.data)
        ctx = res.data["data"]["context"]
        self.assertEqual(set(ctx), {"labId", "submissionId", "totalScore", "gradeEndpoint"})
        self.assertEqual(ctx["labId"], lab_id)
        self.assertEqual(ctx["submissionId"], sub_id)
        self.assertEqual(ctx["gradeEndpoint"], "/api/lab-gate/grade/")
        self.assertNotIn(token, json.dumps(ctx, ensure_ascii=False))


class LabGradeConcurrencyTest(TransactionTestCase):
    """S2 真实并发：两个线程同时用同一票据上报，只有一个成功、票据只消费一次。

    `TransactionTestCase` 不包外层事务，两个线程用各自 DB 连接真实抢行锁；
    普通 `TestCase` 的原子事务会让第二线程看不到数据，测不出并发。
    """

    HTML = b"<html><head><title>x</title></head><body>concurrency</body></html>"

    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.teacher = User.objects.create_user("t402", password="pass1234", role="teacher", real_name="并发老师")
        self.student = User.objects.create_user("20270003", password="pass1234", role="student", real_name="并发学生")
        self.course = Course.objects.create(name="并发课程", teacher=self.teacher)
        self.classroom = ClassRoom.objects.create(name="并发班", teacher=self.teacher)
        ClassCourse.objects.create(classroom=self.classroom, course=self.course)
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        self.tc = APIClient()
        self.tc.force_authenticate(self.teacher)
        self.sc = APIClient()
        self.sc.force_authenticate(self.student)

        res = self.tc.post("/api/labs/", {
            "page_source": "custom", "course": self.course.id, "title": "并发上报实验",
            "total_score": "100", "pass_score": "60",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.lab_id = res.data["data"]["id"]
        res = self.tc.post(f"/api/labs/{self.lab_id}/page/", {
            "file": SimpleUploadedFile("c.html", self.HTML, content_type="text/html"),
        }, format="multipart")
        self.assertIn(res.status_code, (200, 201), res.data)
        self.tc.post("/api/lab-schedules/", {"lab": self.lab_id, "classroom": self.classroom.id}, format="json")
        self.tc.post(f"/api/labs/{self.lab_id}/publish/", format="json")
        res = self.sc.post("/api/lab-submissions/start/", {"lab": self.lab_id}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.token = res.data["data"]["attempt_token"]
        self.sub_id = res.data["data"]["submission"]["id"]

    def tearDown(self):
        # TransactionTestCase 会 flush 表，磁盘上的上传文件需显式清理
        from apps.labs.models import LabPage

        for page in LabPage.objects.all():
            if page.file:
                page.file.delete(save=False)
        super().tearDown()

    def test_two_concurrent_reports_only_one_wins(self):
        import threading

        from apps.labs.models import LabAttemptToken, LabSubmission
        from django.db import connections

        barrier = threading.Barrier(2)
        results = {}

        def worker(idx):
            try:
                barrier.wait(timeout=15)
                client = APIClient()
                res = client.post("/api/lab-gate/grade/", {
                    "total_score": "86.5", "elapsed_seconds": 10,
                }, format="json", HTTP_X_LAB_TOKEN=self.token)
                results[idx] = (res.status_code, str(res.data))
            except Exception as exc:  # 线程内异常必须回收，不能静默丢
                results[idx] = ("EXC", repr(exc))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(i,)) for i in (0, 1)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertFalse(any(t.is_alive() for t in threads), "并发线程必须在超时内结束")
        self.assertEqual(len(results), 2, results)

        codes = sorted(v[0] for v in results.values())
        self.assertEqual(codes, [200, 400], f"S2：只能一个成功、一个被拒；实际 {results}")
        ticket = LabAttemptToken.objects.get(token=self.token)
        self.assertTrue(ticket.consumed, "S2：票据必须被消费")
        self.assertEqual(
            LabSubmission.objects.filter(pk=self.sub_id, status="submitted").count(), 1
        )
        sub = LabSubmission.objects.get(pk=self.sub_id)
        self.assertEqual(Decimal(str(sub.total_score)), Decimal("86.5"))


class LabExternalAnalyticsTest(TestCase):
    """C17/C18：章节画像与班级导出对 external 只出「总分 + 用时」，步骤指标标不适用。"""

    @classmethod
    def setUpTestData(cls):
        from django.utils import timezone

        cls.teacher = User.objects.create_user("t403", password="pass1234", role="teacher", real_name="统计老师")
        cls.student = User.objects.create_user("20270004", password="pass1234", role="student", real_name="统计学生")
        cls.course = Course.objects.create(name="统计课程", teacher=cls.teacher)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第5章", is_published=True)
        cls.classroom = ClassRoom.objects.create(name="统计班", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)
        template = LabTemplate.objects.create(code="st3-stat", title="ARP实验", default_standard_minutes=30)
        cls.tpl_lab = Lab.objects.create(
            template=template, course=cls.course, catalog=cls.catalog,
            title="预置步骤实验", status=Lab.Status.PUBLISHED, total_score=100,
        )
        cls.custom_lab = Lab.objects.create(
            page_source="custom", course=cls.course, catalog=cls.catalog,
            title="自定义上报实验", status=Lab.Status.PUBLISHED, total_score=100,
        )
        LabSchedule.objects.create(lab=cls.tpl_lab, classroom=cls.classroom)
        LabSchedule.objects.create(lab=cls.custom_lab, classroom=cls.classroom)
        now = timezone.now()
        LabSubmission.objects.create(
            lab=cls.tpl_lab, student=cls.student, status=LabSubmission.Status.SUBMITTED,
            total_score=88, passed_steps=4, total_steps=5, elapsed_seconds=1200,
            submitted_at=now, grading_source="steps",
        )
        LabSubmission.objects.create(
            lab=cls.custom_lab, student=cls.student, status=LabSubmission.Status.SUBMITTED,
            total_score=86.5, grading_source="external", elapsed_seconds=742,
            submitted_at=now, graded_at=now,
            score_breakdown={"total": 86.5, "source": "external", "elapsed_seconds": 742},
        )

    def test_chapter_profile_excludes_external_step_metrics(self):
        from apps.analytics.services import build_chapter_profile

        profile = build_chapter_profile(self.student, self.catalog, for_student=True)
        self.assertEqual(len(profile["labs"]), 2, profile["labs"])
        ext = next(x for x in profile["labs"] if x["title"] == "自定义上报实验")
        self.assertEqual(ext["total_score"], 86.5)
        self.assertEqual(ext["elapsed_seconds"], 742)
        self.assertIsNone(ext["passed_steps"], "C17：不得用 0/0 拉低步骤通过率")
        self.assertIsNone(ext["total_steps"])
        self.assertEqual(ext["grading_source"], "external")
        self.assertIn("不适用", ext["step_metrics"])
        tpl = next(x for x in profile["labs"] if x["title"] == "预置步骤实验")
        self.assertEqual(tpl["passed_steps"], 4, "C17：预置实验指标零回归")
        self.assertEqual(tpl["total_steps"], 5)
        self.assertIsNone(tpl["step_metrics"])

    def test_class_export_sheet4_marks_external_as_na(self):
        from apps.analytics.export import build_class_export_workbook

        wb = build_class_export_workbook(self.classroom, self.course, sections={"lab"})
        ws = wb["实验明细"]
        headers = [ws.cell(row=2, column=c).value for c in range(1, ws.max_column + 1)]
        rows = {}
        for r in range(3, ws.max_row + 1):
            rows[ws.cell(row=r, column=3).value] = {
                headers[c - 1]: ws.cell(row=r, column=c).value
                for c in range(1, ws.max_column + 1)
            }
        ext = rows["自定义上报实验"]
        self.assertEqual(ext["总分"], 86.5)
        self.assertIsNotNone(ext["用时(分钟)"])
        for col in ("基础分", "操作准确性", "完成效率", "完成度", "通过步骤", "总步骤"):
            self.assertEqual(ext[col], "不适用", f"C18：{col} 应标注不适用")
        tpl = rows["预置步骤实验"]
        self.assertEqual(tpl["通过步骤"], 4, "C18：预置实验列零回归")
        self.assertEqual(tpl["总步骤"], 5)
        self.assertNotEqual(tpl["基础分"], "不适用")


class LabIntegrationSpecTest(TestCase):
    """Stage 4：`GET /api/labs/{id}/integration-spec/` 动态接入说明（纯渲染）。"""

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user("t501", password="pass1234", role="teacher", real_name="许老师")
        cls.other_teacher = User.objects.create_user("t502", password="pass1234", role="teacher", real_name="何老师")
        cls.student = User.objects.create_user("20280001", password="pass1234", role="student", real_name="沈同学")
        cls.admin = User.objects.create_user("adm501", password="pass1234", role="admin", real_name="管理员")
        cls.course = Course.objects.create(name="计算机网络", teacher=cls.teacher)
        cls.other_course = Course.objects.create(name="操作系统", teacher=cls.other_teacher)

    def setUp(self):
        self.tc = APIClient()
        self.tc.force_authenticate(self.teacher)
        self.otc = APIClient()
        self.otc.force_authenticate(self.other_teacher)
        self.sc = APIClient()
        self.sc.force_authenticate(self.student)
        self.adc = APIClient()
        self.adc.force_authenticate(self.admin)
        self.anon = APIClient()

    def _make_lab(self, title="VLAN 配置实验", total_score="100", report_note=""):
        res = self.tc.post("/api/labs/", {
            "course": self.course.id, "title": title,
            "total_score": total_score, "pass_score": "60",
            "page_source": "custom", "report_note": report_note,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        return res.data["data"]["id"]

    def _spec(self, lab_id, client=None):
        return (client or self.tc).get(f"/api/labs/{lab_id}/integration-spec/")

    def test_dynamic_markdown_contains_all_required_sections(self):
        """§6.2：按实验名 / 总分 / 上报地址动态渲染，含 schema、错误码、最小 HTML、AI 指令。"""
        lab_id = self._make_lab(title="VLAN 与 Trunk 配置实验", total_score="85.5")
        res = self._spec(lab_id)
        self.assertEqual(res.status_code, 200, res.data)
        data = res.data["data"]
        md = data["markdown"]
        self.assertEqual(data["lab_title"], "VLAN 与 Trunk 配置实验")
        self.assertEqual(data["total_score"], "85.5")
        self.assertEqual(data["grade_endpoint"], "/api/lab-gate/grade/")
        self.assertEqual(data["grade_debug_endpoint"], f"/api/labs/{lab_id}/grade-debug/")
        self.assertNotIn("@@", md, "所有占位符必须被替换，不能把模板泄漏给教师/AI")
        for text in (
            "VLAN 与 Trunk 配置实验", "85.5", "/api/lab-gate/grade/",
            "## 1. 你的任务", "## 2. 与平台交互", "## 4. 可直接复制给 AI",
            "LabBridge.validate()", "LabBridge.reportGrade(", "ctx.totalScore",
            "同一学生多次提交只保留最高分",
            "本次实验已提交", "成绩超出实验总分范围", "实验票据已使用",
            "提交过于频繁",
        ):
            self.assertIn(text, md, f"接入说明缺少：{text}")
        # 调试端点与 AI 无关（教师在线调试由前端按钮自带 lab id），不应出现在说明里；
        # 响应字段 grade_debug_endpoint 仍保留（API 兼容）。
        self.assertNotIn("grade-debug", md)
        # 同源绝对地址由 request 预填，不是写死的内部 IP
        # Stage 11：说明里的上报地址一律相对路径（不写死域名/端口）
        self.assertIn("POST /api/lab-gate/grade/", md)
        self.assertNotIn("http://testserver", md)
        # Stage 6：教师补充说明功能下线，说明里不再出现该段
        self.assertNotIn("report_note", data, "补充说明字段不应再出现在接入说明响应中")
        self.assertNotIn("教师补充说明", md)

    def test_report_note_section_removed(self):
        """Stage 6：教师补充说明功能整体下线——创建时不入说明，旧存量数据也不回显。"""
        lab_id = self._make_lab()
        res = self._spec(lab_id).data["data"]
        self.assertNotIn("report_note", res)
        self.assertNotIn("（教师未填写补充说明）", res["markdown"])
        self.assertNotIn("## 8. 教师补充说明", res["markdown"])

    def test_permissions_teacher_only_and_row_level(self):
        """C46：显式 [IsTeacher]（不含 admin），行级归属由 get_queryset 保证。"""
        lab_id = self._make_lab()
        self.assertEqual(self._spec(lab_id, self.tc).status_code, 200)
        self.assertEqual(self._spec(lab_id, self.sc).status_code, 403, "学生不可读接入说明")
        self.assertEqual(self._spec(lab_id, self.adc).status_code, 403, "IsTeacher 不含 admin（C46）")
        self.assertEqual(self._spec(lab_id, self.otc).status_code, 404, "跨课程教师不可读他人实验")
        self.assertIn(self._spec(lab_id, self.anon).status_code, (401, 403))

    def test_pure_render_no_side_effects_and_draft_ok(self):
        """纯渲染：不写库、不产生提交、草稿态可用（Stage 4 UI 顺序 创建→说明→调试→发布）。"""
        from apps.labs.models import LabPage, LabSubmission

        lab_id = self._make_lab()
        lab = Lab.objects.get(pk=lab_id)
        self.assertEqual(lab.status, "draft")
        before = (lab.last_debug, lab.status, LabSubmission.objects.count(), LabPage.objects.count())
        first = self._spec(lab_id)
        second = self._spec(lab_id)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["data"]["markdown"], second.data["data"]["markdown"])
        lab.refresh_from_db()
        self.assertEqual(
            (lab.last_debug, lab.status, LabSubmission.objects.count(), LabPage.objects.count()),
            before, "接入说明必须是纯渲染，不得写库或产生提交",
        )

    def test_markdown_is_dynamic_per_lab(self):
        """两个实验的说明各自预填自己的名称与总分，不串参数。"""
        a = self._make_lab(title="实验甲", total_score="60")
        b = self._make_lab(title="实验乙", total_score="120")
        ma = self._spec(a).data["data"]["markdown"]
        mb = self._spec(b).data["data"]["markdown"]
        self.assertNotEqual(ma, mb)
        self.assertIn("实验甲", ma)
        self.assertNotIn("实验乙", ma)
        self.assertIn("0 ~ 60", ma)
        self.assertNotIn("0 ~ 120", ma)
        self.assertIn("实验乙", mb)
        self.assertIn("0 ~ 120", mb)

    def test_markdown_is_concise_and_scan_clean(self):
        """Stage 9 教师反馈：接入说明精简——无大段 schema/最小 HTML 代码块，保留桥接要点。"""
        import re

        lab_id = self._make_lab()
        md = self._spec(lab_id).data["data"]["markdown"]
        # 不再内嵌最小 HTML 代码块（避免复制给 AI 的内容冗余）
        self.assertEqual(re.findall(r"```html", md), [], "精简版说明不应再内嵌 ```html 代码块")
        # LabBridge 用法的 js 代码块仍保留（教师/AI 需要知道三个 API）
        self.assertIn("```js", md)
        self.assertIn("LabBridge.reportGrade(", md)
        # 体积约束：说明保持紧凑，不超过 8KB（Stage 9 原 6KB 上限放宽——
        # 2026-11-09 教师确认质量优先：保留完整命名纪律与交付自检清单）
        self.assertLess(len(md.encode("utf-8")), 8 * 1024, "接入说明应保持紧凑")

    def test_no_ticket_leaked_into_page_contract(self):
        """C25/C45：说明明确票据只在平台父页面，不下发 attempt token 给页面。"""
        lab_id = self._make_lab()
        md = self._spec(lab_id).data["data"]["markdown"]
        self.assertIn("平台父页面", md)
        self.assertIn("iframe 内页面不接触票据", md)
        self.assertNotIn("window.LabBridge.token", md)
        self.assertNotIn("attemptToken", md)
        # C40 的约束是「iframe 属性不得含 allow-same-origin」，说明文档里本就应
        # 明确写出「无 allow-same-origin」；这里断言沙箱属性串正确且没有被放宽。
        self.assertIn('sandbox="allow-scripts allow-forms allow-modals"', md)
        self.assertNotIn("allow-scripts allow-forms allow-modals allow-same-origin", md)



class LabBestScorePolicyTest(TestCase):
    """Stage 6 计分规则：首次提交的成绩即实验成绩，后续重做只保留历史最高分。

    低分重做不覆盖任何成绩字段（步骤明细/报文/用时），仅状态流转为 submitted。
    """

    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user("t501", password="pass1234", role="teacher", real_name="赵老师")
        cls.student = User.objects.create_user("20280001", password="pass1234", role="student", real_name="钱同学")
        cls.course = Course.objects.create(name="计算机网络", teacher=cls.teacher)
        cls.catalog = Catalog.objects.create(course=cls.course, title="第5章 计分规则", is_published=True)
        cls.classroom = ClassRoom.objects.create(name="网络2801", teacher=cls.teacher)
        ClassCourse.objects.create(classroom=cls.classroom, course=cls.course)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)
        cls.template = LabTemplate.objects.create(
            code="st6-arp", title="ARP实验", default_standard_minutes=30,
            random_config={"ranges": {"s1": [1, 9], "s2": [1, 9]}},
        )

    def setUp(self):
        self.tc = APIClient()
        self.tc.force_authenticate(self.teacher)
        self.sc = APIClient()
        self.sc.force_authenticate(self.student)

    HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
    <title>计分规则测试页</title></head><body><h1>自定义实验</h1>
    <script>window.__custom_lab__ = true;</script></body></html>""".encode("utf-8")

    def _make_lab(self, page_source="template"):
        payload = {
            "course": self.course.id, "catalog": self.catalog.id,
            "total_score": "100", "page_source": page_source,
        }
        if page_source == "template":
            payload["template"] = self.template.id
        res = self.tc.post("/api/labs/", payload, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        lab_id = res.data["data"]["id"]
        if page_source == "custom":
            from django.core.files.uploadedfile import SimpleUploadedFile

            res = self.tc.post(f"/api/labs/{lab_id}/page/", {
                "file": SimpleUploadedFile("best.html", self.HTML, content_type="text/html"),
            }, format="multipart")
            self.assertEqual(res.status_code, 200, res.data)
        res = self.tc.post("/api/lab-schedules/", {"lab": lab_id, "classroom": self.classroom.id}, format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        res = self.tc.post(f"/api/labs/{lab_id}/publish/", format="json")
        self.assertIn(res.status_code, (200, 201), res.data)
        return lab_id

    def _start(self, lab_id):
        res = self.sc.post("/api/lab-submissions/start/", {"lab": lab_id}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        data = res.data["data"]
        return data["attempt_token"], data["submission"]["id"]

    def _submit_template(self, lab_id, passes):
        token, sub_id = self._start(lab_id)
        steps = {str(i + 1): ("pass" if i < passes else "fail") for i in range(5)}
        res = self.sc.post(f"/api/lab-submissions/{sub_id}/submit/", {
            "attempt_token": token, "steps_result": steps,
            "error_log": [], "elapsed_seconds": 600,
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        return self.sc.get("/api/lab-submissions/", {"lab": lab_id}).data["data"]["results"][0]

    def _grade_external(self, lab_id, total):
        token, sub_id = self._start(lab_id)
        res = self.gc_normal().post(
            "/api/lab-gate/grade/", {"total_score": total, "elapsed_seconds": 300},
            format="json", HTTP_X_LAB_TOKEN=token,
        )
        self.assertEqual(res.status_code, 200, res.data)
        return self.sc.get("/api/lab-submissions/", {"lab": lab_id}).data["data"]["results"][0]

    def gc_normal(self):
        from rest_framework.test import APIClient as _C

        c = _C()
        return c

    def test_template_redo_keeps_history(self):
        """Stage 11 多轮记录：低分重做生成独立低分记录，第一次提交锁定不变。"""
        lab_id = self._make_lab("template")
        first = self._submit_template(lab_id, passes=5)   # 高分
        self.assertGreater(Decimal(str(first["total_score"])), Decimal("80"))
        second = self._submit_template(lab_id, passes=2)  # 低分重做
        self.assertEqual(second["attempt"], 2)
        self.assertEqual(second["status"], "submitted")
        self.assertLess(Decimal(str(second["total_score"])), Decimal(str(first["total_score"])),
                        "低分重做是独立的新一轮记录，分数如实保留")
        subs = self.sc.get("/api/lab-submissions/", {"lab": lab_id}).data["data"]["results"]
        self.assertEqual(len(subs), 2, "重做应保留历史：两轮记录并存")
        first_locked = sorted(subs, key=lambda s: s["attempt"])[0]
        self.assertEqual(Decimal(str(first_locked["total_score"])), Decimal(str(first["total_score"])),
                         "第一次提交的成绩锁定不变（教师端「实验成绩」列口径）")
        self.assertEqual(first_locked["submitted_at"], first["submitted_at"])

    def test_template_redo_updates_on_higher(self):
        lab_id = self._make_lab("template")
        first = self._submit_template(lab_id, passes=2)   # 低分
        second = self._submit_template(lab_id, passes=5)  # 高分重做
        self.assertGreater(Decimal(str(second["total_score"])), Decimal(str(first["total_score"])),
                           "高分重做应更新成绩")
        self.assertEqual(second["attempt"], 2)

    def test_external_redo_keeps_history(self):
        """Stage 11 多轮记录：三轮作答三条记录，第一次提交锁定、最高分可聚合。"""
        lab_id = self._make_lab("custom")
        s1 = self._grade_external(lab_id, 60)
        self.assertEqual(Decimal(str(s1["total_score"])), Decimal("60"))
        s2 = self._grade_external(lab_id, 90)
        self.assertEqual(Decimal(str(s2["total_score"])), Decimal("90"), "重做产生独立的新一轮记录")
        s3 = self._grade_external(lab_id, 50)
        self.assertEqual(Decimal(str(s3["total_score"])), Decimal("50"), "低分重做是独立的低分记录")
        self.assertEqual(s3["grading_source"], "external")
        self.assertIsNotNone(s3["submitted_at"])
        subs = self.sc.get("/api/lab-submissions/", {"lab": lab_id}).data["data"]["results"]
        self.assertEqual(len(subs), 3, "三轮作答三条记录，历史完整保留")
        first_locked = sorted(subs, key=lambda s: s["attempt"])[0]
        self.assertEqual(Decimal(str(first_locked["total_score"])), Decimal("60"), "第一次提交 60 分锁定")
        best = max(Decimal(str(s["total_score"])) for s in subs)
        self.assertEqual(best, Decimal("90"), "历史最高分 90 分可从记录聚合")
