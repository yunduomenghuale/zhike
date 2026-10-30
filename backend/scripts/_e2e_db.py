"""E2E / 校验脚本的数据库隔离（SQLite 副本 或 独立 MySQL 库）。

## 为什么需要

`p1_permission_matrix.py` / `p4_graduation_check.py` / `p5_security_check.py`
以及 `test/e2e/*.js` 都会**造数据再删数据**。原本靠 `SQLITE_PATH` 指向
`db.sqlite3` 的副本做隔离；切到 MySQL 后若直连开发主库，会污染真实数据。

## 两种模式

| 模式 | 触发方式 | 隔离手段 |
|---|---|---|
| SQLite（历史，默认） | 设 `SQLITE_PATH` | 复制 `db.sqlite3` 到工作目录 |
| MySQL（切库后） | 设 `E2E_DATABASE_URL=mysql://user:pass@host:3306/zk_e2e` | 独立库，脚本拒绝指向 `zk` / `test_zk` |

MySQL 模式的库需要先建好表：

    set DATABASE_URL=mysql://zk:zk123456@127.0.0.1:3306/zk_e2e
    python manage.py migrate

## 用法（脚本内）

    from _e2e_db import prepare, ensure_schema
    desc = prepare(BASE_DIR / "db.sqlite3", WORK_DIR / "db.sqlite3", WORK_DIR)
    django.setup()
    ensure_schema()          # MySQL 模式下检查是否已 migrate
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

# 绝不允许 E2E 打在主库上
PROTECTED_DB_NAMES = {"zk", "test_zk", "mysql", "sys", "performance_schema", "information_schema"}


def _db_name_of(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("?")[0].strip()


def prepare(source_db: Path, work_db: Path, work_dir: Path) -> str:
    """配置本次运行使用的数据库，返回人类可读描述。

    MySQL 模式会设置 `DATABASE_URL`（子进程 runserver 继承 os.environ，
    且 settings 的 load_dotenv 不覆盖已存在的环境变量，因此优先级正确）。
    SQLite 模式保持原行为：设 `SQLITE_PATH` 并复制副本。
    """
    e2e_url = (os.environ.get("E2E_DATABASE_URL") or "").strip()
    if e2e_url:
        if not e2e_url.startswith(("mysql://", "mysql2://")):
            raise SystemExit(f"E2E_DATABASE_URL 只支持 mysql://，收到 {e2e_url[:24]}…")
        name = _db_name_of(e2e_url)
        if name in PROTECTED_DB_NAMES:
            raise SystemExit(
                f"拒绝执行：E2E_DATABASE_URL 指向了 {name}。E2E 会造数据，必须用独立的 zk_e2e 库。"
            )
        os.environ["DATABASE_URL"] = e2e_url
        os.environ.pop("SQLITE_PATH", None)
        return f"MySQL 独立库 {name}（{e2e_url.split('@')[-1]}）"

    if not os.environ.get("SQLITE_PATH"):
        raise SystemExit(
            "拒绝执行：请设置 SQLITE_PATH（SQLite 副本）"
            "或 E2E_DATABASE_URL（独立 MySQL 库，如 mysql://zk:pw@127.0.0.1:3306/zk_e2e），"
            "避免在开发库上造数据。"
        )
    work_dir.mkdir(parents=True, exist_ok=True)
    if not work_db.exists() or os.environ.get("E2E_COPY_SQLITE", "1") == "1":
        shutil.copyfile(source_db, work_db)
    return f"SQLite 副本 {work_db}"


def ensure_schema() -> None:
    """MySQL 模式下校验目标库已建表，未建表则给出可直接执行的命令。"""
    from django.db import connection

    if connection.vendor != "mysql":
        return
    tables = connection.introspection.table_names()
    if "django_migrations" in tables:
        return
    name = connection.settings_dict["NAME"]
    raise SystemExit(
        f"目标库 {name} 还没有表结构。请先执行：\n"
        f"  set DATABASE_URL={os.environ.get('DATABASE_URL', '')}\n"
        f"  python manage.py migrate"
    )
