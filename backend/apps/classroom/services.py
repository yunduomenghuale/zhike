"""班级学生的唯一写入口。

「学生属于哪个班」在这个系统里只有一处答案：`ClassStudent` 中占用状态
（active / inactive）的那一条记录。`User` 上**没有** classroom 字段，不要再加。

所有入班 / 转班 / 移出 / 学籍变更都必须经过本模块，原因：

1. 单班规则由数据库条件唯一约束（`uniq_occupied_class_per_student`）强制，
   绕过本模块直接 create 会抛 IntegrityError，最终以 500 形态冒到接口层；
2. 转班必须把旧关系置 `transferred` 而不是 `removed`，否则学生看不到旧班成绩；
3. 每次变更要落审计，散落的写操作必然漏。

调用方拿到 `ClassServiceError` 后应转成 4xx（见 `to_api_response`）。
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.users.models import User

from .models import ClassRoom, ClassStudent

OCCUPYING = set(ClassStudent.OCCUPYING_STATUSES)


class ClassServiceError(Exception):
    """业务规则冲突。`code` 用于映射 HTTP 状态码，`detail` 供接口原样返回。"""

    def __init__(self, detail: str, code: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.code = code


def _verify_students(students) -> list[User]:
    """校验入参全是学生账号，返回去重后的列表。"""
    seen, result = set(), []
    for obj in students:
        user = obj if isinstance(obj, User) else User.objects.filter(pk=obj).first()
        if user is None:
            raise ClassServiceError("学生不存在", code=404)
        if user.role != User.Role.STUDENT:
            raise ClassServiceError(f"{user.username} 不是学生账号", code=400)
        if user.pk in seen:
            continue
        seen.add(user.pk)
        result.append(user)
    if not result:
        raise ClassServiceError("未指定学生", code=400)
    return result


def occupied_relation(student, exclude_classroom=None):
    """学生当前的占用关系（最多一条）。没有则返回 None。"""
    qs = ClassStudent.objects.filter(student=student, learn_status__in=OCCUPYING)
    if exclude_classroom is not None:
        qs = qs.exclude(classroom=exclude_classroom)
    return qs.first()


def _log(action, actor, classroom, students, old=None, new=None, note=""):
    """落一条审计。actor 为空时（脚本/迁移）跳过，避免 PROTECT 报错。"""
    if actor is None:
        return
    from apps.platform_admin.models import AdminActionLog

    AdminActionLog.objects.create(
        actor=actor,
        action=action,
        target_type="classroom",
        target_id=classroom.pk,
        target_label=classroom.name,
        old_value=old,
        new_value=new,
        note=note[:255],
    )


@transaction.atomic
def assign_students(classroom: ClassRoom, students, *, operator=None, note="") -> dict:
    """入班唯一入口。

    - 已在目标班：幂等成功（不报错，计入 unchanged）
    - 已在别的班：抛 ClassServiceError（409），附当前班级，由调用方决定是否改走 transfer
    - 迁移/脚本场景可用 `force_transfer=True` 直接转班
    """
    students = _verify_students(students)
    created, unchanged = [], []
    for user in students:
        current = occupied_relation(user)
        if current is not None:
            if current.classroom_id == classroom.pk:
                unchanged.append(user)
                continue
            raise ClassServiceError(
                f"{user.username} 已在「{current.classroom.name}」，转班请使用转班操作",
                code=409,
            )
        try:
            ClassStudent.objects.create(
                classroom=classroom,
                student=user,
                learn_status=ClassStudent.LearnStatus.ACTIVE,
            )
        except IntegrityError as exc:  # 并发下另一请求抢先占位
            raise ClassServiceError(
                f"{user.username} 已被其他班级接收，请刷新后重试", code=409
            ) from exc
        created.append(user)

    if created:
        _log(
            "class_member_add",
            operator,
            classroom,
            created,
            new={"added": [u.username for u in created]},
            note=note,
        )
    return {"created": created, "unchanged": unchanged}


@transaction.atomic
def transfer_students(classroom: ClassRoom, students, *, operator=None, note="", sync_year=True) -> dict:
    """转班：旧关系置 transferred（保留历史可见性），新班建 active。

    学生当前没有班级时抛 400 —— 那是"入班"，不是"转班"，混在一起会让审计
    看不出到底是补录还是转专业。
    """
    students = _verify_students(students)
    moved = []
    for user in students:
        current = occupied_relation(user)
        if current is None:
            raise ClassServiceError(
                f"{user.username} 当前没有班级，请使用入班操作", code=400
            )
        if current.classroom_id == classroom.pk:
            continue
        current.learn_status = ClassStudent.LearnStatus.TRANSFERRED
        current.save(update_fields=["learn_status", "updated_at"])
        try:
            ClassStudent.objects.create(
                classroom=classroom,
                student=user,
                learn_status=ClassStudent.LearnStatus.ACTIVE,
            )
        except IntegrityError as exc:
            raise ClassServiceError(
                f"{user.username} 转班冲突，请刷新后重试", code=409
            ) from exc
        if sync_year and classroom.enrollment_year:
            # 学制/届别跟随班级，除非教师/管理员显式覆盖过（此处按班级统一）
            user.enrollment_year = classroom.enrollment_year
            user.duration_years = classroom.duration_years or user.duration_years
            user.save(update_fields=["enrollment_year", "duration_years"])
        moved.append(user)

    if moved:
        _log(
            "class_member_transfer",
            operator,
            classroom,
            moved,
            new={"transferred_in": [u.username for u in moved]},
            note=note,
        )
    return {"moved": moved}


@transaction.atomic
def remove_students(classroom: ClassRoom, students, *, operator=None, reason="", withdraw=True) -> dict:
    """移出班级。

    withdraw=True（默认）：同时把学籍置 withdrawn —— 用于退学/转出；
    withdraw=False：只解除班级关系，学籍保持 enrolled —— 用于分班纠错。
    """
    students = _verify_students(students)
    removed = []
    for user in students:
        rel = ClassStudent.objects.filter(
            classroom=classroom, student=user, learn_status__in=OCCUPYING
        ).first()
        if rel is None:
            continue
        rel.learn_status = ClassStudent.LearnStatus.REMOVED
        rel.save(update_fields=["learn_status", "updated_at"])
        if withdraw and user.edu_status != User.EduStatus.WITHDRAWN:
            user.edu_status = User.EduStatus.WITHDRAWN
            user.status_changed_at = timezone.now()
            user.status_note = (reason or "移出班级")[:200]
            user.save(update_fields=["edu_status", "status_changed_at", "status_note"])
        removed.append(user)

    if removed:
        _log(
            "class_member_remove",
            operator,
            classroom,
            removed,
            new={"removed": [u.username for u in removed], "withdraw": withdraw},
            note=reason,
        )
    return {"removed": removed}


@transaction.atomic
def change_edu_status(user: User, edu_status: str, *, operator=None, note="") -> User:
    """学籍状态变更（在读/休学/毕业/退学），可回退。

    只改学籍，不动班级关系：毕业生仍保留 active 班级关系，才能看历史课程。
    """
    valid = {c[0] for c in User.EduStatus.choices}
    if edu_status not in valid:
        raise ClassServiceError(f"未知的学籍状态：{edu_status}", code=400)
    old = user.edu_status
    if old == edu_status:
        return user
    user.edu_status = edu_status
    user.status_changed_at = timezone.now()
    user.status_note = (note or "")[:200]
    user.save(update_fields=["edu_status", "status_changed_at", "status_note"])
    if operator is not None:
        from apps.platform_admin.models import AdminActionLog

        AdminActionLog.objects.create(
            actor=operator,
            action="class_member_status",
            target_type="user",
            target_id=user.pk,
            target_label=user.username,
            old_value={"edu_status": old},
            new_value={"edu_status": edu_status},
            note=(note or "")[:255],
        )
    return user
