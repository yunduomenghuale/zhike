# -*- coding: utf-8 -*-
"""Stage 5：成绩上报端点性能冒烟 + 限流不误伤验证（本地 8005 真实 HTTP）。

批次 A：20 次快速连续上报（同一学生）。`lab_grade` 档位 10/min，
        预期前 10 次 200、后 10 次 429；记录 p50 / 429 数 / 错误数，
        验证「除预期限流外无 5xx、无业务错误」。
批次 B：等待限流窗口冷却后，按正常使用节奏（间隔 7s）上报 10 次，
        预期 10/10 全部 200 code=0，证明限流不误伤正常使用。

每次上报都走真实链路：学生 start 领一次性票据 → POST /api/lab-gate/grade/
（X-Lab-Token 头 + 总分报文）→ 票据消费、成绩落库。

跑法：cd backend && PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe ../test/e2e/stage5-perf.py
"""
import json
import os
import re
import statistics
import subprocess
import sys
import time

import requests

BASE = os.environ.get("BASE", "http://127.0.0.1:8005")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, "backend")
FIXTURE = os.path.join(ROOT, "test", "e2e", "fixtures", "stage4-from-spec.html")

S = requests.Session()
S.trust_env = False

PASSED = 0
FAILED = 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"PASS | {name} | {detail}")
    else:
        FAILED += 1
        print(f"FAIL | {name} | {detail}")
    return cond


def api(method, path, token=None, **kw):
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return S.request(method, f"{BASE}/api{path}", headers=headers, timeout=60, **kw)


def data(r):
    try:
        return r.json().get("data")
    except Exception:
        return None


def login(username, password):
    r = api("POST", "/auth/login/", json={"username": username, "password": password})
    return ((r.json().get("data") or {}).get("token") or {}).get("access")


def orm_prepare(course_id, ts):
    code = f'''
from apps.classroom.models import ClassRoom, ClassCourse, ClassStudent
from apps.classroom.services import assign_students
from apps.courses.models import Course
from apps.users.models import User
course = Course.objects.get(pk={course_id})
student = User.objects.get(username="20249999")
rel = ClassStudent.objects.filter(student=student, learn_status="active").select_related("classroom").first()
if rel:
    cls = rel.classroom
else:
    cls = ClassRoom.objects.create(name="Stage5性能班{ts}", code="S5P{ts}", teacher=course.teacher)
    assign_students(cls, [student], operator=course.teacher, note="stage5-perf")
ClassCourse.objects.get_or_create(classroom=cls, course=course)
print("CLASS_ID=" + str(cls.id))
'''
    p = subprocess.run([sys.executable, "manage.py", "shell", "-c", code],
                       cwd=BACKEND, capture_output=True, text=True)
    m = re.search(r"CLASS_ID=(\d+)", p.stdout or "")
    assert m, f"班级准备失败: {p.stdout[-300:]} {p.stderr[-300:]}"
    return int(m.group(1))


def report_one(tok_s, lab_id, seq):
    """一次完整上报：start 领票据 → grade 上报，返回 (status, code, 耗时ms)。"""
    r = api("POST", "/lab-submissions/start/", token=tok_s, json={"lab": lab_id})
    if r.status_code != 200:
        return r.status_code, None, None
    ticket = (data(r) or {}).get("attempt_token")
    if not ticket:
        return r.status_code, None, None
    t0 = time.perf_counter()
    g = S.post(f"{BASE}/api/lab-gate/grade/",
               headers={"X-Lab-Token": ticket},
               json={"total_score": 80, "elapsed_seconds": 600}, timeout=60)
    cost = (time.perf_counter() - t0) * 1000
    try:
        code = g.json().get("code")
    except Exception:
        code = None
    print(f"  #{seq:02d} grade status={g.status_code} code={code} cost={cost:.1f}ms")
    return g.status_code, code, cost


def summarize(label, rows):
    ok = [x for x in rows if x[0] == 200 and x[1] == 0]
    throttled = [x for x in rows if x[0] == 429]
    errors = [x for x in rows if x[0] not in (200, 429) or (x[0] == 200 and x[1] != 0)]
    costs = sorted(x[2] for x in ok if x[2] is not None)
    p50 = statistics.median(costs) if costs else None
    if costs:
        p95 = costs[max(0, int(len(costs) * 0.95) - 1)]
        print(f"[{label}] total={len(rows)} ok={len(ok)} throttled429={len(throttled)} "
              f"errors={len(errors)} p50={p50:.1f}ms p95={p95:.1f}ms")
    else:
        print(f"[{label}] total={len(rows)} ok={len(ok)} throttled429={len(throttled)} "
              f"errors={len(errors)} p50=n/a")
    return {"total": len(rows), "ok": len(ok), "throttled": len(throttled),
            "errors": len(errors), "p50": p50}


def main():
    ts = int(time.time())
    print("=" * 72)
    print("Stage 5 · 成绩上报性能冒烟 + 限流不误伤（本地 8005，真实 HTTP）")
    print("=" * 72)

    tok_t = login("t101", "pass1234")
    tok_s = login("20249999", "pass1234")
    check("A1 教师/学生真实登录成功", bool(tok_t and tok_s))
    assert tok_t and tok_s

    course_id = (data(api("POST", "/courses/", token=tok_t,
                          json={"name": f"Stage5性能冒烟{ts}", "term": "2026秋"})) or {}).get("id")
    check("A2 建课程", bool(course_id), f"course_id={course_id}")
    assert course_id

    r = api("POST", "/labs/", token=tok_t, json={
        "title": f"Stage5成绩上报性能实验{ts}", "course": course_id,
        "page_source": "custom", "total_score": 100, "pass_score": 60,
        "standard_minutes": 30, "allow_resubmit": True,
        "report_note": "Stage 5 性能冒烟",
    })
    lab = data(r) or {}
    lab_id = lab.get("id")
    check("A3 建 custom 实验（allow_resubmit=True 便于重复取票）",
          r.status_code == 201 and lab.get("page_source") == "custom",
          f"status={r.status_code} id={lab_id}")
    assert lab_id

    with open(FIXTURE, "rb") as fh:
        up = api("POST", f"/labs/{lab_id}/page/", token=tok_t,
                 files={"file": ("stage4-from-spec.html", fh, "text/html")})
    def uploaded_body(resp):
        if not resp.headers.get("Content-Type", "").startswith("application/json"):
            return {}
        try:
            return resp.json()
        except Exception:
            return {}

    up_body = uploaded_body(up)
    up_data = up_body.get("data") if isinstance(up_body.get("data"), dict) else {}
    if up.status_code == 200 and up_data.get("require_confirm"):
        with open(FIXTURE, "rb") as fh:
            up = api("POST", f"/labs/{lab_id}/page/", token=tok_t,
                     files={"file": ("stage4-from-spec.html", fh, "text/html")},
                     data={"confirm": "1"})
        up_body = uploaded_body(up)
        up_data = up_body.get("data") if isinstance(up_body.get("data"), dict) else {}
    check("A4 真实上传单 HTML 页面（S8 静态扫描通过）",
          up.status_code == 200 and up_body.get("code") == 0
          and not up_data.get("require_confirm"),
          f"status={up.status_code} code={up_body.get('code')}")
    assert up.status_code == 200

    class_id = orm_prepare(course_id, ts)
    r = api("POST", "/lab-schedules/", token=tok_t,
            json={"lab": lab_id, "classroom": class_id})
    check("A5 排课 201", r.status_code == 201)
    r = api("POST", f"/labs/{lab_id}/publish/", token=tok_t)
    check("A6 发布 200", r.status_code == 200, f"status={r.status_code}")
    assert r.status_code == 200

    print("-" * 72)
    print("批次 A：20 次快速连续上报（验证 10/min 限流档位按设计生效）")
    print("-" * 72)
    rows_a = [report_one(tok_s, lab_id, i + 1) for i in range(20)]
    sa = summarize("A", rows_a)
    check("P1 快速连打出现 429（lab_grade 10/min 档位生效）", sa["throttled"] > 0,
          f"429={sa['throttled']} ok={sa['ok']}")
    check("P2 快速连打零 5xx / 零业务错误（限流之外无误伤）", sa["errors"] == 0,
          f"errors={sa['errors']}")
    check("P3 成功请求 p50 在合理范围（< 5000ms）", sa["p50"] is not None and sa["p50"] < 5000,
          f"p50={sa['p50']}")
    check("P4 每次成功上报均返回 code=0", sa["ok"] == len([x for x in rows_a if x[0] == 200]),
          f"ok={sa['ok']}")

    print("-" * 72)
    print("批次 B：等待限流窗口冷却 62s，再按 7s 正常节奏上报 10 次")
    print("-" * 72)
    time.sleep(62)
    rows_b = []
    for i in range(10):
        if i:
            time.sleep(7)
        rows_b.append(report_one(tok_s, lab_id, i + 1))
    sb = summarize("B", rows_b)
    check("P5 正常使用节奏 10/10 全部成功（限流不误伤）",
          sb["ok"] == 10 and sb["throttled"] == 0 and sb["errors"] == 0,
          f"ok={sb['ok']} 429={sb['throttled']} errors={sb['errors']}")
    check("P6 正常节奏 p50 在合理范围（< 5000ms）", sb["p50"] is not None and sb["p50"] < 5000,
          f"p50={sb['p50']:.1f}ms" if sb["p50"] else "p50=n/a")

    # 落库复核：最后一次上报确实是 external 且服务端算了用时
    r = api("GET", "/lab-submissions/", token=tok_s)
    rows = (data(r) or {}).get("results") or []
    mine = [x for x in rows if x.get("lab") == lab_id]
    check("P7 落库记录为 external 且有服务端用时",
          bool(mine) and mine[0].get("grading_source") == "external"
          and mine[0].get("total_score") is not None
          and mine[0].get("elapsed_seconds") is not None,
          f"count={len(mine)} source={mine[0].get('grading_source') if mine else None}")

    print("=" * 72)
    print(f"总计 {PASSED + FAILED} 项，通过 {PASSED} 项，失败 {FAILED} 项")
    print("ALL_PASS" if FAILED == 0 else "HAS_FAILURE")
    print("=" * 72)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
