"""RAGAS 知识库问答质量评估（需求第 7.2 节 RAG 的质量度量）。

用法：
    python manage.py eval_rag --course 1 --n 10                 # 从知识库片段自动生成测试问题
    python manage.py eval_rag --course 1 --from-records --n 20  # 用真实学生提问
    python manage.py eval_rag --course 1 --questions-file qs.json

裁判模型默认 Kimi（Moonshot OpenAI 兼容接口），在 .env 配置：
    KIMI_API_KEY / KIMI_BASE_URL / KIMI_MODEL
answer_relevancy 指标需要 embedding，复用通义 TONGYI_EMBED_MODEL（Moonshot 无 embedding 接口）。

指标（均不需要人工标注答案）：
    faithfulness        回答是否被检索上下文支撑（防幻觉）
    answer_relevancy    回答是否切题（防跑题）
    context_precision   检索回来的片段里相关的占比（检索质量）
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "用 RAGAS 评估课程知识库问答（RAG）质量"

    def add_arguments(self, parser):
        parser.add_argument("--course", type=int, required=True, help="课程 ID")
        parser.add_argument("--n", type=int, default=10, help="测试问题数量（默认 10）")
        parser.add_argument(
            "--from-records",
            action="store_true",
            help="从问答记录 QARecord 中取真实学生提问（不自动生成）",
        )
        parser.add_argument(
            "--questions-file",
            type=str,
            default="",
            help="JSON 文件：[\"问题1\", ...] 或 [{\"question\": \"...\"}, ...]",
        )
        parser.add_argument("--top-k", type=int, default=5, help="检索片段数（与线上一致，默认 5）")
        parser.add_argument("--out", type=str, default="", help="报告输出路径（默认 eval_reports/ 下按时间命名）")

    # ------------------------------------------------------------------ 问题来源
    def _load_questions(self, course_id: int, options) -> list[str]:
        from apps.knowledge.models import KnowledgeChunk, QARecord

        n = options["n"]
        if options["questions_file"]:
            data = json.loads(Path(options["questions_file"]).read_text(encoding="utf-8"))
            questions = [q["question"] if isinstance(q, dict) else str(q) for q in data]
            return [q.strip() for q in questions if str(q).strip()][:n]

        if options["from_records"]:
            qs = (
                QARecord.objects.filter(course_id=course_id)
                .order_by("-created_at")
                .values_list("question", flat=True)[: n * 3]
            )
            seen, questions = set(), []
            for q in qs:
                q = q.strip()
                if q and q not in seen:
                    seen.add(q)
                    questions.append(q)
                if len(questions) >= n:
                    break
            if not questions:
                raise CommandError("该课程暂无问答记录，去掉 --from-records 改用自动生成")
            return questions

        # 从知识库片段自动生成
        from apps.ai.services import get_provider

        chunks = list(KnowledgeChunk.objects.filter(course_id=course_id).order_by("?")[:n])
        if not chunks:
            raise CommandError("该课程知识库为空，请先上传教辅资料并入库")
        provider = get_provider()
        questions = []
        for chunk in chunks:
            prompt = (
                "你是一名学生。请根据以下课程资料片段，提出一个该片段能够回答的、"
                "学生会真实问出的问题。只输出问题本身，不要编号、不要解释。\n\n"
                f"资料片段：\n{chunk.content[:1500]}"
            )
            try:
                q = provider.chat([{"role": "user", "content": prompt}]).strip().splitlines()[0]
                q = q.strip().lstrip("0123456789.、）) ")
                if q:
                    questions.append(q)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"生成问题失败，跳过该片段：{exc}"))
        if not questions:
            raise CommandError("问题生成全部失败，请检查业务大模型配置")
        return questions

    # ------------------------------------------------------------------ 跑问答，收集样本
    def _collect_samples(self, course_id: int, questions: list[str], top_k: int):
        from apps.ai.services import get_provider, knowledge_qa
        from apps.ai.vectorstore import search_chunks

        provider = get_provider()
        samples = []
        for i, question in enumerate(questions, 1):
            self.stdout.write(f"[{i}/{len(questions)}] {question[:40]}")
            # 检索：与线上 _gather_course_context 的知识库检索部分保持一致
            contexts: list[str] = []
            try:
                query_vec = provider.embed([question])[0]
                contexts = [c.content for c, score in search_chunks(course_id, query_vec, top_k=top_k) if score > 0]
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"  检索失败：{exc}"))
            # 生成：直接调线上同一条问答链路
            try:
                answer, _cited = knowledge_qa(course_id=course_id, question=question)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"  问答失败，跳过：{exc}"))
                continue
            samples.append({"question": question, "answer": answer, "contexts": contexts})
        return samples

    # ------------------------------------------------------------------ RAGAS 评估
    def _evaluate(self, samples):
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings

        class KimiChatOpenAI(ChatOpenAI):
            """Kimi k3 目前只允许 temperature=1；ragas 会按指标传入其它值，这里强制覆盖。"""

            def _get_request_payload(self, input_, *, stop=None, **kwargs):
                kwargs["temperature"] = 1
                return super()._get_request_payload(input_, stop=stop, **kwargs)

        try:
            from ragas.metrics.collections import (
                Faithfulness,
                LLMContextPrecisionWithoutReference,
                ResponseRelevancy,
            )
        except ImportError:  # ragas < 0.4 的导入路径
            from ragas.metrics import (
                Faithfulness,
                LLMContextPrecisionWithoutReference,
                ResponseRelevancy,
            )
        from ragas import EvaluationDataset, evaluate
        from ragas.dataset_schema import SingleTurnSample
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper

        api_key = os.environ.get("KIMI_API_KEY", "")
        if not api_key:
            raise CommandError("未配置 KIMI_API_KEY，请在 backend/.env 中填入 Moonshot 的 API Key")
        judge_llm = LangchainLLMWrapper(
            KimiChatOpenAI(
                model=os.environ.get("KIMI_MODEL", "kimi-k3"),
                api_key=api_key,
                base_url=os.environ.get("KIMI_BASE_URL", "https://api.moonshot.cn/v1"),
                timeout=120,
                max_retries=2,
            )
        )
        judge_embeddings = LangchainEmbeddingsWrapper(
            OpenAIEmbeddings(
                model=os.environ.get("TONGYI_EMBED_MODEL", "text-embedding-v4"),
                api_key=os.environ.get("TONGYI_API_KEY", ""),
                base_url=os.environ.get("TONGYI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                chunk_size=10,  # DashScope 单次 embedding 请求条数上限
                check_embedding_ctx_length=False,  # DashScope 只接受原文，langchain 默认会转成 token 数组
                timeout=60,
            )
        )

        dataset = EvaluationDataset(
            samples=[
                SingleTurnSample(
                    user_input=s["question"], response=s["answer"], retrieved_contexts=s["contexts"]
                )
                for s in samples
            ]
        )
        metrics = [Faithfulness(), ResponseRelevancy(), LLMContextPrecisionWithoutReference()]
        return evaluate(dataset=dataset, metrics=metrics, llm=judge_llm, embeddings=judge_embeddings)

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        from apps.ai.services import get_provider
        from apps.knowledge.models import KnowledgeChunk

        course_id = options["course"]
        if not KnowledgeChunk.objects.filter(course_id=course_id).exists():
            raise CommandError(f"课程 {course_id} 知识库为空，无法评估")
        provider_name = type(get_provider()).__name__
        if "mock" in provider_name.lower():
            self.stdout.write(self.style.WARNING("当前 AI_PROVIDER=mock，检索与回答均为假数据，评估结果无意义！"))

        questions = self._load_questions(course_id, options)
        self.stdout.write(f"共 {len(questions)} 个测试问题，开始跑问答链路…")
        samples = self._collect_samples(course_id, questions, options["top_k"])
        if not samples:
            raise CommandError("没有成功采集到任何问答样本")
        if len(samples) < 5:
            self.stdout.write(self.style.WARNING("有效样本少于 5 条，结果仅适合链路调试，不代表整体 RAG 质量"))

        self.stdout.write(f"采集到 {len(samples)} 条样本，调用 Kimi 裁判评估中…")
        result = self._evaluate(samples)
        df = result.to_pandas()

        # 控制台输出
        metric_cols = [c for c in df.columns if c not in ("user_input", "response", "retrieved_contexts")]
        if not metric_cols:
            raise CommandError("RAGAS 未返回任何评估指标，请检查版本和裁判模型配置")
        failed_metrics = {
            column: int(df[column].isna().sum())
            for column in metric_cols
            if df[column].isna().any()
        }
        if failed_metrics:
            details = "、".join(f"{name} 缺失 {count} 条" for name, count in failed_metrics.items())
            raise CommandError(
                f"RAGAS 评估未产生有效完整分数（{details}），未写入误导性报告；"
                "请检查裁判模型输出、Embedding 配置和服务日志"
            )
        self.stdout.write("\n===== 逐条结果 =====")
        for _, row in df.iterrows():
            scores = "  ".join(f"{c}={row[c]:.3f}" for c in metric_cols)
            self.stdout.write(f"Q: {str(row['user_input'])[:36]}…  {scores}")
        self.stdout.write(self.style.SUCCESS("\n===== 平均分 ====="))
        means = {}
        for c in metric_cols:
            means[c] = round(float(df[c].mean()), 4)
            self.stdout.write(self.style.SUCCESS(f"{c}: {means[c]:.4f}"))

        # 落盘报告
        out = options["out"] or str(
            Path(settings.BASE_DIR) / "eval_reports" / f"ragas_{datetime.now():%Y%m%d_%H%M%S}.json"
        )
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(
            json.dumps(
                {
                    "course_id": course_id,
                    "judge_model": os.environ.get("KIMI_MODEL", "kimi-k3"),
                    "sample_count": len(samples),
                    "means": means,
                    "samples": df.to_dict(orient="records"),
                },
                ensure_ascii=False,
                indent=2,
                default=str,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        self.stdout.write(self.style.SUCCESS(f"报告已保存：{out}"))
