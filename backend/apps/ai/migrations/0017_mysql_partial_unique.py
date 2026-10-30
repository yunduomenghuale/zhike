"""MySQL：补齐 AI 模块的三条条件唯一约束。

1. `AITask.uniqi_active_chapter_summary` —— 同一学生同一章节只允许一条进行中的总结任务；
2. `AITask.uniq_active_question_gen` —— 同一教师同一课程只允许一条进行中的生题任务；
3. `AIQuotaPolicy.uniq_ai_quota_global_default` —— 全局默认配额（user_id IS NULL）最多一行。

注意第 3 条：`user` 是 OneToOneField，已经自带 UNIQUE(user_id)，但 MySQL 的唯一索引
允许多个 NULL，仅靠它挡不住"两行全局默认"，所以仍需单独的生成列约束。

MySQL 无部分索引、Django 静默跳过（见 apps/common/mysql_partial_unique.py）；
SQLite 侧继续使用 Meta.constraints 里的原生部分索引。
"""
from django.db import migrations

from apps.common.mysql_partial_unique import drop_partial_unique, ensure_partial_unique

SPECS = [
    {
        "table": "ai_aitask",
        "column": "occ_active_summary",
        "column_type": "BIGINT",
        "expression": (
            "IF(task_type = 'chapter_summary' AND status IN ('pending','running'), 1, NULL)"
        ),
        "index": "uniqi_active_chapter_summary_mysql",
        # 组合键中含 NULL 时 MySQL 视为互不相同，与 SQLite 部分索引的 NULL 语义一致
        "columns": ["occ_active_summary", "student_id", "catalog_id"],
    },
    {
        "table": "ai_aitask",
        "column": "occ_active_gen",
        "column_type": "BIGINT",
        "expression": (
            "IF(task_type = 'question_gen' AND status IN ('pending','running'), 1, NULL)"
        ),
        "index": "uniq_active_question_gen_mysql",
        "columns": ["occ_active_gen", "triggered_by_id", "course_id"],
    },
    {
        "table": "ai_aiquotapolicy",
        "column": "occ_global",
        "column_type": "TINYINT",
        "expression": "IF(user_id IS NULL, 1, NULL)",
        "index": "uniq_ai_quota_global_default_mysql",
        "columns": ["occ_global"],
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

    dependencies = [("ai", "0016_aiquotapolicy")]
    operations = [migrations.RunPython(forwards, backwards)]
