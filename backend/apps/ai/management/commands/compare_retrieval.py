"""双读比对：同一批 query、同一个查询向量，比较 json 与 qdrant 两套后端的 top-k。

用途有两个：
1. **切换前验收**：Qdrant 正常时两套结果应高度重合（同一批向量、同样的过滤），
   重合率不达标说明回填不完整（某批漏了）或过滤翻译不等价（payload 字段错）；
2. **上线后巡检**：`RAG_VECTOR_BACKEND` 切到 qdrant 后，定期跑一遍确认没漂移。

调用两个后端时**直接用同一个查询向量**（只 embed 一次），并且绕开重排——
重排会掩盖向量召回层的差异，比对就失去意义。

用法：
    python manage.py compare_retrieval --course 7 --queries-file qs.txt
    python manage.py compare_retrieval --course 7 --queries "第一章讲了什么;考核方式是什么"
    python manage.py compare_retrieval --course 7 --from-chunks 8      # 用片段原文自查对齐
    python manage.py compare_retrieval --course 7 --catalog 12 --top-k 15 --student
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

PASS_RATE = 0.95


def _cut_score(hits, top_k: int) -> float:
    """第 top_k 名的分数（不足 top_k 条时取最后一条；空结果取 -inf）。

    用作「同分容差」比较的门槛：以较低一方的第 k 名分数为界，两边都取分界以上
    的片段——并列组要么整组计入、要么整组不计入，与实现内部的排序顺序无关。
    """
    if not hits:
        return float("-inf")
    idx = min(top_k, len(hits)) - 1
    return float(hits[idx][1])


def compare_hits(json_hits, qdrant_hits, top_k: int) -> dict:
    """单条查询的比对结果（严格按 id + 同分容差门槛）。

    纯函数（只吃 (chunk, score) 列表），不碰网络与数据库，便于单测并列场景。
    """
    json_ids = [c.id for c, _ in json_hits]
    qdrant_ids = [c.id for c, _ in qdrant_hits]
    strict_overlap = len(set(json_ids[:top_k]) & set(qdrant_ids[:top_k]))
    band = min(_cut_score(json_hits, top_k), _cut_score(qdrant_hits, top_k))
    eps = 1e-6 * max(1.0, abs(band)) if band != float("-inf") else 0.0
    json_band = {c.id for c, s in json_hits if float(s) >= band - eps}
    qdrant_band = {c.id for c, s in qdrant_hits if float(s) >= band - eps}
    band_overlap = len(json_band & qdrant_band)
    band_base = max(len(json_band), len(qdrant_band), 1)
    # 两边都没有候选（如该课程章节未发布 → 学生池为空）：这不是「不重合」，
    # 而是这条查询什么都没验证。记 100% 并单独计数，避免把空结果判成不达标。
    empty = not json_band and not qdrant_band
    scores = {c.id: float(s) for c, s in json_hits}
    delta = [abs(float(s) - scores[c.id]) for c, s in qdrant_hits if c.id in scores]
    return {
        "json_ids": json_ids[:top_k],
        "qdrant_ids": qdrant_ids[:top_k],
        "strict_overlap": strict_overlap,
        "strict_rate": 1.0 if empty else round(strict_overlap / top_k, 4),
        "band": round(band, 6) if band != float("-inf") else None,
        "band_sizes": [len(json_band), len(qdrant_band)],
        "band_overlap": band_overlap,
        "overlap": band_overlap,
        "overlap_rate": 1.0 if empty else round(band_overlap / band_base, 4),
        "empty": empty,
        "only_json": sorted(json_band - qdrant_band),
        "only_qdrant": sorted(qdrant_band - json_band),
        "max_score_delta": round(max(delta), 6) if delta else 0.0,
    }


class Command(BaseCommand):
    help = "比对 json / qdrant 两套向量后端的 top-k 重合率（切换验收与漂移巡检）"

    def add_arguments(self, parser):
        parser.add_argument("--course", type=int, required=True, help="课程 ID")
        parser.add_argument("--catalog", type=int, default=0, help="章节 ID（候选池收敛到该章节，可选）")
        parser.add_argument("--student", action="store_true", help="按学生视角过滤（含发布状态/班级可见性）")
        parser.add_argument("--classroom", type=int, action="append", default=[], help="学生班级 ID（可重复）")
        parser.add_argument("--top-k", type=int, default=0, help="比对条数（默认取 AI_RERANK_RECALL=15）")
        parser.add_argument(
            "--tie-margin",
            type=int,
            default=50,
            help="同分容差比较时额外多取的条数（默认 50；用于兜住并列组）",
        )
        parser.add_argument("--queries", type=str, default="", help="分号分隔的查询串")
        parser.add_argument("--queries-file", type=str, default="", help="每行一个查询串的文本文件")
        parser.add_argument("--from-chunks", type=int, default=0, help="不提供查询时，随机取 N 个片段原文当查询")
        parser.add_argument("--out", type=str, default="", help="报告路径（默认 rag_reports/ 下按时间命名）")
        parser.add_argument("--json-out", type=str, default="", help="同时输出机器可读的 JSON（默认与 md 同名）")

    # ------------------------------------------------------------------ 查询集
    def _load_queries(self, options) -> list[str]:
        if options["queries_file"]:
            path = Path(options["queries_file"])
            if not path.exists():
                raise CommandError(f"查询文件不存在：{path}")
            lines = path.read_text(encoding="utf-8").splitlines()
            queries = [line.strip() for line in lines if line.strip()]
            if not queries:
                raise CommandError("查询文件为空")
            return queries

        if options["queries"].strip():
            return [q.strip() for q in options["queries"].split(";") if q.strip()]

        n = int(options["from_chunks"] or 0)
        if n > 0:
            from apps.knowledge.models import KnowledgeChunk

            chunks = (
                KnowledgeChunk.objects.filter(course_id=options["course"])
                .exclude(embedding=[])
                .order_by("?")[:n]
            )
            queries = [c.content.strip()[:500] for c in chunks if c.content.strip()]
            if not queries:
                raise CommandError("该课程没有可用片段，无法生成自查查询")
            return queries

        raise CommandError("请提供查询：--queries / --queries-file / --from-chunks 三选一")

    # ------------------------------------------------------------------ 主流程
    def handle(self, *args, **options):
        from apps.ai.providers.factory import get_provider
        from apps.ai.providers.mock import MockProvider
        from apps.ai.vector_backends import get_json_backend, get_qdrant_backend
        from apps.ai.vectorstore import ChunkFilter

        if (getattr(settings, "QDRANT_URL", "") or "").strip() == "":
            raise CommandError("QDRANT_URL 未配置：比对需要两套后端同时可用")
        if (getattr(settings, "RAG_VECTOR_BACKEND", "json") or "json").lower() != "qdrant":
            self.stdout.write(
                self.style.WARNING(
                    "当前 RAG_VECTOR_BACKEND 不是 qdrant：本命令直接调后端比对，"
                    "结果不受该开关影响（用于切换前验收）"
                )
            )

        provider = get_provider("embed")
        if isinstance(provider, MockProvider):
            raise CommandError(
                "向量模型为模拟模式（64 维假向量），比对无意义：请先在管理端配置真实向量模型"
            )

        queries = self._load_queries(options)
        top_k = int(options["top_k"] or 0) or int(getattr(settings, "AI_RERANK_RECALL", 15) or 15)
        tie_margin = max(int(options["tie_margin"] or 0), 0)
        flt = ChunkFilter.build(
            options["course"],
            catalog_id=options["catalog"] or None,
            student_access=options["student"],
            classroom_ids=options["classroom"],
        )
        json_be = get_json_backend()
        qdrant_be = get_qdrant_backend()
        qdrant_be.ensure_ready()

        rows = []
        # 同分并列（同一段文本被重复入库 → 向量完全相同 → 余弦完全相同）会让第 k 名
        # 的截断取决于实现内部的排序稳定性：json 与 qdrant 可能各自取到并列组里的
        # 不同成员，严格按 id 比就会「假不达标」。因此多取 margin 条，再用「第 k 名
        # 的分数」为门槛比较门槛以上的集合（并列组要么都进、要么都不进）。
        fetch_k = top_k + tie_margin
        for i, query in enumerate(queries, 1):
            self.stdout.write(f"[{i}/{len(queries)}] {query[:40]}")
            vec = provider.embed([query], allow_fallback=False)[0]
            try:
                json_hits = json_be.search(flt, vec, fetch_k)
            except Exception as exc:  # noqa: BLE001
                raise CommandError(f"json 后端检索失败：{exc}") from exc
            try:
                qdrant_hits = qdrant_be.search(flt, vec, fetch_k)
            except Exception as exc:  # noqa: BLE001
                raise CommandError(
                    f"qdrant 后端检索失败（集合/连接问题）：{exc}"
                ) from exc

            row = compare_hits(json_hits, qdrant_hits, top_k)
            row["query"] = query
            rows.append(row)

        rates = [r["overlap_rate"] for r in rows]
        strict_rates = [r["strict_rate"] for r in rows]
        avg = sum(rates) / len(rates)
        passed = sum(1 for r in rates if r >= PASS_RATE)
        strict_passed = sum(1 for r in strict_rates if r >= PASS_RATE)
        only_json_ids = sorted({i for r in rows for i in r["only_json"]})
        only_qdrant_ids = sorted({i for r in rows for i in r["only_qdrant"]})

        report = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "backend": "json vs qdrant",
            "collection": qdrant_be.collection,
            "vector_size": qdrant_be.vector_size,
            "filter": flt.describe(),
            "top_k": top_k,
            "queries": len(rows),
            "summary": {
                "avg_overlap_rate": round(avg, 4),
                "min_overlap_rate": round(min(rates), 4),
                "pass_at_95": f"{passed}/{len(rows)}",
                "pass": passed == len(rows),
                "avg_strict_rate": round(sum(strict_rates) / len(strict_rates), 4),
                "strict_pass_at_95": f"{strict_passed}/{len(rows)}",
                "tie_affected_queries": sum(
                    1 for r in rows if r["strict_rate"] < r["overlap_rate"]
                ),
                # 两边都没候选的查询（学生池为空等）：没验证任何东西，单独计数
                "empty_queries": sum(1 for r in rows if r.get("empty")),
                "only_json_ids": only_json_ids,
                "only_qdrant_ids": only_qdrant_ids,
                "max_score_delta": round(max(r["max_score_delta"] for r in rows), 6),
            },
            "rows": rows,
        }

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path(options["out"]) if options["out"] else (
            Path(settings.BASE_DIR) / "rag_reports" / f"compare_retrieval_{stamp}.md"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self._render_markdown(report), encoding="utf-8")
        json_out = Path(options["json_out"]) if options["json_out"] else out.with_suffix(".json")
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        self.stdout.write(
            f"同分容差重合率 {avg:.1%}（最低 {min(rates):.1%}，≥{PASS_RATE:.0%}: {passed}/{len(rows)}）"
            f" · 严格 top{top_k} 重合率 {sum(strict_rates)/len(strict_rates):.1%}"
            f"（≥{PASS_RATE:.0%}: {strict_passed}/{len(rows)}，"
            f"其中 {report['summary']['tie_affected_queries']} 个查询受同分并列影响）"
        )
        if only_json_ids:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(only_json_ids)} 个片段只在 json 侧命中（疑似未回填）："
                    f"{only_json_ids[:10]}"
                )
            )
        if only_qdrant_ids:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(only_qdrant_ids)} 个片段只在 qdrant 侧命中（疑似 payload 过期/已删除）："
                    f"{only_qdrant_ids[:10]}"
                )
            )
        self.stdout.write(self.style.SUCCESS(f"报告已写入：{out}"))
        self.stdout.write(f"机器可读：{json_out}")
        if passed != len(rows):
            raise CommandError(f"{len(rows) - passed} 个查询重合率低于 {PASS_RATE:.0%}")

    # ------------------------------------------------------------------ 报告
    def _render_markdown(self, report: dict) -> str:
        s = report["summary"]
        flt = report["filter"]
        lines = [
            "# 向量后端双读比对报告（json vs qdrant）",
            "",
            f"- 生成时间：{report['generated_at']}",
            f"- 集合：`{report['collection']}`（size={report['vector_size']}, Cosine）",
            f"- 过滤：course_id={flt['course_id']} · catalog_id={flt['catalog_id']} · "
            f"student_access={flt['student_access']} · classroom_ids={flt['classroom_ids']} · "
            f"include_script={flt['include_script']}",
            f"- 比对条数：top_k={report['top_k']} · 查询数 {report['queries']}",
            "",
            "## 汇总",
            "",
            f"- 平均重合率（同分容差）：**{s['avg_overlap_rate']:.2%}**",
            f"- 最低重合率（同分容差）：{s['min_overlap_rate']:.2%}",
            f"- 达标（≥95%，同分容差）：{s['pass_at_95']} → {'通过' if s['pass'] else '不通过'}",
            f"- 严格 top-k 重合率：平均 {s['avg_strict_rate']:.2%}，"
            f"达标 {s['strict_pass_at_95']}，受并列影响 {s['tie_affected_queries']} 个查询",
            f"- 两边均无候选的查询（未验证任何差异）：{s.get('empty_queries', 0)} 个",
            f"- 同片段分数最大偏差：{s['max_score_delta']}（原样搬运应仅浮点误差）",
            f"- 仅 json 命中（疑似未回填）：{len(s['only_json_ids'])} 个 {s['only_json_ids'][:20]}",
            f"- 仅 qdrant 命中（疑似 payload 过期）：{len(s['only_qdrant_ids'])} 个 {s['only_qdrant_ids'][:20]}",
            "",
            "> 同分容差：以两边第 k 名中较低的那个分数为门槛比较「门槛以上集合」。"
            "同一段文本被重复入库时两套后端的分数完全相同，严格按 id 比会因内部排序"
            "稳定性差异出现假不达标；门槛比较让并列组整组计入或整组排除。",
            "",
            "## 明细",
            "",
            "| # | 查询 | 门槛分 | 容差集(json/qdrant) | 容差重合 | 容差重合率 | 严格重合率 | 仅 JSON | 仅 Qdrant |",
            "|---|------|--------|--------------------|---------|-----------|-----------|---------|-----------|",
        ]
        for idx, row in enumerate(report["rows"], 1):
            query = row["query"].replace("|", "｜")[:30]
            sizes = row.get("band_sizes") or [0, 0]
            lines.append(
                f"| {idx} | {query} | {row.get('band', 0)} | {sizes[0]}/{sizes[1]} | "
                f"{row['overlap']} | {row['overlap_rate']:.1%} | {row.get('strict_rate', 0):.1%} | "
                f"{len(row['only_json'])} | {len(row['only_qdrant'])} |"
            )
        lines.append("")
        return "\n".join(lines)
