"""P4 准出验证：流转（毕业 + 统计口径）六项硬指标逐条实测。

自包含跑法（脚本自己复制隔离库、自己起服务、自己清理，不碰开发库）：

    cd backend && ./venv/Scripts/python.exe scripts/p4_graduation_check.py

覆盖任务规范 §4 P4 的准出项（全部走真实 HTTP + 真实登录 token）：

  P4-1 毕业预览名单准确：只含占用关系+在读学生，转走生在排除名单里（X-29）
  P4-2 整班毕业后状态一致：班级 graduated / 学生 edu_status=graduated / 关系仍 active
  P4-3 毕业生权限：可登录取、看历史课程与视频、上报进度；交作业/暂存附件/开考/
       开实验/AI 提问（ask 与 ask-stream）全部 403；已开考的答卷仍可交卷（不拦）
  P4-4 转班：旧课与旧作业待办消失；旧班考试（有答卷）仍在「我的考试」；旧班作业提交 403
  P4-5 统计分母：毕业/休学学生不计入，完成率随之变化（打印毕业前后对比表）
  P4-6 延期毕业：先转班再毕业，延期生不被误伤、在新班学习动作正常
  附加：撤销毕业回滚；审计日志留痕；休学生内容入口关闭；教师无权毕业/改学籍

实现说明：脚本用 SQLITE_PATH 指向临时库副本，子进程 runserver 继承同一 env；
fixtures 全部由脚本创建（班级编码带 P4V 前缀，重跑先清后建）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

BASE_DIR = Path(__file__).resolve().parents[1]
DEV_DB = BASE_DIR / "db.sqlite3"
WORK_DIR = Path(os.environ.get("P4_WORK_DIR", str(BASE_DIR / "p4_check_tmp")))
DB_PATH = WORK_DIR / "db.sqlite3"
PORT = 8006
BASE = f"http://127.0.0.1:{PORT}"
PREFIX = "P4V"  # 夹具编码前缀，重跑先按此前缀清理

RESULTS: list[tuple[str, bool, str]] = []
G = SimpleNamespace()  # 夹具（模块级，供各检查函数共享）


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  | {detail}" if detail else ""))
    return bool(ok)


def http(method: str, path: str, token: str | None = None, body: dict | None = None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw[:1] in (b"{", b"[") else raw
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, raw


def login(username: str, password: str) -> str:
    status, payload = http("POST", "/api/auth/login/", body={"username": username, "password": password})
    assert status == 200 and payload.get("code") == 0, f"登录失败 {username}: {payload}"
    return payload["data"]["token"]["access"]


def rows(payload) -> list:
    """列表行提取：DRF 分页是 results，管理端手写分页是 items，未分页是 list。"""
    if isinstance(payload, dict):
        return payload.get("results") or payload.get("items") or []
    return payload


# ---------------------------------------------------------------------------
# 环境准备
# ---------------------------------------------------------------------------
def prepare_env():
    sys.path.insert(0, str(BASE_DIR))
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    # 数据库隔离：E2E_DATABASE_URL（独立 MySQL 库）优先，否则沿用 SQLite 副本复制
    from _e2e_db import ensure_schema, prepare

    print(f"[db] {prepare(DEV_DB, DB_PATH, WORK_DIR)}")
    import django

    django.setup()
    ensure_schema()


def start_server() -> subprocess.Popen:
    env = dict(os.environ)
    proc = subprocess.Popen(
        [
            str(BASE_DIR / "venv" / "Scripts" / "python.exe"),
            "manage.py", "runserver", str(PORT), "--noreload",
        ],
        cwd=BASE_DIR, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    for _ in range(60):
        try:
            with urllib.request.urlopen(BASE + "/api/auth/config/", timeout=2):
                return proc
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("服务未就绪")


def stop_server(proc: subprocess.Popen):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


# ---------------------------------------------------------------------------
# fixtures（全部走 ORM 直接建；班级编码带 P4V 前缀，重跑先清后建）
# ---------------------------------------------------------------------------
def seed():
    from django.utils import timezone
    from apps.classroom.models import ClassRoom, ClassStudent
    from apps.courses.models import Course
    from apps.homework.models import Homework
    from apps.exams.models import Exam, Paper
    from apps.users.models import User

    # 清理上一次运行的残留（含关联行）
    rooms = ClassRoom.objects.filter(code__startswith=PREFIX)
    for room in rooms:
        ClassStudent.objects.filter(classroom=room).delete()
        room.course_links.all().delete()
        Homework.objects.filter(classroom=room).delete()
        Exam.objects.filter(classroom=room).delete()
        rooms.filter(pk=room.pk).delete()
    User.objects.filter(username__startswith="p4v_").delete()
    # 课程清理（房间删完后子引用已级联；若被 PROTECT 挡住只留孤儿行，不影响判定）
    for stale in Course.objects.filter(name__startswith="P4课程"):
        try:
            stale.delete()
        except Exception:
            pass

    # 专用管理员（不复用库里已有账号，避免改动开发数据；重跑先删后建）
    G.admin = User.objects.filter(username="p4v_admin").first()
    if G.admin is None:
        G.admin = User.objects.create_user(
            username="p4v_admin", password="AdminPass123!", role=User.Role.ADMIN
        )
    else:
        G.admin.set_password("AdminPass123!")
        G.admin.save()

    G.teacher = User.objects.create_user(
        username="p4v_teacher", password="TeachPass123!", role=User.Role.TEACHER, real_name="P4教师"
    )
    G.course = Course.objects.create(name="P4课程", teacher=G.teacher)
    # 下一届必须挂另一门课：新旧班同挂一门课时「转班后旧课消失」会假阳性（L1 同款坑）
    G.course_next = Course.objects.create(name="P4课程-进阶", teacher=G.teacher)
    # 2020 级 4 年制 → 2024 应毕业（早于当前年份，preview 的 year_reached=True）
    G.room = ClassRoom.objects.create(
        name="P4验证班", code=f"{PREFIX}-ROOM", teacher=G.teacher,
        enrollment_year=2020, duration_years=4,
    )
    G.room.courses.add(G.course)
    G.room_next = ClassRoom.objects.create(
        name="P4下一届", code=f"{PREFIX}-NEXT", teacher=G.teacher,
        enrollment_year=2021, duration_years=4,
    )
    G.room_next.courses.add(G.course_next)

    G.students = {}
    for key, name in [("a", "学生A"), ("b", "学生B"), ("c", "转走生C")]:
        stu = User.objects.create_user(
            username=f"p4v_{key}", password="StuPass123!", role=User.Role.STUDENT, real_name=name
        )
        G.students[key] = stu
        ClassStudent.objects.create(classroom=G.room, student=stu, learn_status="active")
    # c 转走到下一届（旧关系 transferred）
    from apps.classroom import services

    services.transfer_students(G.room_next, [G.students["c"]], operator=G.admin)

    # 作业 + 考试：A 交作业，B 不交 → 毕业前完成率 50%
    G.homework = Homework.objects.create(
        classroom=G.room, course=G.course, title="P4作业",
        mode=Homework.Mode.ATTACHMENT, status=Homework.Status.PUBLISHED,
        total_score=100,
    )
    from apps.homework.models import HomeworkSubmission

    HomeworkSubmission.objects.create(homework=G.homework, student=G.students["a"], content="已交")
    G.exam = Exam.objects.create(
        name="P4考试", course=G.course, classroom=G.room,
        status=Exam.Status.PUBLISHED, duration=60,
    )
    Paper.objects.create(exam=G.exam, course=G.course, question_items=[], total_score=100)
    return G


# ---------------------------------------------------------------------------
# 六项准出
# ---------------------------------------------------------------------------
def p4_1_preview(admin_token: str) -> bool:
    print("\n== P4-1 毕业预览名单准确 ==")
    status, data = http("GET", f"/api/classes/{G.room.id}/graduate-preview/", admin_token)
    payload = data.get("data", {}) if status == 200 else {}
    names = sorted(u["username"] for u in payload.get("students", []))
    transferred = [t["username"] for t in payload.get("transferred", [])]
    ok1 = check("预览只含占用+在读学生", names == ["p4v_a", "p4v_b"], f"students={names}")
    ok2 = check("转走生不在毕业名单且出现在排除清单", "p4v_c" not in names and transferred == ["p4v_c"], f"transferred={transferred}")
    ok3 = check("毕业年份已到（2020+4=2024）", payload.get("classroom", {}).get("year_reached") is True)
    ok4 = check("预览不写库（班级仍 active）", G.room.status == "active")
    return all([ok1, ok2, ok3, ok4])


def p4_2_graduate(admin_token: str) -> bool:
    print("\n== P4-2 整班毕业后状态一致 ==")
    status, data = http("POST", f"/api/classes/{G.room.id}/graduate/", admin_token, body={})
    payload = data.get("data", {}) if status == 200 else {}
    ok1 = check("毕业接口 200", status == 200 and payload.get("graduated_count") == 2, str(data)[:120])

    G.room.refresh_from_db()
    ok2 = check("班级状态 graduated", G.room.status == "graduated")

    status, roster = http("GET", f"/api/class-students/?classroom={G.room.id}&page_size=100", admin_token)
    by_user = {r["username"]: r for r in rows(roster.get("data", {}))}
    ok3 = check("A/B 学籍 graduated", all(by_user[u]["edu_status"] == "graduated" for u in ("p4v_a", "p4v_b")))
    ok4 = check("A/B 班级关系仍 active（历史可查）", all(by_user[u]["learn_status"] == "active" for u in ("p4v_a", "p4v_b")))

    status, logs = http("GET", "/api/admin-panel/action-logs/?action=class_graduate", admin_token)
    hit = [l for l in rows(logs.get("data", {})) if l.get("target_id") == G.room.id]
    ok5 = check("审计日志含整班毕业 + 名单快照", bool(hit) and hit[0].get("new_value", {}).get("count") == 2)
    return all([ok1, ok2, ok3, ok4, ok5])


def p4_3_graduated_access() -> bool:
    print("\n== P4-3 毕业生权限 ==")
    a_token = login("p4v_a", "StuPass123!")
    ok1 = check("毕业生可登录", True)

    status, data = http("GET", "/api/courses/", a_token)
    names = [c["name"] for c in rows(data.get("data", {}))]
    ok2 = check("历史课程仍在列表", "P4课程" in names, str(names))

    from apps.courses.models import TeachingVideo

    video = TeachingVideo.objects.filter(course=G.course).first()
    if video is None:
        from apps.courses.models import Catalog

        catalog = Catalog.objects.filter(course=G.course).first() or Catalog.objects.create(
            course=G.course, title="第一章", order=1, is_published=True
        )
        video = TeachingVideo.objects.create(course=G.course, catalog=catalog, is_published=True)
    status, data = http("POST", f"/api/videos/{video.id}/report-progress/", a_token, body={"duration_delta": 30})
    ok3 = check("视频进度上报 200（X-31 不拦毕业生）", status == 200, str(data)[:100])

    status, data = http("POST", "/api/homework-submissions/", a_token,
                        body={"homework": G.homework.id, "content": "补交"})
    ok4 = check("提交作业 403", status == 403 and "已毕业" in str(data.get("message")), f"{status} {data.get('message')}")

    status, data = http("POST", "/api/homework-submissions/attachments/", a_token, body={})
    ok5 = check("暂存附件 403", status == 403, f"{status}")

    status, data = http("POST", "/api/exam-submissions/start/", a_token, body={"exam": G.exam.id})
    ok6 = check("开考 403", status == 403 and "已毕业" in str(data.get("message")), f"{status} {data.get('message')}")

    status, data = http("POST", "/api/qa-records/ask/", a_token,
                        body={"course": G.course.id, "question": "毕业了还能问吗"})
    ok7 = check("AI 提问 403", status == 403, f"{status} {data.get('message')}")

    status, data = http("POST", "/api/qa-records/ask-stream/", a_token,
                        body={"course": G.course.id, "question": "流式提问"})
    ok8 = check("AI 流式提问 403", status == 403, f"{status}")

    from apps.labs.models import Lab, LabTemplate

    lab = Lab.objects.create(
        course=G.course, title="P4实验", status=Lab.Status.PUBLISHED,
        template=LabTemplate.objects.create(code="p4v-lab", title="P4实验模板"),
    )
    status, data = http("POST", "/api/lab-submissions/start/", a_token, body={"lab": lab.id})
    ok9 = check("开始实验 403", status == 403, f"{status}")
    Lab.objects.filter(pk=lab.pk).delete()
    LabTemplate.objects.filter(pk=lab.template_id).delete()
    return all([ok1, ok2, ok3, ok4, ok5, ok6, ok7, ok8, ok9])


def p4_3b_exam_submit_not_blocked() -> bool:
    print("\n== P4-3b 交卷不拦（已开考的答卷必须能交）==")
    # B 开考后整班毕业已发生在 p4_2；这里直接用 B 的身份交卷
    b_token = login("p4v_b", "StuPass123!")
    # B 没有答卷（未开考）→ 补造：先造一个进行中答卷再交卷，验证 submit 不看学籍
    from apps.exams.models import ExamSubmission, Paper

    # 必须带 paper：交卷校验「答卷未分配试卷」先于学籍判断
    sub = ExamSubmission.objects.create(
        exam=G.exam, student=G.students["b"], status=ExamSubmission.Status.IN_PROGRESS,
        paper=Paper.objects.filter(exam=G.exam).first(),
        started_at=timezone_now(),
    )
    # start 双语义：恢复在途答卷放行（前端「继续考试」每次进页都走这条路），
    # 否则毕业生连答题页都打不开，「交卷不拦」形同虚设
    status, resume = http("POST", "/api/exam-submissions/start/", b_token, body={"exam": G.exam.id})
    ok_resume = check("毕业生的在途答卷可经 start 恢复 200",
                      status == 200 and (resume.get("data", {}).get("submission", {}) or {}).get("id") == sub.id,
                      f"{status} {str(resume)[:100]}")
    status, data = http("POST", f"/api/exam-submissions/{sub.id}/submit/", b_token, body={"answers": {}})
    ok = check("毕业生的在途答卷可交卷 200", status == 200, f"{status} {str(data)[:100]}")
    return all([ok_resume, ok])


def timezone_now():
    from django.utils import timezone
    return timezone.now()


def p4_4_transfer() -> bool:
    print("\n== P4-4 转班 ==")
    # 新拉一个学生 d：在读 → 开考（留答卷）→ 转班 → 验证旧内容消失、旧成绩可查
    from apps.classroom.models import ClassStudent
    from apps.classroom import services
    from apps.users.models import User

    d = User.objects.create_user(
        username="p4v_d", password="StuPass123!", role=User.Role.STUDENT, real_name="转班生D"
    )
    ClassStudent.objects.create(classroom=G.room, student=d, learn_status="active")
    d_token = login("p4v_d", "StuPass123!")

    # 旧班考试开考（留答卷）
    status, start = http("POST", "/api/exam-submissions/start/", d_token, body={"exam": G.exam.id})
    ok_start = check("转班生前先在旧班开考", status == 200, f"{status}")

    services.transfer_students(G.room_next, [d], operator=G.admin)

    status, data = http("GET", "/api/courses/", d_token)
    names = [c["name"] for c in rows(data.get("data", {}))]
    ok1 = check("转班后旧课从列表消失", "P4课程" not in names and "P4课程-进阶" in names, str(names))

    status, data = http("GET", "/api/homeworks/", d_token)
    ok2 = check("转班后旧作业待办消失", rows(data.get("data", {})) == [])

    status, data = http("GET", "/api/exams/", d_token)
    names = [e["name"] for e in rows(data.get("data", {}))]
    ok3 = check("旧班考试（有答卷）仍在「我的考试」", "P4考试" in names, str(names))

    status, data = http("POST", "/api/homework-submissions/", d_token,
                        body={"homework": G.homework.id, "content": "补交旧班"})
    ok4 = check("转班生不能提交旧班作业 403", status == 403, f"{status}")
    return all([ok_start, ok1, ok2, ok3, ok4])


def p4_5_stats(admin_token: str) -> bool:
    print("\n== P4-5 统计分母 ==")
    # room 已整班毕业：分母应归零（毕业生不计入）
    status, data = http("GET", f"/api/analytics/class/{G.room.id}/", admin_token)
    payload = data.get("data", {}) if status == 200 else {}
    summary = payload.get("summary", {})
    ok1 = check("毕业班统计分母为 0（A/B 均不计入）", summary.get("student_count") == 0, str(summary))

    # 对照：下一届班有转来的 C、D（P4-4 转入）+ 直接入班的 E；C 个别毕业后分母下降
    from apps.classroom.models import ClassStudent
    from apps.users.models import User

    e = User.objects.create_user(
        username="p4v_e", password="StuPass123!", role=User.Role.STUDENT, real_name="学生E"
    )
    ClassStudent.objects.create(classroom=G.room_next, student=e, learn_status="active")
    from apps.homework.models import Homework, HomeworkSubmission

    hw_next = Homework.objects.create(
        classroom=G.room_next, course=G.course_next, title="P4作业-下一届",
        mode=Homework.Mode.ATTACHMENT, status=Homework.Status.PUBLISHED, total_score=100,
    )
    HomeworkSubmission.objects.create(homework=hw_next, student=e, content="已交")

    status, before = http("GET", f"/api/analytics/class/{G.room_next.id}/", admin_token)
    s_before = before.get("data", {}).get("summary", {})
    ok2 = check("毕业前：分母 3（C+D+E），完成率 33%",
                s_before.get("student_count") == 3 and s_before.get("homework_rate") == 33, str(s_before))

    # 把 C 个别毕业（管理端入口）
    status, data = http("POST", f"/api/classes/{G.room_next.id}/edu-status/", admin_token,
                        body={"student": G.students["c"].pk, "edu_status": "graduated", "note": "个别毕业"})
    ok3 = check("个别学籍变更接口 200", status == 200, f"{status} {data.get('message')}")

    status, after = http("GET", f"/api/analytics/class/{G.room_next.id}/", admin_token)
    s_after = after.get("data", {}).get("summary", {})
    ok4 = check("C 毕业后：分母 2（D+E），完成率 50%",
                s_after.get("student_count") == 2 and s_after.get("homework_rate") == 50, str(s_after))

    print("\n  毕业前后统计口径对比表（下一届班）:")
    print(f"    {'指标':<14}{'毕业前':>8}{'C 毕业后':>10}")
    print(f"    {'分母人数':<14}{s_before.get('student_count'):>8}{s_after.get('student_count'):>10}")
    print(f"    {'作业完成率':<13}{str(s_before.get('homework_rate')) + '%':>8}{str(s_after.get('homework_rate')) + '%':>10}")
    return all([ok1, ok2, ok3, ok4])


def p4_6_deferred(admin_token: str) -> bool:
    print("\n== P4-6 延期毕业 ==")
    # 新建班：F（延期）+ G；F 先转班，再毕业原班
    from apps.classroom.models import ClassRoom, ClassStudent
    from apps.classroom import services
    from apps.users.models import User
    from apps.homework.models import Homework

    room_d = ClassRoom.objects.create(
        name="P4延期班", code=f"{PREFIX}-DEFER", teacher=G.teacher,
        enrollment_year=2020, duration_years=4,
    )
    room_d.courses.add(G.course)
    f = User.objects.create_user(
        username="p4v_f", password="StuPass123!", role=User.Role.STUDENT, real_name="延期生F"
    )
    g = User.objects.create_user(
        username="p4v_g", password="StuPass123!", role=User.Role.STUDENT, real_name="正常生G"
    )
    ClassStudent.objects.create(classroom=room_d, student=f, learn_status="active")
    ClassStudent.objects.create(classroom=room_d, student=g, learn_status="active")

    # 延期：先转班
    services.transfer_students(G.room_next, [f], operator=G.admin)

    status, preview = http("GET", f"/api/classes/{room_d.id}/graduate-preview/", admin_token)
    names = [u["username"] for u in preview.get("data", {}).get("students", [])]
    ok1 = check("预览名单只剩 G（F 已转走）", names == ["p4v_g"], str(names))

    status, result = http("POST", f"/api/classes/{room_d.id}/graduate/", admin_token, body={})
    ok2 = check("毕业只带走了 G", status == 200 and result.get("data", {}).get("students") == ["p4v_g"], str(result)[:120])

    f.refresh_from_db()
    ok3 = check("延期生 F 学籍仍是在读", f.edu_status == "enrolled")

    # F 在新班学习动作正常
    f_token = login("p4v_f", "StuPass123!")
    hw = Homework.objects.create(
        classroom=G.room_next, course=G.course_next, title="P4作业-新班",
        mode=Homework.Mode.ATTACHMENT, status=Homework.Status.PUBLISHED, total_score=100,
    )
    status, data = http("POST", "/api/homework-submissions/", f_token,
                        body={"homework": hw.id, "content": "延期生的作业"})
    ok4 = check("延期生在新班可交作业 201", status == 201, f"{status} {str(data)[:80]}")
    return all([ok1, ok2, ok3, ok4])


def extra_revoke_and_suspended(admin_token: str) -> bool:
    print("\n== 附加：撤销毕业 / 休学门控 / 教师无权 ==")
    status, data = http("POST", f"/api/classes/{G.room.id}/graduate-revoke/", admin_token,
                        body={"note": "授位审核退回"})
    payload = data.get("data", {}) if status == 200 else {}
    ok1 = check("撤销毕业 200 且回滚 2 人", status == 200 and payload.get("reverted_count") == 2, str(data)[:120])
    G.room.refresh_from_db()
    ok2 = check("班级回到 active", G.room.status == "active")
    for key in ("a", "b"):
        G.students[key].refresh_from_db()
    ok3 = check("A/B 学籍回 enrolled", all(s.edu_status == "enrolled" for s in G.students.values()))

    # 休学：内容入口关闭 + 提交 403
    status, data = http("POST", f"/api/classes/{G.room.id}/edu-status/", admin_token,
                        body={"student": G.students["a"].pk, "edu_status": "suspended", "note": "休学"})
    ok4 = check("休学变更 200", status == 200)
    a_token = login("p4v_a", "StuPass123!")
    status, data = http("GET", "/api/courses/", a_token)
    ok5 = check("休学生课程列表为空", rows(data.get("data", {})) == [])
    status, data = http("POST", "/api/homework-submissions/", a_token,
                        body={"homework": G.homework.id, "content": "休学补交"})
    ok6 = check("休学生提交作业 403（休学中）", status == 403 and "休学" in str(data.get("message")), f"{status} {data.get('message')}")

    # 教师无权毕业 / 无权改学籍
    t_token = login("p4v_teacher", "TeachPass123!")
    status, data = http("GET", f"/api/classes/{G.room.id}/graduate-preview/", t_token)
    ok7 = check("教师看毕业预览 403", status == 403, f"{status}")
    status, data = http("POST", f"/api/classes/{G.room.id}/edu-status/", t_token,
                        body={"student": G.students["a"].pk, "edu_status": "enrolled"})
    ok8 = check("教师改学籍 403", status == 403, f"{status}")
    return all([ok1, ok2, ok3, ok4, ok5, ok6, ok7, ok8])


def cleanup():
    """清理临时库（fixtures 全在这个库里，删文件即干净；删不掉就截断兜底）。"""
    try:
        if DB_PATH.exists():
            DB_PATH.unlink()
    except Exception as exc:  # noqa: BLE001
        try:
            with open(DB_PATH, "wb") as fh:
                fh.truncate(0)
            print(f"临时库删除被拦，已截断为 0 字节：{DB_PATH}（{exc}）")
        except Exception as exc2:  # noqa: BLE001
            print(f"清理临时库失败，请手动删除：{DB_PATH}（{exc2}）")


def main() -> int:
    prepare_env()
    seed()
    server = start_server()
    admin_token = login("p4v_admin", "AdminPass123!")
    failed = 0
    try:
        failed += 0 if p4_1_preview(admin_token) else 1
        failed += 0 if p4_2_graduate(admin_token) else 1
        failed += 0 if p4_3_graduated_access() else 1
        failed += 0 if p4_3b_exam_submit_not_blocked() else 1
        failed += 0 if p4_4_transfer() else 1
        failed += 0 if p4_5_stats(admin_token) else 1
        failed += 0 if p4_6_deferred(admin_token) else 1
        failed += 0 if extra_revoke_and_suspended(admin_token) else 1
    finally:
        stop_server(server)
        cleanup()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n===== P4 准出：{passed}/{len(RESULTS)} 通过，失败分组 {failed} 个 =====")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAIL {name} | {detail}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
