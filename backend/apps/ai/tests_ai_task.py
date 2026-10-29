"""AITask 异步任务框架 + 班级学情分析流水线测试（P1d）。

覆盖（对齐设计方案 §8 回归重点）：
- 任务状态机（pending → running → success/failed）；
- 替身 Provider 全流程（三段报告 + 学生简评 + no_data 名单）；
- 线程上下文埋点（F3：AICallLog.triggered_by / trace_id 非空）；
- 频率限制（F6：10 分钟 1 次，上次失败允许立即重试）；
- 任务可见性 4 条规则（F7）；
- 无数据学生标记与排除（D6）；
- 空数据班级跳过全部 LLM 调用（F5）；
- 分段/分批失败降级（degraded，报告仍完整）；
- Mock 确定性产物全流程。
"""
import json
import re
import time
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient
from unittest.mock import patch

from apps.courses.models import Catalog, Course, TeachingVideo
from apps.classroom.models import ClassRoom, ClassStudent
from apps.questions.models import AnswerRecord, Question

from apps.ai.models import AICallLog, AITask
from apps.ai.providers.base import BaseAIProvider
from apps.ai.providers.mock import MockProvider
from apps.ai.tasks import submit_ai_task

User = get_user_model()


class _InlineThread:
    """测试替身：同步执行线程目标（替代 daemon 线程）。

    测试库是内存 shared-cache SQLite：表级锁不做 busy 重试，daemon 线程与
    主线程并发读写同一张表（ai_aitask）会随机 SQLITE_LOCKED——真实文件库
    有 busy handler 不受影响（本地冒烟已覆盖真线程全路径）。同步执行后
    状态机/埋点/限流断言完全确定性；copy_call_context / run_in_context /
    信号量 / close_old_connections 等机制原样执行，未被绕过。
    """

    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)

    def join(self, timeout=None):
        return


class _FakeThreading:
    """仅替换 apps.ai.tasks 命名空间里的 threading（不影响全局模块）。"""

    Thread = _InlineThread


class _ScriptedProvider(BaseAIProvider):
    """按 prompt 关键词返回确定性 JSON 的测试替身（经 record_ai_call 埋点）。"""

    name = "stub"

    def chat(self, messages, **kwargs):
        from apps.ai.calllog import record_ai_call

        with record_ai_call("chat", self.name, "stub-model", input_text=messages) as rec:
            text = self._script(messages)
            rec.set_output(text)
            return text

    def _script(self, messages):
        content = messages[-1]["content"] if messages else ""
        if "本章学习数据" in content:
            return json.dumps(
                {
                    "overview": "本章完成了视频学习与章节练习，整体节奏正常。",
                    "knowledge_points": [
                        {"name": "递归", "status": "weak", "evidence": "练习 1/2 错"}
                    ],
                    "weak_points": ["递归终止条件判断不熟练"],
                    "highlights": ["练习完成率 100%"],
                    "qa_insight": "",
                    "suggestions": ["重看第 1 页讲解并重练递归习题"],
                    "next_step": "先重练本章错题再进入下一章。",
                },
                ensure_ascii=False,
            )
        if "学习简评" in content:
            ids = re.findall(r'"student_id": (\d+)', content)
            return json.dumps(
                [{"student_id": int(i), "comment": f"简评-{i}"} for i in ids],
                ensure_ascii=False,
            )
        if "整体学情" in content:
            return json.dumps({"overview": "OVERVIEW", "knowledge": "KNOWLEDGE"}, ensure_ascii=False)
        if "学生分层" in content:
            return json.dumps({"layers": "LAYERS", "warnings": "WARNINGS"}, ensure_ascii=False)
        if "教学干预建议" in content:
            return json.dumps({"advice": "ADVICE"}, ensure_ascii=False)
        return "{}"

    def embed(self, texts):
        raise NotImplementedError


class _FailingProvider(_ScriptedProvider):
    """全部调用直接抛错的替身（验证降级路径）。"""

    name = "stub-fail"

    def chat(self, messages, **kwargs):
        raise RuntimeError("stub boom")


class AnalyticsTaskTests(TransactionTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username="t_task", password="pw123456!", role=User.Role.TEACHER
        )
        self.other_teacher = User.objects.create_user(
            username="t_task2", password="pw123456!", role=User.Role.TEACHER
        )
        self.admin = User.objects.create_user(
            username="adm_task", password="pw123456!", role=User.Role.ADMIN
        )
        self.student_a = User.objects.create_user(
            username="s_task_a", password="pw123456!", role=User.Role.STUDENT
        )
        self.student_b = User.objects.create_user(
            username="s_task_b", password="pw123456!", role=User.Role.STUDENT
        )
        self.course = Course.objects.create(name="任务课程", teacher=self.teacher)
        self.classroom = ClassRoom.objects.create(name="任务班级", teacher=self.teacher)
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
        # student_a：一错一对（有数据）；student_b：无任何记录
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
        # daemon 线程改同步执行（见 _InlineThread 说明）
        thread_patcher = patch("apps.ai.tasks.threading", _FakeThreading)
        thread_patcher.start()
        self.addCleanup(thread_patcher.stop)

    # -- 工具 -------------------------------------------------------------
    def _wait(self, task_id, timeout=45):
        task = AITask.objects.get(id=task_id)
        for _ in range(timeout):
            task.refresh_from_db()
            if task.status in (AITask.Status.SUCCESS, AITask.Status.FAILED):
                return task
            time.sleep(1)
        return task

    def _patch_provider(self, provider):
        """patch 分析流水线的 Provider 并保活到测试结束。

        daemon 线程异步执行：with 块会在 submit 返回后即退出，线程随后才调
        get_provider——必须 start/addCleanup 拉长 patch 生命周期。
        """
        patcher = patch("apps.ai.analytics_ai.get_provider", return_value=provider)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _submit(self, provider):
        self._patch_provider(provider)
        task = submit_ai_task(
            AITask.TaskType.CLASS_ANALYTICS,
            user=self.teacher,
            classroom=self.classroom,
            course=self.course,
        )
        return self._wait(task.id)

    # -- 用例 -------------------------------------------------------------
    def test_submit_returns_pending_task(self):
        self._patch_provider(_ScriptedProvider())
        task = submit_ai_task(
            AITask.TaskType.CLASS_ANALYTICS,
            user=self.teacher,
            classroom=self.classroom,
            course=self.course,
        )
        self.assertEqual(task.status, AITask.Status.PENDING)
        self.assertEqual(task.version, 1)
        self.assertEqual(task.triggered_by, self.teacher)
        self._wait(task.id)

    def test_pipeline_success_with_scripted_provider(self):
        task = self._submit(_ScriptedProvider())
        self.assertEqual(task.status, AITask.Status.SUCCESS, task.error)
        result = task.result
        # 三段报告合并
        for token in ("OVERVIEW", "KNOWLEDGE", "LAYERS", "WARNINGS", "ADVICE"):
            self.assertIn(token, result["report"])
        self.assertEqual(result["report_sections"]["overview"], "OVERVIEW")
        # 仅覆盖有数据学生；无数据学生只进名单
        # result 经 JSONField 往返，字典键为字符串（前端 JS 取值不受影响）
        self.assertEqual(
            result["comments"], {str(self.student_a.id): f"简评-{self.student_a.id}"}
        )
        self.assertEqual(
            [s["student_id"] for s in result["no_data_students"]], [self.student_b.id]
        )
        self.assertFalse(result["degraded"])
        self.assertEqual(result["failed_comment_count"], 0)
        self.assertEqual(task.progress["stage"], "done")
        self.assertIsNotNone(task.finished_at)

    def test_thread_context_records_triggered_by(self):
        """F3：daemon 线程经 copy_call_context 恢复上下文，埋点不丢触发人。"""
        client = APIClient()
        client.force_authenticate(user=self.teacher)
        self._patch_provider(_ScriptedProvider())
        resp = client.post(f"/api/analytics/class/{self.classroom.id}/ai-report/")
        self.assertEqual(resp.status_code, 200, resp.data)
        task = self._wait(resp.data["data"]["task_id"])
        self.assertEqual(task.status, AITask.Status.SUCCESS, task.error)
        logs = AICallLog.objects.filter(scene=AICallLog.Scene.ANALYTICS)
        self.assertTrue(logs.exists(), "流水线应有埋点流水")
        self.assertTrue(all(log.triggered_by_id == self.teacher.id for log in logs))
        self.assertTrue(all(log.trace_id for log in logs))
        self.assertTrue(all(log.course_id == self.course.id for log in logs))

    def test_rate_limit_blocks_duplicate(self):
        """F6：同班级 10 分钟 1 次；上一次 FAILED 允许立即重试。"""
        client = APIClient()
        client.force_authenticate(user=self.teacher)
        self._patch_provider(_ScriptedProvider())
        first = client.post(f"/api/analytics/class/{self.classroom.id}/ai-report/")
        self.assertEqual(first.status_code, 200, first.data)
        second = client.post(f"/api/analytics/class/{self.classroom.id}/ai-report/")
        self.assertEqual(second.status_code, 429, second.data)
        # 把在跑/已完成的任务标记为失败 → 允许立即重试
        AITask.objects.filter(
            task_type=AITask.TaskType.CLASS_ANALYTICS, classroom=self.classroom
        ).update(status=AITask.Status.FAILED)
        third = client.post(f"/api/analytics/class/{self.classroom.id}/ai-report/")
        self.assertEqual(third.status_code, 200, third.data)
        self._wait(third.data["data"]["task_id"])

    def test_task_visibility_rules(self):
        """F7：4 条可见性规则，否则 404。"""
        class_task = AITask.objects.create(
            task_type=AITask.TaskType.CLASS_ANALYTICS,
            classroom=self.classroom,
            course=self.course,
            triggered_by=self.other_teacher,
            status=AITask.Status.SUCCESS,
        )
        chapter_task = AITask.objects.create(
            task_type=AITask.TaskType.CHAPTER_SUMMARY,
            classroom=self.classroom,
            course=self.course,
            catalog=self.catalog,
            student=self.student_a,
            triggered_by=self.student_a,
            status=AITask.Status.SUCCESS,
        )
        client = APIClient()

        client.force_authenticate(user=self.other_teacher)  # 发起人本人
        self.assertEqual(client.get(f"/api/ai-tasks/{class_task.id}/").status_code, 200)

        client.force_authenticate(user=self.teacher)  # 班级归属教师
        self.assertEqual(client.get(f"/api/ai-tasks/{class_task.id}/").status_code, 200)

        client.force_authenticate(user=self.student_a)  # 与班级分析无关的学生
        self.assertEqual(client.get(f"/api/ai-tasks/{class_task.id}/").status_code, 404)
        self.assertEqual(client.get(f"/api/ai-tasks/{chapter_task.id}/").status_code, 200)

        client.force_authenticate(user=self.student_b)  # 非总结对象学生
        self.assertEqual(client.get(f"/api/ai-tasks/{chapter_task.id}/").status_code, 404)

        client.force_authenticate(user=self.admin)  # 平台管理员
        self.assertEqual(client.get(f"/api/ai-tasks/{class_task.id}/").status_code, 200)
        self.assertEqual(client.get(f"/api/ai-tasks/{chapter_task.id}/").status_code, 200)

        self.assertEqual(client.get("/api/ai-tasks/999999/").status_code, 404)

    def test_no_data_class_skips_all_calls(self):
        """F5：全班无数据 → 跳过全部 LLM 调用，固定文案直接 SUCCESS。"""
        from apps.classroom.services import transfer_students

        empty = ClassRoom.objects.create(name="无数据班级", teacher=self.teacher)
        empty.courses.add(self.course)
        # 单班约束：student_b 已在 setUp 的班级里，要把他挪过来必须走转班（旧关系置 transferred），
        # 不能直接再 create 一条占用关系。
        transfer_students(empty, [self.student_b], operator=self.teacher)
        self._patch_provider(_ScriptedProvider())
        task = submit_ai_task(
            AITask.TaskType.CLASS_ANALYTICS,
            user=self.teacher,
            classroom=empty,
            course=self.course,
        )
        task = self._wait(task.id)
        self.assertEqual(task.status, AITask.Status.SUCCESS, task.error)
        self.assertIn("暂无学习数据", task.result["report"])
        self.assertEqual(
            [s["student_id"] for s in task.result["no_data_students"]], [self.student_b.id]
        )
        self.assertEqual(task.result["comments"], {})
        self.assertFalse(
            AICallLog.objects.filter(scene=AICallLog.Scene.ANALYTICS).exists(),
            "全班无数据不应产生任何 LLM 调用",
        )

    def test_degrade_when_provider_fails(self):
        """单段/单批全部失败：降级拼装，status 仍 SUCCESS 且 degraded。"""
        task = self._submit(_FailingProvider())
        self.assertEqual(task.status, AITask.Status.SUCCESS, task.error)
        self.assertTrue(task.result["degraded"])
        self.assertIn("本班共", task.result["report"])  # 降级拼装文案
        self.assertEqual(task.result["comments"], {})
        self.assertEqual(task.result["failed_comment_count"], 1)

    def test_mock_provider_deterministic_output(self):
        """Mock provider：确定性假数据，无 Key 环境可演示全流程。"""
        task = self._submit(MockProvider())
        self.assertEqual(task.status, AITask.Status.SUCCESS, task.error)
        self.assertIn("【模拟数据】", task.result["report"])
        self.assertIn(str(self.student_a.id), task.result["comments"])
        self.assertEqual(
            [s["student_id"] for s in task.result["no_data_students"]], [self.student_b.id]
        )


class ChapterSummaryTaskTests(TransactionTestCase):
    """章节学习总结任务测试（P2，设计 §4.1/§4.4）。

    覆盖：提交幂等（pending/success 复用）/ force 版本递进与 5 分钟限频 /
    FAILED 允许立即重提 / report_progress 完成自动触发 / 越权课程 404 /
    GET 无记录返回 null / Mock 确定性 / 失败降级 degraded。
    """

    def setUp(self):
        self.teacher = User.objects.create_user(
            username="t_sum", password="pw123456!", role=User.Role.TEACHER
        )
        self.student = User.objects.create_user(
            username="s_sum", password="pw123456!", role=User.Role.STUDENT
        )
        self.outsider = User.objects.create_user(
            username="s_out", password="pw123456!", role=User.Role.STUDENT
        )
        self.course = Course.objects.create(name="总结课程", teacher=self.teacher)
        self.other_course = Course.objects.create(name="校外课程", teacher=self.teacher)
        self.classroom = ClassRoom.objects.create(name="总结班级", teacher=self.teacher)
        self.classroom.courses.add(self.course)
        ClassStudent.objects.create(classroom=self.classroom, student=self.student)
        self.catalog = Catalog.objects.create(
            course=self.course, title="第一章", order=1, is_published=True
        )
        self.other_catalog = Catalog.objects.create(
            course=self.other_course, title="别课章节", order=1, is_published=True
        )
        self.video = TeachingVideo.objects.create(
            course=self.course, catalog=self.catalog, is_published=True
        )
        # daemon 线程改同步执行（见 _InlineThread 说明）
        thread_patcher = patch("apps.ai.tasks.threading", _FakeThreading)
        thread_patcher.start()
        self.addCleanup(thread_patcher.stop)

    # -- 工具 -------------------------------------------------------------
    def _wait(self, task_id, timeout=45):
        task = AITask.objects.get(id=task_id)
        for _ in range(timeout):
            task.refresh_from_db()
            if task.status in (AITask.Status.SUCCESS, AITask.Status.FAILED):
                return task
            time.sleep(1)
        return task

    def _patch_provider(self, provider):
        patcher = patch("apps.ai.analytics_ai.get_provider", return_value=provider)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, client, *, force=None, catalog_id=None, course_id=None):
        body = {
            "course_id": course_id if course_id is not None else self.course.id,
            "catalog_id": catalog_id if catalog_id is not None else self.catalog.id,
        }
        if force is not None:
            body["force"] = force
        return client.post("/api/analytics/chapter-summaries/", body, format="json")

    def _latest(self):
        return (
            AITask.objects.filter(
                task_type=AITask.TaskType.CHAPTER_SUMMARY,
                student=self.student,
                catalog=self.catalog,
            )
            .order_by("-version", "-id")
            .first()
        )

    # -- 用例 -------------------------------------------------------------
    def test_submit_returns_pending_and_completes(self):
        client = APIClient()
        client.force_authenticate(user=self.student)
        self._patch_provider(_ScriptedProvider())
        resp = self._post(client)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(resp.data["data"]["cached"])
        task = self._wait(resp.data["data"]["task_id"])
        self.assertEqual(task.status, AITask.Status.SUCCESS, task.error)
        self.assertEqual(task.version, 1)
        self.assertEqual(task.progress["stage"], "done")
        result = task.result
        for key in ("overview", "knowledge_points", "weak_points", "highlights",
                    "suggestions", "next_step"):
            self.assertIn(key, result)
        self.assertEqual(result["knowledge_points"][0]["name"], "递归")
        self.assertEqual(result["knowledge_points"][0]["status"], "weak")
        self.assertFalse(result["degraded"])
        self.assertIn("profile_snapshot", result)

    def test_duplicate_submit_reuses_task(self):
        """幂等：已有 SUCCESS 记录 → 跳过，返回旧任务（cached=True）。"""
        client = APIClient()
        client.force_authenticate(user=self.student)
        self._patch_provider(_ScriptedProvider())
        first = self._post(client)
        first_task = self._wait(first.data["data"]["task_id"])
        second = self._post(client)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertTrue(second.data["data"]["cached"])
        self.assertEqual(second.data["data"]["task_id"], first_task.id)
        self.assertEqual(AITask.objects.filter(
            task_type=AITask.TaskType.CHAPTER_SUMMARY, student=self.student
        ).count(), 1)

    def test_force_creates_new_version(self):
        """force=True → 新建一版（version 递进）；限频按 created_at 判 5 分钟。"""
        client = APIClient()
        client.force_authenticate(user=self.student)
        self._patch_provider(_ScriptedProvider())
        first = self._wait(self._post(client).data["data"]["task_id"])
        # 回溯 created_at 绕限频（模拟 5 分钟前的旧版本）
        AITask.objects.filter(id=first.id).update(
            created_at=timezone.now() - timedelta(minutes=10)
        )
        second = self._post(client, force="1")
        self.assertEqual(second.status_code, 200, second.data)
        self.assertFalse(second.data["data"]["cached"])
        task = self._wait(second.data["data"]["task_id"])
        self.assertEqual(task.status, AITask.Status.SUCCESS, task.error)
        self.assertEqual(task.version, 2)

    def test_force_rate_limited_within_5_minutes(self):
        """D8：force 限频 5 分钟 1 次 → 429。"""
        client = APIClient()
        client.force_authenticate(user=self.student)
        self._patch_provider(_ScriptedProvider())
        self._wait(self._post(client).data["data"]["task_id"])
        resp = self._post(client, force="1")
        self.assertEqual(resp.status_code, 429, resp.data)

    def test_failed_task_allows_immediate_resubmit(self):
        """上一次 FAILED → 允许立即重提（不消耗 force 限频）。"""
        client = APIClient()
        client.force_authenticate(user=self.student)
        self._patch_provider(_ScriptedProvider())
        first = self._wait(self._post(client).data["data"]["task_id"])
        AITask.objects.filter(id=first.id).update(status=AITask.Status.FAILED)
        resp = self._post(client)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(resp.data["data"]["cached"])
        task = self._wait(resp.data["data"]["task_id"])
        self.assertEqual(task.version, 2)
        self.assertEqual(task.status, AITask.Status.SUCCESS, task.error)

    def test_report_progress_auto_trigger(self):
        """视频学完自动触发章节总结；重复上报幂等（summary_task_id=null）。"""
        client = APIClient()
        client.force_authenticate(user=self.student)
        self._patch_provider(_ScriptedProvider())
        resp = client.post(
            f"/api/videos/{self.video.id}/report-progress/",
            {"last_page": 0, "completed": "1", "page_count": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        task_id = resp.data["data"].get("summary_task_id")
        self.assertIsNotNone(task_id, "学完章节应自动提交总结任务")
        task = self._wait(task_id)
        self.assertEqual(task.status, AITask.Status.SUCCESS, task.error)
        # 再次上报完成：已有 SUCCESS → 不重复提交
        again = client.post(
            f"/api/videos/{self.video.id}/report-progress/",
            {"last_page": 0, "completed": "1", "page_count": 1},
            format="json",
        )
        self.assertEqual(again.status_code, 200, again.data)
        self.assertIsNone(again.data["data"].get("summary_task_id"))

    def test_post_unauthorized_course_404(self):
        """越权：总结未选修课程的章节 → 404。"""
        client = APIClient()
        client.force_authenticate(user=self.outsider)
        self._patch_provider(_ScriptedProvider())
        resp = self._post(client)
        self.assertEqual(resp.status_code, 404, resp.data)

    def test_get_without_record_returns_null(self):
        """无记录：GET 返回 summary=null（不报错，前端不弹错误 toast）。"""
        client = APIClient()
        client.force_authenticate(user=self.student)
        resp = client.get(
            "/api/analytics/chapter-summaries/",
            {"course_id": self.course.id, "catalog_id": self.catalog.id},
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIsNone(resp.data["data"]["summary"])

    def test_get_returns_latest_success(self):
        client = APIClient()
        client.force_authenticate(user=self.student)
        self._patch_provider(_ScriptedProvider())
        self._wait(self._post(client).data["data"]["task_id"])
        resp = client.get(
            "/api/analytics/chapter-summaries/",
            {"course_id": self.course.id, "catalog_id": self.catalog.id},
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        summary = resp.data["data"]["summary"]
        self.assertIsNotNone(summary)
        self.assertEqual(summary["version"], 1)
        self.assertFalse(summary["degraded"])
        self.assertEqual(summary["result"]["knowledge_points"][0]["name"], "递归")

    def test_mock_provider_deterministic(self):
        """Mock provider：确定性假总结（【模拟数据】前缀）。"""
        client = APIClient()
        client.force_authenticate(user=self.student)
        self._patch_provider(MockProvider())
        resp = self._post(client)
        task = self._wait(resp.data["data"]["task_id"])
        self.assertEqual(task.status, AITask.Status.SUCCESS, task.error)
        self.assertTrue(task.result["overview"].startswith("【模拟数据】"))
        self.assertTrue(
            all(s.startswith("【模拟数据】") for s in task.result["suggestions"])
        )

    def test_fallback_when_provider_fails(self):
        """LLM 两次均失败 → 统计拼装降级，status 仍 SUCCESS 且 degraded。"""
        client = APIClient()
        client.force_authenticate(user=self.student)
        self._patch_provider(_FailingProvider())
        resp = self._post(client)
        task = self._wait(resp.data["data"]["task_id"])
        self.assertEqual(task.status, AITask.Status.SUCCESS, task.error)
        self.assertTrue(task.result["degraded"])
        self.assertIn("（本节由统计数据自动生成）", task.result["overview"])
