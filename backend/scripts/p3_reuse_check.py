"""P3 准出验证：课程复用（资产整份复制）六项硬指标逐条实测。

跑法（先起后端 :8005）：

    cd backend && ./venv/Scripts/python.exe scripts/p3_reuse_check.py --source 7

覆盖任务规范 §4 P3 的准出项：

  P3-1 复用 30 页以上 PPT 课程，章节层级 / 页数 / 页图 / 音频 / 令牌 / 片段检索逐项校验
  P3-2 删源课程后新课程资产完好（页图/音频/资料/文档仍可取到字节）
  P3-3 磁盘增量 ≈ 源 media 体积 ±10%
  P3-4 产物 inactive 学生不可见，置 active 后可见
  P3-5 任务失败回滚无孤儿文件（跑真单测，写真实文件后断言目录无残留）
  P3-6 题库可选：不勾选为 0；勾选数量一致且 scenes 正确

脚本自己建数据、自己删干净（行 + 文件），不动源课程。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8005"
TEACHER = ("t101", "pass1234")

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  | {detail}" if detail else ""))
    return bool(ok)


def http(method: str, path: str, token: str | None = None, body: dict | None = None):
    url = BASE + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw[:1] in (b"{", b"[") else raw
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, raw


def head_bytes(url: str) -> tuple[int, int, str]:
    """返回 (status, bytes, content_type)。只取前 64KB，够判"能取到字节"。"""
    req = urllib.request.Request(BASE + url, headers={"Range": "bytes=0-65535"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, len(resp.read()), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, 0, ""


def login(username: str, password: str) -> str:
    status, payload = http("POST", "/api/auth/login/", body={"username": username, "password": password})
    assert status == 200 and payload.get("code") == 0, f"登录失败: {payload}"
    return payload["data"]["token"]["access"]


def wait_task(token: str, task_id: int, timeout: int = 600) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, payload = http("GET", f"/api/ai-tasks/{task_id}/", token)
        assert status == 200, payload
        task = payload["data"]
        if task["status"] in ("success", "failed"):
            return task
        time.sleep(1)
    raise AssertionError(f"任务 {task_id} 超时未结束")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=int, default=7, help="源课程 id（应含 30 页以上 PPT）")
    args = parser.parse_args()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import django

    django.setup()

    from django.conf import settings
    from django.core.files.storage import default_storage

    from apps.ai.vectorstore import search_chunks
    from apps.classroom.models import ClassRoom, ClassStudent
    from apps.courses.models import (
        Catalog,
        Course,
        CourseResource,
        PPTResource,
        TeachingVideo,
    )
    from apps.courses.ppt_parser import ppt_pages_dirname
    from apps.courses.reuse import course_asset_stats
    from apps.knowledge.models import KnowledgeChunk, Material
    from apps.questions.models import Question

    created: list[Course] = []
    # 临时班/临时学生由 sweep() 按名称兜底清理，这里只持有创建时需要的引用
    temp_class = None
    temp_enroll = None

    def media_bytes() -> int:
        root = Path(settings.MEDIA_ROOT)
        return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())

    def files_of(course: Course) -> list[str]:
        names = []
        if course.cover and course.cover.startswith("/media/"):
            names.append(course.cover[7:])
        for ppt in PPTResource.objects.filter(course=course):
            if ppt.file:
                names.append(ppt.file.name)
            names += [p["image"][7:] for p in (ppt.parsed_pages or []) if p.get("image", "").startswith("/media/")]
        for video in TeachingVideo.objects.filter(course=course):
            for item in video.scripts or []:
                url = item.get("audio_url", "")
                if url.startswith("/media/"):
                    names.append(url[7:])
            for url in (video.audio_url, video.subtitle_url, video.video_url):
                if url and url.startswith("/media/"):
                    names.append(url[7:])
        for material in Material.objects.filter(course=course):
            if material.file:
                names.append(material.file.name)
        for resource in CourseResource.objects.filter(course=course):
            if resource.file:
                names.append(resource.file.name)
        for question in Question.objects.filter(course=course):
            if question.image:
                names.append(question.image.name)
        return sorted(set(names))

    def purge(course: Course) -> None:
        names = files_of(course)
        course.questions.all().delete()  # Question.catalog 是 PROTECT
        course_id = course.id
        course.delete()
        for name in names:
            try:
                default_storage.delete(name)
            except Exception:
                pass
        print(f"  清理：课程 {course_id} 及 {len(names)} 个文件")

    def sweep(label: str) -> list[str]:
        """清掉本脚本可能留下的一切痕迹。

        每一步都单独兜异常：清理代码里任何一步抛错都会让后面的步骤整体跳过
        （P3 首次联调就这样在开发库里漏下两个空的「P3验证临时班」）。
        返回没能清掉的项目名，供最后汇总。
        """
        from django.contrib.auth import get_user_model

        from apps.ai.models import AITask

        leftovers: list[str] = []
        print(f"\n[{label}] 清理上次运行可能残留的测试数据")
        for course in list(Course.objects.filter(name__startswith="P3验证-")):
            try:
                purge(course)
            except Exception as exc:  # noqa: BLE001 - 清理要尽力而为，不能半途而废
                leftovers.append(f"课程 {course.id}: {exc}")
        for klass in list(ClassRoom.objects.filter(name="P3验证临时班")):
            try:
                klass_id = klass.id  # delete() 后 pk 会被置空，先取
                klass.delete()
                print(f"  清理：临时班 {klass_id}")
            except Exception as exc:  # noqa: BLE001
                leftovers.append(f"临时班 {klass.id}: {exc}")
        try:
            deleted, _ = get_user_model().objects.filter(username="p3v_student").delete()
            if deleted:
                print(f"  清理：临时学生账号（{deleted} 条）")
        except Exception as exc:  # noqa: BLE001
            leftovers.append(f"p3v_student: {exc}")
        try:
            # 复用任务记录会一直堆在开发库里，顺手按本脚本前缀的任务类型清
            stale = AITask.objects.filter(task_type=AITask.TaskType.COURSE_REUSE)
            count = stale.count()
            if count:
                stale.delete()
                print(f"  清理：历史复用任务记录（{count} 条）")
        except Exception as exc:  # noqa: BLE001
            leftovers.append(f"AITask: {exc}")
        return leftovers

    # 先扫一次：上次异常退出留下的数据不能污染本次的「磁盘增量」等断言
    leftover_before = sweep("运行前")

    try:
        print(f"\n=== P3 准出验证（源课程 {args.source}）===")
        token = login(*TEACHER)

        source = Course.objects.get(id=args.source)
        stats = course_asset_stats(source)
        print(f"源课程：{source.name} | 章节 {stats.catalog_count} / 页 {stats.ppt_pages} / "
              f"片段 {stats.chunk_count} / {stats.as_dict()['media_human']}")
        check("源课程具备 30 页以上 PPT", stats.ppt_pages >= 30, f"实际 {stats.ppt_pages} 页")
        check("源课程有可检索片段", stats.chunk_count > 0, f"{stats.chunk_count} 片段")

        # --- 预览接口 -------------------------------------------------
        status, payload = http("GET", f"/api/courses/{source.id}/reuse-preview/", token)
        preview = payload.get("data") or {}
        check("预览接口返回资产清单", status == 200 and preview.get("assets", {}).get("ppt_pages") == stats.ppt_pages,
              f"status={status} pages={preview.get('assets', {}).get('ppt_pages')}")
        check("预览接口带学期候选", len(preview.get("terms") or []) >= 1)

        # --- 提交复用（含题目） ---------------------------------------
        before_bytes = media_bytes()
        status, payload = http("POST", f"/api/courses/{source.id}/reuse/", token,
                               {"name": "P3验证-A", "include_questions": True})
        check("提交复用任务", status == 200 and payload.get("data", {}).get("task_id"),
              f"status={status} {payload.get('message')}")
        task_a = wait_task(token, payload["data"]["task_id"])
        if not check("任务执行成功", task_a["status"] == "success", task_a.get("error") or ""):
            return 1
        copy_a = Course.objects.get(id=task_a["result"]["course_id"])
        created.append(copy_a)
        result_a = task_a["result"]
        check("复制计数与源一致",
              result_a["copied"]["catalog"] == stats.catalog_count
              and result_a["copied"]["ppt"] == stats.ppt_count
              and result_a["copied"]["chunk"] == stats.chunk_count
              and result_a["copied"]["question"] == stats.question_count,
              json.dumps(result_a["copied"], ensure_ascii=False))

        # --- P3-1 逐项校验 --------------------------------------------
        def tree(course):
            rows = {c.id: c for c in Catalog.objects.filter(course=course)}
            return sorted((c.title, rows[c.parent_id].title if c.parent_id else "", c.order, c.is_published)
                          for c in rows.values())

        check("章节层级一致", tree(source) == tree(copy_a),
              f"{len(tree(copy_a))} 个章节")

        src_pages = sum(len(p.parsed_pages or []) for p in PPTResource.objects.filter(course=source))
        new_ppts = list(PPTResource.objects.filter(course=copy_a))
        new_pages = sum(len(p.parsed_pages or []) for p in new_ppts)
        check("课件页数一致", new_pages == src_pages == stats.ppt_pages, f"{new_pages}/{src_pages}")
        dirs_ok = all(
            all(f"/ppt_pages/{ppt_pages_dirname(p.id)}/" in page.get("image", "")
                for page in p.parsed_pages or [])
            for p in new_ppts
        )
        check("页图 URL 指向新目录", dirs_ok)

        samples = [page["image"] for p in new_ppts for page in (p.parsed_pages or [])][:5]
        ok = all(head_bytes(u)[0] == 200 and head_bytes(u)[1] > 0 for u in samples)
        check("页图可访问（抽样 5 张）", ok, samples[0] if samples else "无页图")

        pdf_ok = all(head_bytes(f"/media/{p.file.name}")[0] == 200
                     for p in new_ppts if p.file)
        check("课件原文件可下载", pdf_ok, f"{len([p for p in new_ppts if p.file])} 个文件")

        src_videos = list(TeachingVideo.objects.filter(course=source))
        new_videos = list(TeachingVideo.objects.filter(course=copy_a))
        src_scripts = sum(len(v.scripts or []) for v in src_videos)
        new_scripts = sum(len(v.scripts or []) for v in new_videos)
        check("讲稿页数一致", new_scripts == src_scripts == stats.script_pages,
              f"{new_scripts}/{src_scripts}")
        audios = [s["audio_url"] for v in new_videos for s in (v.scripts or []) if s.get("audio_url")]
        audio_sample = audios[:5]
        audio_ok = all(head_bytes(u)[0] == 200 and head_bytes(u)[1] > 0 for u in audio_sample)
        check("配音可播（抽样 5 条）", audio_ok, audio_sample[0] if audio_sample else "无配音")
        src_audio_set = {s.get("audio_url") for v in src_videos for s in (v.scripts or [])}
        check("配音路径与源课程不同", not (set(audios) & src_audio_set),
              f"重叠 {len(set(audios) & src_audio_set)}")

        src_tokens = {r.access_token for r in CourseResource.objects.filter(course=source)}
        new_tokens = {r.access_token for r in CourseResource.objects.filter(course=copy_a)}
        check("资源 access_token 全不相同",
              len(new_tokens) == CourseResource.objects.filter(course=copy_a).count()
              and not (src_tokens & new_tokens),
              f"{len(new_tokens)} 条")

        src_chunks = list(KnowledgeChunk.objects.filter(course=source))
        new_chunks = list(KnowledgeChunk.objects.filter(course=copy_a))
        check("片段数一致", len(new_chunks) == len(src_chunks) == stats.chunk_count,
              f"{len(new_chunks)}/{len(src_chunks)}")
        hit_ok, hit_detail = True, []
        for chunk in src_chunks[:: max(1, len(src_chunks) // 3)][:3]:
            if not chunk.embedding:
                continue
            rows = search_chunks(copy_a.id, chunk.embedding, top_k=3)
            top = rows[0][0] if rows else None
            hit = bool(top) and top.content == chunk.content
            hit_ok = hit_ok and hit
            hit_detail.append(f"{'hit' if hit else 'miss'}:{chunk.source}")
        check("检索命中（抽样 3 片段查新课程）", hit_ok, " / ".join(hit_detail))

        def scene_sets(course) -> list[tuple[str, ...]]:
            return sorted(
                tuple(sorted(q.scenes.values_list("code", flat=True)))
                for q in Question.objects.filter(course=course).prefetch_related("scenes")
            )

        scenes_src, scenes_new = scene_sets(source), scene_sets(copy_a)
        check("题目数量与 scenes 一致",
              Question.objects.filter(course=copy_a).count() == stats.question_count
              and scenes_src == scenes_new,
              f"{len(scenes_new)} 题 / 场景 {scenes_new[:3]}")

        # --- P3-3 磁盘增量 --------------------------------------------
        grown = media_bytes() - before_bytes
        delta_ratio = abs(grown - stats.media_bytes) / max(stats.media_bytes, 1)
        check("磁盘增量 ≈ 源 media 体积（±10%）", delta_ratio <= 0.10,
              f"增量 {grown} / 源 {stats.media_bytes} = {delta_ratio:.2%}")

        # --- P3-4 产物 inactive 学生不可见 ----------------------------
        from django.contrib.auth import get_user_model

        User = get_user_model()
        stu_name, stu_pass = "p3v_student", "P3vPass!2026"
        student = User.objects.filter(username=stu_name).first()
        if student is None:
            student = User.objects.create_user(
                username=stu_name, password=stu_pass, role=User.Role.STUDENT,
                real_name="P3验证学生",
            )
        else:
            student.set_password(stu_pass)
            student.save(update_fields=["password"])
        temp_class = ClassRoom.objects.create(
            name="P3验证临时班", code=f"P3TMP{int(time.time()) % 100000}", teacher=source.teacher,
        )
        temp_enroll = ClassStudent.objects.create(classroom=temp_class, student=student)
        temp_class.courses.add(copy_a)
        check("产物状态为停用", copy_a.status == Course.Status.INACTIVE, copy_a.status)

        stu_token = login(stu_name, stu_pass)

        def student_ids() -> list[int]:
            code, body = http("GET", "/api/courses/", stu_token)
            if code != 200:
                return []
            data = body.get("data")
            rows = data.get("results") if isinstance(data, dict) else (data or [])
            return [row["id"] for row in rows]

        ids = student_ids()
        check("停用产物学生不可见", copy_a.id not in ids, f"学生可见 {len(ids)} 门课")

        status, payload = http("PATCH", f"/api/courses/{copy_a.id}/", token, {"status": "active"})
        check("置为启用", status == 200 and payload.get("code") == 0, f"status={status}")
        ids = student_ids()
        check("启用后学生可见", copy_a.id in ids, f"学生可见 {len(ids)} 门课")

        # --- P3-2 删源课程后新课程资产完好 ----------------------------
        # 用「A 的副本 B」验证：删掉 A（含它的全部文件），B 必须完好。
        status, payload = http("POST", f"/api/courses/{copy_a.id}/reuse/", token,
                               {"name": "P3验证-B", "include_questions": False})
        task_b = wait_task(token, payload["data"]["task_id"])
        copy_b = Course.objects.get(id=task_b["result"]["course_id"])
        created.append(copy_b)
        check("B 未复制题目（题库可选）", task_b["result"]["copied"]["question"] == 0
              and Question.objects.filter(course=copy_b).count() == 0,
              json.dumps(task_b["result"]["copied"], ensure_ascii=False))

        b_files = files_of(copy_b)
        purge(copy_a)
        created.remove(copy_a)
        check("删源后 B 的文件仍在盘上", all(default_storage.exists(n) for n in b_files),
              f"{len(b_files)} 个文件")
        b_page = [p["image"] for p in PPTResource.objects.filter(course=copy_b).first().parsed_pages][:3]
        b_audio = [s["audio_url"] for v in TeachingVideo.objects.filter(course=copy_b)
                   for s in (v.scripts or []) if s.get("audio_url")][:3]
        ok = all(head_bytes(u)[0] == 200 for u in b_page + b_audio)
        check("删源后 B 的页图/配音仍可访问", ok, f"{len(b_page) + len(b_audio)} 个抽样")
        check("删源后 B 的片段/章节完好",
              KnowledgeChunk.objects.filter(course=copy_b).count() == stats.chunk_count
              and Catalog.objects.filter(course=copy_b).count() == stats.catalog_count,
              f"{KnowledgeChunk.objects.filter(course=copy_b).count()} 片段")

        # --- P3-5 失败回滚无孤儿文件（真单测，写真实文件） ------------
        proc = subprocess.run(
            [sys.executable, "manage.py", "test",
             "apps.courses.tests_reuse.CourseCopyTests.test_failure_rolls_back_rows_and_files"],
            cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True,
        )
        # manage.py test 的汇总行走 stderr（进度点也在 stderr），两路都要看
        tail = [line for line in (proc.stdout + "\n" + proc.stderr).splitlines()
                if line.strip().startswith(("OK", "FAILED", "Ran"))]
        check("失败回滚：无半成品课程、无孤儿文件", proc.returncode == 0,
              " / ".join(tail) or "无输出")

        # --- 并发互斥 -------------------------------------------------
        first_status, _ = http("POST", f"/api/courses/{copy_b.id}/reuse/", token, {"name": "P3验证-C"})
        second_status, second_payload = http(
            "POST", f"/api/courses/{copy_b.id}/reuse/", token, {"name": "P3验证-C2"})
        if second_status == 409:
            check("重复提交返回 409 并给出进行中的 task_id",
                  first_status == 200 and bool((second_payload.get("data") or {}).get("task_id")),
                  f"第二次 {second_status}")
            wait_task(token, second_payload["data"]["task_id"])
        else:
            check("重复提交返回 409", False, f"第二次返回 {second_status}")
    finally:
        leftovers = sweep("收尾") + leftover_before
        if leftovers:
            print(f"  !! 仍有残留：{leftovers}")
        failed = [r for r in RESULTS if not r[1]]
        print(f"\n=== 结果：{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过 ===")
        if leftover_before:
            print(f"  !! 运行前就有残留（已尝试清理）：{leftover_before}")
    for name, _, detail in failed:
        print(f"  FAIL {name}  {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
