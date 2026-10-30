"""MySQL 升级专项验收（上线前最后一次全链路检查）。

## 为什么单独写

`manage.py test` 的 712 个用例是"功能正确性"，它们大多不关心方言差异；而
SQLite→MySQL 的风险恰恰集中在方言面：事务与行锁、条件唯一约束、JSON 列检索、
按本地日分组、排序规则、分页性能。本脚本用**真实 HTTP 链路**（DRF APIClient +
真实 JWT 认证链 + 真实数据库）逐项验证这些点，作为切换后的准出证据。

## 覆盖矩阵

| 组 | 关注点 | 为什么在 MySQL 上才可能出问题 |
|---|---|---|
| G1 认证 | 登录/刷新/匿名拦截/管理员边界 | JWT 吊销查库、权限类 |
| G2 课程章节 | 列表/树形/学生可见范围 | `distinct()` + join |
| G3 考试 | 开考/暂存/交卷/成绩发布/并发交卷 | **save 依赖 select_for_update，MySQL 真行锁** |
| G4 作业 | 列表/提交/重复提交/批改可见性 | 唯一约束、成绩门控 |
| G5 RAG | 向量检索/跨课程隔离/问答落库 | **embedding 存 JSON 列，exclude(embedding=[])** |
| G6 统计 | 看板趋势/时区日界/Excel 导出/督管概览 | **TruncDate 走 CONVERT_TZ** |
| G7 检索 | 分页/中文搜索/大小写/排序 | utf8mb4_0900_ai_ci 排序规则 |
| G8 约束稳定性 | 重复入班/AI 任务防双跑/连续请求 | **生成列唯一索引、连接复用** |

## 跑法

    set E2E_DATABASE_URL=mysql://zk:zk123456@127.0.0.1:3306/zk_e2e
    python scripts/mysql_upgrade_check.py

E2E 库建议先克隆开发库（否则缺 t101 等真实账号）：

    mysqldump -uzk -p --single-transaction --set-gtid-purged=OFF zk | mysql -uzk -p zk_e2e

脚本只造 `MYCHK` 前缀的夹具，结束时清理；AI 能力临时切成 mock，避免打真实大模型。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "scripts"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from _e2e_db import ensure_schema, prepare  # noqa: E402

print(f"[db] {prepare(BASE_DIR / 'db.sqlite3', BASE_DIR / 'db.sqlite3', BASE_DIR)}")

import django  # noqa: E402

django.setup()
ensure_schema()

from django.db import IntegrityError, connection, transaction  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.ai.models import AICallLog, AICapabilityConfig, AITask  # noqa: E402
from apps.classroom.models import ClassRoom  # noqa: E402
from apps.classroom.services import assign_students  # noqa: E402
from apps.courses.models import Course  # noqa: E402
from apps.exams.models import Exam, ExamSubmission  # noqa: E402
from apps.homework.models import Homework, HomeworkSubmission  # noqa: E402
from apps.knowledge.models import KnowledgeChunk, QARecord  # noqa: E402
from apps.users.models import User  # noqa: E402

PASSWORD = "mychk123456!"
COURSE_ID = 7  # Java程序设计（t101，146 个片段）
EXAM_ID = 27  # 第2章 章节测验（班级 3，4 题，10 分，进行中）
CLASS_ID = 3

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, ok, detail: str = "") -> bool:
    ok = bool(ok)
    (PASS if ok else FAIL).append(label)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  | {detail}" if detail else ""))
    return ok


def client_for(username: str, password: str = "pass1234") -> APIClient:
    c = APIClient()
    c.raise_request_exception = False
    resp = c.post("/api/auth/login/", {"username": username, "password": password}, format="json")
    assert resp.status_code == 200, f"登录失败 {username}: {resp.status_code} {resp.data}"
    token = resp.data["data"]["token"]["access"]
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    c._token = token  # noqa: SLF001 - 供并发用例复用
    return c


def body(resp):
    """剥掉统一响应壳 {code, message, data}；DRF 原生 201 直接返回对象时原样返回。"""
    data = getattr(resp, "data", None)
    if isinstance(data, dict) and "code" in data and "data" in data:
        return data["data"]
    return data


def rows(payload) -> list:
    """列表行提取：统一响应壳内是 results（DRF 分页）/ items（手写分页）/ 裸 list。"""
    if isinstance(payload, dict):
        return payload.get("results") or payload.get("items") or []
    return payload if isinstance(payload, list) else []


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def build_fixture():
    course = Course.objects.get(id=COURSE_ID)
    classroom = ClassRoom.objects.get(id=CLASS_ID)
    fx = {"course": course, "classroom": classroom}

    fx["s1"] = User.objects.create_user(
        username="MYCHK_s1", password=PASSWORD, role=User.Role.STUDENT, real_name="验收学生1"
    )
    fx["s2"] = User.objects.create_user(
        username="MYCHK_s2", password=PASSWORD, role=User.Role.STUDENT, real_name="验收学生2"
    )
    assign_students(classroom, [fx["s1"], fx["s2"]], note="MySQL 升级验收")

    fx["hw"] = Homework.objects.create(
        classroom=classroom,
        course=course,
        title="MYCHK作业-附件模式",
        description="验收用",
        mode=Homework.Mode.ATTACHMENT,
        status=Homework.Status.PUBLISHED,
        total_score=100,
    )
    return fx


def cleanup(fx):
    HomeworkSubmission.objects.filter(homework=fx["hw"]).delete()
    Homework.objects.filter(id=fx["hw"].id).delete()
    ExamSubmission.objects.filter(exam_id=EXAM_ID, student__username__startswith="MYCHK_").delete()
    ExamSubmission.objects.filter(exam_id=26, student__username__startswith="MYCHK_").delete()
    QARecord.objects.filter(student__username__startswith="MYCHK_").delete()
    AICallLog.objects.filter(provider="mychk_probe").delete()
    AITask.objects.filter(triggered_by__username__startswith="MYCHK_").delete()
    User.objects.filter(username__startswith="MYCHK_").delete()  # queryset 删除绕过 User.delete 保护


# ---------------------------------------------------------------------------
# G1 认证
# ---------------------------------------------------------------------------
def g1_auth(fx):
    print("\n== G1 认证与权限边界 ==")
    t = APIClient()
    t.raise_request_exception = False
    r = t.post("/api/auth/login/", {"username": "t101", "password": "pass1234"}, format="json")
    check("教师登录 200", r.status_code == 200, str(r.status_code))
    token_data = r.data["data"]["token"]
    t.credentials(HTTP_AUTHORIZATION=f"Bearer {token_data['access']}")

    r = t.get("/api/courses/")
    check("教师课程列表 200", r.status_code == 200, str(r.status_code))

    anon = APIClient()
    anon.raise_request_exception = False
    r = anon.get("/api/courses/")
    check("匿名访问业务接口 401", r.status_code == 401, str(r.status_code))

    s = client_for("MYCHK_s1", PASSWORD)
    r = s.get("/api/admin-panel/qa-quality-stats/")
    check("学生访问管理端 403", r.status_code == 403, str(r.status_code))

    r = t.post("/api/auth/refresh/", {"refresh": token_data["refresh"]}, format="json")
    check("refresh 换新 access 200", r.status_code == 200, str(r.status_code))
    return t, s


# ---------------------------------------------------------------------------
# G2 课程与章节
# ---------------------------------------------------------------------------
def g2_course(t, s):
    print("\n== G2 课程与章节 ==")
    r = t.get("/api/courses/")
    ids = [row["id"] for row in rows(body(r))] if r.status_code == 200 else []
    check("教师课程列表含课程7", COURSE_ID in ids, f"ids={ids[:8]}")

    r = t.get(f"/api/catalogs/?course={COURSE_ID}&tree=1")
    check("章节树 tree=1 200", r.status_code == 200, str(r.status_code))
    roots = rows(body(r))
    check("章节树返回根节点", len(roots) > 0, f"根节点 {len(roots)}")

    r = s.get("/api/courses/")
    sids = [row["id"] for row in rows(body(r))] if r.status_code == 200 else []
    check("学生可见在读课程7", COURSE_ID in sids, f"ids={sids}")


# ---------------------------------------------------------------------------
# G3 考试（核心：save 事务 + 行锁 + 成绩可见性）
# ---------------------------------------------------------------------------
def g3_exam(t, s):
    print("\n== G3 考试（暂存/交卷/发布/并发）==")
    exam = Exam.objects.get(id=EXAM_ID)
    paper = exam.papers.first()
    qids = [item["question_id"] for item in paper.question_items]

    r = s.post("/api/exam-submissions/start/", {"exam": EXAM_ID}, format="json")
    check("学生开考 200", r.status_code == 200, f"{r.status_code} {str(r.data)[:80]}")
    if r.status_code != 200:
        return
    sub_id = (body(r) or {}).get("submission", {}).get("id")

    answers = {str(qid): {"value": "A"} for qid in qids}
    r = s.post(f"/api/exam-submissions/{sub_id}/save/", {"answers": answers}, format="json")
    check("暂存答案 200（save 的事务修复）", r.status_code == 200, f"{r.status_code} {str(r.data)[:100]}")

    sub = ExamSubmission.objects.get(id=sub_id)
    check("暂存已落库", bool(sub.answers) and sub.saved_at is not None, f"answers={len(sub.answers)}")
    check("暂存后状态仍 in_progress", sub.status == ExamSubmission.Status.IN_PROGRESS, sub.status)

    r = s.post(f"/api/exam-submissions/{sub_id}/submit/", {"answers": answers}, format="json")
    check("交卷 200", r.status_code == 200, f"{r.status_code} {str(r.data)[:80]}")

    r = s.post(f"/api/exam-submissions/{sub_id}/submit/", {"answers": answers}, format="json")
    check("重复交卷被拒 400", r.status_code == 400, str(r.status_code))

    r = s.post(f"/api/exam-submissions/{sub_id}/save/", {"answers": answers}, format="json")
    check("交卷后暂存被拒 400", r.status_code == 400, str(r.status_code))

    sub.refresh_from_db()
    check("交卷后状态 submitted", sub.status == ExamSubmission.Status.SUBMITTED, sub.status)
    check("客观题自动判分已出", sub.total_score is not None, f"total={sub.total_score}")

    r = s.get(f"/api/exam-submissions/{sub_id}/review/")
    leaked = r.status_code == 200 and r.data.get("data", {}).get("score_released") is False
    check("成绩未发布时 review 标记未发布", leaked, f"{r.status_code} released={r.data.get('data', {}).get('score_released')}")

    r = t.post(f"/api/exams/{EXAM_ID}/release-scores/")
    check("教师发布成绩 200", r.status_code == 200, f"{r.status_code} {str(r.data)[:80]}")

    r = s.get(f"/api/exam-submissions/{sub_id}/review/")
    ok = r.status_code == 200 and r.data.get("data", {}).get("score_released") is True
    check("发布后 review 可见成绩", ok, f"released={r.data.get('data', {}).get('score_released') if r.status_code == 200 else r.status_code}")


def g3_concurrent(t):
    """并发交卷：同一答卷两线程同时提交，只能成功一次（MySQL 真行锁）。"""
    print("\n== G3b 并发交卷 ==")
    s2 = client_for("MYCHK_s2", PASSWORD)
    r = s2.post("/api/exam-submissions/start/", {"exam": 26}, format="json")
    if r.status_code != 200:
        check("并发交卷前置：开考 200", False, f"{r.status_code} {str(r.data)[:80]}")
        return
    sub_id = (body(r) or {}).get("submission", {}).get("id")
    token = s2._token  # noqa: SLF001
    results = []
    lock = threading.Lock()

    def submit():
        c = APIClient()
        c.raise_request_exception = False
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        resp = c.post(f"/api/exam-submissions/{sub_id}/submit/", {"answers": {}}, format="json")
        with lock:
            results.append(resp.status_code)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=60)

    check("并发交卷无 500", all(code < 500 for code in results), str(sorted(results)))
    check("并发交卷只成功一次", results.count(200) == 1, str(sorted(results)))
    n = ExamSubmission.objects.filter(id=sub_id, status=ExamSubmission.Status.SUBMITTED).count()
    check("最终只有一条已提交答卷", n == 1, f"count={n}")


# ---------------------------------------------------------------------------
# G4 作业
# ---------------------------------------------------------------------------
def g4_homework(t, s, fx):
    print("\n== G4 作业 ==")
    r = s.get("/api/homeworks/")
    ids = [row["id"] for row in rows(body(r))] if r.status_code == 200 else []
    check("学生作业列表含自建作业", fx["hw"].id in ids, f"ids={ids[:8]}")

    r = s.post(
        "/api/homework-submissions/",
        {"homework": fx["hw"].id, "content": "MySQL 验收提交内容"},
        format="json",
    )
    check("作业提交 201", r.status_code == 201, f"{r.status_code} {str(r.data)[:120]}")
    submit_payload = body(r) or {}
    sub_id = submit_payload.get("id") if isinstance(submit_payload, dict) else None

    r = s.post(
        "/api/homework-submissions/",
        {"homework": fx["hw"].id, "content": "重复提交"},
        format="json",
    )
    check("重复提交被拒 400（非 500）", r.status_code in (400, 409), f"{r.status_code} {str(getattr(r, 'data', r.content[:80]))[:100]}")

    if sub_id:
        r = t.post(f"/api/homework-submissions/{sub_id}/grade/", {"score": 88, "comment": "验收批改"}, format="json")
        check("教师批改 200", r.status_code == 200, f"{r.status_code} {str(r.data)[:100]}")
        r = t.post(f"/api/homework-submissions/{sub_id}/release/", {}, format="json")
        check("教师发布成绩 200", r.status_code == 200, f"{r.status_code} {str(r.data)[:100]}")
        r = s.get(f"/api/homework-submissions/{sub_id}/")
        score = (body(r) or {}).get("score") if r.status_code == 200 else None
        check("发布后学生可见分数", str(score) in ("88", "88.0"), f"score={score}")


# ---------------------------------------------------------------------------
# G5 RAG 检索（JSON 向量）
# ---------------------------------------------------------------------------
def g5_rag(s):
    print("\n== G5 向量检索与问答 ==")
    from apps.ai.vectorstore import cosine, search_chunks

    chunk = KnowledgeChunk.objects.filter(course_id=COURSE_ID).exclude(embedding=[]).first()
    check("存在带向量的片段", chunk is not None, f"chunk={getattr(chunk, 'id', None)}")
    if chunk is None:
        return

    hits = search_chunks(COURSE_ID, chunk.embedding, top_k=5)
    check("用片段自身向量可召回自己", any(h[0].id == chunk.id for h in hits), f"hits={len(hits)}")
    top_score = hits[0][1] if hits else 0.0
    check(
        "自召回相似度为 1",
        bool(hits) and abs(cosine(chunk.embedding, hits[0][0].embedding) - 1.0) < 1e-6,
        f"top={top_score:.4f}",
    )

    other = KnowledgeChunk.objects.exclude(course_id=COURSE_ID).exclude(embedding=[]).first()
    if other:
        hits2 = search_chunks(COURSE_ID, other.embedding, top_k=5)
        check("跨课程片段不混入（课程隔离）",
              all(h[0].course_id == COURSE_ID for h in hits2), f"hits={len(hits2)}")

    qa_before = QARecord.objects.count()
    r = s.post("/api/qa-records/ask/", {"course": COURSE_ID, "question": "Java 语言有什么特点？"}, format="json")
    check("知识库问答 200", r.status_code == 200, f"{r.status_code} {str(r.data)[:120]}")
    check("问答记录已落库", QARecord.objects.count() == qa_before + 1,
          f"{qa_before}→{QARecord.objects.count()}")
    rec = QARecord.objects.order_by("-id").first()
    check("cited_chunks 是合法 JSON 数组", isinstance(rec.cited_chunks, list), f"type={type(rec.cited_chunks).__name__}")

    r = s.post("/api/qa-records/ask/", {"course": COURSE_ID, "question": "   "}, format="json")
    check("空问题被拒 400", r.status_code == 400, str(r.status_code))


# ---------------------------------------------------------------------------
# G6 统计与导出（时区 + 聚合）
# ---------------------------------------------------------------------------
def admin_client() -> APIClient:
    c = APIClient()
    c.raise_request_exception = False
    r = c.post("/api/auth/login/", {"username": "admin", "password": "A0987654"}, format="json")
    assert r.status_code == 200, f"admin 登录失败: {r.status_code} {getattr(r, 'data', '')}"
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['data']['token']['access']}")
    return c


def g6_stats(t, s, fx):
    print("\n== G6 看板/统计/导出（时区日界）==")
    from django.db.models import Count
    from django.db.models.functions import TruncDate

    import datetime as dt

    log = AICallLog.objects.create(
        scene="other", capability="chat", provider="mychk_probe", success=True
    )
    AICallLog.objects.filter(pk=log.pk).update(
        created_at=dt.datetime(2026, 10, 15, 20, 0, 0, tzinfo=dt.timezone.utc)
    )
    day = (
        AICallLog.objects.filter(pk=log.pk)
        .annotate(d=TruncDate("created_at", tzinfo=timezone.get_current_timezone()))
        .values_list("d", flat=True)
        .first()
    )
    check("UTC 20:00 的事件按北京日归到次日", day == dt.date(2026, 10, 16), f"归属 {day}")

    # daily 聚合的是问答记录，不是调用流水：另造一条 QARecord 打通"接口层按天分组"
    rec = QARecord.objects.create(
        course_id=COURSE_ID, student=fx["s1"], question="MYCHK时区样本", answer="用于日界验证", session=""
    )
    QARecord.objects.filter(pk=rec.pk).update(
        created_at=dt.datetime(2026, 10, 15, 20, 0, 0, tzinfo=dt.timezone.utc)
    )

    admin = admin_client()
    # 显式指定窗口：默认窗口是"近 N 天"，会排除掉下面造的 10-15 样本
    r = admin.get("/api/admin-panel/qa-quality-stats/?start=2026-10-10&end=2026-10-31")
    ok = r.status_code == 200
    payload = body(r) or {}
    daily = payload.get("daily") or []
    days = [str(item.get("date") or item.get("day") or "") for item in daily]
    check("平台 QA 质量看板 200", ok, str(r.status_code))
    check("看板按天趋势非空（TruncDate 可用）", len(daily) > 0, f"{len(daily)} 天")
    check("日分组含北京日 2026-10-16（时区偏移生效）",
          any("2026-10-16" in d for d in days), f"days={sorted(days)[:4]}")

    r = t.get(f"/api/analytics/class/{CLASS_ID}/export/?course={COURSE_ID}")
    if r.status_code == 200 and hasattr(r, "streaming_content"):
        blob = b"".join(r.streaming_content)
    else:
        blob = getattr(r, "content", b"") if r.status_code == 200 else b""
    check("班级学习数据导出 200", r.status_code == 200, str(r.status_code))
    check("导出内容是 xlsx（PK 头）", blob[:2] == b"PK", f"head={blob[:2]}")
    check("导出体积合理（>3KB）", len(blob) > 3000, f"{len(blob)} bytes")

    r = t.get(f"/api/analytics/class/{CLASS_ID}/?course={COURSE_ID}")
    check("班级学习统计 200", r.status_code == 200, f"{r.status_code} {str(r.data)[:80]}")

    r = admin.get("/api/admin-panel/overview/")
    check("督管概览 200", r.status_code == 200, f"{r.status_code} {str(getattr(r, 'data', ''))[:80]}")


# ---------------------------------------------------------------------------
# G7 分页 / 搜索 / 排序（排序规则）
# ---------------------------------------------------------------------------
def g7_query(t):
    print("\n== G7 分页/搜索/排序（utf8mb4_0900_ai_ci）==")
    r = t.get("/api/questions/?page=1&page_size=5")
    ok = r.status_code == 200
    data = body(r) if ok else {}
    items = rows(data)
    check("题库分页 200", ok, str(r.status_code))
    check("分页 page_size 生效", len(items) <= 5, f"返回 {len(items)} 条")
    check("分页总数存在", (data.get("total") or 0) > 0, f"total={data.get('total')}")

    r = t.get("/api/questions/?search=Java")
    hit_upper = (body(r) or {}).get("total") if r.status_code == 200 else 0
    r = t.get("/api/questions/?search=java")
    hit_lower = (body(r) or {}).get("total") if r.status_code == 200 else 0
    check("中文/英文关键词搜索有命中", (hit_upper or 0) > 0, f"Java={hit_upper}")
    check("大小写不敏感搜索一致（ci 排序规则）", hit_upper == hit_lower, f"Java={hit_upper} java={hit_lower}")

    r = t.get("/api/questions/?ordering=-id&page_size=5")
    ids = [row["id"] for row in rows(body(r))] if r.status_code == 200 else []
    check("排序 -id 生效", ids == sorted(ids, reverse=True), str(ids))


# ---------------------------------------------------------------------------
# G8 约束与稳定性
# ---------------------------------------------------------------------------
def g8_constraints(t, fx):
    print("\n== G8 约束/稳定性 ==")
    from apps.classroom.services import ClassServiceError

    try:
        assign_students(fx["classroom"], [fx["s1"]], note="重复入班")
        check("重复入班幂等成功（不报 500）", True, "unchanged")
    except ClassServiceError as exc:
        check("重复入班返回业务错误（非 500）", True, str(exc)[:80])
    except Exception as exc:  # noqa: BLE001
        check("重复入班返回业务错误（非 500）", False, f"{type(exc).__name__}: {exc}")

    # 生成列唯一索引：同一学生第二条占用关系必须被数据库拦下
    other = ClassRoom.objects.exclude(id=fx["classroom"].id).first()
    try:
        with transaction.atomic():
            from apps.classroom.models import ClassStudent

            ClassStudent.objects.create(
                classroom=other, student=fx["s1"], learn_status=ClassStudent.LearnStatus.ACTIVE
            )
        check("第二条 active 占用被数据库拦截", False, "未拦截")
    except IntegrityError as exc:
        check("第二条 active 占用被数据库拦截", True, str(exc)[:90])

    # AI 任务防双跑（生成列条件唯一）
    AITask.objects.create(
        task_type=AITask.TaskType.CHAPTER_SUMMARY,
        status=AITask.Status.PENDING,
        student=fx["s1"],
        catalog=fx["course"].catalogs.first(),
        triggered_by=fx["s1"],
    )
    try:
        with transaction.atomic():
            AITask.objects.create(
                task_type=AITask.TaskType.CHAPTER_SUMMARY,
                status=AITask.Status.PENDING,
                student=fx["s1"],
                catalog=fx["course"].catalogs.first(),
                triggered_by=fx["s1"],
            )
        check("同章节同学生第二条进行中任务被拦截", False, "未拦截")
    except IntegrityError as exc:
        check("同章节同学生第二条进行中任务被拦截", True, str(exc)[:90])

    codes = []
    for _ in range(60):
        r = t.get("/api/courses/")
        codes.append(r.status_code)
    check("连续 60 次请求无 5xx（连接复用稳定）", all(c < 500 for c in codes), f"5xx={sum(1 for c in codes if c >= 500)}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    print(f"目标库：{connection.settings_dict['NAME']}（vendor={connection.vendor}）")
    if connection.vendor != "mysql":
        print("! 当前不是 MySQL，本脚本的意义在于验证 MySQL 方言")
    if connection.settings_dict["NAME"] == "zk":
        print("! 检测到 E2E 指向开发主库 zk，拒绝执行（请用 zk_e2e）")
        return 2

    # AI 切 mock：避免验收打到真实大模型（慢/计费/不稳定）
    original = {c.capability: c.provider for c in AICapabilityConfig.objects.all()}
    AICapabilityConfig.objects.all().update(provider="mock")
    print(f"[ai] 原配置 {original}，本次临时切 mock")

    Course7 = Course.objects.get(id=COURSE_ID)
    fx = None
    t0 = time.time()
    try:
        fx = build_fixture()
        t, s = g1_auth(fx)
        g2_course(t, s)
        g3_exam(t, s)
        g3_concurrent(t)
        g4_homework(t, s, fx)
        g5_rag(s)
        g6_stats(t, s, fx)
        g7_query(t)
        g8_constraints(t, fx)
    finally:
        if fx:
            cleanup(fx)
        for cap, provider in original.items():
            AICapabilityConfig.objects.filter(capability=cap).update(provider=provider)

    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项，耗时 {time.time() - t0:.1f}s")
    for name in FAIL:
        print("  未通过：" + name)
    print("=" * 60)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
