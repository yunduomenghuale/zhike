"""MySQL：补齐「同课程同学生的旧会话标识唯一」的条件约束。

`QASession.Meta.constraints` 里的 `uniq_qasession_legacy` 只约束 legacy_key 非空的行
（兼容旧前端/移动端传 session 字符串）。MySQL 无部分索引，Django 会静默跳过，
故用生成列 + 唯一索引等价实现；SQLite 侧仍走原生部分索引。

详见 apps/common/mysql_partial_unique.py。
"""
from django.db import migrations

from apps.common.mysql_partial_unique import drop_partial_unique, ensure_partial_unique

TABLE = "knowledge_qasession"
COLUMN = "occ_legacy_key"
INDEX = "uniq_qasession_legacy_mysql"
EXPR = "IF(legacy_key = '', NULL, legacy_key)"
COLUMNS = ["course_id", "student_id", "occ_legacy_key"]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    ensure_partial_unique(
        schema_editor,
        table=TABLE,
        column=COLUMN,
        column_type="VARCHAR(64)",
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

    dependencies = [("knowledge", "0011_qarecord_skip_retrieval")]
    operations = [migrations.RunPython(forwards, backwards)]
