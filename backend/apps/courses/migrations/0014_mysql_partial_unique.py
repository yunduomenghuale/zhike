"""MySQL：补齐两条条件唯一约束。

1. `courses_term.unique_current_term` —— 全库只能有一个当前学期（is_current=True）；
2. `courses_courseresource.unique_course_resource_path` —— 同课程下预置资源 path 唯一
   （文档类 path 恒为空，不参与判重）。

MySQL 无部分索引，Django 会静默跳过这两条条件约束（见
apps/common/mysql_partial_unique.py 的说明）。本迁移只在 MySQL 上执行，
SQLite 侧继续使用 Meta.constraints 里的原生部分索引。
"""
from django.db import migrations

from apps.common.mysql_partial_unique import drop_partial_unique, ensure_partial_unique

SPECS = [
    {
        "table": "courses_term",
        "column": "occ_current",
        "column_type": "TINYINT",
        "expression": "IF(is_current = 1, 1, NULL)",
        "index": "unique_current_term_mysql",
        "columns": ["occ_current"],
    },
    {
        "table": "courses_courseresource",
        "column": "occ_path",
        "column_type": "VARCHAR(255)",
        "expression": "IF(path = '', NULL, path)",
        "index": "unique_course_resource_path_mysql",
        "columns": ["course_id", "occ_path"],
    },
]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    for spec in SPECS:
        ensure_partial_unique(schema_editor, **spec)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    for spec in reversed(SPECS):
        drop_partial_unique(
            schema_editor,
            table=spec["table"],
            column=spec["column"],
            index=spec["index"],
        )


class Migration(migrations.Migration):
    # MySQL 的 DDL 不能回滚，Django 禁止在事务里执行 DDL
    # （schema_editor.execute 会抛 TransactionManagementError）。
    # 这里显式退出事务，配合 mysql_partial_unique 的幂等判断，
    # 中途失败可原地重跑。
    atomic = False

    dependencies = [("courses", "0013_alter_course_teacher")]
    operations = [migrations.RunPython(forwards, backwards)]
