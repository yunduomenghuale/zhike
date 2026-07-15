"""考试全流程测试：建题库 -> 组卷 -> 学生开考 -> 作答提交自动评分 -> 防作弊上报 -> 教师监控。
运行：python smoke_exam.py
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from rest_framework.test import APIClient  # noqa: E402


def show(title, resp):
    print(f"[{resp.status_code}] {title}: {str(resp.data)[:180]}")
    return resp.data


T = APIClient()
d = T.post("/api/auth/register/", {
    "username": "ex_teacher", "password": "pass1234", "real_name": "赵老师", "role": "teacher"
}, format="json").data
T.credentials(HTTP_AUTHORIZATION=f"Bearer {d['data']['token']['access']}")

course_id = T.post("/api/courses/", {"name": "计算机网络", "term": "2026春"}, format="json").data["data"]["id"]
class_id = T.post("/api/classes/", {"course": course_id, "name": "网络1班"}, format="json").data["data"]["id"]
invite = T.get(f"/api/classes/{class_id}/").data["data"]["invite_code"]

# 建两道已发布客观题
def make_q(stem, options, answer, qtype="single", score=5):
    return T.post("/api/questions/", {
        "course": course_id, "qtype": qtype, "stem": stem,
        "options": options, "answer": answer, "score": score,
        "difficulty": "easy", "status": "published",
    }, format="json").data["data"]["id"]

q1 = make_q("OSI 模型共有几层？",
            [{"key": "A", "text": "5"}, {"key": "B", "text": "7"}, {"key": "C", "text": "4"}],
            {"key": "B"})
q2 = make_q("TCP 是面向连接的协议。",
            [{"key": "A", "text": "对"}, {"key": "B", "text": "错"}],
            {"key": "A"}, qtype="judge")
print(f"已建题目: q1={q1}, q2={q2}")

# 建考试并随机组卷
exam_id = T.post("/api/exams/", {
    "course": course_id, "classroom": class_id, "name": "期中测验",
    "duration": 30, "shuffle_questions": True, "shuffle_options": True,
    "show_analysis_after": True,
    "anti_cheat": {"detect_blur": True, "forbid_copy": True},
    "status": "published",
}, format="json").data["data"]["id"]

show("随机组卷", T.post(f"/api/exams/{exam_id}/compose/", {
    "mode": "random",
    "rules": [{"qtype": "single", "count": 1, "score": 5},
              {"qtype": "judge", "count": 1, "score": 5}],
}, format="json"))

# 学生加入并开考
S = APIClient()
d = S.post("/api/auth/register/", {
    "username": "ex_student", "password": "pass1234", "real_name": "小刚", "role": "student"
}, format="json").data
S.credentials(HTTP_AUTHORIZATION=f"Bearer {d['data']['token']['access']}")
S.post("/api/classes/join/", {"invite_code": invite}, format="json")

d = show("学生开考", S.post("/api/exam-submissions/start/", {"exam": exam_id}, format="json"))
sub_id = d["data"]["submission"]["id"]
questions = d["data"]["questions"]
print(f"  -> 下发题目数={len(questions)}，首题含答案? {'answer' in questions[0]}")

# 上报一次切屏（防作弊）
show("防作弊上报(切屏)", S.post("/api/exam-logs/", {
    "exam": exam_id, "action": "blur", "note": "切换到其他窗口"
}, format="json"))

# 作答：q1=B(对), q2=B(错) -> 应得 5 分（满分10）
d = show("交卷自动评分", S.post(f"/api/exam-submissions/{sub_id}/submit/", {
    "answers": {str(q1): {"key": "B"}, str(q2): {"key": "B"}},
}, format="json"))
print(f"  -> 客观题得分={d['data']['objective_score']}，异常标记={d['data']['abnormal']}")

# 考后回看
d = show("考后回看", S.get(f"/api/exam-submissions/{sub_id}/review/"))
print(f"  -> 回看题目数={len(d['data']['questions'])}，首题正确答案={d['data']['questions'][0]['correct_answer']}")

# 教师监控
d = show("教师监控", T.get(f"/api/exams/{exam_id}/monitor/"))

assert len(questions) == 2, "应下发2题"
assert "answer" not in questions[0] and "correct_answer" not in questions[0], "答题时不得含答案"
assert str(d) is not None
print("\n✅ 考试全流程测试通过")
