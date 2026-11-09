#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage 4 真实浏览器 E2E 的前置数据准备（本地 8005 / 8092 通用）。

做三件事，全部走真实 HTTP + 真实库：
1. 用教师账号登录，建一门带时间戳的课程，并用 ORM 建班级 / 关联课程 / 备好学籍
   （P0–P5 后班级 CRUD 收归管理员、入班走 ClassStudent 单一写入口）；
2. 临时建一个 custom 实验 → 调真实 `GET /api/labs/{id}/integration-spec/` →
   从返回的动态 Markdown 中**提取最小 HTML 片段**存成上传样本 → 删除临时实验；
   这样浏览器 E2E 上传的页面就是「复制出来的说明里那一份」，直接验证「说明可直接使用」；
3. 产物写 D:/tmp/stage4-setup.json（路径可用 OUT 环境变量覆盖）。

用法：
  cd backend && ./venv/Scripts/python.exe ../test/e2e/lab-custom-setup.py
"""
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

import requests

BASE = os.environ.get("BASE", "http://127.0.0.1:8005")
OUT = os.environ.get("OUT", "D:/tmp/stage4-setup.json")
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "stage4-from-spec.html")
MIN_LAB = os.path.join(os.path.dirname(__file__), "fixtures", "min-lab.html")
TEACHER = ("t101", "pass1234")
STUDENT = ("20249999", "pass1234")
# S5_REMOTE 非空时，ORM 段经 SSH 在 124 的 zhike_s5test_backend 容器里执行
# （BASE 走 SSH 隧道，如 http://127.0.0.1:18092）；为空则维持本地 manage.py 子进程。
S5_REMOTE = os.environ.get("S5_REMOTE", "")

s = requests.Session()
s.trust_env = False


def run_manage_shell(code):
    """manage.py shell：默认本地子进程；S5_REMOTE 时经 SSH 灌进远端容器的 REPL stdin。"""
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
                          capture_output=True, text=True, check=True)


def api(method, path, token=None, expect=200, **kw):
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = "Bearer " + token
    r = s.request(method, BASE + "/api" + path, headers=headers, timeout=30, **kw)
    assert r.status_code == expect, f"{method} {path} -> {r.status_code}: {r.text[:300]}"
    return r.json().get("data")


def login(username, password):
    d = api("POST", "/auth/login/", json={"username": username, "password": password})
    return d["token"]["access"]


def main():
    ts = int(time.time())
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    try:
        t_token = login(*TEACHER)
        s_token = login(*STUDENT)
    except AssertionError:
        # 开发库账号密码被改过：与 e2e_real_test.py 同款真实库重置
        proc = run_manage_shell("""
from django.contrib.auth import get_user_model
U = get_user_model()
t, _ = U.objects.get_or_create(username='t101', defaults={'role': 'teacher'})
t.set_password('pass1234'); t.role = 'teacher'; t.is_staff = True; t.save()
s, _ = U.objects.get_or_create(username='20249999', defaults={'role': 'student'})
s.set_password('pass1234'); s.role = 'student'; s.save()
print('PWD_RESET_DONE')
""")
        assert "PWD_RESET_DONE" in proc.stdout, f"密码复位失败: {proc.stdout[-300:]} {proc.stderr[-300:]}"
        t_token = login(*TEACHER)
        s_token = login(*STUDENT)
    print("login OK: teacher=t101 student=20249999")

    # 1. 课程 + 班级 + 学籍（真实库）
    course = api("POST", "/courses/", token=t_token, expect=201,
                 json={"name": f"Stage4 实验管理UI-{stamp}", "term": "2026秋"})
    course_id = course["id"]

    shell_code = f'''
from apps.classroom.models import ClassRoom, ClassCourse, ClassStudent
from apps.classroom.services import assign_students
from apps.courses.models import Course
from apps.users.models import User
course = Course.objects.get(pk={course_id})
student = User.objects.get(username="20249999")
rel = ClassStudent.objects.filter(student=student, learn_status__in=["active", "inactive"]).select_related("classroom").first()
if rel:
    cls = rel.classroom
else:
    cls = ClassRoom.objects.create(name="Stage4班{ts}", code="S4{ts}", teacher=course.teacher)
    assign_students(cls, [student], operator=course.teacher, note="stage4 e2e")
ClassCourse.objects.get_or_create(classroom=cls, course=course)
print("CLASS_ID=" + str(cls.id))
print("CLASS_NAME=" + cls.name)
'''
    proc = run_manage_shell(shell_code)
    m = re.search(r"CLASS_ID=(\d+)", proc.stdout)
    m_name = re.search(r"CLASS_NAME=(.+)", proc.stdout)
    assert m and m_name, f"班级准备失败: {proc.stdout[-400:]} {proc.stderr[-400:]}"
    class_id = int(m.group(1))
    class_name = m_name.group(1).strip()
    print(f"course OK: id={course_id} name={course['name']}")
    print(f"class/student OK: class_id={class_id} name={class_name}")

    # 2. 校验动态接入说明的关键要素（Stage 9：说明精简后不再内嵌最小 HTML，
    #    上传样本改用仓库内的静态 fixture test/e2e/fixtures/min-lab.html）
    tmp = api("POST", "/labs/", token=t_token, expect=201, json={
        "course": course_id, "title": f"临时说明提取-{stamp}",
        "total_score": "100", "pass_score": "60", "page_source": "custom",
    })
    tmp_id = tmp["id"]
    spec = api("GET", f"/labs/{tmp_id}/integration-spec/", token=t_token)
    md = spec["markdown"]
    for text in ("LabBridge.validate()", "LabBridge.reportGrade(", "ctx.totalScore",
                 "本次实验已提交", "成绩超出实验总分范围", "实验票据已使用", "提交过于频繁"):
        assert text in md, f"动态说明缺少关键要素：{text}"
    assert "@@" not in md, "动态说明占位符未完全展开"
    api("DELETE", f"/labs/{tmp_id}/", token=t_token, expect=200)
    html = io.open(MIN_LAB, encoding="utf-8").read()
    os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
    with io.open(FIXTURE, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    print(f"spec OK: markdown={len(md)} chars -> {FIXTURE} (static min-lab {len(html)} chars)")
    print("temp lab deleted OK")

    out = {
        "base": BASE,
        "course_id": course_id,
        "course_name": course["name"],
        "class_id": class_id,
        "class_name": class_name,
        "teacher_token": t_token,
        "student_token": s_token,
        "teacher": TEACHER[0],
        "student": STUDENT[0],
        "password": TEACHER[1],
        "fixture_path": FIXTURE.replace("\\", "/"),
        "spec_total_score": spec["total_score"],
        "lab_title": f"Stage4 自定义实验-{stamp}",
    }
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("out=" + OUT)


if __name__ == "__main__":
    main()
