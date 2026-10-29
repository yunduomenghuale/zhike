"""P1 权限矩阵实测：4 角色 × 关键动作，逐格断言。

为什么要单独跑一遍：pytest 用例是按功能点写的，容易漏掉"换个角色再打同一个接口"；
而 P1 的核心改动就是把权限锚点从 `ClassRoom.teacher` 换成 `Course.teacher`，
最容易出的错正是"某个角色在某个接口上越权或过权"。

跑法（必须用临时库副本，避免污染开发库）：

    cp db.sqlite3 D:/tmp/p1_matrix.sqlite3
    SQLITE_PATH=D:/tmp/p1_matrix.sqlite3 ./venv/Scripts/python.exe scripts/p1_permission_matrix.py

脚本自带 fixture：教师B + 教师B的课（挂进教师A的班）+ 备用学生，
全部以 p1_ 前缀命名，重复执行会先清干净再建。
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.db import transaction  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.classroom.models import ClassCourse, ClassRoom, ClassStudent  # noqa: E402
from apps.courses.models import Course  # noqa: E402
from apps.exams.models import Exam  # noqa: E402
from apps.homework.models import Homework  # noqa: E402
from apps.users.models import User  # noqa: E402

PREFIX = "p1_"
PASS, FAIL = [], []


def check(label, got, want):
    ok = got in want if isinstance(want, (set, tuple, list)) else got == want
    (PASS if ok else FAIL).append(label)
    print(f"  {'OK  ' if ok else 'FAIL'} {label:<44} got={got} want={sorted(want) if isinstance(want, set) else want}")
    return ok


def _rows(payload):
    """列表接口兼容「裸数组 / results / items」三种形态。"""
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("results", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    return data or []


# ---------------------------------------------------------------------------
# fixture
# ---------------------------------------------------------------------------
def build_fixture():
    admin = User.objects.filter(role=User.Role.ADMIN, is_active=True).order_by("id").first()
    teacher_a = User.objects.filter(username="t101").first()
    assert admin, "开发库里没有管理员账号"
    assert teacher_a, "开发库里没有 t101"

    course_a = Course.objects.filter(teacher=teacher_a, status=Course.Status.ACTIVE).order_by("id").first()
    assert course_a, "t101 没有进行中的课程"
    link = ClassCourse.objects.filter(course=course_a).order_by("id").first()
    assert link, "t101 的课程没挂任何班级"
    classroom = link.classroom

    # 幂等：先清掉上一轮残留（顺序遵守 PROTECT：先关系后用户）
    ClassRoom.objects.filter(code__startswith=PREFIX.upper()).delete()
    ClassCourse.objects.filter(course__name__startswith="P1-").delete()
    Course.objects.filter(name__startswith="P1-").delete()
    User.objects.filter(username__startswith=PREFIX).delete()

    teacher_b = User.objects.create_user(
        username=f"{PREFIX}teacher_b", password="Passw0rd!123", role=User.Role.TEACHER,
        real_name="P1教师B",
    )
    course_b = Course.objects.create(
        name="P1-教师B课程", teacher=teacher_b, status=Course.Status.ACTIVE,
    )
    ClassCourse.objects.create(classroom=classroom, course=course_b)
    ClassCourse.objects.get_or_create(classroom=classroom, course=course_a)
    # 未挂进这个班的课程：学生列表里必须看不到（X-03 用）
    course_other = Course.objects.create(
        name="P1-未挂班课程", teacher=teacher_b, status=Course.Status.ACTIVE,
    )

    student = (
        ClassStudent.objects.filter(classroom=classroom, learn_status__in=ClassStudent.OCCUPYING_STATUSES)
        .select_related("student").first()
    )
    assert student, f"班级 {classroom.name} 里没有学生，无法测学生视角"
    student_user = student.student

    spares = []
    for i in (1, 2):
        stu = User.objects.create_user(
            username=f"{PREFIX}spare_{i}", password="Passw0rd!123", role=User.Role.STUDENT,
            real_name=f"P1备用学生{i}",
        )
        spares.append(stu)

    return {
        "admin": admin, "teacher_a": teacher_a, "teacher_b": teacher_b,
        "course_a": course_a, "course_b": course_b, "course_other": course_other,
        "classroom": classroom, "student_user": student_user, "spares": spares,
    }


# ---------------------------------------------------------------------------
# 矩阵
# ---------------------------------------------------------------------------
def run(fx):
    def client(user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    cli = {role: client(fx[role]) for role in ("admin", "teacher_a", "teacher_b", "student_user")}
    roles = ["admin", "teacher_a", "teacher_b", "student_user"]
    cls_id = fx["classroom"].id
    course_a, course_b = fx["course_a"], fx["course_b"]

    def hit(method, path, role, body=None):
        fn = getattr(cli[role], method.lower())
        resp = fn(path, body, format="json") if body is not None else fn(path)
        return resp.status_code

    print("\n[1] 建班（管理员专属）")
    created_ids = []
    for role in roles:
        body = {"code": f"{PREFIX.upper()}NEW-{role}", "name": f"P1-建班-{role}", "courses": [course_a.id]}
        code = hit("post", "/api/classes/", role, body)
        check(f"建班 / {role}", code, {201} if role == "admin" else {403})
    created_ids = list(ClassRoom.objects.filter(name__startswith="P1-建班-").values_list("id", flat=True))
    throwaway = ClassRoom.objects.filter(name="P1-建班-admin").first()
    assert throwaway, "管理员建班未落库，检查 建班 用例"

    print("\n[2] 改班 / 归档（管理员专属）")
    for role in roles:
        code = hit("patch", f"/api/classes/{cls_id}/", role, {"name": fx["classroom"].name})
        check(f"改班 / {role}", code, {200} if role == "admin" else {403})
    for role in roles:
        code = hit("patch", f"/api/classes/{throwaway.id}/", role, {"status": "archived"})
        # 非管理员看到 403（该班在他授课范围内，但组织字段不许改）
        # 或 404（该班根本不在他可见范围，按不泄露存在性处理）
        check(f"归档 / {role}", code, {200} if role == "admin" else {403, 404})
        if role == "admin":
            hit("patch", f"/api/classes/{throwaway.id}/", "admin", {"status": "active"})

    print("\n[3] 班级成员增删（管理员专属）")
    for role in roles:
        code = hit("post", f"/api/classes/{cls_id}/add-student/", role,
                   {"username": fx["spares"][0].username})
        check(f"加成员 / {role}", code, {200, 201} if role == "admin" else {403})
    rel = ClassStudent.objects.filter(classroom=fx["classroom"], student=fx["spares"][0]).first()
    assert rel, "管理员加成员未落库，后续移除无法验证"
    for role in roles:
        code = hit("delete", f"/api/class-students/{rel.id}/", role)
        check(f"移成员 / {role}", code, {200, 204} if role == "admin" else {403})

    print("\n[4] 给班级挂自己的课（管理员 + 两位任课教师）")
    def restore_links():
        ClassCourse.objects.get_or_create(classroom=fx["classroom"], course=course_a)
        ClassCourse.objects.get_or_create(classroom=fx["classroom"], course=course_b)

    for role, own in (("admin", [course_a.id, course_b.id]), ("teacher_a", [course_a.id]),
                      ("teacher_b", [course_b.id]), ("student_user", [course_a.id])):
        code = hit("patch", f"/api/classes/{cls_id}/", role, {"courses": own})
        check(f"挂课 / {role}", code, {200} if role != "student_user" else {403})
        restore_links()

    print("\n[5] 发作业 / 发考试")
    for role, cid in (("admin", course_a.id), ("teacher_a", course_a.id),
                      ("teacher_b", course_b.id), ("student_user", course_a.id)):
        code = hit("post", "/api/homeworks/", role,
                   {"course": cid, "classroom": cls_id, "title": f"P1-作业-{role}"})
        check(f"发作业 / {role}", code, {201} if role != "student_user" else {403})
        code = hit("post", "/api/exams/", role,
                   {"course": cid, "classroom": cls_id, "name": f"P1-考试-{role}"})
        check(f"发考试 / {role}", code, {201} if role != "student_user" else {403})

    print("\n[6] 班级统计（不带 course：落到自己的课）")
    for role in roles:
        resp = cli[role].get(f"/api/analytics/class/{cls_id}/")
        want = {403} if role == "student_user" else {200}
        check(f"统计无参 / {role}", resp.status_code, want)
        if resp.status_code == 200:
            got_course = (resp.data.get("data") or {}).get("course_id")
            expect_course = {"admin": course_a.id, "teacher_a": course_a.id, "teacher_b": course_b.id}[role]
            check(f"统计无参 / {role} 落到自己的课", got_course, expect_course)

    print("\n[7] 班级统计带「别人的课」id（X-02 验收点）")
    for role in roles:
        resp = cli[role].get(f"/api/analytics/class/{cls_id}/?course={course_a.id}")
        want = {403} if role in ("teacher_b", "student_user") else {200}
        check(f"统计?course=A的课 / {role}", resp.status_code, want)

    print("\n[8] 学生详情带「别人的课」id（X-02 验收点）")
    stu_id = fx["student_user"].id
    for role in roles:
        resp = cli[role].get(f"/api/analytics/class/{cls_id}/students/{stu_id}/?course={course_a.id}")
        want = {403} if role in ("teacher_b", "student_user") else {200}
        check(f"学生详情?course=A的课 / {role}", resp.status_code, want)

    print("\n[9] 邀请码加入（已下线，学生 410）")
    for role in roles:
        code = hit("post", "/api/classes/join/", role,
                   {"invite_code": fx["classroom"].invite_code})
        check(f"邀请码 / {role}", code, {410} if role == "student_user" else {403})

    print("\n[10] 学生课程列表过滤（X-03）")
    resp = cli["student_user"].get("/api/courses/")
    payload = resp.data.get("data")
    rows = payload.get("results") if isinstance(payload, dict) else payload
    ids = {row["id"] for row in (rows or [])}
    check("学生可见本班教师A的课", fx["course_a"].id in ids, True)
    check("学生可见本班教师B的课", fx["course_b"].id in ids, True)
    check("学生看不到未挂进本班的课", fx["course_other"].id in ids, False)

    print("\n[11] 回归：学习统计导出 + 督管看板（锚点换过之后必须仍然通）")
    resp = cli["teacher_a"].get(
        f"/api/analytics/class/{cls_id}/export/?course={course_a.id}&sheets=overview"
    )
    check("教师导出 Excel 状态码", resp.status_code, 200)
    head = b"".join(resp.streaming_content)[:2] if getattr(resp, "streaming_content", None) else b""
    check("导出内容是真 xlsx（PK 头）", head, b"PK")

    resp = cli["admin"].get("/api/admin-panel/classes/")
    check("督管班级列表 / admin", resp.status_code, 200)
    class_rows = _rows(resp.data)
    check("督管班级列表非空", len(class_rows) > 0, True)
    if class_rows:
        row = class_rows[0]
        check("督管班级行带 student_count（占用口径）", isinstance(row.get("student_count"), int), True)
        check("督管班级行带建班人字段", "creator_name" in row, True)

    resp = cli["admin"].get("/api/admin-panel/teachers/")
    check("督管教师列表 / admin", resp.status_code, 200)
    teacher_rows = _rows(resp.data)
    check("督管教师列表非空", len(teacher_rows) > 0, True)
    if teacher_rows:
        check("督管教师行带 class_count", isinstance(teacher_rows[0].get("class_count"), int), True)
        check("督管教师行带 student_count", isinstance(teacher_rows[0].get("student_count"), int), True)

    # 清理本轮造的教学数据（作业/考试/建班/挂课关系/课程）
    Homework.objects.filter(title__startswith="P1-作业-").delete()
    Exam.objects.filter(name__startswith="P1-考试-").delete()
    ClassRoom.objects.filter(id__in=created_ids).delete()
    ClassCourse.objects.filter(course__name__startswith="P1-").delete()
    Course.objects.filter(name__startswith="P1-").delete()


def main():
    if not os.environ.get("SQLITE_PATH"):
        print("拒绝执行：请设置 SQLITE_PATH 指向临时副本（例 D:/tmp/p1_matrix.sqlite3），"
              "避免在开发库上造数据。")
        return 2
    print(f"[0] 使用数据库 {os.environ['SQLITE_PATH']}")
    with transaction.atomic():
        fx = build_fixture()
    run(fx)
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for name in FAIL:
        print("  未通过：" + name)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
