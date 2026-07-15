"""端到端冒烟测试：走 DRF 接口验证注册/登录/建课/AI 目录识别/组卷评分。
运行：python smoke_test.py
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from rest_framework.test import APIClient  # noqa: E402

c = APIClient()


def show(title, resp):
    print(f"[{resp.status_code}] {title}: {str(resp.data)[:160]}")
    return resp.data


# 1. 教师注册
d = show("教师注册", c.post("/api/auth/register/", {
    "username": "teacher1", "password": "pass1234", "real_name": "张老师", "role": "teacher"
}, format="json"))
token = d["data"]["token"]["access"]
c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

# 2. 当前用户
show("我的信息", c.get("/api/auth/me/"))

# 3. 建课程
d = show("创建课程", c.post("/api/courses/", {
    "name": "人工智能导论", "intro": "AI 基础课", "term": "2026春"
}, format="json"))
course_id = d["data"]["id"]

# 4. AI 从授课计划识别目录（走 mock provider）
show("AI 目录识别", c.post("/api/catalogs/generate-from-plan/", {
    "course": course_id, "plan_text": "第一章 绪论；第二章 基础知识"
}, format="json"))

# 5. 手动加一个章节
d = show("创建章节", c.post("/api/catalogs/", {
    "course": course_id, "title": "第一章 绪论", "order": 1, "is_published": True
}, format="json"))
catalog_id = d["data"]["id"]

# 6. AI 生成题目（草稿）
show("AI 生成题目", c.post("/api/questions/generate/", {
    "course": course_id, "catalog": catalog_id, "count": 1, "qtype": "single"
}, format="json"))

# 7. 建班级
d = show("创建班级", c.post("/api/classes/", {
    "course": course_id, "name": "AI导论1班"
}, format="json"))
invite = d["data"]["invite_code"]

# 8. 学生注册 + 用邀请码加入
c2 = APIClient()
d = show("学生注册", c2.post("/api/auth/register/", {
    "username": "student1", "password": "pass1234", "real_name": "小明", "role": "student"
}, format="json"))
c2.credentials(HTTP_AUTHORIZATION=f"Bearer {d['data']['token']['access']}")
show("学生加入班级", c2.post("/api/classes/join/", {"invite_code": invite}, format="json"))

# 9. 学生知识库提问（无资料 -> 应提示资料不足）
show("知识库提问(无资料)", c2.post("/api/qa-records/ask/", {
    "course": course_id, "question": "什么是人工智能？"
}, format="json"))

print("\n✅ 冒烟测试完成")
