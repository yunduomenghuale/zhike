"""重建知识库向量（换向量模型 / 修复 mock 向量后必须执行）。

为什么必须做：向量模型更换后，新旧向量空间不兼容——cosine 维度不符时
静默返回 0.0（不报错但检索全沉底）；同维度更隐蔽（不报错也不生效）。

覆盖教辅资料与课件 PPT（课件是向量库的主要内容，每页一个片段）。

用法：
    python manage.py rebuild_vectors --course 1            # 只重建某课程（资料+课件）
    python manage.py rebuild_vectors --material 12         # 只重建某份资料（续跑失败项）
    python manage.py rebuild_vectors --ppt 5               # 只重建某部课件（续跑失败项）
    python manage.py rebuild_vectors --all                 # 全站重建（资料+当前启用课件）

出错处理：事前校验（向量模型不可用）失败即止、不动数据；单项失败
记录原因并继续，退出码非 0，修复后按 --material / --ppt 续跑即可。
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "用当前向量模型重建知识库片段向量（资料+课件；换模型/修复 mock 向量后必须执行）"

    def add_arguments(self, parser):
        parser.add_argument("--course", type=int, default=None, help="只重建指定课程的资料与当前启用课件")
        parser.add_argument("--material", type=int, default=None, help="只重建指定资料（续跑失败项）")
        parser.add_argument("--ppt", type=int, default=None, help="只重建指定课件（续跑失败项）")
        parser.add_argument("--all", action="store_true", help="重建全部资料与当前启用课件")

    def handle(self, *args, **options):
        from apps.courses.models import PPTResource
        from apps.knowledge.models import Material
        from apps.knowledge.services import rebuild_vectors

        course_id, material_id, ppt_id, rebuild_all = (
            options["course"], options["material"], options["ppt"], options["all"],
        )
        if not (course_id or material_id or ppt_id or rebuild_all):
            raise CommandError(
                "请指定范围：--course ID / --material ID / --ppt ID / --all 之一"
            )

        materials = Material.objects.none()
        ppts = PPTResource.objects.none()
        if material_id:
            materials = Material.objects.filter(pk=material_id)
            if not materials.exists():
                raise CommandError(f"资料 {material_id} 不存在")
        elif ppt_id:
            ppts = PPTResource.objects.filter(pk=ppt_id)
            if not ppts.exists():
                raise CommandError(f"课件 {ppt_id} 不存在")
        elif course_id:
            materials = Material.objects.filter(course_id=course_id)
            ppts = PPTResource.objects.filter(course_id=course_id, is_active=True)
        else:
            materials = Material.objects.all()
            ppts = PPTResource.objects.filter(is_active=True)

        report = rebuild_vectors(materials, ppts)
        if report.get("error"):
            raise CommandError(report["error"])

        self.stdout.write(
            f"向量模型：{report['provider']} · {report['model'] or '未设置模型名'}（维度 {report['dimension']}）"
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"重建完成：资料 {report['materials']['success']}/{report['materials']['total']} 份，"
                f"课件 {report['ppts']['success']}/{report['ppts']['total']} 部，"
                f"共 {report['chunks']} 个片段"
            )
        )
        if report["failed"]:
            for item in report["failed"]:
                obj_id = item.get("material_id") or item.get("ppt_id")
                kind_label = "资料" if item["kind"] == "material" else "课件"
                self.stdout.write(
                    self.style.ERROR(
                        f"失败：{kind_label} {obj_id}（{item['file_name']}）→ {item['reason']}"
                    )
                )
            self.stdout.write(
                self.style.WARNING(
                    "修复后可用 python manage.py rebuild_vectors --material <ID> / --ppt <ID> 逐项续跑"
                )
            )
            raise CommandError(f"{len(report['failed'])} 项重建失败")
