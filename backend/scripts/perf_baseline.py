"""关键接口的性能基线对比（SQLite vs MySQL，同一份业务数据）。

## 目的

切库后最容易"不报错但变慢"的地方是：
- 向量检索：`search_chunks` 每次把整门课片段的 embedding（每行 ~20KB JSON）读进 Python，
  SQLite 是本地文件读，MySQL 要过 TCP + 协议解析；
- 看板/统计：多处 `TruncDate` 聚合（CONVERT_TZ 无法走索引）；
- 导出：多 sheet 聚合。

本脚本用进程内 APIClient 计时（排除网络与前端），每项跑多次取中位数，
输出对照表；判定阈值为「MySQL 中位数 ≤ SQLite 中位数 × 3」（设计文档 C-18）。

## 跑法

    # SQLite（基线）
    DATABASE_URL=sqlite python scripts/perf_baseline.py --label sqlite
    # MySQL
    python scripts/perf_baseline.py --label mysql

两次输出都保存到 output/perf_<label>.json，便于对比。
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

COURSE_ID = 7
CLASS_ID = 3
ROUNDS = 5


def login(username="t101", password="pass1234"):
    c = APIClient()
    c.raise_request_exception = False
    r = c.post("/api/auth/login/", {"username": username, "password": password}, format="json")
    if r.status_code != 200:
        raise SystemExit(f"登录失败 {username}: {r.status_code}")
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['data']['token']['access']}")
    return c


def admin_login():
    return login("admin", "A0987654")


def timeit(fn, rounds=ROUNDS):
    """跑 rounds 次取中位数（ms）；首次调用用于预热，不计入。"""
    fn()
    samples = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples), min(samples), max(samples)


def main():
    label = None
    for i, arg in enumerate(sys.argv):
        if arg == "--label" and i + 1 < len(sys.argv):
            label = sys.argv[i + 1]
    label = label or connection.vendor

    print(f"数据库：{connection.settings_dict['NAME']}（vendor={connection.vendor}）")
    t = login()
    a = admin_login()

    from apps.ai.vectorstore import search_chunks
    from apps.knowledge.models import KnowledgeChunk

    chunk = KnowledgeChunk.objects.filter(course_id=COURSE_ID).exclude(embedding=[]).first()
    vec = chunk.embedding

    cases = [
        ("登录（JWT 签发）", lambda: login()),
        ("课程列表", lambda: t.get("/api/courses/")),
        ("章节树 tree=1", lambda: t.get(f"/api/catalogs/?course={COURSE_ID}&tree=1")),
        ("题库分页 20 条", lambda: t.get("/api/questions/?page=1&page_size=20")),
        ("题库搜索(icontains)", lambda: t.get("/api/questions/?search=Java")),
        # 只做检索、不跑完整问答：问答会写 QARecord，SQLite 侧是冻结库不应再写；
        # 而性能瓶颈本来就在"读全部片段向量"，search_chunks 已覆盖。
        ("向量检索 top5（读全部片段向量）", lambda: search_chunks(COURSE_ID, vec, top_k=5)),
        ("班级学习统计", lambda: t.get(f"/api/analytics/class/{CLASS_ID}/?course={COURSE_ID}")),
        ("平台 QA 看板（按天聚合）", lambda: a.get("/api/admin-panel/qa-quality-stats/")),
        ("班级数据导出 xlsx", lambda: t.get(f"/api/analytics/class/{CLASS_ID}/export/?course={COURSE_ID}")),
    ]

    result = {"label": label, "vendor": connection.vendor, "db": connection.settings_dict["NAME"], "cases": {}}
    print(f"\n{'场景':<34}{'中位(ms)':>10}{'最小':>9}{'最大':>9}")
    print("-" * 64)
    for name, fn in cases:
        try:
            med, lo, hi = timeit(fn)
        except Exception as exc:  # noqa: BLE001 - 单项失败不影响整体
            print(f"{name:<34}{'ERROR':>10}  {type(exc).__name__}: {exc}")
            result["cases"][name] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        result["cases"][name] = {"median_ms": round(med, 2), "min_ms": round(lo, 2), "max_ms": round(hi, 2)}
        print(f"{name:<34}{med:>10.1f}{lo:>9.1f}{hi:>9.1f}")

    out_dir = BASE_DIR.parent / "output"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"perf_{label}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
