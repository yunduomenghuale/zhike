"""P3 E2E fixtures：历史报告 + 全班学生章节总结（class 1 / course 5 / 首个 catalog）。

- class_analytics 历史报告 1 条（success，error='e2e-p3' 标记）
- 班级每生一条 chapter_summary（catalog=首个章节，success）
- 第二个顶层章节（无总结数据，切换章节空态测试用）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from django.contrib.auth import get_user_model

from apps.ai.models import AITask
from apps.courses.models import Catalog
from apps.classroom.models import ClassRoom, ClassStudent

U = get_user_model()
t = U.objects.get(username="t101")
cr = ClassRoom.objects.get(id=1)
course = cr.courses.order_by("id").first()
catalog = Catalog.objects.filter(course=course).order_by("order", "id").first()
students = [
    cs.student for cs in ClassStudent.objects.filter(classroom=cr).select_related("student").order_by("id")
]
assert students, "class 1 无学生"

# 第二个顶层章节（切换章节空态测试用；无总结数据）
Catalog.objects.get_or_create(
    course=course,
    title="第5章 E2E测试章",
    parent__isnull=True,
    defaults={"order": 9, "is_published": True},
)

# 清理旧冒烟数据
AITask.objects.filter(task_type="class_analytics", classroom=cr, error="e2e-p3").delete()
AITask.objects.filter(
    task_type="chapter_summary", student__in=[s.id for s in students], catalog=catalog
).delete()

# 进行中的分析任务（刷新恢复轮询测试用；先建→id 小于下面的成功任务，
# 保证历史列表 vis[0] 仍是成功任务）
AITask.objects.create(
    task_type="class_analytics",
    classroom=cr,
    course=course,
    triggered_by=t,
    status="running",
    error="e2e-p3",
    progress={
        "stage": "analyzing",
        "done": 1,
        "total": 2,
        "message": "E2E-P3 恢复任务：正在分析班级数据",
    },
)

# 历史报告 fixture
AITask.objects.create(
    task_type="class_analytics",
    classroom=cr,
    course=course,
    triggered_by=t,
    status="success",
    error="e2e-p3",
    result={
        "report": (
            "## 整体学情\nE2E-P3 历史报告：班级整体掌握情况良好。\n"
            "## 知识点掌握分析\n递归与 VLAN 为薄弱知识点。\n"
            "## 学生分层画像\n领先层 2 人，风险层 1 人。\n"
            "## 风险预警\n部分学生练习投入不足。\n"
            "## 教学干预建议\n安排一次习题讲解课。"
        ),
        "comments": {str(students[0].id): "E2E-P3 简评：整体表现稳定，注意练习完成度。"},
        "stats_snapshot": {"analyzed_count": 2},
        "generated_at": "2026-10-22 15:00:00",
    },
)

# 班级每生的章节总结 fixture
SUMMARY = {
    "overview": "E2E-P3 总结：本章视频学习完成，练习完成度良好，递归相关知识点掌握不牢。",
    "knowledge_points": [
        {"name": "递归终止条件", "status": "weak", "evidence": "练习 2/5 错，作业第3题错"},
        {"name": "VLAN 原理", "status": "solid", "evidence": "练习 4/4 对"},
    ],
    "weak_points": ["递归终止条件", "递归时间复杂度分析"],
    "highlights": ["视频学习完成度高", "VLAN 相关练习全对"],
    "qa_insight": "询问过递归深度问题，反映对递归机制理解不清晰",
    "suggestions": ["重看第 3 页关于递归终止条件的讲解", "重练递归相关练习题", "完成本章作业第 3 题"],
    "next_step": "今晚重看第 3 页讲解并完成 5 道递归练习",
    "generated_at": "2026-10-22 16:00:00",
}
for stu in students:
    AITask.objects.create(
        task_type="chapter_summary",
        student=stu,
        catalog=catalog,
        course=course,
        version=1,
        status="success",
        triggered_by=stu,
        result=dict(SUMMARY),
    )

print(
    f"fixtures ok: class={cr.id} course={course.id} catalog={catalog.id} "
    f"students={[s.id for s in students]}"
)
