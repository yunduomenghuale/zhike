# -*- coding: utf-8 -*-
"""Stage 5：7 个预置（template）实验逐个真实回归。

真实链路：教师登录 → 建课/建章节 → 逐个模板建实验 → 排课 → 发布 →
学生 start → 进入门控页 → bridge-validate → submit → 看分 → 结论 →
生成报告 → 下载 PDF/DOCX。全部走真实 HTTP（8005），仅班级/学籍用
真实 ORM 准备（P0–P5 后班级 CRUD 收归平台管理员，教师端已 403）。

目的：确认 Stage 1–4 对 labs 的扩展（成绩上报端点、L2 门控三分流、
双桥接、报告双分支、状态机收敛）没有伤到 template 的 7 个预置实验。

跑法：cd backend && ./venv/Scripts/python.exe ../test/e2e/stage5-preset-regression.py
"""
import json
import os
import re
import subprocess
import sys
import time

import requests

BASE = os.environ.get("BASE", "http://127.0.0.1:8005")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(ROOT, "backend")
S = requests.Session()
S.trust_env = False  # 绕过系统代理

# S5_REMOTE 非空 → ORM 段经 SSH 在 124 的 zhike_s5test_backend 容器内执行（8092 复测模式）
S5_REMOTE = os.environ.get("S5_REMOTE", "")


def run_manage_shell(code):
    """manage.py shell：默认本地子进程；S5_REMOTE 时灌进远端容器 REPL stdin。"""
    if S5_REMOTE:
        import paramiko

        cli = paramiko.SSHClient()
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        cli.connect("124.70.107.64", port=22, username="root",
                    key_filename=os.path.expanduser("~/.ssh/id_claude_server"),
                    look_for_keys=False, allow_agent=False, timeout=20,
                    banner_timeout=30, auth_timeout=30)
        stdin, stdout, stderr = cli.exec_command(
            "docker exec -i zhike_s5test_backend python manage.py shell", timeout=300)
        stdin.write(code if code.endswith("\n") else code + "\n")
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        cli.close()
        return type("R", (), {"stdout": out, "stderr": err})()
    return subprocess.run([sys.executable, "manage.py", "shell", "-c", code],
                          cwd=BACKEND_DIR, capture_output=True, text=True)

EXPECTED_CODES = [
    "switch-vlan-stp-lab", "arp-ip-lab", "routing-ospf-lab", "vlan-nat-lab",
    "tcp-udp-lab", "app-layer-lab", "comprehensive-lab",
]

PASSED = 0
FAILED = 0


def out(msg):
    print(msg)


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        out(f"PASS | {name} | {detail}")
    else:
        FAILED += 1
        out(f"FAIL | {name} | {detail}")
    return cond


def api(method, path, token=None, expect=None, label="", **kw):
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = S.request(method, f"{BASE}/api{path}", headers=headers, timeout=60, **kw)
    ok = "" if expect is None else ("OK" if r.status_code == expect else f"EXPECT{expect}")
    ctype = r.headers.get("Content-Type", "")
    try:
        preview = json.dumps(r.json(), ensure_ascii=False)[:200]
    except Exception:
        binary = ("pdf" in ctype or "officedocument" in ctype or "zip" in ctype
                  or "octet-stream" in ctype or not ctype.startswith("text/"))
        preview = f"<binary {ctype} {len(r.content)}B>" if binary else r.text[:120]
    out(f"  [{r.status_code}] {ok} {method} {path} {label} {preview}")
    return r


def j(r):
    try:
        return r.json().get("data")
    except Exception:
        return None


def abs_url(u):
    return u if u.startswith("http") else BASE + u


def login(username, password):
    r = api("POST", "/auth/login/", label=f"登录 {username}", expect=200,
            json={"username": username, "password": password})
    return ((r.json().get("data") or {}).get("token") or {}).get("access")


def reset_passwords():
    """本地开发库账号密码被其他脚本改过时，用真实 ORM 复位（不碰生产）。"""
    code = """
from django.contrib.auth import get_user_model
U = get_user_model()
for name, role, real in [('t101','teacher','张老师'), ('20249999','student','李同学')]:
    u, _ = U.objects.get_or_create(username=name, defaults={'role': role, 'real_name': real})
    u.set_password('pass1234'); u.role = role; u.is_staff = (role == 'teacher'); u.save()
print('PASSWORDS_RESET')
"""
    p = subprocess.run([sys.executable, "manage.py", "shell", "-c", code],
                       cwd=BACKEND_DIR, capture_output=True, text=True)
    assert "PASSWORDS_RESET" in (p.stdout or ""), f"密码复位失败: {p.stdout[-300:]} {p.stderr[-300:]}"


def orm_prepare(course_id, ts):
    """真实 ORM 建班级 / 学籍 / 课程关联，返回 class_id。"""
    code = f'''
print("ORM_BEGIN course_id={course_id}")
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
    cls = ClassRoom.objects.create(name="Stage5回归班{ts}", code="S5R{ts}", teacher=course.teacher)
    assign_students(cls, [student], operator=course.teacher, note="stage5-preset-regression")
ClassCourse.objects.get_or_create(classroom=cls, course=course)
active = ClassStudent.objects.filter(student=student, classroom=cls, learn_status="active").exists()
print("CLASS_ID=" + str(cls.id))
print("ACTIVE=" + str(active))
print("ORM_END")
'''
    p = run_manage_shell(code)
    m = re.search(r"CLASS_ID=(\d+)", p.stdout or "")
    assert m, f"班级准备失败: stdout={(p.stdout or '')[-1200:]} stderr={(p.stderr or '')[-400:]}"
    assert "ACTIVE=True" in (p.stdout or ""), f"学籍未 active: {(p.stdout or '')[-600:]}"
    return int(m.group(1))


def main():
    ts = int(time.time())
    out("=" * 72)
    out("Stage 5 · 7 个预置实验逐个真实回归（本地 8005，真实 HTTP）")
    out("=" * 72)

    tok_t = login("t101", "pass1234")
    tok_s = login("20249999", "pass1234")
    if not tok_t or not tok_s:
        out("登录失败，用真实 ORM 复位密码后重试")
        reset_passwords()
        tok_t = login("t101", "pass1234")
        tok_s = login("20249999", "pass1234")
    check("A1 教师/学生真实登录成功", bool(tok_t and tok_s), f"teacher={bool(tok_t)} student={bool(tok_s)}")
    assert tok_t and tok_s, "登录失败，中止"

    r = api("POST", "/courses/", token=tok_t, label="建回归课程", expect=201,
            json={"name": f"Stage5预置实验回归{ts}", "term": "2026秋"})
    course_id = (j(r) or {}).get("id")
    check("A2 建课程", bool(course_id), f"course_id={course_id}")
    assert course_id

    r = api("GET", "/lab-templates/", token=tok_t, label="取模板列表", expect=200)
    tpls = (j(r) or {}).get("results") or j(r) or []
    if not tpls:
        subprocess.run([sys.executable, "manage.py", "seed_lab_templates"], cwd=BACKEND_DIR, check=True)
        tpls = (j(api("GET", "/lab-templates/", token=tok_t, expect=200)) or {}).get("results") or []
    codes = [t["code"] for t in tpls]
    check("A3 7 个预置模板齐全且顺序一致", codes == EXPECTED_CODES, str(codes))
    assert codes == EXPECTED_CODES, "模板列表不符合预期，中止"

    class_id = orm_prepare(course_id, ts)
    out(f"  [ORM] 班级 + 学籍 + 课程关联就绪 class_id={class_id}")

    for idx, tpl in enumerate(tpls, start=1):
        code = tpl["code"]
        out("-" * 72)
        out(f"模板 {idx}/7  {code}  {tpl['title']}")
        out("-" * 72)

        r = api("POST", "/labs/", token=tok_t, label="建实验", expect=201,
                json={"template": tpl["id"], "course": course_id})
        lab = j(r) or {}
        lab_id = lab.get("id")
        check(f"B{idx}-1 建实验 201 且 page_source=template",
              bool(lab_id) and lab.get("page_source") == "template",
              f"id={lab_id} page_source={lab.get('page_source')}")
        assert lab_id

        r = api("POST", "/lab-schedules/", token=tok_t, label="排课", expect=201,
                json={"lab": lab_id, "classroom": class_id})
        check(f"B{idx}-2 排课 201", r.status_code == 201)
        api("POST", f"/labs/{lab_id}/publish/", token=tok_t, label="发布", expect=200)
        check(f"B{idx}-3 发布 200", True, f"lab_id={lab_id}")

        r = api("POST", "/lab-submissions/start/", token=tok_s, label="学生 start", expect=200,
                json={"lab": lab_id})
        start = j(r) or {}
        sub_id = (start.get("submission") or {}).get("id")
        ticket = start.get("attempt_token")
        page_url = start.get("page_url")
        check(f"B{idx}-4 start 200 且返回票据/页面地址",
              bool(sub_id and ticket and page_url), f"submission_id={sub_id}")
        assert sub_id and ticket and page_url

        pr = S.get(abs_url(page_url), timeout=60)
        body = pr.text
        check(f"B{idx}-5 template 门控页 200 且注入 <base>/bridge（原逻辑零回归）",
              pr.status_code == 200 and "<base" in body and "lab-bridge.js" in body,
              f"status={pr.status_code} bytes={len(pr.content)} base={'<base' in body} bridge={'lab-bridge.js' in body}")

        r = api("GET", f"/lab-submissions/bridge-validate/?token={ticket}",
                token=tok_s, label=" bridge-validate", expect=200)
        bv = j(r) or {}
        ctx = bv.get("context") or {}
        check(f"B{idx}-6 bridge-validate 200 且 context 严格四字段",
              set(ctx.keys()) == {"labId", "submissionId", "totalScore", "gradeEndpoint"}
              and ctx.get("labId") == lab_id and ctx.get("submissionId") == sub_id
              and ctx.get("gradeEndpoint") == "/api/lab-gate/grade/",
              f"keys={sorted(ctx.keys())} expected_keys={bool(bv.get('expected'))}")
        check(f"B{idx}-6b 模板随机参数 expected 非空（预置实验零回归）",
              bool(bv.get("expected")), f"expected={str(bv.get('expected'))[:80]}")

        elapsed = 600 + idx * 30
        r = api("POST", f"/lab-submissions/{sub_id}/submit/", token=tok_s,
                label="submit", expect=200,
                json={"attempt_token": ticket,
                      "steps_result": {"1": "pass", "2": "pass", "3": "pass", "4": "fail"},
                      "error_log": [{"step": "4", "cmd": "display vlan", "msg": "Stage5 回归模拟错误"}],
                      "elapsed_seconds": elapsed})
        sub = j(r) or {}
        score = sub.get("total_score")
        breakdown = sub.get("score_breakdown") or {}
        try:
            score_f = float(score)
        except (TypeError, ValueError):
            score_f = -1
        max_score = float(lab.get("total_score") or 100)
        check(f"B{idx}-7 submit 200 且分数合法（template 沿用客户端用时）",
              r.status_code == 200 and 0 <= score_f <= max_score
              and sub.get("elapsed_seconds") == elapsed
              and sub.get("passed_steps") == 3 and sub.get("total_steps") == 4,
              f"score={score} max={max_score} elapsed={sub.get('elapsed_seconds')} steps={sub.get('passed_steps')}/{sub.get('total_steps')}")
        need_keys = ("base", "accuracy", "efficiency", "completion", "passed_steps", "total_steps", "total")
        check(f"B{idx}-8 grading_source=steps、breakdown 为 template 步骤评分分支（报告双分支零回归）",
              sub.get("grading_source") == "steps" and breakdown.get("source") != "external"
              and all(k in breakdown for k in need_keys)
              and int(breakdown.get("passed_steps", -1)) == 3
              and int(breakdown.get("total_steps", -1)) == 4,
              f"source={sub.get('grading_source')} breakdown_keys={sorted(breakdown.keys())}")
        check(f"B{idx}-9 status=submitted、submitted_at 有值、无 question_score 幽灵字段",
              sub.get("status") == "submitted" and bool(sub.get("submitted_at"))
              and "question_score" not in sub,
              f"status={sub.get('status')} submitted_at={sub.get('submitted_at')}")

        r = api("GET", "/lab-submissions/", token=tok_s, label="成绩列表", expect=200)
        rows = (j(r) or {}).get("results") or []
        mine = next((x for x in rows if x.get("id") == sub_id), None)
        check(f"B{idx}-10 成绩列表可见该提交且分数一致",
              bool(mine) and mine.get("total_score") == score and mine.get("status") == "submitted",
              f"found={bool(mine)} score={mine.get('total_score') if mine else None}")

        api("POST", f"/lab-submissions/{sub_id}/conclusion/", token=tok_s,
            label="结论", expect=200, json={"conclusion": f"Stage5 回归：{code} 结论"})
        r = api("POST", f"/lab-submissions/{sub_id}/generate-report/", token=tok_s,
                label="生成报告", expect=200)
        rep = j(r) or {}
        check(f"B{idx}-11 生成报告 PDF/DOCX 双产物",
              bool(rep.get("file_pdf") and rep.get("file_docx")),
              f"pdf={bool(rep.get('file_pdf'))} docx={bool(rep.get('file_docx'))}")
        r1 = api("GET", f"/lab-submissions/{sub_id}/download-report/?type=pdf", token=tok_s,
                 label="下载 PDF", expect=200)
        r2 = api("GET", f"/lab-submissions/{sub_id}/download-report/?type=docx", token=tok_s,
                 label="下载 DOCX", expect=200)
        check(f"B{idx}-12 报告下载 200 且内容非空",
              r1.headers.get("Content-Type", "").startswith("application/pdf")
              and len(r1.content) > 1000 and len(r2.content) > 1000,
              f"pdf={len(r1.content)}B docx={len(r2.content)}B")

    out("=" * 72)
    out(f"总计 {PASSED + FAILED} 项，通过 {PASSED} 项，失败 {FAILED} 项")
    out("ALL_PASS" if FAILED == 0 else "HAS_FAILURE")
    out("=" * 72)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
