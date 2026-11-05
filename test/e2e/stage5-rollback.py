# -*- coding: utf-8 -*-
"""Stage 5：迁移回滚演练（独立库隔离，绝不碰主库 zk / zk_e2e / 生产）。

演练链：
  1. 空库全量 migrate → labs.0006 [X]，LabPage 表 + 新字段存在
  2. migrate labs 0005（真回退）→ 0006 [ ]，表/列被删
  3. migrate labs（真前进）→ 0006 [X]，表/列恢复
  4. migrate labs 0005 --fake（只回退记录、保留表）→ 模拟「旧代码 + 残留表」
  5. 原生 SQL 读旧字段 + 读残留表 → 旧代码不受 LabPage 表存在影响
  6. migrate labs 0006 --fake 对齐记录 → 最终 0006 [X]
  7. makemigrations --check --dry-run 零输出
  8. 复核主库 zk 与 zk_e2e 的 0006 仍 [X]（隔离性）

跑法：cd backend && PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe ../test/e2e/stage5-rollback.py
"""
import os
import subprocess
import sys

import MySQLdb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, "backend")
DBURL = "mysql://zk:zk123456@127.0.0.1:3306/zk_s5_rollback"
DBNAME = "zk_s5_rollback"

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


def env_for(url):
    e = os.environ.copy()
    e["DATABASE_URL"] = url
    e["PYTHONIOENCODING"] = "utf-8"
    return e


def manage(args, url=DBURL):
    p = subprocess.run([sys.executable, "manage.py"] + args, cwd=BACKEND,
                       env=env_for(url), capture_output=True, text=True)
    print(f"$ manage.py {' '.join(args)}  (exit={p.returncode})")
    for line in (p.stdout or "").strip().splitlines():
        print("    " + line[:220])
    if p.returncode != 0:
        for line in (p.stderr or "").strip().splitlines()[-12:]:
            print("    ERR " + line[:220])
    return p


def showmigrations(url):
    p = manage(["showmigrations", "labs"], url=url)
    return p.stdout or ""


def db_state():
    """只读查 information_schema，绕开当前 Django 模型（回退期间模型字段不匹配）。"""
    c = MySQLdb.connect(host="127.0.0.1", user="zk", passwd="zk123456",
                        port=3306, db=DBNAME, charset="utf8mb4")
    cur = c.cursor()
    cur.execute("""SELECT COUNT(*) FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA=%s AND TABLE_NAME='labs_labpage'""", (DBNAME,))
    has_table = cur.fetchone()[0] == 1
    cur.execute("""SELECT COLUMN_NAME FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA=%s AND TABLE_NAME='labs_lab'""", (DBNAME,))
    cols = {r[0] for r in cur.fetchall()}
    cur.execute("""SELECT COLUMN_NAME FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA=%s AND TABLE_NAME='labs_labsubmission'""", (DBNAME,))
    sub_cols = {r[0] for r in cur.fetchall()}
    c.close()
    return {
        "table": has_table,
        "lab_new": {"page_source", "last_debug", "report_note"} <= cols,
        "sub_new": {"grading_source", "grade_raw", "grade_raw_digest", "graded_at"} <= sub_cols,
        "lab_old": {"id", "title", "status", "template_id"} <= cols,
    }


def reset_db():
    """重置演练库，保证脚本可重复运行。

    安全边界：库名必须精确等于 zk_s5_rollback，且不属于受保护库；
    zk 账号仅有全局 CREATE/DROP 与按库显式授权，不会波及 zk / zk_e2e。
    前置：root 需先执行 GRANT ALL ON zk_s5_rollback.* TO 'zk'@'localhost'（本地一次性）。
    """
    assert DBNAME == "zk_s5_rollback", f"拒绝重置非演练库 {DBNAME}"
    c = MySQLdb.connect(host="127.0.0.1", user="zk", passwd="zk123456",
                        port=3306, charset="utf8mb4")
    cur = c.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS `{DBNAME}`")
    cur.execute(f"CREATE DATABASE `{DBNAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    c.close()
    print(f"[reset] 演练库 {DBNAME} 已重建（空库）")


def raw_sql_ok():
    """模拟旧代码：只读旧字段 + 残留表存在也不影响查询。"""
    c = MySQLdb.connect(host="127.0.0.1", user="zk", passwd="zk123456",
                        port=3306, db=DBNAME, charset="utf8mb4")
    cur = c.cursor()
    cur.execute("SELECT id, title, status, template_id FROM labs_lab LIMIT 1")
    row = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM labs_labpage")
    n = cur.fetchone()[0]
    c.close()
    return True, row, n


def applied(text):
    """0006 行是否 [X]。"""
    for line in text.splitlines():
        if "0006_lab_custom_page_grading" in line:
            return "[X]" in line
    return None


def main():
    print("=" * 72)
    print("Stage 5 · 迁移回滚演练（独立库 zk_s5_rollback；主库 zk / zk_e2e 只读复核）")
    print("=" * 72)

    # 隔离性前置：确认目标不是保护库
    check("R0 演练库名不是受保护库", DBNAME not in ("zk", "test_zk", "zk_e2e"), DBNAME)
    reset_db()

    p = manage(["migrate"])
    check("R1 空库全量 migrate 成功", p.returncode == 0)
    if p.returncode != 0:
        return 1
    st = db_state()
    check("R2 0006 已应用，LabPage 表 + Lab/LabSubmission 新字段齐备",
          applied(showmigrations(DBURL)) is True and st["table"] and st["lab_new"] and st["sub_new"],
          f"applied={applied(showmigrations(DBURL))} {st}")

    p = manage(["migrate", "labs", "0005"])
    check("R3 真回退到 0005 成功", p.returncode == 0)
    st = db_state()
    check("R4 回退后 0006 未应用、LabPage 表与新字段已移除",
          applied(showmigrations(DBURL)) is False and not st["table"]
          and not st["lab_new"] and not st["sub_new"] and st["lab_old"],
          f"applied={applied(showmigrations(DBURL))} {st}")

    p = manage(["migrate", "labs"])
    check("R5 真前进回 0006 成功", p.returncode == 0)
    st = db_state()
    check("R6 前进后结构完整恢复（可前进可回退）",
          applied(showmigrations(DBURL)) is True and st["table"] and st["lab_new"] and st["sub_new"],
          f"applied={applied(showmigrations(DBURL))} {st}")

    p = manage(["migrate", "labs", "0005", "--fake"])
    check("R7 --fake 回退记录成功（模拟旧代码部署、表残留）", p.returncode == 0)
    st = db_state()
    check("R8 记录为 0005 但 LabPage 表与新字段仍在（表可保留）",
          applied(showmigrations(DBURL)) is False and st["table"] and st["lab_new"],
          f"applied={applied(showmigrations(DBURL))} {st}")

    try:
        ok, row, n = raw_sql_ok()
        check("R9 旧字段只读查询成功且残留 LabPage 表不干扰（旧代码兼容）",
              ok, f"lab_row={row} labpage_rows={n}")
    except Exception as exc:
        check("R9 旧字段只读查询成功且残留 LabPage 表不干扰（旧代码兼容）", False, str(exc))

    p = manage(["migrate", "labs", "0006", "--fake"])
    check("R10 --fake 对齐记录后 0006 重新标记已应用", p.returncode == 0
          and applied(showmigrations(DBURL)) is True and db_state()["table"])

    p = manage(["makemigrations", "--check", "--dry-run"], url=DBURL)
    check("R11 模型与迁移一致（No changes detected）", p.returncode == 0,
          (p.stdout or "").strip()[:80])

    for label, url in [("主库 zk", "mysql://zk:zk123456@127.0.0.1:3306/zk"),
                       ("E2E 库 zk_e2e", "mysql://zk:zk123456@127.0.0.1:3306/zk_e2e")]:
        txt = showmigrations(url)
        check(f"R12 隔离性：{label} 的 0006 仍为 [X]（演练未波及）", applied(txt) is True,
              f"applied={applied(txt)}")

    print("=" * 72)
    print(f"总计 {PASSED + FAILED} 项，通过 {PASSED} 项，失败 {FAILED} 项")
    print("ALL_PASS" if FAILED == 0 else "HAS_FAILURE")
    print("=" * 72)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
