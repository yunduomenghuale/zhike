"""把存量教学视频的逐页讲解稿批量入向量库（讲稿入检索体系的回填命令）。

背景：讲稿入库（ingest_video_scripts）随讲稿生成/编辑自动触发，但存量的
已生成讲稿需要一次性回填才能参与检索。本命令幂等——重复执行会按
「先算后删、事务内替换」重建各视频的讲稿片段，不产生重复。

用法：
    python manage.py ingest_scripts              # 回填全部已有讲稿的视频
    python manage.py ingest_scripts --course 7   # 只回填某课程

向量模型不可用（Mock/接口异常）时各视频静默返回 0 并记入失败清单；
单项失败不影响其他项，修复后可再次执行（幂等续跑）。
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "把存量教学视频的逐页讲解稿入向量库（幂等，可重复执行续跑）"

    def add_arguments(self, parser):
        parser.add_argument("--course", type=int, default=None, help="只回填指定课程")

    def handle(self, *args, **options):
        from apps.ai.services import ingest_video_scripts
        from apps.courses.models import TeachingVideo

        qs = TeachingVideo.objects.exclude(scripts=[]).select_related("ppt", "catalog")
        if options["course"]:
            qs = qs.filter(course_id=options["course"])
        videos = list(qs)
        if not videos:
            self.stdout.write(self.style.WARNING("没有需要回填的讲稿"))
            return

        ok, failed = 0, []
        for video in videos:
            count = ingest_video_scripts(video)
            if count:
                ok += 1
                self.stdout.write(f"  视频 {video.id}（章节 {video.catalog_id}）：{count} 页片段")
            else:
                failed.append(video.id)
        self.stdout.write(
            self.style.SUCCESS(f"回填完成：{ok}/{len(videos)} 部讲稿已入库")
        )
        if failed:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(failed)} 部未入库（向量模型不可用或讲稿为空）：视频 {failed}，"
                    "修复后重新执行本命令即可续跑"
                )
            )
