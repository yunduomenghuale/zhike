"""MySQL 部分唯一约束的等价实现（供迁移调用，不依赖任何模型定义）。

## 为什么需要这层

`models.UniqueConstraint(condition=...)` 在 PostgreSQL / SQLite 上落成"部分唯一索引"，
但 MySQL 没有部分索引能力。Django 的处理是——**静默跳过**：
`django/db/backends/base/schema.py` 的 `_unique_supported()` 发现
`supports_partial_indexes=False` 就返回 False，`_unique_sql()` 随即 `return None`，
既不建索引、也不抛异常、也不告警。结果是数据库级不变量凭空消失。

## 等价表达

"生成列取 NULL + 普通唯一索引"：

    occ_x = CASE WHEN <condition> THEN <key> END      -- 不满足条件时为 NULL
    UNIQUE KEY (occ_x, ...)

MySQL 唯一索引对 NULL 互不冲突，于是"不满足条件的行"全部放行、
"满足条件的行"才参与唯一性判定，与部分唯一索引语义一致，
NULL 组合键的处理也与 SQLite 完全一致（含 NULL 的键互不冲突）。

## 可重复执行

MySQL 的 DDL 隐式提交、不可回滚：若 `ADD COLUMN` 成功而 `ADD UNIQUE KEY` 失败，
迁移记录不会写入，但列已存在。此处的实现先查 `information_schema` 再动手，
让同一个迁移在失败后可以原地重跑，不会卡在 "Duplicate column name"。
"""


def _column_exists(schema_editor, table, column):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
            [table, column],
        )
        return cursor.fetchone()[0] > 0


def _index_exists(schema_editor, table, index):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s",
            [table, index],
        )
        return cursor.fetchone()[0] > 0


def ensure_partial_unique(
    schema_editor,
    *,
    table: str,
    column: str,
    column_type: str,
    expression: str,
    index: str,
    columns: list[str],
):
    """建"生成列 + 唯一索引"。幂等：列/索引已存在则跳过。"""
    if not _column_exists(schema_editor, table, column):
        schema_editor.execute(
            f"ALTER TABLE `{table}` ADD COLUMN `{column}` {column_type} "
            f"GENERATED ALWAYS AS ({expression}) STORED"
        )
    if not _index_exists(schema_editor, table, index):
        cols = ", ".join(f"`{c}`" for c in columns)
        schema_editor.execute(f"ALTER TABLE `{table}` ADD UNIQUE KEY `{index}` ({cols})")


def drop_partial_unique(schema_editor, *, table: str, column: str, index: str):
    """反向：先删索引再删列（顺序反了 MySQL 会因索引依赖列而拒绝）。"""
    if _index_exists(schema_editor, table, index):
        schema_editor.execute(f"ALTER TABLE `{table}` DROP INDEX `{index}`")
    if _column_exists(schema_editor, table, column):
        schema_editor.execute(f"ALTER TABLE `{table}` DROP COLUMN `{column}`")
