"""MySQL：补齐「一个学生同时只能占用一个班」的数据库级约束。

`ClassStudent.Meta.constraints` 里的 `uniq_occupied_class_per_student` 是条件唯一约束
（只有 active/inactive 占位，transferred/removed 允许留多条历史）。MySQL 不支持
部分索引，Django 会静默跳过它，所以这里用生成列 + 唯一索引等价实现。
SQLite 侧仍走原生部分索引，本迁移对非 MySQL 直接跳过（但记录照写，保持两库迁移序列一致）。

详见 apps/common/mysql_partial_unique.py 与 docs/MySQL切换-实施设计与冲突评审.md（C-01）。
"""
from django.db import migrations

from apps.common.mysql_partial_unique import drop_partial_unique, ensure_partial_unique

TABLE = "classroom_classstudent"
COLUMN = "occ_student_id"
INDEX = "uniq_occupied_class_per_student_mysql"
EXPR = "CASE WHEN learn_status IN ('active','inactive') THEN student_id END"
COLUMNS = ["occ_student_id"]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    ensure_partial_unique(
        schema_editor,
        table=TABLE,
        column=COLUMN,
        column_type="BIGINT",
        expression=EXPR,
        index=INDEX,
        columns=COLUMNS,
    )


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    drop_partial_unique(schema_editor, table=TABLE, column=COLUMN, index=INDEX)


class Migration(migrations.Migration):
    # MySQL 的 DDL 不能回滚，Django 禁止在事务里执行 DDL
    # （schema_editor.execute 会抛 TransactionManagementError）。
    # 这里显式退出事务，配合 mysql_partial_unique 的幂等判断，
    # 中途失败可原地重跑。
    atomic = False

    dependencies = [("classroom", "0007_disable_invite")]
    operations = [migrations.RunPython(forwards, backwards)]
