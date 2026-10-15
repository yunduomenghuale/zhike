"""下载系统内置本地模型权重（向量化 BGE-M3 / 重排序 Qwen3-Reranker-0.6B）。

用途：
- 部署预热：镜像构建（PRELOAD_MODELS=true）或容器启动后手动执行，避免首次请求时
  惰性下载阻塞（BGE-M3 约 2.3GB、Qwen3-Reranker 约 1.2GB，视网络数分钟）；
- 幂等：已下载（目录含 config.json）自动跳过；失败退出码非 0，可重跑续传。

用法：
  python manage.py download_models            # 全部
  python manage.py download_models --embed    # 仅向量化
  python manage.py download_models --rerank   # 仅重排序
  python manage.py download_models --check    # 只报告就绪状态，不下载
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.ai.local_models import default_model, ensure_downloaded, is_downloaded, model_path


class Command(BaseCommand):
    help = "下载系统内置本地模型权重（ModelScope），供 local 服务商的向量/重排序使用"

    def add_arguments(self, parser):
        parser.add_argument("--embed", action="store_true", help="仅下载向量化模型")
        parser.add_argument("--rerank", action="store_true", help="仅下载重排序模型")
        parser.add_argument("--check", action="store_true", help="只报告就绪状态，不下载")

    def handle(self, *args, **options):
        kinds = ["embed", "rerank"]
        if options["embed"] or options["rerank"]:
            kinds = [k for k in kinds if options[k]]
        self.stdout.write(f"模型目录：{settings.AI_MODELS_DIR}")

        failed = []
        for kind in kinds:
            name = default_model(kind)
            path = model_path(name)
            if is_downloaded(name):
                self.stdout.write(self.style.SUCCESS(f"[{kind}] 已就绪：{name} → {path}"))
                continue
            if options["check"]:
                self.stdout.write(self.style.WARNING(f"[{kind}] 未下载：{name}"))
                failed.append(kind)
                continue
            self.stdout.write(f"[{kind}] 开始下载 {name} …")
            try:
                ensure_downloaded(name)
            except Exception as exc:  # noqa: BLE001 - 单项失败不阻断其余下载
                self.stdout.write(self.style.ERROR(f"[{kind}] 下载失败：{exc}"))
                failed.append(kind)
                continue
            self.stdout.write(self.style.SUCCESS(f"[{kind}] 下载完成：{path}"))

        if failed:
            if options["check"]:
                raise CommandError(f"未就绪：{'、'.join(failed)}")
            raise CommandError(f"部分模型下载失败（{'、'.join(failed)}），修复后可重跑本命令续传")
        self.stdout.write(self.style.SUCCESS("全部模型就绪" if not options["check"] else "全部模型已就绪"))
