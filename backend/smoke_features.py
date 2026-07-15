"""新功能冒烟：手动加学生 + 作业发布/提交/批改 + 学生作业可见性。"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from rest_framework.test import APIClient  # noqa: E402


def show(t, r):
    print(f"[{r.status_code}] {t}: {str(r.data)[:150]}")
    return r.data


T = APIClient()
d = T.post("/api/auth/register/", {"username": "hw_t", "password": "pass1234", "real_name": "李老师", "role": "teacher"}, format="json").data
T.credentials(HTTP_AUTHORIZATION=f"Bearer {d['data']['token']['access']}")
course = T.post("/api/courses/", {"name": "操作系统", "term": "2026春"}, format="json").data["data"]["id"]
cls = T.post("/api/classes/", {"course": course, "name": "OS1班"}, format="json").data["data"]["id"]

# 学生注册
S = APIClient()
d = S.post("/api/auth/register/", {"username": "hw_s", "password": "pass1234", "real_name": "小李", "role": "student"}, format="json").data
S.credentials(HTTP_AUTHORIZATION=f"Bearer {d['data']['token']['access']}")

# 教师手动按用户名加学生
show("手动加学生", T.post(f"/api/classes/{cls}/add-student/", {"username": "hw_s"}, format="json"))

# 教师发布作业
hw = show("发布作业", T.post("/api/homeworks/", {
    "classroom": cls, "title": "第一章作业", "description": "完成课后习题1-5", "total_score": 100, "status": "published"
}, format="json"))["data"]["id"]

# 学生应能看到该作业
d = show("学生看作业列表", S.get("/api/homeworks/"))
vis = d["data"]["results"] if isinstance(d["data"], dict) else d["data"]
print(f"  -> 学生可见作业数={len(vis)}")

# 学生提交
sub = show("学生提交作业", S.post("/api/homework-submissions/", {"homework": hw, "content": "我的答案：……"}, format="json"))["data"]["id"]

# 教师批改
show("教师批改", T.post(f"/api/homework-submissions/{sub}/grade/", {"score": 92, "comment": "不错"}, format="json"))

# 学生查看批改结果
d = show("学生看提交", S.get("/api/homework-submissions/"))
mine = d["data"]["results"] if isinstance(d["data"], dict) else d["data"]
print(f"  -> 我的提交得分={mine[0]['score']}, 状态={mine[0]['correct_status']}")

assert len(vis) == 1, "学生应看到1个作业"
assert mine[0]["score"] == "92.0" or float(mine[0]["score"]) == 92, "批改分应为92"
print("\n✅ 新功能冒烟通过")
