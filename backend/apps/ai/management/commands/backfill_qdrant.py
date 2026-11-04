"""把 MySQL 里的存量片段向量原样搬运进 Qdrant（不重算 embedding）。

为什么必须「原样搬运」：
- 成本：重算 = 对全站片段再调一次 embedding API（按 token 计费）；
- 一致性：同一文本两次嵌入会有极微小差异，双读比对时会把「同一个片段
  在两套后端分数略有不同」误判成 bug；原样搬运则两套后端的分数只有浮点
  误差，重合率校验才有意义。

断点续跑：按主键 keyset 分页（``id > last_id ORDER BY id``），每批成功写入后
把 ``last_id`` 落到 checkpoint 文件。中断重跑从 checkpoint 继续，已写过的
不重复写（upsert 本身也幂等，双保险）；checkpoint 丢失时全量重跑也不会产生
重复点或丢数据（ID = chunk_id）。

用法：
    python manage.py backfill_qdrant                     # 全量（自动续跑）
    python manage.py backfill_qdrant --course 7          # 只补某课程
    python manage.py backfill_qdrant --reset             # 删集合重建后全量
    python manage.py backfill_qdrant --dry-run           # 只体检不写
    python manage.py backfill_qdrant --no-resume         # 忽略 checkpoint 从头跑
    python manage.py backfill_qdrant --batch-size 1000 --timeout 60
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

CHECKPOINT_NAME = "qdrant-backfill-state.json"
_RELATIONS = (
    "material",
    "material__catalog",
    "ppt",
    "ppt__catalog",
    "video",
    "video__catalog",
)


class Command(BaseCommand):
    help = "把存量知识库片段向量搬运进 Qdrant（不重算 embedding，支持断点续跑）"

    def add_arguments(self, parser):
        parser.add_argument("--course", type=int, default=None, help="只回填指定课程")
        parser.add_argument("--batch-size", type=int, default=1000, help="每批读取条数（默认 1000）")
        parser.add_argument("--start-after", type=int, default=0, help="从该 chunk_id 之后开始（覆盖 checkpoint）")
        parser.add_argument("--reset", action="store_true", help="删除集合并重建（清空后全量重填）")
        parser.add_argument("--no-resume", action="store_true", help="忽略 checkpoint，从头发车")
        parser.add_argument("--no-checkpoint", action="store_true", help="不写 checkpoint 文件（调试用）")
        parser.add_argument("--checkpoint", type=str, default="", help="checkpoint 文件路径（默认 data/qdrant-backfill-state.json）")
        parser.add_argument("--dry-run", action="store_true", help="只读库校验，不写 Qdrant")
        parser.add_argument("--timeout", type=int, default=60, help="Qdrant 客户端超时秒数（回填放宽，默认 60）")

    # ------------------------------------------------------------------ 工具
    def _checkpoint_path(self) -> Path:
        configured = getattr(self, "_checkpoint_override", "")
        if configured:
            return Path(configured)
        return Path(settings.BASE_DIR) / "data" / CHECKPOINT_NAME

    def _read_checkpoint(self, scope: str) -> int:
        path = self._checkpoint_path()
        if not path.exists():
            return 0
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        if state.get("scope") != scope:
            return 0
        try:
            return int(state.get("last_id") or 0)
        except (TypeError, ValueError):
            return 0

    def _write_checkpoint(self, scope: str, last_id: int, written: int) -> None:
        path = self._checkpoint_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "scope": scope,
                    "last_id": int(last_id),
                    "written": int(written),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _clear_checkpoint(self) -> None:
        path = self._checkpoint_path()
        if path.exists():
            path.unlink()

    # ------------------------------------------------------------------ 主流程
    def handle(self, *args, **options):
        from apps.ai.vector_backends import get_qdrant_backend
        from apps.knowledge.models import KnowledgeChunk

        course_id = options["course"]
        batch_size = max(int(options["batch_size"] or 1000), 1)
        scope = f"course:{course_id}" if course_id else "all"
        dry_run = options["dry_run"]
        self._checkpoint_override = options.get("checkpoint") or ""

        if options["timeout"]:
            # 客户端按配置构造，命令侧放宽超时（批量写入比在线检索慢得多）
            settings.QDRANT_TIMEOUT = int(options["timeout"])

        configured = (getattr(settings, "RAG_VECTOR_BACKEND", "json") or "json").lower()
        if configured != "qdrant":
            self.stdout.write(
                self.style.WARNING(
                    f"当前 RAG_VECTOR_BACKEND={configured}（未启用 Qdrant 检索）："
                    "本命令只负责把数据搬进去，切换仍需改配置并重启 worker/backend"
                )
            )

        backend = get_qdrant_backend()
        if options["reset"]:
            backend.drop_collection()
            self._clear_checkpoint()
            self.stdout.write(self.style.WARNING(f"已删除集合 {backend.collection}"))
        backend.ensure_ready()
        self.stdout.write(
            f"目标集合：{backend.collection}（size={backend.vector_size}, distance=Cosine）"
            f" · 地址 {getattr(settings, 'QDRANT_URL', '') or '未配置'}"
        )

        # 先建 queryset 再数：course 过滤在 SQL 层做，避免「过滤后空页就退出」的坑
        base = KnowledgeChunk.objects.exclude(embedding=[])
        if course_id:
            base = base.filter(course_id=course_id)
        expected = base.count()

        start_after = int(options["start_after"] or 0)
        if not start_after and not options["no_resume"]:
            start_after = self._read_checkpoint(scope)
            if start_after:
                self.stdout.write(
                    self.style.WARNING(f"检测到断点：从 chunk_id > {start_after} 续跑")
                )
        self.stdout.write(f"范围 {scope}：待搬运 {expected} 个片段")

        read = written = skipped = 0
        last_id = start_after
        started = time.monotonic()
        # keyset 分页：不用 offset（大表深翻页越跑越慢，且中途插入会错位）
        while True:
            page = list(
                base.filter(id__gt=last_id).order_by("id").select_related(*_RELATIONS)[:batch_size]
            )
            if not page:
                break
            read += len(page)
            last_id = page[-1].id
            valid = [c for c in page if len(c.embedding or []) == backend.vector_size]
            skipped += len(page) - len(valid)
            if not dry_run and valid:
                written += backend.upsert(valid)
            if not options["no_checkpoint"] and not dry_run:
                self._write_checkpoint(scope, last_id, written)
            self.stdout.write(
                f"  id<={last_id} 读取 {read}/{expected} · 写入 {written}"
                + (f" · 维度不符跳过 {skipped}" if skipped else "")
            )

        elapsed = time.monotonic() - started
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"[dry-run] 读取 {read} 条，可写入 {read - skipped} 条，"
                    f"维度不符 {skipped} 条；未写入 Qdrant"
                )
            )
            return
        if not options["no_checkpoint"]:
            self._clear_checkpoint()
        points = backend.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"回填完成：读取 {read} · 写入 {written} · 跳过 {skipped} · "
                f"耗时 {elapsed:.1f}s · 集合当前点数 {points}"
            )
        )
        if skipped:
            self.stdout.write(
                self.style.WARNING(
                    f"{skipped} 条片段向量维度不是 {backend.vector_size}，未写入："
                    "多为历史 Mock 64 维假向量，需用 rebuild_vectors 重新生成后再回填"
                )
            )
            raise CommandError(f"{skipped} 条片段维度不符，未写入 Qdrant")
