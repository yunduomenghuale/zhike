# -*- coding: utf-8 -*-
"""清理作业 E2E 残留数据：E2E-附件作业/E2E-客观题作业（含提交/答题记录/媒体文件）、
学生在 hw2 上的 E2E 提交、暂存目录孤儿文件。保留 hw11（用户手动测试作业）与 hw2/hw5 本身。

运行：venv/Scripts/python.exe manage.py shell -c "exec(open('cleanup_hw_e2e.py',encoding='utf-8').read())"
"""
import os
from django.conf import settings

from apps.questions.models import AnswerRecord
from apps.homework.models import Homework, HomeworkAnswer, HomeworkSubmission

# 1) E2E 创建的作业（附件作业 + 客观题作业）
e2e_hws = list(Homework.objects.filter(title__startswith="E2E-").values_list("id", flat=True))
if e2e_hws:
    HomeworkAnswer.objects.filter(homework_question__homework_id__in=e2e_hws).delete()
    AnswerRecord.objects.filter(scene=AnswerRecord.Scene.HOMEWORK, scene_ref_id__in=e2e_hws).delete()
    subs = HomeworkSubmission.objects.filter(homework_id__in=e2e_hws)
    print("删除 E2E 作业", len(e2e_hws), "个，提交", subs.count(), "份")
    subs.delete()  # 先删提交（级联会随作业删除，显式删除以便统计）
    Homework.objects.filter(id__in=e2e_hws).delete()

# 2) 学生在 hw2/hw5 上的 E2E 提交记录（保留作业本身）
for hw_id in (2, 5):
    hw = Homework.objects.filter(id=hw_id).first()
    if not hw:
        continue
    subs = HomeworkSubmission.objects.filter(homework=hw)
    if subs.exists():
        HomeworkAnswer.objects.filter(homework_question__homework=hw).delete()
        AnswerRecord.objects.filter(scene=AnswerRecord.Scene.HOMEWORK, scene_ref_id=hw.id).delete()
        print(f"删除 hw{hw_id}（{hw.title}）的提交", subs.count(), "份")
        subs.delete()

# 3) 删除 E2E 上传产生的媒体文件（homework/ 与 homework_submit/ 下的孤儿/残留）
media = settings.MEDIA_ROOT
removed = 0
for sub in ("homework", "homework_submit", "homework_preview"):
    directory = os.path.join(media, sub)
    if not os.path.isdir(directory):
        continue
    for name in os.listdir(directory):
        p = os.path.join(directory, name)
        if os.path.isfile(p):
            # 保留非 E2E 内容无法逐一甄别时只清理预览缓存（内容可重建）与暂存孤儿；
            # homework/ 下为教师正式附件，仅当作业已删成为孤儿时才清理
            pass
# homework_preview 为可重建缓存，直接清空
import shutil
preview_dir = os.path.join(media, "homework_preview")
if os.path.isdir(preview_dir):
    shutil.rmtree(preview_dir, ignore_errors=True)
    print("已清空 PDF 预览缓存目录")

# homework_submit 暂存目录：提交已删，全部为孤儿
submit_dir = os.path.join(media, "homework_submit")
if os.path.isdir(submit_dir):
    for name in os.listdir(submit_dir):
        p = os.path.join(submit_dir, name)
        if os.path.isfile(p):
            os.remove(p)
            removed += 1
print("已清理暂存孤儿文件", removed, "个")

# 4) homework/ 下被删作业的附件成为孤儿：当前无提交/作业引用即删除
referenced = set()
for hw in Homework.objects.all():
    for item in hw.attachments or []:
        url = str(item.get("url") or "")
        if url.startswith(settings.MEDIA_URL):
            referenced.add(url[len(settings.MEDIA_URL):])
for sub in HomeworkSubmission.objects.all():
    for item in sub.attachments or []:
        url = str(item.get("url") or "")
        if url.startswith(settings.MEDIA_URL):
            referenced.add(url[len(settings.MEDIA_URL):])
hw_dir = os.path.join(media, "homework")
if os.path.isdir(hw_dir):
    orphan = 0
    for name in os.listdir(hw_dir):
        p = os.path.join(hw_dir, name)
        rel = f"homework/{name}"
        if os.path.isfile(p) and rel not in referenced:
            os.remove(p)
            orphan += 1
    print("已清理 homework/ 孤儿附件", orphan, "个")

print("清理完成")
