"""整班毕业批处理（方案 §5.5，P4 流转）。

「毕业」在这个系统里是**整班**操作：班级 `status=graduated` + 该班**占用关系
且在读**的学生 `edu_status=graduated`。三条边界条件写死在模块里，调用方绕不开：

1. **判定 = 占用关系（active/inactive）且 edu_status=enrolled**。已转走的学生
   （旧关系是 `transferred`）不能被原班顺手毕业（X-29）——那是纯数据事故：
   本人在新班毫无感知，直到某天发现自己不能再学新课。preview 会把被排除的
   转班学生列出来，让管理员直接看到「谁没被毕业」。
2. **`ClassStudent` 保持 active**。毕业生要能看历史课程与成绩，关系不能删、
   不能置 removed（设计 §5.5 第 4 条）。
3. **延期毕业没有特殊代码路径**：整班毕业无法留人，延期学生先转班（service
   保证旧关系置 `transferred`），再毕业原班。

前置校验（X-14）分级处理：有进行中考试 / 未截止作业时 preview 摆出清单，
`graduate` 默认 409 拒绝，`force=True` 才放行——「按已提交计」的统计口径
不在本模块范围（P4 遗留，见测试报告）。

撤销（授位审核退回）：班级回 `active`、本班占用关系中已毕业的学生回
`enrolled`。只回滚**本批标记**的学生（`status_note` 等于毕业时写入的
「整班毕业（班名）」）——班里若有更早「个别提前毕业」的学生，不会因为
整班撤销被摘掉学位。
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.users.models import User

from .models import ClassRoom, ClassStudent
from .services import OCCUPYING, _log  # 审计落点与入班/转班共用同一入口


class GraduationError(Exception):
    """毕业业务规则冲突。`code` 映射 HTTP 状态码，`data` 供接口附加上下文。"""

    def __init__(self, detail: str, code: int = 409, data: dict | None = None):
        super().__init__(detail)
        self.detail = detail
        self.code = code
        self.data = data or {}


def _batch_marker(classroom: ClassRoom) -> str:
    """整批毕业写在 `status_note` 里的标记。撤销时只认这个标记——
    班里更早「个别提前毕业」的学生 note 不同，不会被误摘。"""
    return f"整班毕业（{classroom.name}）"[:200]


def _target_students(classroom: ClassRoom) -> list:
    """将被毕业的学生：本班占用关系（active/inactive）且学籍在读。"""
    return list(
        ClassStudent.objects.filter(
            classroom=classroom,
            learn_status__in=OCCUPYING,
            student__edu_status=User.EduStatus.ENROLLED,
        )
        .select_related("student")
        .order_by("student__username")
    )


def _transferred_students(classroom: ClassRoom) -> list:
    """已转走/移出的历史关系——毕业时必须排除他们（X-29）。"""
    return list(
        ClassStudent.objects.filter(
            classroom=classroom,
            learn_status__in=[
                ClassStudent.LearnStatus.TRANSFERRED,
                ClassStudent.LearnStatus.REMOVED,
            ],
        )
        .select_related("student")
        .order_by("student__username")
    )


def _blockers(classroom: ClassRoom, student_ids: list[int]) -> dict:
    """在途考试与未截止作业清单（X-14）：毕业即关闭提交入口，这些会永久缺失。"""
    from apps.exams.models import ExamSubmission
    from apps.homework.models import Homework

    now = timezone.now()
    in_progress = [
        {"exam": sub.exam.name, "student": sub.student.real_name or sub.student.username}
        for sub in ExamSubmission.objects.filter(
            exam__classroom=classroom,
            student_id__in=student_ids,
            status=ExamSubmission.Status.IN_PROGRESS,
        ).select_related("exam", "student")
    ]
    open_homeworks = [
        {"title": hw.title, "deadline": hw.deadline.isoformat() if hw.deadline else None}
        for hw in Homework.objects.filter(
            classroom=classroom, status=Homework.Status.PUBLISHED, deadline__gt=now
        ).order_by("deadline")
    ]
    return {"in_progress_exams": in_progress, "open_homeworks": open_homeworks}


def graduate_preview(classroom: ClassRoom) -> dict:
    """毕业前名单预览（方案 §5.5 第 2 条：防误操作的唯一一道闸）。

    不写库。返回将被毕业的学生、被排除的转班学生、在途清单与毕业年份校验，
    供管理端确认页直接渲染。
    """
    targets = _target_students(classroom)
    transferred = _transferred_students(classroom)
    target_ids = [cs.student_id for cs in targets]
    blockers = _blockers(classroom, target_ids)

    graduate_year = classroom.graduate_year
    year_reached = graduate_year is None or timezone.localdate().year >= graduate_year

    return {
        "classroom": {
            "id": classroom.id,
            "name": classroom.name,
            "code": classroom.code,
            "status": classroom.status,
            "enrollment_year": classroom.enrollment_year,
            "duration_years": classroom.duration_years,
            "graduate_year": graduate_year,
            "year_reached": year_reached,
        },
        "students": [
            {
                "id": cs.student_id,
                "username": cs.student.username,
                "name": cs.student.real_name or cs.student.username,
                "edu_status": cs.student.edu_status,
            }
            for cs in targets
        ],
        "student_count": len(targets),
        "transferred": [
            {
                "username": cs.student.username,
                "name": cs.student.real_name or cs.student.username,
                "learn_status": cs.learn_status,
            }
            for cs in transferred
        ],
        "blockers": blockers,
        "already_graduated": classroom.status == ClassRoom.Status.GRADUATED,
    }


@transaction.atomic
def graduate_class(classroom: ClassRoom, *, operator=None, force: bool = False, note: str = "") -> dict:
    """执行整班毕业。返回毕业人数与名单（供接口回包与测试断言）。"""
    if classroom.status == ClassRoom.Status.GRADUATED:
        raise GraduationError("班级已毕业，无需重复操作", code=409)
    if classroom.status == ClassRoom.Status.ARCHIVED:
        raise GraduationError("班级已归档，不能执行毕业", code=409)

    targets = _target_students(classroom)
    if not targets:
        raise GraduationError("班级没有可毕业的学生（需要存在占用关系且在读的学生）", code=400)

    target_ids = [cs.student_id for cs in targets]
    blockers = _blockers(classroom, target_ids)
    has_blockers = bool(blockers["in_progress_exams"] or blockers["open_homeworks"])
    if has_blockers and not force:
        raise GraduationError(
            "存在进行中考试或未截止作业，毕业后将无法补交；请先处理，或确认后强制毕业",
            code=409,
            data=blockers,
        )

    graduate_year = classroom.graduate_year
    if graduate_year is not None and timezone.localdate().year < graduate_year and not force:
        raise GraduationError(
            f"班级预计 {graduate_year} 年毕业，当前未到毕业年份；如需提前毕业请确认后强制提交",
            code=409,
            data={"expected_graduate_year": graduate_year},
        )

    graduated = []
    for cs in targets:
        student = cs.student
        student.edu_status = User.EduStatus.GRADUATED
        student.status_changed_at = timezone.now()
        student.status_note = _batch_marker(classroom)
        student.save(update_fields=["edu_status", "status_changed_at", "status_note"])
        graduated.append(student)
        # ClassStudent.learn_status 不动：保持 active，毕业生才看得到历史课程与成绩

    classroom.status = ClassRoom.Status.GRADUATED
    classroom.save(update_fields=["status", "updated_at"])

    _log(
        "class_graduate",
        operator,
        classroom,
        graduated,
        old={"status": "active"},
        new={
            "status": "graduated",
            "count": len(graduated),
            "students": [u.username for u in graduated],
            "force": force,
        },
        note=note or "整班毕业",
    )
    return {
        "classroom_id": classroom.id,
        "graduated_count": len(graduated),
        "students": [u.username for u in graduated],
        "forced": force,
    }


@transaction.atomic
def revoke_graduation(classroom: ClassRoom, *, operator=None, note: str = "") -> dict:
    """撤销整班毕业（授位审核退回）：班级回 active，本班已毕业学生回 enrolled。

    只回滚**本批毕业**标记的学生（`status_note` 等于毕业时写入的标记）：
    班里若有更早「个别提前毕业」的学生，不能因为整班撤销而被摘掉学位——
    这类学生的 note 是当时单独变更写的，与整批标记不同，天然被排除。
    """
    if classroom.status != ClassRoom.Status.GRADUATED:
        raise GraduationError("班级未毕业，无需撤销", code=400)

    marker = _batch_marker(classroom)
    reverted = []
    for cs in (
        ClassStudent.objects.filter(
            classroom=classroom,
            learn_status__in=OCCUPYING,
            student__edu_status=User.EduStatus.GRADUATED,
            student__status_note=marker,
        )
        .select_related("student")
        .order_by("student__username")
    ):
        student = cs.student
        student.edu_status = User.EduStatus.ENROLLED
        student.status_changed_at = timezone.now()
        student.status_note = f"撤销整班毕业（{classroom.name}）"[:200]
        student.save(update_fields=["edu_status", "status_changed_at", "status_note"])
        reverted.append(student)

    classroom.status = ClassRoom.Status.ACTIVE
    classroom.save(update_fields=["status", "updated_at"])

    _log(
        "class_graduate",
        operator,
        classroom,
        reverted,
        old={"status": "graduated"},
        new={
            "status": "active",
            "reverted_count": len(reverted),
            "students": [u.username for u in reverted],
        },
        note=note or "撤销整班毕业",
    )
    return {
        "classroom_id": classroom.id,
        "reverted_count": len(reverted),
        "students": [u.username for u in reverted],
    }
