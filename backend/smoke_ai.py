"""验证大模型接入：Provider + 对话 + 目录识别 + 真实向量。"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.ai.providers.factory import get_provider  # noqa: E402
from apps.ai.services import generate_catalog_from_plan  # noqa: E402

p = get_provider()
print("当前 Provider:", p.name)

print("\n=== 对话 ===")
print(p.chat([{"role": "user", "content": "用一句话说明什么是二分查找"}]))

print("\n=== 目录识别 ===")
print(generate_catalog_from_plan("第一章 绪论（1.1 概念 1.2 目标）；第二章 线性表（2.1 顺序表）"))

print("\n=== 向量 embedding ===")
vecs = p.embed(["栈是后进先出的线性表", "队列是先进先出的线性表"])
print(f"返回 {len(vecs)} 条向量，维度 = {len(vecs[0])}")

print("\n✅ 接入验证完成")
