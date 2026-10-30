"""SQLite → MySQL 数据搬迁（一次性工具，不进生产镜像）。

## 设计要点（详见 docs/MySQL切换-实施设计与冲突评审.md §5）

1. **不搬 6 张表**：`django_content_type` / `auth_permission` / `auth_group` /
   `auth_group_permissions` / `users_user_user_permissions` / `users_user_groups`
   由 MySQL 侧 `migrate` 的 post_migrate 自行生成。原因：源库含 4 个已删模型的孤儿
   content type（AIConfiguration / CourseVideo / LabAnswer / LabQuestion），照搬会
   外键失败或灌入死权限；而本项目权限体系零业务引用（三张 M2M 全 0 行）。
   `django_migrations` 也不搬——MySQL 侧由 migrate 自己写。

2. **只关 FOREIGN_KEY_CHECKS，不关 UNIQUE_CHECKS**：唯一索引是导入期的数据质量闸门，
   关掉等于把源库脏数据悄悄灌进来。

3. **逐表事务**：一张表一个事务，失败即停并打印表名/列名/失败行主键；源库数据量小，
   重跑用 `--reset` 清空目标业务表再来，幂等。

4. **排除生成列**：`apps/common/mysql_partial_unique.py` 建的 `occ_*` 列是
   `GENERATED ALWAYS AS ... STORED`，不可写入，否则 MySQL 报 3105。

5. **类型归一手工做**：SQLite 是弱类型，同列可能混存 int/real/text。
   datetime 统一解析成 naive UTC（源库 USE_TZ 存的就是 UTC）；
   Decimal 统一 `Decimal(str(v))` 防 float 误差；JSON 原样透传（MySQL 会校验）。

## 用法

    # 预检（不写库）
    python scripts/sqlite_to_mysql.py --source db.sqlite3 --dry-run

    # 正式搬迁（目标库须已 migrate 完成）
    python scripts/sqlite_to_mysql.py --source db.sqlite3

    # 重跑前清空目标业务表
    python scripts/sqlite_to_mysql.py --source db.sqlite3 --reset

    # 只校验，不搬
    python scripts/sqlite_to_mysql.py --source db.sqlite3 --verify-only

前提：环境变量 `DATABASE_URL` 指向目标 MySQL。
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
from decimal import Decimal, InvalidOperation

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.apps import apps  # noqa: E402
from django.db import connection, transaction  # noqa: E402

# 由目标库自行生成 / 由 migrate 维护，永不搬迁
SKIP_TABLES = {
    "django_migrations",
    "django_content_type",
    "auth_permission",
    "auth_group",
    "auth_group_permissions",
    "users_user_user_permissions",
    "users_user_groups",
    "sqlite_sequence",
}

# 指纹校验用（只取纯文本列，避免 Decimal/JSON 的表示差异造成假失败）
FINGERPRINTS = [
    ("users_user", ["id", "username", "password"]),
    ("questions_question", ["id", "stem"]),
    ("knowledge_knowledgechunk", ["id", "content"]),
]

# 外键孤儿检查（关键链路）
ORPHAN_CHECKS = [
    (
        "classroom_classstudent → users_user",
        "SELECT COUNT(*) FROM classroom_classstudent cs "
        "LEFT JOIN users_user u ON u.id = cs.student_id WHERE u.id IS NULL",
    ),
    (
        "knowledge_knowledgechunk → courses_course",
        "SELECT COUNT(*) FROM knowledge_knowledgechunk k "
        "LEFT JOIN courses_course c ON c.id = k.course_id WHERE c.id IS NULL",
    ),
    (
        "exams_examsubmission → exams_exam",
        "SELECT COUNT(*) FROM exams_examsubmission s "
        "LEFT JOIN exams_exam e ON e.id = s.exam_id WHERE e.id IS NULL",
    ),
]

# 需要比对 JSON 数组长度的列（MySQL 会规范化 JSON 文本，不能做文本 hash）
JSON_LENGTH_CHECKS = [
    ("knowledge_knowledgechunk", "embedding"),
]


def log(msg=""):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# 元数据
# ---------------------------------------------------------------------------
def mysql_tables(cursor) -> list[str]:
    cursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = DATABASE() ORDER BY table_name"
    )
    return [r[0] for r in cursor.fetchall()]


def mysql_columns(cursor, table) -> dict[str, str]:
    """返回 {列名: DATA_TYPE}，**排除生成列**。

    注意：不能用 "GENERATED" 子串一刀切——JSONField 的默认值表达式在
    information_schema 里显示为 EXTRA='DEFAULT_GENERATED'，那是"有默认值"，
    不是生成列；误排除会让 subjective_scores / question_layout / context_snapshot
    这类 JSON 列整列漏搬（静默丢数据）。真正的生成列标记是
    'STORED GENERATED' / 'VIRTUAL GENERATED'。
    """
    cursor.execute(
        "SELECT column_name, data_type, extra FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = %s ORDER BY ordinal_position",
        [table],
    )
    cols = {}
    for name, dtype, extra in cursor.fetchall():
        extra_upper = (extra or "").upper()
        if "STORED GENERATED" in extra_upper or "VIRTUAL GENERATED" in extra_upper:
            continue
        cols[name] = (dtype or "").lower()
    return cols


def sqlite_tables(con) -> list[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def sqlite_columns(con, table) -> list[str]:
    return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]


def topo_order(tables: list[str]) -> list[str]:
    """按外键依赖排序（父表先）。做不出拓扑序时退回字典序，不影响正确性
    （连接上已关 FOREIGN_KEY_CHECKS，顺序只为失败时更好定位）。"""
    by_table = {m._meta.db_table: m for m in apps.get_models()}
    remaining = list(tables)
    ordered: list[str] = []
    seen: set[str] = set()
    while remaining:
        progressed = False
        for table in list(remaining):
            model = by_table.get(table)
            parents = set()
            if model is not None:
                for field in model._meta.concrete_fields:
                    if field.is_relation and field.many_to_one:
                        parents.add(field.target_field.model._meta.db_table)
            if not parents or parents <= seen or table in parents:
                ordered.append(table)
                seen.add(table)
                remaining.remove(table)
                progressed = True
        if not progressed:  # 有环：剩下的按字典序追加
            ordered.extend(sorted(remaining))
            break
    return ordered


# ---------------------------------------------------------------------------
# 类型归一
# ---------------------------------------------------------------------------
def to_datetime(value):
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day)
    else:
        text = str(value).strip().replace("T", " ").replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed


def to_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value).strip()[:10])


def convert(value, data_type: str):
    if value is None:
        return None
    if data_type in ("datetime", "timestamp"):
        return to_datetime(value)
    if data_type == "date":
        return to_date(value)
    if data_type in ("decimal", "numeric"):
        try:
            return Decimal(str(value))
        except InvalidOperation as exc:  # 源库脏值：直接暴露，不静默兜底
            raise ValueError(f"无法转 Decimal: {value!r}") from exc
    if data_type == "json":
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8")
        return value if isinstance(value, str) else json_dumps(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return value


def json_dumps(value):
    import json

    return json.dumps(value, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 迁移
# ---------------------------------------------------------------------------
def reset_target(cursor, tables):
    log("清空目标库业务表…")
    for table in tables:
        cursor.execute(f"TRUNCATE TABLE `{table}`")


def copy_table(cursor, con, table, batch_size, dry_run):
    src_cols = sqlite_columns(con, table)
    tgt_cols = mysql_columns(cursor, table)
    common = [c for c in src_cols if c in tgt_cols]
    dropped = [c for c in src_cols if c not in tgt_cols]
    if dropped:
        # 源库有数据却搬不过去 = 静默丢数据，必须显式告警而不是打一行就算了
        for column in dropped:
            non_null = con.execute(
                'SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL' % (table, column)
            ).fetchone()[0]
            level = "!!" if non_null else "  "
            log(f"    {level} {table}.{column}: 目标库无此列，非空行 {non_null}")
    if not common:
        return 0, 0

    quoted_cols = ", ".join('"%s"' % c for c in common)
    select_sql = 'SELECT %s FROM "%s"' % (quoted_cols, table)
    rows = con.execute(select_sql).fetchall()
    if not rows:
        return 0, 0
    if dry_run:
        return len(rows), 0

    col_list = ", ".join(f"`{c}`" for c in common)
    placeholders = ", ".join(["%s"] * len(common))
    insert_sql = f"INSERT INTO `{table}` ({col_list}) VALUES ({placeholders})"
    types = [tgt_cols[c] for c in common]

    inserted = 0
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        payload = []
        for row in chunk:
            try:
                payload.append([convert(v, t) for v, t in zip(row, types)])
            except Exception as exc:
                raise ValueError(f"{table} 第 {start} 行类型转换失败: {exc}") from exc
        cursor.executemany(insert_sql, payload)
        inserted += len(payload)
    return len(rows), inserted


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def verify(cursor, con, tables):
    failures = []
    log()
    log("=" * 74)
    log("校验：逐表行数")
    log("=" * 74)
    for table in tables:
        src = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
        tgt = cursor.fetchone()[0]
        flag = "OK  " if src == tgt else "差异"
        if src != tgt:
            failures.append(f"{table} 行数 {src} != {tgt}")
        log(f"  [{flag}] {table:<38} {src:>7} → {tgt}")

    log()
    log("=" * 74)
    log("校验：文本指纹（按主键排序 sha256）")
    log("=" * 74)
    for table, cols in FINGERPRINTS:
        if table not in tables:
            continue
        col_sql = ", ".join(cols)
        src_rows = con.execute(f'SELECT {col_sql} FROM "{table}" ORDER BY id').fetchall()
        cursor.execute(f"SELECT {col_sql} FROM `{table}` ORDER BY id")
        tgt_rows = cursor.fetchall()
        if len(src_rows) != len(tgt_rows):
            failures.append(f"{table} 指纹行数不一致")
            log(f"  [差异] {table}: 行数不一致")
            continue
        src_hash = hashlib.sha256(repr([tuple(map(str, r)) for r in src_rows]).encode()).hexdigest()
        tgt_hash = hashlib.sha256(repr([tuple(map(str, r)) for r in tgt_rows]).encode()).hexdigest()
        ok = src_hash == tgt_hash
        if not ok:
            failures.append(f"{table} 指纹不一致")
        log(f"  [{'OK  ' if ok else '差异'}] {table:<38} {src_hash[:16]} vs {tgt_hash[:16]}")

    log()
    log("=" * 74)
    log("校验：JSON 数组长度")
    log("=" * 74)
    for table, column in JSON_LENGTH_CHECKS:
        if table not in tables:
            continue
        # 用 Python 解析而不是 SQLite 的 json_array_length()：不依赖 SQLite 的 JSON1 编译选项
        src = {}
        for pk, raw in con.execute(
            'SELECT id, "%s" FROM "%s" WHERE "%s" IS NOT NULL' % (column, table, column)
        ):
            if isinstance(raw, str) and raw.strip() not in ("", "[]", "null"):
                src[pk] = len(json.loads(raw))
        cursor.execute(
            "SELECT id, JSON_LENGTH(`%s`) FROM `%s` "
            "WHERE `%s` IS NOT NULL AND JSON_LENGTH(`%s`) > 0" % (column, table, column, column)
        )
        tgt = dict(cursor.fetchall())
        bad = [k for k in src if src[k] != tgt.get(k)]
        if bad:
            failures.append(f"{table}.{column} JSON 长度不一致 {len(bad)} 行")
        log(
            f"  [{'OK  ' if not bad else '差异'}] {table}.{column}: "
            f"非空 {len(src)} 行，不一致 {len(bad)} 行"
        )

    log()
    log("=" * 74)
    log("校验：外键孤儿")
    log("=" * 74)
    for label, sql in ORPHAN_CHECKS:
        try:
            cursor.execute(sql)
            n = cursor.fetchone()[0]
        except Exception as exc:  # 表不存在等
            log(f"  [跳过] {label}: {exc}")
            continue
        if n:
            failures.append(f"{label} 孤儿 {n} 行")
        log(f"  [{'OK  ' if n == 0 else '孤儿'}] {label}: {n}")

    log()
    log("=" * 74)
    log("校验：AUTO_INCREMENT 位")
    log("=" * 74)
    cursor.execute(
        "SELECT table_name, auto_increment FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND auto_increment IS NOT NULL"
    )
    for table, auto_inc in cursor.fetchall():
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = 'id'",
            [table],
        )
        if not cursor.fetchone()[0]:
            continue
        cursor.execute(f"SELECT COALESCE(MAX(id), 0) FROM `{table}`")
        max_id = cursor.fetchone()[0]
        ok = auto_inc > max_id
        if not ok:
            failures.append(f"{table} 自增位 {auto_inc} <= MAX(id) {max_id}")
        log(f"  [{'OK  ' if ok else '异常'}] {table:<38} auto={auto_inc:<8} max_id={max_id}")

    log()
    log("=" * 74)
    if failures:
        log(f"校验未通过，共 {len(failures)} 项：")
        for item in failures:
            log(f"  - {item}")
        return False
    log("校验全部通过。")
    log("=" * 74)
    return True


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="SQLite → MySQL 数据搬迁")
    parser.add_argument("--source", required=True, help="源 SQLite 文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    parser.add_argument("--reset", action="store_true", help="导入前 TRUNCATE 目标业务表")
    parser.add_argument("--verify-only", action="store_true", help="只跑校验")
    parser.add_argument("--only", nargs="*", help="只处理这些表")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    if connection.vendor != "mysql":
        log(f"目标库不是 MySQL（vendor={connection.vendor}），请设置 DATABASE_URL=mysql://…")
        return 2

    if not os.path.exists(args.source):
        log(f"源库不存在：{args.source}")
        return 2

    con = sqlite3.connect(args.source)
    con.text_factory = lambda b: b.decode("utf-8", "replace")

    with connection.cursor() as cursor:
        cursor.execute("SELECT DATABASE()")
        dbname = cursor.fetchone()[0]
        log(f"源：{args.source}")
        log(f"目标：MySQL {dbname}（vendor={connection.vendor}）")

        tgt_tables = set(mysql_tables(cursor))
        src_tables = set(sqlite_tables(con))

        candidates = [
            t
            for t in src_tables
            if t in tgt_tables and t not in SKIP_TABLES and not t.startswith("sqlite_")
        ]
        if args.only:
            candidates = [t for t in candidates if t in set(args.only)]
        missing = sorted(src_tables - tgt_tables - SKIP_TABLES)
        if missing:
            log(f"! 源库有而目标库没有的表（跳过）：{missing}")

        ordered = topo_order(sorted(candidates))
        log(f"待搬迁 {len(ordered)} 张表\n")

        if args.verify_only:
            return 0 if verify(cursor, con, ordered) else 1

        if args.reset and not args.dry_run:
            # 外键检查关掉才能 TRUNCATE 被引用的表；UNIQUE_CHECKS 不动（保留唯一性校验）
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            try:
                reset_target(cursor, ordered)
            finally:
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

        log("=" * 74)
        log("搬迁")
        log("=" * 74)
        total_src = total_ins = 0
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        try:
            for table in ordered:
                if args.dry_run:
                    src_n, ins_n = copy_table(cursor, con, table, args.batch_size, True)
                else:
                    # 每表一个事务：失败只回滚这张表，重跑用 --reset 清空再来
                    with transaction.atomic():
                        src_n, ins_n = copy_table(cursor, con, table, args.batch_size, False)
                total_src += src_n
                total_ins += ins_n
                mark = "（dry-run）" if args.dry_run else ""
                log(f"  {table:<40} {src_n:>7} 行{mark}")
        except Exception:
            log("\n搬迁失败，当前表已回滚；修复后可用 --reset 重跑。")
            raise
        finally:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

        log()
        log(f"合计源 {total_src} 行，写入 {total_ins} 行")

        if args.dry_run:
            log("\n（dry-run：未写入，跳过校验）")
            return 0

        ok = verify(cursor, con, ordered)
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
