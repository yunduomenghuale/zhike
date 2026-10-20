"""管理端操作审计的写入助手。

约定：
- 只记录**成功执行**的写操作（调用方在返回 2xx 响应前调用）；
- target_* 描述被操作对象；old_value/new_value 为字段级快照（JSON）；
- 敏感字段（密码、API Key）只记存在性/掩码，由调用方保证不传入明文。
"""
from .models import AdminActionLog


def log_admin_action(
    actor,
    action: str,
    *,
    target_type: str = "",
    target_id=None,
    target_label: str = "",
    old_value=None,
    new_value=None,
    note: str = "",
) -> AdminActionLog:
    """落一条审计记录。action 取 AdminActionLog.Action 的值。"""
    return AdminActionLog.objects.create(
        actor=actor,
        action=action,
        target_type=target_type or "",
        target_id=target_id,
        target_label=(target_label or "")[:200],
        old_value=old_value,
        new_value=new_value,
        note=(note or "")[:255],
    )
