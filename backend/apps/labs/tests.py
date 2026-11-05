"""labs 一期冒烟测试：模板库 → 建实验 → 排课发布 → start/bridge → 提交评分 → 复核/重置 → 统计。"""
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
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
        for leaked in ("random_seed", "expected", "res.data.status"):
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
