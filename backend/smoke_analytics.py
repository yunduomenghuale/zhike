"""统计/预警/错题本冒烟。"""
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from rest_framework.test import APIClient


def show(t, r):
    print(f"[{r.status_code}] {t}: {str(r.data)[:150]}")
    return r.data


T = APIClient()
d = T.post("/api/auth/register/", {"username": "an_t", "password": "pass1234", "real_name": "钱老师", "role": "teacher"}, format="json").data
T.credentials(HTTP_AUTHORIZATION=f"Bearer {d['data']['token']['access']}")
course = T.post("/api/courses/", {"name": "离散数学", "term": "2026春"}, format="json").data["data"]["id"]
cls = T.post("/api/classes/", {"course": course, "name": "离散1班"}, format="json").data["data"]["id"]
invite = T.get(f"/api/classes/{cls}/").data["data"]["invite_code"]
ch = T.post("/api/catalogs/", {"course": course, "title": "第一章 集合", "is_published": True}, format="json").data["data"]["id"]
T.post("/api/questions/", {
    "course": course, "catalog": ch, "qtype": "single", "stem": "空集是任何集合的？",
    "options": [{"key": "A", "text": "真子集"}, {"key": "B", "text": "子集"}],
    "answer": {"key": "B"}, "analysis": "空集是任何集合的子集。", "status": "published",
}, format="json")
q_id = T.get(f"/api/questions/?course={course}").data["data"]["results"][0]["id"]

# 学生加入并答错
S = APIClient()
d = S.post("/api/auth/register/", {"username": "an_s", "password": "pass1234", "real_name": "小钱", "role": "student"}, format="json").data
S.credentials(HTTP_AUTHORIZATION=f"Bearer {d['data']['token']['access']}")
S.post("/api/classes/join/", {"invite_code": invite}, format="json")
S.post("/api/questions/practice-submit/", {"answers": {str(q_id): {"key": "A"}}}, format="json")  # 答错

# 教师看班级统计
d = show("班级统计", T.get(f"/api/analytics/class/{cls}/"))
stu = d["data"]["students"][0]
print(f"  -> 学生 {stu['name']}: 练习 {stu['practice_correct']}/{stu['practice_total']} 正确率 {stu['accuracy']}% 预警={stu['warnings']}")
print(f"  -> 班级汇总: {d['data']['summary']}")

# 学生看错题本
d = show("错题本", S.get("/api/analytics/my-wrong-questions/"))
print(f"  -> 错题数={d['data']['total']}，首题正确答案={d['data']['results'][0]['correct_answer']}，我的答案={d['data']['results'][0]['my_answer']}")

assert stu["accuracy"] == 0, "答错应正确率0"
assert "练习正确率低" in stu["warnings"], "应触发低正确率预警"
assert d["data"]["total"] == 1, "应有1道错题"
print("\n✅ 统计/预警/错题本冒烟通过")
