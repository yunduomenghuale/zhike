"""labs 一期冒烟测试：模板库 → 建实验 → 排课发布 → start/bridge → 提交评分 → 复核/重置 → 统计。"""
from decimal import Decimal

from django.test import TestCase
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
