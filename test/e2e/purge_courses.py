"""E2E 之后的清理：删掉指定课程（含其 media 文件），避免开发库与磁盘留垃圾。

E2E 里通过 API 删课程只会删行、不会删文件（Django 不做文件回收），
所以浏览器测试建的副本必须用这个脚本清，否则每次跑都涨一百多 MB。

    cd backend && ./venv/Scripts/python.exe ../test/e2e/purge_courses.py 12 13
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.core.files.storage import default_storage  # noqa: E402

from apps.courses.models import Course, CourseResource, PPTResource, TeachingVideo  # noqa: E402
from apps.knowledge.models import Material  # noqa: E402
from apps.questions.models import Question  # noqa: E402


def files_of(course: Course) -> list[str]:
    names: list[str] = []
    if course.cover and course.cover.startswith("/media/"):
        names.append(course.cover[7:])
    for ppt in PPTResource.objects.filter(course=course):
        if ppt.file:
            names.append(ppt.file.name)
        names += [p["image"][7:] for p in (ppt.parsed_pages or [])
                  if str(p.get("image", "")).startswith("/media/")]
    for video in TeachingVideo.objects.filter(course=course):
        for item in video.scripts or []:
            url = str(item.get("audio_url") or "")
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


def main(argv: list[str]) -> int:
    if not argv:
        print("用法：purge_courses.py <course_id> [course_id ...]")
        return 2
    for raw in argv:
        try:
            course = Course.objects.get(id=int(raw))
        except (ValueError, Course.DoesNotExist):
            print(f"跳过 {raw}：不存在")
            continue
        names = files_of(course)
        name = course.name
        course.questions.all().delete()  # Question.catalog 是 PROTECT
        course.delete()
        removed = 0
        for item in names:
            try:
                default_storage.delete(item)
                removed += 1
            except Exception:
                pass
        print(f"已删课程 {raw}「{name}」及 {removed} 个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
