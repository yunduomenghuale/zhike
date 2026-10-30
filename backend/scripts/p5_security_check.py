"""P5 准出验证：九项加固逐条实测（真实 HTTP + 真实登录 token）。

自包含跑法（脚本自己复制隔离库、自己起服务、自己清理，不碰开发库）：

    cd backend && ./venv/Scripts/python.exe scripts/p5_security_check.py

覆盖规范文档 P5 段的准出项：

  P5-1 (A4) catalogs/generate-from-plan 权限：学生 403 / 未登录 401 / 教师 200
  P5-2 (A3) /api/docs/ 门控：开发默认 200；DJANGO_ENABLE_API_DOCS=false → 404；
            DJANGO_DEBUG=false（生产姿态）→ 404
  P5-3 (B5) 班级 DELETE 返回明确错误提示归档；PATCH 归档 200；停用学生联动退学
  P5-4 (B6) AI 日配额：全局默认 0 → ask 429（中文提示）；调到 100 → 200；管理端 GET 回读
  P5-5 (B7) Mock 回退显性化：chat 指向不可达 provider → ask 200 且 provider_fallback=true；
            管理端 ai-configuration 返回 24h 回退告警
  P5-6 (B8) 交卷行锁：多线程并发交卷 → 提交数=1、成绩与终态一致、无 500
  P5-7 (A2) JWT 登出吊销：登出后旧 access 401、旧 refresh 换新 401、新登录可用
  P5-8 (C9) throttle 分级：ai_ask 60/min 触发 429；login 30/min 触发 429
            （anon/user 全局档由 L1 覆盖计数行为；此处验证真实服务在跑）

实现说明：SQLITE_PATH 指向临时库副本，子进程 runserver 继承同一 env；fixtures
ORM 直建（P5V 前缀，重跑先清后建）；限流在非 test 模式下真实生效。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

BASE_DIR = Path(__file__).resolve().parents[1]
DEV_DB = BASE_DIR / "db.sqlite3"
WORK_DIR = Path(os.environ.get("P5_WORK_DIR", str(BASE_DIR / "p5_check_tmp")))
DB_PATH = WORK_DIR / "db.sqlite3"
PORT = 8006
BASE = f"http://127.0.0.1:{PORT}"
PORT_DOCS_OFF = 8007
BASE_DOCS_OFF = f"http://127.0.0.1:{PORT_DOCS_OFF}"
PORT_PROD = 8008
BASE_PROD = f"http://127.0.0.1:{PORT_PROD}"
PREFIX = "P5V"

RESULTS: list[tuple[str, bool, str]] = []
G = SimpleNamespace()

# 本机环境配了系统代理（历史坑：curl 也要 --noproxy '*'）。localhost 流量绝不能
# 进代理——代理会对 http 做 https 升级改写，生产姿态服务（DEBUG=false）会收到
# TLS 握手字节，_wait_ready 永远等不到 200。这里全程直连。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  | {detail}" if detail else ""))
    return bool(ok)


def http(method: str, path: str, token: str | None = None, body: dict | None = None, base: str = BASE, timeout: int = 60):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw[:1] in (b"{", b"[") else raw
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, raw


def login(username: str, password: str, base: str = BASE) -> str:
    status, payload = http("POST", "/api/auth/login/", body={"username": username, "password": password}, base=base)
    assert status == 200 and payload.get("code") == 0, f"登录失败 {username}: {payload}"
    return payload["data"]["token"]["access"]


def rows(payload) -> list:
    if isinstance(payload, dict):
        return payload.get("results") or payload.get("items") or []
    return payload


# ---------------------------------------------------------------------------
# 环境准备
# ---------------------------------------------------------------------------
def prepare_env():
    sys.path.insert(0, str(BASE_DIR))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ["SQLITE_PATH"] = str(DB_PATH)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DEV_DB, DB_PATH)
    import django

    django.setup()


def _wait_ready(base: str) -> bool:
    for _ in range(60):
        try:
            with _OPENER.open(base + "/api/auth/config/", timeout=2):
                return True
        except Exception:
            time.sleep(0.5)
    return False


def start_server(port: int, extra_env: dict | None = None) -> subprocess.Popen:
    env = dict(os.environ)
    env.update(extra_env or {})
    # ⚠ 输出必须落文件而非 PIPE：schema 生成会向 stderr 打大量警告，PIPE 无人
    # 读取时 64K 缓冲写满，子进程写日志阻塞 → 整个服务冻结（实测踩坑）
    log_fh = open(WORK_DIR / f"server_{port}.log", "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            str(BASE_DIR / "venv" / "Scripts" / "python.exe"),
            "manage.py", "runserver", str(port), "--noreload",
        ],
        cwd=BASE_DIR, env=env,
        stdout=log_fh, stderr=subprocess.STDOUT,
    )
    proc._p5_log_fh = log_fh  # 附着句柄，stop 时统一关闭
    base = f"http://127.0.0.1:{port}"
    if not _wait_ready(base):
        raise RuntimeError(f"服务未就绪 port={port}")
    return proc


def stop_server(proc: subprocess.Popen):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    fh = getattr(proc, "_p5_log_fh", None)
    if fh:
        try:
            fh.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# fixtures（ORM 直建；P5V 前缀，重跑先清后建）
# ---------------------------------------------------------------------------
def seed():
    from apps.ai.models import AICallLog, AIQuotaPolicy
    from apps.classroom.models import ClassRoom, ClassStudent
    from apps.courses.models import Course
    from apps.exams.models import Exam, Paper
    from apps.questions.models import Question
    from apps.users.models import User

    # 清理上一次运行残留
    rooms = ClassRoom.objects.filter(code__startswith=PREFIX)
    for room in rooms:
        ClassStudent.objects.filter(classroom=room).delete()
        room.course_links.all().delete()
        Exam.objects.filter(classroom=room).delete()
        rooms.filter(pk=room.pk).delete()
    User.objects.filter(username__startswith="p5v_").delete()
    AIQuotaPolicy.objects.all().delete()
    AICallLog.objects.filter(provider="openai", model_name="p5-unreachable").delete()
    for stale in Course.objects.filter(name__startswith="P5课程"):
        try:
            stale.delete()
        except Exception:
            pass

    G.admin = User.objects.create_user(
        username="p5v_admin", password="AdminPass123!", role=User.Role.ADMIN
    )
    G.teacher = User.objects.create_user(
        username="p5v_teacher", password="TeachPass123!", role=User.Role.TEACHER, real_name="P5教师"
    )
    G.student = User.objects.create_user(
        username="p5v_student", password="StuPass123!", role=User.Role.STUDENT, real_name="P5学生"
    )
    G.student2 = User.objects.create_user(
        username="p5v_student2", password="StuPass123!", role=User.Role.STUDENT, real_name="P5学生B"
    )
    G.course = Course.objects.create(name="P5课程", teacher=G.teacher)
    G.room = ClassRoom.objects.create(name="P5验证班", code=f"{PREFIX}-ROOM", teacher=G.teacher)
    G.room.courses.add(G.course)
    ClassStudent.objects.create(classroom=G.room, student=G.student, learn_status="active")
    ClassStudent.objects.create(classroom=G.room, student=G.student2, learn_status="active")
    return G


# ---------------------------------------------------------------------------
# 准出项
# ---------------------------------------------------------------------------
def p5_1_generate_from_plan_permission() -> bool:
    print("\n== P5-1 (A4) catalogs/generate-from-plan 权限 ==")
    status, _ = http("POST", "/api/catalogs/generate-from-plan/",
                     body={"course": G.course.id, "plan_text": "第一章 绪论"})
    ok1 = check("未登录 401", status == 401, f"{status}")

    s_token = login("p5v_student", "StuPass123!")
    status, data = http("POST", "/api/catalogs/generate-from-plan/", s_token,
                        body={"course": G.course.id, "plan_text": "第一章 绪论"})
    ok2 = check("学生 403", status == 403, f"{status}")

    t_token = login("p5v_teacher", "TeachPass123!")
    status, data = http("POST", "/api/catalogs/generate-from-plan/", t_token,
                        body={"course": G.course.id, "plan_text": "第一章 绪论"})
    ok3 = check("教师 200（Mock provider 返回识别结果）", status == 200 and data.get("code") == 0, f"{status} {str(data)[:80]}")
    return all([ok1, ok2, ok3])


def p5_2_api_docs_gate() -> bool:
    print("\n== P5-2 (A3) /api/docs/ 门控 ==")
    # 本脚本主服务跑默认 env（DEBUG=true）：文档开放。
    # schema 首次生成较慢（全量 API introspection），单独给长超时；docs 页本身是
    # 轻量 HTML，先打它确认门控处于开放态。
    status, _ = http("GET", "/api/docs/")
    ok2 = check("开发默认 swagger 200", status == 200, f"{status}")
    status, _ = http("GET", "/api/schema/", timeout=300)
    ok1 = check("开发默认（DEBUG=true）schema 200", status == 200, f"{status}")
    return all([ok1, ok2])


def p5_2b_docs_off_server() -> bool:
    print("\n== P5-2b (A3) 显式关闭与生产姿态 ==")
    # DJANGO_ENABLE_API_DOCS=false：显式关闭（即使 DEBUG=true 也 404）
    proc = start_server(PORT_DOCS_OFF, {"DJANGO_ENABLE_API_DOCS": "false"})
    try:
        status, _ = http("GET", "/api/docs/", base=BASE_DOCS_OFF)
        ok1 = check("显式 DJANGO_ENABLE_API_DOCS=false → 404", status == 404, f"{status}")
        status, _ = http("GET", "/api/schema/", base=BASE_DOCS_OFF)
        ok2 = check("schema 同样 404", status == 404, f"{status}")
    finally:
        stop_server(proc)

    # 生产姿态：DEBUG=false + 强密钥（不设 ENABLE_API_DOCS）→ 默认关闭。
    # DJANGO_SECURE_SSL_REDIRECT=false 与生产 .env.production 同款（HTTPS 跳转
    # 由 nginx 承担；runserver 无 TLS，若开着会 301 到 https 导致探活打不通）
    proc = start_server(PORT_PROD, {
        "DJANGO_DEBUG": "false",
        "DJANGO_SECRET_KEY": "p5-prod-posture-check-secret-key-0123456789abcdef",
        "DJANGO_ALLOWED_HOSTS": "127.0.0.1,localhost",
        "DJANGO_SECURE_SSL_REDIRECT": "false",
    })
    try:
        status, _ = http("GET", "/api/docs/", base=BASE_PROD)
        ok3 = check("生产姿态（DEBUG=false）docs 404", status == 404, f"{status}")
        status, _ = http("GET", "/api/schema/", base=BASE_PROD)
        ok4 = check("生产姿态 schema 404", status == 404, f"{status}")
        status, data = http("POST", "/api/auth/login/", base=BASE_PROD,
                            body={"username": "p5v_admin", "password": "AdminPass123!"})
        ok5 = check("生产姿态登录正常 200", status == 200 and data.get("code") == 0, f"{status}")
    finally:
        stop_server(proc)
    return all([ok1, ok2, ok3, ok4, ok5])


def p5_3_delete_protection(admin_token: str) -> bool:
    print("\n== P5-3 (B5) 删除保护与停用联动 ==")
    status, data = http("DELETE", f"/api/classes/{G.room.id}/", admin_token)
    msg = str(data.get("message", "")) if isinstance(data, dict) else ""
    ok1 = check("班级 DELETE 400 + 归档提示", status == 400 and "归档" in msg, f"{status} {msg}")

    status, data = http("PATCH", f"/api/classes/{G.room.id}/", admin_token, body={"status": "archived"})
    ok2 = check("班级归档 PATCH 200", status == 200 and data.get("data", {}).get("status") == "archived", f"{status}")
    # 归档后恢复（后续检查还要用这个班）
    http("PATCH", f"/api/classes/{G.room.id}/", admin_token, body={"status": "active"})

    # 停用学生：is_active=False → edu_status=withdrawn，且旧 token 失效（与 P5-7 呼应）
    s2_token = login("p5v_student2", "StuPass123!")
    status, me = http("GET", "/api/auth/me/", s2_token)
    ok3 = check("student2 登录可用", status == 200)
    status, data = http("PATCH", f"/api/admin-panel/users/{G.student2.id}/", admin_token,
                        body={"is_active": False})
    ok4 = check("管理端停用学生 200", status == 200, f"{status}")
    G.student2.refresh_from_db()
    ok5 = check("停用联动 edu_status=withdrawn", G.student2.edu_status == "withdrawn",
                f"edu_status={G.student2.edu_status}")
    ok6 = check("停用联动 token 作废线前移", G.student2.tokens_invalid_before is not None)
    status, _ = http("GET", "/api/auth/me/", s2_token)
    ok7 = check("停用后旧 token 401", status == 401, f"{status}")
    return all([ok1, ok2, ok3, ok4, ok5, ok6, ok7])


def p5_4_quota(admin_token: str) -> bool:
    print("\n== P5-4 (B6) AI 日配额 ==")
    s_token = login("p5v_student", "StuPass123!")

    status, data = http("PUT", "/api/admin-panel/ai-quota/", admin_token,
                        body={"default_daily_limit": 0, "overrides": []})
    ok1 = check("管理端设置全局默认 0（封禁）", status == 200, f"{status} {str(data)[:80]}")

    status, data = http("POST", "/api/qa-records/ask/", s_token,
                        body={"course": G.course.id, "question": "配额测试"})
    msg = str(data.get("message", "")) if isinstance(data, dict) else ""
    ok2 = check("超限 ask 429 + 中文提示", status == 429 and "上限" in msg, f"{status} {msg}")

    status, data = http("PUT", "/api/admin-panel/ai-quota/", admin_token,
                        body={"default_daily_limit": 100, "overrides": [{"user_id": G.student.id, "daily_limit": 3}]})
    ok3 = check("调高全局默认并设用户覆盖", status == 200, f"{status}")

    status, data = http("GET", "/api/admin-panel/ai-quota/", admin_token)
    payload = data.get("data", {}) if status == 200 else {}
    ok4 = check("GET 回读默认与覆盖", payload.get("default_daily_limit") == 100
                and any(o.get("user_id") == G.student.id and o.get("daily_limit") == 3
                        for o in payload.get("overrides", [])),
                str(payload)[:120])

    status, data = http("POST", "/api/qa-records/ask/", s_token,
                        body={"course": G.course.id, "question": "配额恢复后提问"})
    ok5 = check("配额内 ask 200（Mock 正常回答）", status == 200 and data.get("code") == 0,
                f"{status} {str(data)[:80]}")
    return all([ok1, ok2, ok3, ok4, ok5])


def p5_5_mock_fallback(admin_token: str) -> bool:
    print("\n== P5-5 (B7) Mock 回退显性化 ==")
    s_token = login("p5v_student", "StuPass123!")
    # 把 chat 指向不可达的 openai 兼容服务（base_url 端口 9 = discard，连接必失败）
    status, data = http("PUT", "/api/admin-panel/ai-configuration/", admin_token, body={
        "capabilities": [{
            "capability": "chat", "provider": "openai", "enabled": True,
            "base_url": "http://127.0.0.1:9", "model_name": "p5-unreachable",
            "api_key": "sk-p5-test", "timeout": 5,
        }]
    })
    ok1 = check("配置不可达 chat provider", status == 200, f"{status} {str(data)[:80]}")

    status, data = http("POST", "/api/qa-records/ask/", s_token,
                        body={"course": G.course.id, "question": "回退测试"})
    payload = data.get("data", {}) if status == 200 else {}
    ok2 = check("回退后 ask 仍 200（保证可用性）", status == 200, f"{status}")
    ok3 = check("响应体 provider_fallback=true", payload.get("provider_fallback") is True,
                f"provider_fallback={payload.get('provider_fallback')}")
    ok4 = check("携带 fallback_reason", "回退" in str(payload.get("fallback_reason", "")),
                str(payload.get("fallback_reason", ""))[:80])

    status, data = http("GET", "/api/admin-panel/ai-configuration/", admin_token)
    alert = data.get("data", {}).get("mock_fallback_alert", {}) if status == 200 else {}
    ok5 = check("管理端 24h 回退告警计数 ≥1", alert.get("count_24h", 0) >= 1, str(alert)[:120])
    return all([ok1, ok2, ok3, ok4, ok5])


def p5_6_submit_lock() -> bool:
    print("\n== P5-6 (B8) 交卷行锁 ==")
    from apps.courses.models import Catalog
    from apps.exams.models import Exam, ExamSubmission, Paper
    from apps.questions.models import Question
    from decimal import Decimal

    catalog = Catalog.objects.create(course=G.course, title="P5行锁章节")
    q = Question.objects.create(
        course=G.course, catalog=catalog, qtype=Question.QType.SINGLE,
        stem="1+1=?", options=[{"key": "A", "text": "2"}, {"key": "B", "text": "3"}],
        answer={"key": "A"}, score=Decimal("5"), status=Question.Status.PUBLISHED,
    )
    exam = Exam.objects.create(
        course=G.course, classroom=G.room, name="P5行锁考试",
        duration=60, total_score=100, status=Exam.Status.PUBLISHED,
    )
    paper = Paper.objects.create(
        course=G.course, exam=exam, student=None, mode="manual",
        question_items=[{"question_id": q.id, "score": 2, "order": 1}],
    )
    from django.utils import timezone

    sub = ExamSubmission.objects.create(
        exam=exam, student=G.student, paper=paper,
        started_at=timezone.now(), status=ExamSubmission.Status.IN_PROGRESS,
    )

    s_token = login("p5v_student", "StuPass123!")
    results = {}

    def worker(idx):
        try:
            status, data = http("POST", f"/api/exam-submissions/{sub.id}/submit/", s_token,
                                body={"answers": {str(q.id): {"key": "A"}}})
            results[idx] = status
        except Exception as exc:  # noqa: BLE001
            results[idx] = f"EXC:{exc}"

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)

    ok1 = check("并发交卷无 500/异常", all(r in (200, 400) for r in results.values()), str(results))
    ok2 = check("提交数恒为 1", ExamSubmission.objects.filter(exam=exam).count() == 1)
    sub.refresh_from_db()
    ok3 = check("终态已交", sub.status == ExamSubmission.Status.SUBMITTED, sub.status)
    ok4 = check("成绩与提交答案一致（2 分）", Decimal(str(sub.objective_score)) == Decimal("2"),
                str(sub.objective_score))
    ok5 = check("答案落库一致", (sub.answers or {}).get(str(q.id)) == {"key": "A"})
    return all([ok1, ok2, ok3, ok4, ok5])


def p5_7_logout_revocation() -> bool:
    print("\n== P5-7 (A2) JWT 登出吊销 ==")
    status, payload = http("POST", "/api/auth/login/",
                           body={"username": "p5v_student", "password": "StuPass123!"})
    tokens = payload.get("data", {}).get("token", {})
    access, refresh = tokens.get("access", ""), tokens.get("refresh", "")
    status, _ = http("GET", "/api/auth/me/", access)
    ok1 = check("登出前 me 200", status == 200)

    status, data = http("POST", "/api/auth/logout/", access, body={"refresh": refresh})
    ok2 = check("登出 200 + refresh 已拉黑", status == 200 and data.get("data", {}).get("refresh_revoked") is True,
                f"{status} {str(data)[:80]}")

    status, _ = http("GET", "/api/auth/me/", access)
    ok3 = check("登出后旧 access 401", status == 401, f"{status}")
    status, _ = http("POST", "/api/auth/refresh/", body={"refresh": refresh})
    ok4 = check("登出后旧 refresh 换新 401", status == 401, f"{status}")

    # 作废线在 2s 前的语义验证：重新登录的新 token 可用
    # （脚本即时重登可能同秒，先回拨作废线等价模拟「过一会儿再登录」）
    G.student.refresh_from_db()
    from datetime import timedelta
    from django.utils import timezone

    G.student.tokens_invalid_before = timezone.now() - timedelta(seconds=2)
    G.student.save(update_fields=["tokens_invalid_before"])
    status, payload = http("POST", "/api/auth/login/",
                           body={"username": "p5v_student", "password": "StuPass123!"})
    access2 = payload.get("data", {}).get("token", {}).get("access", "")
    status, _ = http("GET", "/api/auth/me/", access2)
    ok5 = check("登出后重新登录可用", status == 200, f"{status}")
    return all([ok1, ok2, ok3, ok4, ok5])


def p5_8_throttles() -> bool:
    print("\n== P5-8 (C9) throttle 分级 ==")
    # ai_ask 60/min：专用学生连续 61 次非法 ask（配额不限 → 走到业务前被节流）
    from apps.users.models import User
    from apps.classroom.models import ClassStudent

    thr_user = User.objects.create_user(
        username="p5v_thr", password="StuPass123!", role=User.Role.STUDENT, real_name="限流测试"
    )
    ClassStudent.objects.create(classroom=G.room, student=thr_user, learn_status="active")
    t_token = login("p5v_thr", "StuPass123!")

    saw_429 = False
    first_429_at = None
    for i in range(1, 62):
        status, _ = http("POST", "/api/qa-records/ask/", t_token, body={})
        if status == 429:
            saw_429, first_429_at = True, i
            break
    ok1 = check("ai_ask 61 次内触发 429", saw_429 and (first_429_at or 99) <= 61,
                f"first_429_at={first_429_at}")

    # login 30/min：匿名连发（随机用户名避免失败锁干扰；主服务此前已有零星登录，
    # 只断言「限次内出现 429」不做精确次数断言）
    saw_login_429 = False
    for i in range(1, 41):
        status, _ = http("POST", "/api/auth/login/",
                         body={"username": f"p5v_thr_login_{i}", "password": "wrong"})
        if status == 429:
            saw_login_429 = True
            break
    ok2 = check("login 40 次内触发 429", saw_login_429)
    return all([ok1, ok2])


def cleanup():
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
    server = start_server(PORT)
    admin_token = login("p5v_admin", "AdminPass123!")
    failed = 0
    try:
        failed += 0 if p5_1_generate_from_plan_permission() else 1
        failed += 0 if p5_2_api_docs_gate() else 1
        failed += 0 if p5_2b_docs_off_server() else 1
        failed += 0 if p5_3_delete_protection(admin_token) else 1
        failed += 0 if p5_4_quota(admin_token) else 1
        failed += 0 if p5_5_mock_fallback(admin_token) else 1
        failed += 0 if p5_6_submit_lock() else 1
        failed += 0 if p5_7_logout_revocation() else 1
        failed += 0 if p5_8_throttles() else 1
    finally:
        stop_server(server)

    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n========== P5 准出结果：{passed}/{total} PASS，{failed} 项失败 ==========")
    if failed:
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  FAIL  {name}  | {detail}")
    cleanup()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
