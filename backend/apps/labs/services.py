"""实验成绩提交状态机（Stage 3 / S2）。

`finalize_submission()` 是「写状态 + 写分数 + 消费票据」的**唯一入口**，现有
`LabSubmissionViewSet.submit`（预置实验，服务端步骤重算）与新增的
`GradeReportView`（自定义实验，页面上报总分）共用，避免两套状态机漂移。

`parse_grade_payload()` 是 `POST /api/lab-gate/grade/` 与 `grade-debug`
dry-run **共用同一套极简校验**，保证模拟结果与真实上报一致。

S2 三条硬约束：
1. `select_for_update()` 在**同一个事务内**同时锁 `LabSubmission` 与
   `LabAttemptToken` 两行（固定顺序 submission → ticket，避免死锁）；
2. **锁后重新读取并复验**状态 / 票据，绝不信任锁前读到的对象；
3. `consume_token()` 放在**同一事务内**（旧实现在事务外，进程崩溃会留下
   可重放的未消费票据，C31）。任一环节抛异常整事务回滚，票据仍有效，
   学生可直接重试，无需中间态、无需队列。
"""
from decimal import Decimal, InvalidOperation
import json

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from . import bridge
from .models import LabAttemptToken, LabSubmission

# 报文序列化上限（S3：只收两个数，正常永远达不到；防御超大 grade_raw）
MAX_GRADE_BYTES = 64 * 1024


def parse_grade_payload(data, lab) -> dict:
    """校验成绩上报报文，只返回两个值 + 报文大小。失败抛中文 ValidationError。

    - `total_score`：可转 1 位小数，`0 ≤ x ≤ lab.total_score`；
    - 客户端 `elapsed_seconds`：**仅留痕、不采信**，但必须是非负数（S1）；
    - 整个请求体序列化后 ≤ 64KB；
    - 不接受 `submitted_at` / 实验 id / 学生身份等字段（传了也忽略）。
    """
    if not isinstance(data, dict):
        raise ValidationError("上报内容格式不正确")
    try:
        raw_bytes = len(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValidationError("上报内容无法序列化") from exc
    if raw_bytes > MAX_GRADE_BYTES:
        raise ValidationError("上报内容过大（超过 64KB）")

    if "total_score" not in data:
        raise ValidationError("缺少总成绩")
    try:
        score = Decimal(str(data["total_score"]))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError("总成绩格式不正确") from exc
    if not score.is_finite():
        raise ValidationError("总成绩格式不正确")
    # 最多 1 位小数
    if score != score.quantize(Decimal("0.1")):
        raise ValidationError("总成绩最多保留 1 位小数")
    max_score = Decimal(str(lab.total_score))
    if score < 0 or score > max_score:
        raise ValidationError(f"成绩超出实验总分范围（0 ~ {lab.total_score}）")

    raw_elapsed = data.get("elapsed_seconds", 0)
    try:
        client_elapsed = int(raw_elapsed)
    except (TypeError, ValueError) as exc:
        raise ValidationError("用时格式不正确") from exc
    if client_elapsed < 0:
        raise ValidationError("用时不能为负")

    return {
        "total_score": score,
        "client_elapsed_seconds": client_elapsed,
        "raw_bytes": raw_bytes,
    }


def server_elapsed_seconds(sub, now) -> int:
    """S1：正式用时一律由服务端按 `submitted_at - started_at` 计算。"""
    if not sub.started_at:
        return 0
    return max(0, int((now - sub.started_at).total_seconds()))


def is_abnormal(score: Decimal, lab, elapsed: int) -> bool:
    """S5：满分 + 极短用时只标记不拒答。阈值 `min(60, 标准时长*60*0.1)` 秒。"""
    if score != Decimal(str(lab.total_score)):
        return False
    threshold = min(60, lab.effective_standard_minutes * 60 * 0.1)
    return elapsed < threshold


def finalize_submission(ticket: LabAttemptToken, *, apply_result, validate=None) -> LabSubmission:
    """完成一次作答并返回更新后的 submission。

    :param ticket: 由 `bridge.validate_token()` / `LabTokenAuthentication` 得到的票据（未锁）
    :param apply_result: ``callable(sub, now)``，在事务内写分数与过程字段（不负责 save）
    :param validate: ``callable(sub, locked_ticket, now)``，锁后业务复验（窗口/发布/来源等），
                     抛 ``ValidationError`` / ``PermissionDenied`` 即整事务回滚
    """
    with transaction.atomic():
        now = timezone.now()
        # 双行锁：顺序固定，杜绝两个并发请求交叉持锁死锁
        try:
            sub = (
                LabSubmission.objects.select_for_update()
                .select_related("lab", "lab__template", "schedule", "student")
                .get(pk=ticket.submission_id)
            )
            locked_ticket = LabAttemptToken.objects.select_for_update().get(pk=ticket.pk)
        except (LabSubmission.DoesNotExist, LabAttemptToken.DoesNotExist) as exc:
            raise ValidationError("实验票据无效") from exc

        # 锁后复验（锁前对象可能已被别的请求改过）
        if locked_ticket.consumed:
            raise ValidationError("实验票据已使用")
        if locked_ticket.expires_at and now > locked_ticket.expires_at:
            raise ValidationError("实验票据已过期")
        if sub.status != LabSubmission.Status.IN_PROGRESS:
            raise ValidationError("本次实验已提交")
        if locked_ticket.student_id != sub.student_id:
            raise ValidationError("票据与作答不匹配")

        if validate is not None:
            validate(sub, locked_ticket, now)

        sub.status = LabSubmission.Status.SUBMITTED
        sub.submitted_at = now
        apply_result(sub, now)
        sub.save()
        bridge.consume_token(locked_ticket)  # 与写状态同一事务
    return sub
