"""知识库 RAG 端到端测试：上传资料自动入库 -> 学生提问命中引用。
运行：python smoke_knowledge.py
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402


def show(title, resp):
    print(f"[{resp.status_code}] {title}: {str(resp.data)[:200]}")
    return resp.data


teacher = APIClient()
d = teacher.post("/api/auth/register/", {
    "username": "kb_teacher", "password": "pass1234", "real_name": "王老师", "role": "teacher"
}, format="json").data
teacher.credentials(HTTP_AUTHORIZATION=f"Bearer {d['data']['token']['access']}")

course_id = teacher.post("/api/courses/", {"name": "数据结构", "term": "2026春"}, format="json").data["data"]["id"]

# 上传一份真实 TXT 教辅资料（multipart）
content = (
    "栈是一种后进先出（LIFO）的线性表，只允许在表尾进行插入和删除操作。\n"
    "队列是一种先进先出（FIFO）的线性表，在表尾插入、在表头删除。\n"
    "二叉树是每个结点最多有两个子树的树结构，常用于查找与排序。\n"
).encode("utf-8")
upload = SimpleUploadedFile("数据结构讲义.txt", content, content_type="text/plain")
d = show("上传教辅资料(自动入库)", teacher.post(
    "/api/materials/",
    {"course": course_id, "file_name": "数据结构讲义.txt", "file": upload},
    format="multipart",
))
material = d["data"]
print(f"  -> parse_status={material['parse_status']}, chunk_count={material['chunk_count']}")

# 学生提问，应命中资料并返回引用来源
student = APIClient()
d = student.post("/api/auth/register/", {
    "username": "kb_student", "password": "pass1234", "real_name": "小红", "role": "student"
}, format="json").data
student.credentials(HTTP_AUTHORIZATION=f"Bearer {d['data']['token']['access']}")

d = show("学生提问(应命中)", student.post("/api/qa-records/ask/", {
    "course": course_id, "question": "栈和队列有什么区别？"
}, format="json"))
cited = d["data"]["cited_chunks"]
print(f"  -> 命中引用片段数={len(cited)}")
for c in cited[:3]:
    print(f"     · {c['material_name']} (score={c['score']}): {c['snippet'][:40]}")

assert material["parse_status"] == "done", "入库应成功"
assert material["chunk_count"] > 0, "应生成片段"
assert len(cited) > 0, "提问应命中引用"
print("\n✅ 知识库 RAG 端到端测试通过")
