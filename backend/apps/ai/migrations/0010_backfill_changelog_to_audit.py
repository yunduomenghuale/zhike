"""把 AICapabilityChangeLog 存量记录合并进管理端操作审计（AdminActionLog）。

审计双轨合并（2026-10-19）：管理端保存 AI 配置改为只写 AdminActionLog
（action=ai_config_save，new_value.changes 存按能力分组的字段级 diff），
模型层 AICapabilityConfig.save() 停写 AICapabilityChangeLog。本迁移把存量
ChangeLog 逐条导入审计表，保证「为什么某天起行为变了」在单一审计轨可查；
导入行带 note 标记（反向迁移据此删除），created_at 刷回历史时间戳。

changed_by 为空的程序化写入无法映射（AdminActionLog.actor 非空 PROTECT），跳过。
"""

from django.db import migrations

NOTE_MARK = "由 AICapabilityChangeLog 历史记录导入"


def forwards(apps, schema_editor):
    change_logs = apps.get_model("ai", "AICapabilityChangeLog")
    action_logs = apps.get_model("platform_admin", "AdminActionLog")
    capability_labels = dict(
        change_logs._meta.get_field("capability").choices
    )
    for log in change_logs.objects.select_related("changed_by").all():
        if log.changed_by_id is None:
            continue  # actor 非空：无操作人的历史行无法映射，跳过
        display = capability_labels.get(log.capability, log.capability)
        entry = action_logs.objects.create(
            actor_id=log.changed_by_id,
            action="ai_config_save",
            target_type="ai_config",
            target_label=display,
            new_value={
                "capabilities": [log.capability],
                "changes": [{
                    "capability": log.capability,
                    "capability_display": display,
                    "changes": log.changes,
                }],
            },
            note=NOTE_MARK,
        )
        # created_at 是 auto_now_add：先落库再把历史时间戳刷回来
        # （queryset.update 不走 pre_save，不会被覆盖为当前时间）
        if log.created_at:
            action_logs.objects.filter(pk=entry.pk).update(created_at=log.created_at)


def backwards(apps, schema_editor):
    action_logs = apps.get_model("platform_admin", "AdminActionLog")
    action_logs.objects.filter(action="ai_config_save", note=NOTE_MARK).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("platform_admin", "0001_initial"),
        ("ai", "0009_aicapabilityconfig_supports_vision"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
