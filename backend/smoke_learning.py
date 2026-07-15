"""学生学习/练习冒烟：已发布章节可见 + 学生题目隐答案 + 章节练习自动评分并返回解析。"""
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from rest_framework.test import APIClient


def show(t, r):
    print(f"[{r.status_code}] {t}: {str(r.data)[:130]}")
    return r.data


T = APIClient()
d = T.post("/api/auth/register/", {"username": "lz_t", "password": "pass1234", "real_name": "周老师", "role": "teacher"}, format="json").data
T.credentials(HTTP_AUTHORIZATION=f"Bearer {d['data']['token']['access']}")
course = T.post("/api/courses/", {"name": "算法", "term": "2026春"}, format="json").data["data"]["id"]
cls = T.post("/api/classes/", {"course": course, "name": "算法1班"}, format="json").data["data"]["id"]
invite = T.get(f"/api/classes/{cls}/").data["data"]["invite_code"]

# 已发布章节 + 未发布章节
ch_pub = T.post("/api/catalogs/", {"course": course, "title": "第一章 排序", "is_published": True}, format="json").data["data"]["id"]
T.post("/api/catalogs/", {"course": course, "title": "第二章 未发布", "is_published": False}, format="json")

# 该章节已发布题目
T.post("/api/questions/", {
    "course": course, "catalog": ch_pub, "qtype": "single",
    "stem": "冒泡排序平均时间复杂度？", "options": [{"key": "A", "text": "O(n)"}, {"key": "B", "text": "O(n^2)"}],
    "answer": {"key": "B"}, "analysis": "两层循环，平均 O(n^2)。", "status": "published",
}, format="json")
q_id = T.get(f"/api/questions/?course={course}").data["data"]["results"][0]["id"]

# 学生
S = APIClient()
d = S.post("/api/auth/register/", {"username": "lz_s", "password": "pass1234", "real_name": "小周", "role": "student"}, format="json").data
S.credentials(HTTP_AUTHORIZATION=f"Bearer {d['data']['token']['access']}")
S.post("/api/classes/join/", {"invite_code": invite}, format="json")

# 学生看章节：只应看到已发布
d = show("学生看章节树", S.get(f"/api/catalogs/?course={course}&tree=1"))
cats = d["data"]["results"] if isinstance(d["data"], dict) else d["data"]
print(f"  -> 学生可见章节数={len(cats)}（应为1）")

# 学生看题目：不应含答案/解析
d = show("学生看题目(隐答案)", S.get(f"/api/questions/?course={course}&catalog={ch_pub}"))
q0 = (d["data"]["results"] if isinstance(d["data"], dict) else d["data"])[0]
print(f"  -> 含 answer 字段? {'answer' in q0} | 含 analysis? {'analysis' in q0}")

# 章节练习提交（答对）
d = show("章节练习提交", S.post("/api/questions/practice-submit/", {"answers": {str(q_id): {"key": "B"}}}, format="json"))
res = d["data"]
print(f"  -> {res['correct']}/{res['total']} 正确，返回正确答案={res['results'][0]['correct_answer']}，解析已带={bool(res['results'][0]['analysis'])}")

assert len(cats) == 1, "学生应只看到1个已发布章节"
assert "answer" not in q0 and "analysis" not in q0, "学生题目不应含答案/解析"
assert res["correct"] == 1, "应答对1题"
print("\n✅ 学生学习/练习冒烟通过")
