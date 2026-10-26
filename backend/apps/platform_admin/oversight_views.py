"""平台端督管视图（概览趋势/待办异常、课程·班级·教师三维监管、操作审计）。

与 views.py 的分工：views.py 承载存量管理端（用户/AI 配置/流水），
本文件承载督管增强端点。共用 _paginated_response 等助手（从 views 导入）。

ViewSet 化（2026-10-19，三期「风格统一」）：同资源的多端点收口为一个
ViewSet（列表/详情/状态干预/导出），URL 仍逐条显式声明（前端路径不可变），
由 urls.py 的 as_view({方法: 动作}) 映射；单方法端点（概览趋势/告警）
与存量端点保持 APIView——ViewSet 的收益在于同资源多动作收口。
"""
import csv
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.views import APIView
from .throttles import AdminThrottleMixin

from apps.classroom.models import ClassRoom, ClassStudent
from apps.common.permissions import IsPlatformAdmin
from apps.common.response import api_response
from apps.courses.models import Catalog, Course, PPTResource, TeachingVideo
from apps.exams.models import Exam, ExamSubmission
from apps.homework.models import Homework, HomeworkSubmission
from apps.questions.models import Question
from apps.ai.models import AICallLog, AICapabilityConfig

from .audit import log_admin_action
from .models import AdminActionLog
from .serializers import (
    AdminClassSerializer,
    AdminCourseSerializer,
    AdminActionLogSerializer,
    ClassStatusSerializer,
    CourseStatusSerializer,
)
from .services import (
    TRENDS_MAX_DAYS,
    cached_platform_alerts,
    cached_platform_trends,
    class_progress_summary,
    course_last_updates,
    teacher_rows,
)
from .views import _page_params, _paginated_response

User = get_user_model()

_MAX_EXPORT = 5000  # 监管导出上限保护
_AUDIT_MAX_EXPORT = 50000


def _csv_response(filename_prefix: str):
    """CSV 响应（带 BOM，Excel 直接打开中文不乱码）——与 AI 流水导出同一模式。"""
    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    filename = f"{filename_prefix}_{timezone.localtime():%Y%m%d_%H%M}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# 概览：趋势 + 待办异常（A1/A2）
# ---------------------------------------------------------------------------

class AdminTrendsView(AdminThrottleMixin, APIView):
    """平台趋势：近 N 天新增用户/课程/班级 + 日活跃学生，附上周期环比。"""

    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        try:
            days = int(request.query_params.get("days", 30))
        except (TypeError, ValueError):
            days = 30
        if not 1 <= days <= TRENDS_MAX_DAYS:
            return api_response(
                message=f"days 需在 1~{TRENDS_MAX_DAYS} 之间", code=400, status=400
            )
        return api_response(cached_platform_trends(days))


class AdminAlertsView(AdminThrottleMixin, APIView):
    """平台待办与异常：待批改作业/未发布成绩/AI 异常/失败课件/未活跃师生。"""

    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        return api_response({"items": cached_platform_alerts()})


# ---------------------------------------------------------------------------
# 课程监管：列表增强（A3）+ 详情（A4）
# ---------------------------------------------------------------------------

def _course_list_queryset(request):
    queryset = Course.objects.select_related("teacher").annotate(
        class_count=Count("classes", distinct=True),
        student_count=Count("classes__students", distinct=True),
        catalog_count=Count("catalogs", distinct=True),
        ppt_count=Count("ppts", distinct=True, filter=Q(ppts__is_active=True)),
        video_count=Count("videos", distinct=True),
        question_count=Count("questions", distinct=True),
        homework_count=Count("homeworks", distinct=True),
        exam_count=Count("exams", distinct=True),
    ).order_by("-created_at")
    keyword = request.query_params.get("search", "").strip()
    state = request.query_params.get("status", "").strip()
    if keyword:
        queryset = queryset.filter(
            Q(name__icontains=keyword)
            | Q(teacher__username__icontains=keyword)
            | Q(teacher__real_name__icontains=keyword)
            | Q(term__icontains=keyword)
        )
    if state:
        queryset = queryset.filter(status=state)
    return queryset


class AdminCourseViewSet(AdminThrottleMixin, viewsets.ViewSet):
    """课程监管一处收口：列表（资产计数）+ 详情（章节树/作业考试）+ 状态干预 + 导出。

    URL 由 urls.py 逐条显式映射（as_view({方法: 动作})），前端路径不变；
    导出成本高于普通读，用 action_scopes 单独走 admin_export 档。
    """

    method_scopes = {"GET": "admin_read", "PATCH": "admin_write"}
    action_scopes = {"export": "admin_export"}
    permission_classes = [IsPlatformAdmin]
    serializer_class = AdminCourseSerializer

    def list(self, request):
        queryset = _course_list_queryset(request)
        p, size = _page_params(request)
        total = queryset.count()
        rows = list(queryset[(p - 1) * size:(p - 1) * size + size])
        updates = course_last_updates([row.id for row in rows])
        items = []
        for row in rows:
            data = AdminCourseSerializer(row).data
            for field in (
                "catalog_count", "ppt_count", "video_count", "question_count",
                "homework_count", "exam_count",
            ):
                data[field] = getattr(row, field)
            data["last_content_update"] = updates.get(row.id)
            items.append(data)
        return api_response({
            "items": items, "total": total, "page": p, "page_size": size,
        })

    def retrieve(self, request, course_id):
        course = get_object_or_404(
            Course.objects.select_related("teacher"), pk=course_id
        )
        # ---- 资产汇总 ----
        ppt_count = PPTResource.objects.filter(course=course, is_active=True).count()
        stats = {
            "catalogs": Catalog.objects.filter(course=course).count(),
            "ppts": ppt_count,
            "videos": TeachingVideo.objects.filter(course=course).count(),
            "questions": Question.objects.filter(course=course).count(),
            "homework_total": Homework.objects.filter(course=course).count(),
            "homework_active": Homework.objects.filter(
                course=course, status=Homework.Status.PUBLISHED
            ).count(),
            "exam_total": Exam.objects.filter(course=course).count(),
            "exam_active": Exam.objects.filter(
                course=course, status=Exam.Status.PUBLISHED
            ).count(),
            "ppt_failed": PPTResource.objects.filter(
                course=course, parse_status=PPTResource.ParseStatus.FAILED
            ).count(),
        }

        # ---- 章节树（两级）----
        catalogs = list(Catalog.objects.filter(course=course).order_by("order", "id"))
        ppt_by_catalog = {
            p.catalog_id: p for p in PPTResource.objects.filter(course=course, is_active=True)
        }
        video_by_catalog = {
            v.catalog_id: v for v in TeachingVideo.objects.filter(course=course)
        }
        qcount = dict(
            Question.objects.filter(course=course)
            .values_list("catalog_id")
            .annotate(n=Count("id"))
        )

        def node(c):
            ppt = ppt_by_catalog.get(c.id)
            video = video_by_catalog.get(c.id)
            return {
                "id": c.id,
                "title": c.title,
                "order": c.order,
                "is_published": c.is_published,
                # 状态一律附 display 文案，避免前端裸枚举直出（如 audio_ready）
                "ppt_status": ppt.parse_status if ppt else None,
                "ppt_status_display": ppt.get_parse_status_display() if ppt else None,
                "ppt_pages": len(ppt.parsed_pages) if ppt else 0,
                "video_status": video.gen_status if video else None,
                "video_status_display": video.get_gen_status_display() if video else None,
                "video_published": video.is_published if video else False,
                "question_count": qcount.get(c.id, 0),
                "children": [],
            }

        nodes = {c.id: node(c) for c in catalogs}
        roots = []
        for c in catalogs:
            if c.parent_id and c.parent_id in nodes:
                nodes[c.parent_id]["children"].append(nodes[c.id])
            else:
                roots.append(nodes[c.id])

        # ---- 作业 / 考试（按班级归属，附提交率）----
        homeworks = []
        for hw in Homework.objects.filter(course=course).select_related("classroom").order_by("-id"):
            total = ClassStudent.objects.filter(
                classroom=hw.classroom
            ).exclude(learn_status=ClassStudent.LearnStatus.REMOVED).count()
            submitted = HomeworkSubmission.objects.filter(homework=hw).count()
            homeworks.append({
                "id": hw.id,
                "title": hw.title,
                "class_name": hw.classroom.name,
                "status": hw.status,
                "status_display": hw.get_status_display(),
                "deadline": hw.deadline,
                "submitted": submitted,
                "total": total,
                "pending_grading": HomeworkSubmission.objects.filter(
                    homework=hw, correct_status=HomeworkSubmission.CorrectStatus.SUBMITTED
                ).count(),
            })
        exams = []
        for exam in Exam.objects.filter(course=course).select_related("classroom").order_by("-id"):
            total = ClassStudent.objects.filter(
                classroom=exam.classroom
            ).exclude(learn_status=ClassStudent.LearnStatus.REMOVED).count()
            taken = ExamSubmission.objects.filter(
                exam=exam,
                status__in=[ExamSubmission.Status.SUBMITTED, ExamSubmission.Status.TIMEOUT],
            ).count()
            # 成绩发布是答卷级开关：统计已交卷但未发布成绩的人数
            unreleased = ExamSubmission.objects.filter(
                exam=exam,
                status__in=[ExamSubmission.Status.SUBMITTED, ExamSubmission.Status.TIMEOUT],
                score_released=False,
            ).count()
            exams.append({
                "id": exam.id,
                "name": exam.name,
                "class_name": exam.classroom.name,
                "status": exam.status,
                "status_display": exam.get_status_display(),
                "start_at": exam.start_at,
                "end_at": exam.end_at,
                "taken": taken,
                "total": total,
                "unreleased": unreleased,
            })

        # ---- 关联班级进度（轻量汇总；逐学生明细在班级详情端点）----
        classes = []
        for classroom in course.classes.all().order_by("id"):
            summary = class_progress_summary(classroom)
            classes.append({
                "id": classroom.id,
                "name": classroom.name,
                "status": classroom.status,
                "teacher_name": classroom.teacher.real_name or classroom.teacher.username,
                "student_count": ClassStudent.objects.filter(
                    classroom=classroom
                ).exclude(learn_status=ClassStudent.LearnStatus.REMOVED).count(),
                **summary,
            })

        return api_response({
            "id": course.id,
            "name": course.name,
            "intro": course.intro,
            "term": course.term,
            "cover": course.cover,
            "status": course.status,
            "status_display": course.get_status_display(),
            "teacher": {
                "id": course.teacher_id,
                "real_name": course.teacher.real_name,
                "username": course.teacher.username,
            },
            "created_at": course.created_at,
            "stats": stats,
            "catalog_tree": roots,
            "homeworks": homeworks,
            "exams": exams,
            "classes": classes,
        })

    def status(self, request, course_id):
        """课程状态干预（启用/停用/归档）：影响预览 + 服务端落审计。"""
        course = get_object_or_404(Course, pk=course_id)
        serializer = CourseStatusSerializer(course, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        old_status = course.status
        serializer.save()
        # 干预影响预览：归档/停用会波及相关班级与学生，响应带回数量供前端确认展示
        affected = {
            "classes": course.classes.count(),
            "students": ClassStudent.objects.filter(
                classroom__courses=course
            ).exclude(learn_status=ClassStudent.LearnStatus.REMOVED)
            .values("student_id").distinct().count(),
            "running_exams": Exam.objects.filter(
                course=course, status=Exam.Status.PUBLISHED
            ).count(),
        }
        if old_status != course.status:
            log_admin_action(
                request.user,
                AdminActionLog.Action.COURSE_STATUS,
                target_type="course",
                target_id=course.id,
                target_label=course.name,
                old_value={"status": old_status},
                new_value={"status": course.status},
                note=f"影响：{affected['classes']} 个班级 / {affected['students']} 名学生 / "
                     f"{affected['running_exams']} 场已发布考试",
            )
        annotated = Course.objects.select_related("teacher").annotate(
            class_count=Count("classes", distinct=True),
            student_count=Count("classes__students", distinct=True),
        ).get(pk=course.pk)
        return api_response(
            {**AdminCourseSerializer(annotated).data, "affected": affected},
            message="课程状态已更新",
        )

    def export(self, request):
        """课程监管导出 CSV（含资产计数；上限 5000 行）。"""
        queryset = _course_list_queryset(request).order_by("-created_at")[:_MAX_EXPORT]
        updates = course_last_updates([row.id for row in queryset])
        response = _csv_response("courses")
        writer = csv.writer(response)
        writer.writerow([
            "课程ID", "课程名称", "学期", "状态", "授课教师", "用户名",
            "关联班级", "覆盖学生", "章节", "课件", "视频", "题目",
            "作业", "考试", "最近内容更新", "创建时间",
        ])
        for row in queryset:
            updated = updates.get(row.id)
            writer.writerow([
                row.id, row.name, row.term or "", row.get_status_display(),
                row.teacher.real_name or "", row.teacher.username,
                row.class_count, row.student_count, row.catalog_count,
                row.ppt_count, row.video_count, row.question_count,
                row.homework_count, row.exam_count,
                timezone.localtime(updated).strftime("%Y-%m-%d %H:%M") if updated else "",
                timezone.localtime(row.created_at).strftime("%Y-%m-%d %H:%M"),
            ])
        return response


# ---------------------------------------------------------------------------
# 班级监管：列表增强（A8）+ 详情（A6）+ 状态干预（A7）
# ---------------------------------------------------------------------------

class AdminClassViewSet(AdminThrottleMixin, viewsets.ViewSet):
    """班级监管一处收口：列表（进度汇总）+ 详情（逐学生进度）+ 状态干预 + 导出。"""

    method_scopes = {"GET": "admin_read", "PATCH": "admin_write"}
    action_scopes = {"export": "admin_export"}
    permission_classes = [IsPlatformAdmin]
    serializer_class = ClassStatusSerializer

    def list(self, request):
        queryset = ClassRoom.objects.select_related("teacher").annotate(
            course_count=Count("courses", distinct=True),
            student_count=Count("students", distinct=True),
        ).order_by("-created_at")
        keyword = request.query_params.get("search", "").strip()
        state = request.query_params.get("status", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(name__icontains=keyword)
                | Q(teacher__username__icontains=keyword)
                | Q(teacher__real_name__icontains=keyword)
            )
        if state:
            queryset = queryset.filter(status=state)
        p, size = _page_params(request)
        total = queryset.count()
        rows = list(queryset[(p - 1) * size:(p - 1) * size + size])
        items = []
        for row in rows:
            data = AdminClassSerializer(row).data
            data.update(class_progress_summary(row))
            items.append(data)
        return api_response({
            "items": items, "total": total, "page": p, "page_size": size,
        })


    def retrieve(self, request, class_id):
        from apps.analytics.services import build_class_stats

        classroom = get_object_or_404(
            ClassRoom.objects.select_related("teacher"), pk=class_id
        )
        course_id = request.query_params.get("course")
        course = (
            classroom.courses.filter(id=course_id).first()
            if course_id else classroom.courses.order_by("id").first()
        )
        if course is None:
            return api_response(message="该班级尚未关联课程", code=400, status=400)
        stats = build_class_stats(classroom, course.id)
        return api_response({
            "id": classroom.id,
            "name": classroom.name,
            "status": classroom.status,
            "status_display": classroom.get_status_display(),
            "start_at": classroom.start_at,
            "end_at": classroom.end_at,
            "teacher": {
                "id": classroom.teacher_id,
                "real_name": classroom.teacher.real_name,
                "username": classroom.teacher.username,
            },
            "course_id": course.id,
            "course_name": course.name,
            "summary": stats["summary"],
            "students": stats["students"],
        })


    def status(self, request, class_id):
        """班级开课/结课干预：影响预览 + 二次确认由前端负责，服务端落审计。"""
        classroom = get_object_or_404(ClassRoom, pk=class_id)
        serializer = ClassStatusSerializer(classroom, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        old_status = classroom.status
        serializer.save()
        affected = {
            "students": ClassStudent.objects.filter(
                classroom=classroom
            ).exclude(learn_status=ClassStudent.LearnStatus.REMOVED).count(),
            "courses": classroom.courses.count(),
            "active_homeworks": Homework.objects.filter(
                classroom=classroom, status=Homework.Status.PUBLISHED
            ).count(),
            "active_exams": Exam.objects.filter(
                classroom=classroom, status=Exam.Status.PUBLISHED
            ).count(),
        }
        if old_status != classroom.status:
            log_admin_action(
                request.user,
                AdminActionLog.Action.CLASS_STATUS,
                target_type="class",
                target_id=classroom.id,
                target_label=classroom.name,
                old_value={"status": old_status},
                new_value={"status": classroom.status},
                note=f"影响：{affected['students']} 名学生 / {affected['courses']} 门课程 / "
                     f"{affected['active_homeworks']} 份进行中作业 / "
                     f"{affected['active_exams']} 场已发布考试",
            )
        return api_response(
            {
                "id": classroom.id,
                "status": classroom.status,
                "status_display": classroom.get_status_display(),
                "affected": affected,
            },
            message="班级状态已更新",
        )

    def export(self, request):
        """班级监管导出 CSV（含进度汇总；上限 5000 行）。"""
        queryset = ClassRoom.objects.select_related("teacher").annotate(
            course_count=Count("courses", distinct=True),
            student_count=Count("students", distinct=True),
        ).order_by("-created_at")[:_MAX_EXPORT]
        response = _csv_response("classes")
        writer = csv.writer(response)
        writer.writerow([
            "班级ID", "班级名称", "状态", "负责人", "用户名", "关联课程",
            "班级学生", "作业提交率(%)", "考试完成率(%)", "预警人数", "创建时间",
        ])
        for row in queryset:
            summary = class_progress_summary(row)
            writer.writerow([
                row.id, row.name, row.get_status_display(),
                row.teacher.real_name or "", row.teacher.username,
                row.course_count, row.student_count,
                summary["homework_rate"] if summary["homework_rate"] is not None else "",
                summary["exam_rate"] if summary["exam_rate"] is not None else "",
                summary["warning_count"] if summary["warning_count"] is not None else "",
                timezone.localtime(row.created_at).strftime("%Y-%m-%d %H:%M"),
            ])
        return response


# ---------------------------------------------------------------------------
# 教师监管（A9/A10）
# ---------------------------------------------------------------------------

_TEACHER_SORT_KEYS = {
    "ai_calls": "ai_calls",
    "ai_tokens": "ai_tokens",
    "course_count": "course_count",
    "class_count": "class_count",
    "student_count": "student_count",
    "last_active": "last_active",
    "date_joined": "date_joined",
}


class AdminTeacherViewSet(AdminThrottleMixin, viewsets.ViewSet):
    """教师监管一处收口：列表（资产规模 + AI 消耗）+ 详情（课程/班级清单 + AI 分布）+ 导出。"""

    method_scopes = {"GET": "admin_read"}
    action_scopes = {"export": "admin_export"}
    permission_classes = [IsPlatformAdmin]

    def list(self, request):
        search = request.query_params.get("search", "").strip()
        rows = teacher_rows(search)
        sort_key = request.query_params.get("sort", "").strip()
        if sort_key in _TEACHER_SORT_KEYS:
            reverse = request.query_params.get("order", "desc") != "asc"
            rows.sort(
                key=lambda r: (r[sort_key] is not None, r[sort_key]),
                reverse=reverse,
            )
        p, size = _page_params(request)
        total = len(rows)
        items = rows[(p - 1) * size:(p - 1) * size + size]
        return api_response({
            "items": items, "total": total, "page": p, "page_size": size,
        })


    def retrieve(self, request, teacher_id):
        teacher = get_object_or_404(User, pk=teacher_id, role=User.Role.TEACHER)
        courses = []
        for course in Course.objects.filter(teacher=teacher).order_by("-created_at"):
            courses.append({
                "id": course.id,
                "name": course.name,
                "term": course.term,
                "status": course.status,
                "status_display": course.get_status_display(),
                "class_count": course.classes.count(),
                "student_count": ClassStudent.objects.filter(
                    classroom__courses=course
                ).exclude(learn_status=ClassStudent.LearnStatus.REMOVED)
                .values("student_id").distinct().count(),
            })
        classes = []
        for classroom in ClassRoom.objects.filter(teacher=teacher).order_by("-created_at"):
            classes.append({
                "id": classroom.id,
                "name": classroom.name,
                "status": classroom.status,
                "course_count": classroom.courses.count(),
                "student_count": ClassStudent.objects.filter(
                    classroom=classroom
                ).exclude(learn_status=ClassStudent.LearnStatus.REMOVED).count(),
            })
        ai = (
            AICallLog.objects.filter(triggered_by=teacher)
            .values("capability")
            .annotate(
                calls=Count("id"),
                tokens=Sum("total_tokens"),
                chars=Sum("input_chars"),
                items=Sum("item_count"),
            )
            .order_by("-calls")
        )
        capability_labels = dict(AICapabilityConfig.Capability.choices)
        return api_response({
            "id": teacher.id,
            "username": teacher.username,
            "real_name": teacher.real_name,
            "is_active": teacher.is_active,
            "date_joined": teacher.date_joined,
            "last_login": teacher.last_login,
            "courses": courses,
            "classes": classes,
            "ai_by_capability": [
                {
                    "capability": row["capability"],
                    "capability_display": capability_labels.get(row["capability"], row["capability"]),
                    "calls": row["calls"],
                    "tokens": row["tokens"] or 0,
                    # 语音合成无 token  usage，按合成字符数计量；本地模型按条数
                    "chars": row["chars"] or 0,
                    "items": row["items"] or 0,
                }
                for row in ai
            ],
        })

    def export(self, request):
        """教师监管导出 CSV（含 AI 消耗；上限 5000 行）。"""
        rows = teacher_rows(request.query_params.get("search", "").strip())[:_MAX_EXPORT]
        response = _csv_response("teachers")
        writer = csv.writer(response)
        writer.writerow([
            "教师ID", "用户名", "姓名", "账号状态",
            "课程", "班级", "覆盖学生", "AI调用次数", "AI消耗Token",
            "AI消耗字符", "最近登录", "最近活跃", "注册时间",
        ])

        def fmt(dt):
            return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M") if dt else ""

        for row in rows:
            writer.writerow([
                row["id"], row["username"], row["real_name"] or "",
                "正常" if row["is_active"] else "停用",
                row["course_count"], row["class_count"], row["student_count"],
                row["ai_calls"], row["ai_tokens"], row["ai_chars"],
                fmt(row["last_login"]), fmt(row["last_active"]),
                fmt(row["date_joined"]),
            ])
        return response


# ---------------------------------------------------------------------------
# 操作审计（A12）
# ---------------------------------------------------------------------------

def _action_log_queryset(request):
    queryset = AdminActionLog.objects.select_related("actor").all()
    action = request.query_params.get("action", "").strip()
    if action:
        queryset = queryset.filter(action=action)
    actor = request.query_params.get("actor", "").strip()
    if actor.isdigit():
        queryset = queryset.filter(actor_id=int(actor))
    target_type = request.query_params.get("target_type", "").strip()
    if target_type:
        queryset = queryset.filter(target_type=target_type)
    keyword = request.query_params.get("keyword", "").strip()
    if keyword:
        queryset = queryset.filter(
            Q(target_label__icontains=keyword) | Q(actor__username__icontains=keyword)
        )
    start_raw = (request.query_params.get("start") or "").strip()
    end_raw = (request.query_params.get("end") or "").strip()
    if start_raw:
        queryset = queryset.filter(created_at__date__gte=start_raw)
    if end_raw:
        queryset = queryset.filter(created_at__date__lte=end_raw)
    return queryset


class AdminActionLogViewSet(AdminThrottleMixin, viewsets.ViewSet):
    """操作审计一处收口：查询（筛选 + 分页）+ CSV 导出（上限 5 万行）。"""

    method_scopes = {"GET": "admin_read"}
    action_scopes = {"export": "admin_export"}
    permission_classes = [IsPlatformAdmin]
    serializer_class = AdminActionLogSerializer

    def list(self, request):
        return _paginated_response(
            _action_log_queryset(request), request, AdminActionLogSerializer
        )

    def export(self, request):
        """操作审计导出 CSV（上限 5 万行，同 AI 流水口径）。"""
        queryset = _action_log_queryset(request).order_by("-created_at")[:_AUDIT_MAX_EXPORT]
        response = _csv_response("admin_action_logs")
        writer = csv.writer(response)
        writer.writerow([
            "时间", "操作人", "动作", "对象类型", "对象ID", "对象名称",
            "变更内容", "备注",
        ])
        for log in queryset.iterator():
            changes = _audit_change_lines(log)
            writer.writerow([
                timezone.localtime(log.created_at).strftime("%Y-%m-%d %H:%M:%S"),
                log.actor.username,
                log.get_action_display(),
                log.target_type, log.target_id or "", log.target_label,
                "；".join(changes), log.note,
            ])
        return response


def _audit_change_lines(log) -> list:
    """审计记录的变更内容行（CSV 导出口径，与前端「变更内容」列同规则）。

    ai_config_save 为按能力分组的字段级 diff（new_value.changes，单一审计轨）；
    其余动作为 old/new 顶层键 diff。ai_config_save 的合并前存量行只有
    capabilities 列表，退化为「保存能力：…」一行。
    """
    old_value, new_value = log.old_value, log.new_value
    if not old_value and not new_value:
        return []
    if log.action == AdminActionLog.Action.AI_CONFIG_SAVE and isinstance(new_value, dict):
        lines = []
        for group in new_value.get("changes") or []:
            capability = group.get("capability_display") or group.get("capability") or ""
            for change in group.get("changes") or []:
                lines.append(
                    f"{capability}·{change.get('label', '')}: "
                    f"{change.get('old') or '空'} → {change.get('new') or '空'}"
                )
        if lines:
            return lines
        capabilities = new_value.get("capabilities")
        if capabilities:
            return [f"保存能力：{'、'.join(str(c) for c in capabilities)}"]
        return []
    if isinstance(old_value, dict) and isinstance(new_value, dict):
        keys = list(old_value.keys()) + [
            k for k in new_value if k not in old_value
        ]
        return [
            f"{key}: {old_value.get(key, '')} → {new_value.get(key, '')}"
            for key in keys
            if old_value.get(key, "") != new_value.get(key, "")
        ]
    return [f"{old_value or ''} → {new_value or ''}"]
