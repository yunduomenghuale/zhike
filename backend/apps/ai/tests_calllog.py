"""AI 调用埋点（apps/ai/calllog.py）测试。

覆盖：
- record_ai_call 成功/失败两条路径（失败原样上抛 + 错误摘要落库）
- record_stream 流式记录（惰性计时、输出字符累计、is_mock 标记）
- ai_scene / scene_decorator 场景上下文（同场景复用 trace_id，生成器函数兼容）
- suppress_recording 嵌套抑制（真实调用回退 Mock 不双记）
- copy_call_context / run_in_context 线程池上下文传递
- 采样（AI_CALL_LOG_SAMPLE：成功调用可采样，失败调用永远记录）
- Mock Provider 端到端：chat/chat_stream/embed/tts 均落库且 is_mock=True
- 写库失败不影响主业务
- 清理命令 cleanup_ai_call_logs
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.ai.calllog import (
    ai_scene,
    copy_call_context,
    record_ai_call,
    record_stream,
    run_in_context,
    scene_decorator,
    set_current_user,
    suppress_recording,
)
from apps.ai.models import AICallLog
from apps.ai.providers.mock import MockProvider
from apps.courses.models import Course

User = get_user_model()


class RecordAiCallTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username="t_log", password="x", role="teacher")
        self.course = Course.objects.create(name="测试课程", teacher=self.teacher)

    def test_success_records_scene_trace_and_usage(self):
        with ai_scene("qa", course_id=self.course.id):
            with record_ai_call("chat", "deepseek", "deepseek-chat", input_text="你好") as rec:
                rec.set_usage({"prompt_tokens": 10, "completion_tokens": 5})
                rec.set_output("你好，很高兴帮助你")
        log = AICallLog.objects.get()
        self.assertTrue(log.success)
        self.assertEqual(log.capability, "chat")
        self.assertEqual(log.provider, "deepseek")
        self.assertEqual(log.scene, "qa")
        self.assertEqual(log.course_id, self.course.id)
        self.assertTrue(log.trace_id)
        self.assertEqual(log.prompt_tokens, 10)
        self.assertEqual(log.completion_tokens, 5)
        self.assertEqual(log.total_tokens, 15)
        self.assertEqual(log.output_chars, len("你好，很高兴帮助你"))
        self.assertFalse(log.is_mock)

    def test_failure_records_error_and_reraises(self):
        with self.assertRaises(ValueError):
            with ai_scene("script_gen"):
                with record_ai_call("chat", "deepseek", "m", input_text="x"):
                    raise ValueError("upstream 500")
        log = AICallLog.objects.get()
        self.assertFalse(log.success)
        self.assertEqual(log.error, "upstream 500")

    def test_input_digest_and_preview_truncation(self):
        long_text = "甲" * 500
        with record_ai_call("embed", "tongyi", "m", input_text=long_text):
            pass
        log = AICallLog.objects.get()
        self.assertEqual(log.input_chars, 500)
        self.assertEqual(len(log.input_preview), 200)
        self.assertEqual(len(log.input_digest), 64)

    def test_item_count_for_local_models(self):
        with record_ai_call("embed", "local", "bge-m3", item_count=7):
            pass
        log = AICallLog.objects.get()
        self.assertEqual(log.item_count, 7)
        self.assertIsNone(log.total_tokens)

    def test_write_failure_does_not_break_business(self):
        with patch("apps.ai.models.AICallLog.objects.create", side_effect=Exception("db down")):
            # 埋点写库失败只记日志，不影响调用方
            with record_ai_call("chat", "mock", "mock", input_text="x") as rec:
                rec.set_output("ok")
        self.assertEqual(AICallLog.objects.count(), 0)


class RecordStreamTests(TestCase):
    def test_stream_accumulates_output_and_marks_mock(self):
        def gen():
            yield "第一段"
            yield "第二段"

        pieces = list(record_stream("chat", "mock", "mock", gen(), input_text="问题", is_mock=True))
        self.assertEqual(pieces, ["第一段", "第二段"])
        log = AICallLog.objects.get()
        self.assertTrue(log.success)
        self.assertTrue(log.is_mock)
        self.assertEqual(log.output_chars, len("第一段第二段"))

    def test_stream_failure_records_and_reraises(self):
        def gen():
            yield "前半段"
            raise RuntimeError("连接中断")

        with self.assertRaises(RuntimeError):
            list(record_stream("chat", "deepseek", "m", gen(), input_text="问题"))
        log = AICallLog.objects.get()
        self.assertFalse(log.success)
        self.assertEqual(log.error, "连接中断")

    def test_stream_state_mock_fallback(self):
        state = {"mock": False}

        def gen():
            yield "内容"
            state["mock"] = True  # 迭代中发生回退

        list(record_stream("chat", "deepseek", "m", gen(), input_text="问题", state=state))
        log = AICallLog.objects.get()
        self.assertTrue(log.is_mock)


class SceneContextTests(TestCase):
    def test_same_scene_reuses_trace_id(self):
        with ai_scene("script_gen") as outer:
            trace = outer["trace_id"]
            with ai_scene("script_gen") as inner:
                self.assertEqual(inner["trace_id"], trace)
            with ai_scene("qa") as other:
                self.assertNotEqual(other["trace_id"], trace)

    def test_decorator_on_regular_function(self):
        teacher = User.objects.create_user(username="t_dec", password="x", role="teacher")
        course = Course.objects.create(name="装饰器课程", teacher=teacher)

        @scene_decorator("qa", course_getter=lambda args, kwargs: args[0])
        def knowledge_qa(course_id):
            with record_ai_call("chat", "deepseek", "m", input_text="问题"):
                pass
            return "ok"

        self.assertEqual(knowledge_qa(course.id), "ok")
        log = AICallLog.objects.get()
        self.assertEqual(log.scene, "qa")
        self.assertEqual(log.course_id, course.id)

    def test_decorator_on_generator_function(self):
        @scene_decorator("script_gen")
        def generate_pages():
            for _ in range(2):
                with record_ai_call("chat", "deepseek", "m", input_text="页"):
                    pass
                yield "done"

        self.assertEqual(list(generate_pages()), ["done", "done"])
        logs = AICallLog.objects.order_by("id")
        self.assertEqual(logs.count(), 2)
        self.assertTrue(all(log.scene == "script_gen" for log in logs))
        self.assertEqual(logs[0].trace_id, logs[1].trace_id)

    def test_triggered_by_resolution_priority(self):
        user = User.objects.create_user(username="u1", password="x")
        set_current_user(user)
        with record_ai_call("chat", "mock", "mock"):
            pass
        log = AICallLog.objects.get()
        self.assertEqual(log.triggered_by_id, user.id)
        set_current_user(None)

    def test_thread_pool_context_inheritance(self):
        # 白盒验证：线程池任务经 copy_call_context/run_in_context 恢复场景上下文。
        # 不断言 DB——TestCase 的原子事务对工作线程的独立连接不可见（生产为
        # autocommit 无此限制），上下文传播才是本机制的核心。
        from apps.ai.calllog import _scene_ctx

        captured = {}
        with ai_scene("vector_rebuild", course_id=3) as scene:
            trace = scene["trace_id"]
            ctx = copy_call_context()

            def task():
                captured["scene"] = _scene_ctx.get()

            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(run_in_context, ctx, task).result()
        self.assertEqual(captured["scene"]["scene"], "vector_rebuild")
        self.assertEqual(captured["scene"]["course_id"], 3)
        self.assertEqual(captured["scene"]["trace_id"], trace)


class SuppressRecordingTests(TestCase):
    def test_nested_suppression_skips_inner_record(self):
        # 模拟「真实调用失败回退 Mock」：外层记录一条（mark_mock），内层被抑制
        with suppress_recording():
            with record_ai_call("chat", "mock", "mock", input_text="x"):
                pass
        self.assertEqual(AICallLog.objects.count(), 0)

    def test_outer_record_still_flushed_with_mock_flag(self):
        with record_ai_call("chat", "deepseek", "m", input_text="x") as rec:
            rec.mark_mock()  # 回退 Mock 后由外层统一标记
            with suppress_recording():
                with record_ai_call("chat", "mock", "mock", input_text="x"):
                    pass
        logs = AICallLog.objects.all()
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs[0].provider, "deepseek")
        self.assertTrue(logs[0].is_mock)


class SamplingTests(TestCase):
    @override_settings(AI_CALL_LOG_SAMPLE={"qa": 0.0})
    def test_sampled_scene_skips_success_but_keeps_failure(self):
        with ai_scene("qa"):
            with record_ai_call("chat", "deepseek", "m", input_text="x"):
                pass  # 成功：命中 0% 采样，不记录
        self.assertEqual(AICallLog.objects.count(), 0)
        with ai_scene("qa"):
            with self.assertRaises(RuntimeError):
                with record_ai_call("chat", "deepseek", "m", input_text="x"):
                    raise RuntimeError("boom")  # 失败：永远记录
        self.assertEqual(AICallLog.objects.count(), 1)
        self.assertFalse(AICallLog.objects.first().success)


class MockProviderEndToEndTests(TestCase):
    def setUp(self):
        self.provider = MockProvider()

    def test_chat_records_mock_log(self):
        self.provider.chat([{"role": "user", "content": "你好"}])
        log = AICallLog.objects.get()
        self.assertTrue(log.is_mock)
        self.assertTrue(log.success)
        self.assertEqual(log.capability, "chat")

    def test_chat_stream_records_mock_log(self):
        pieces = list(self.provider.chat_stream([{"role": "user", "content": "你好"}]))
        self.assertTrue(pieces)
        log = AICallLog.objects.get()
        self.assertTrue(log.is_mock)
        self.assertGreater(log.output_chars, 0)

    def test_embed_records_item_count(self):
        vectors = self.provider.embed(["文本一", "文本二"])
        log = AICallLog.objects.get()
        self.assertTrue(log.is_mock)
        self.assertEqual(log.capability, "embed")
        self.assertEqual(log.item_count, 2)
        self.assertEqual(len(vectors), 2)

    def test_tts_records_mock_log(self):
        self.provider.tts("需要配音的文本")
        log = AICallLog.objects.get()
        self.assertTrue(log.is_mock)
        self.assertEqual(log.capability, "tts")


class CleanupCommandTests(TestCase):
    def test_cleanup_deletes_expired_only(self):
        now = timezone.now()
        old = AICallLog.objects.create(capability="chat", provider="mock", model_name="m")
        fresh = AICallLog.objects.create(capability="chat", provider="mock", model_name="m")
        AICallLog.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=100))

        out = StringIO()
        call_command("cleanup_ai_call_logs", "--days", "90", stdout=out)
        self.assertIn("已删除 1 条", out.getvalue())
        self.assertEqual(AICallLog.objects.count(), 1)
        self.assertEqual(AICallLog.objects.first().pk, fresh.pk)

    def test_dry_run_keeps_data(self):
        old = AICallLog.objects.create(capability="chat", provider="mock", model_name="m")
        AICallLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=100))
        out = StringIO()
        call_command("cleanup_ai_call_logs", "--days", "90", "--dry-run", stdout=out)
        self.assertIn("将删除 1 条", out.getvalue())
        self.assertEqual(AICallLog.objects.count(), 1)
