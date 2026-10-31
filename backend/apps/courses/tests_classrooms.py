# -*- coding: utf-8 -*-
"""授课班级（课程→班级关联）准出。

现场问题：教师新建课程后，班级管理页看不到任何班，也无法把班级加进课程——
教师可见班级 = 他教的课挂过的班，新课程没挂班就永远看不到（死锁）。
补法：课程负责人通过 classroom-options / link-classrooms 只追加 ClassCourse 关联，
不改班级任何属性（班级维护仍归管理员）。
"""
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from apps.classroom.models import ClassCourse, ClassRoom, ClassStudent
from apps.common.access import classrooms_for_user
from apps.courses.models import Course

User = get_user_model()


class CourseClassroomLinkTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user(
            username="cls-link-t", password="pw123456!", role=User.Role.TEACHER, real_name="任课教师"
        )
        cls.other = User.objects.create_user(
            username="cls-link-o", password="pw123456!", role=User.Role.TEACHER, real_name="其他教师"
        )
        cls.admin = User.objects.create_user(
            username="cls-link-a", password="pw123456!", role=User.Role.ADMIN
        )
        cls.course = Course.objects.create(name="授课班级测试课", teacher=cls.teacher)
        cls.room1 = ClassRoom.objects.create(name="演示班一", code="CLS-01")
        cls.room2 = ClassRoom.objects.create(name="演示班二", code="CLS-02")
        cls.archived = ClassRoom.objects.create(
            name="归档班", code="CLS-ARCH", status=ClassRoom.Status.ARCHIVED
        )

    def test_teacher_sees_no_class_before_linking(self):
        """死锁前提成立：建课后教师可见班级为 0。"""
        self.assertEqual(classrooms_for_user(self.teacher).count(), 0)

    def test_options_list_all_active_classrooms_with_linked_flag(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        client.post(f"/api/courses/{self.course.id}/link-classrooms/",
                    {"classroom_ids": [self.room1.id]}, format="json")
        client.force_authenticate(self.teacher)
        resp = client.get(f"/api/courses/{self.course.id}/classroom-options/")
        self.assertEqual(resp.status_code, 200, resp.data)
        rooms = {row["code"]: row for row in resp.data["data"]["classrooms"]}
        self.assertIn("CLS-01", rooms)
        self.assertIn("CLS-02", rooms)
        self.assertNotIn("CLS-ARCH", rooms)  # 归档班不可选
        self.assertTrue(rooms["CLS-01"]["linked"])
        self.assertFalse(rooms["CLS-02"]["linked"])
        self.assertIn("student_count", rooms["CLS-01"])

    def test_link_classrooms_appends_and_is_idempotent(self):
        client = APIClient()
        client.force_authenticate(self.teacher)
        first = client.post(f"/api/courses/{self.course.id}/link-classrooms/",
                            {"classroom_ids": [self.room1.id, self.room2.id]}, format="json")
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data["data"]["linked"], 2)
        self.assertEqual(ClassCourse.objects.filter(course=self.course).count(), 2)

        again = client.post(f"/api/courses/{self.course.id}/link-classrooms/",
                            {"classroom_ids": [self.room1.id]}, format="json")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data["data"]["linked"], 0)  # 幂等：不重复建
        self.assertEqual(ClassCourse.objects.filter(course=self.course).count(), 2)

    def test_linking_makes_classroom_visible_to_teacher(self):
        """关联后教师能在班级管理页看到该班（修复用户报告的核心症状）。"""
        client = APIClient()
        client.force_authenticate(self.teacher)
        client.post(f"/api/courses/{self.course.id}/link-classrooms/",
                    {"classroom_ids": [self.room1.id]}, format="json")
        self.assertIn(self.room1, list(classrooms_for_user(self.teacher)))

    def test_other_teacher_cannot_link(self):
        """非课程负责人连课程都看不到（404，不泄露存在性），更不能关联。"""
        client = APIClient()
        client.force_authenticate(self.other)
        resp = client.post(f"/api/courses/{self.course.id}/link-classrooms/",
                           {"classroom_ids": [self.room1.id]}, format="json")
        self.assertEqual(resp.status_code, 404, resp.data)
        self.assertFalse(ClassCourse.objects.filter(course=self.course).exists())

    def test_empty_selection_rejected(self):
        client = APIClient()
        client.force_authenticate(self.teacher)
        resp = client.post(f"/api/courses/{self.course.id}/link-classrooms/",
                           {"classroom_ids": []}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_archived_classroom_cannot_be_linked(self):
        client = APIClient()
        client.force_authenticate(self.teacher)
        resp = client.post(f"/api/courses/{self.course.id}/link-classrooms/",
                           {"classroom_ids": [self.archived.id]}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(ClassCourse.objects.filter(course=self.course).exists())


class ClassRoomMyCourseTests(APITestCase):
    """班级列表返回 my_course_ids；多教师共用班级时学生详情默认落「我的课」。

    现场问题：教师刚把课程关联到班级，点学生详情报「该课程未关联到此班级」——
    前端盲取班级第一门课，正好是别的教师的课 → 详情接口 403。
    """

    @classmethod
    def setUpTestData(cls):
        cls.teacher_a = User.objects.create_user(
            username="myc-t-a", password="pw123456!", role=User.Role.TEACHER, real_name="甲老师"
        )
        cls.teacher_b = User.objects.create_user(
            username="myc-t-b", password="pw123456!", role=User.Role.TEACHER, real_name="乙老师"
        )
        cls.admin = User.objects.create_user(username="myc-admin", password="pw123456!", role=User.Role.ADMIN)
        cls.course_b = Course.objects.create(name="乙老师先建的课", teacher=cls.teacher_b)  # id 更小，排在前面
        cls.course_a = Course.objects.create(name="甲老师后建的课", teacher=cls.teacher_a)
        cls.room = ClassRoom.objects.create(name="共用一个班", code="MYC-01")
        ClassCourse.objects.create(classroom=cls.room, course=cls.course_b)
        ClassCourse.objects.create(classroom=cls.room, course=cls.course_a)
        cls.student = User.objects.create_user(
            username="myc-stu", password="pw123456!", role=User.Role.STUDENT, real_name="学生甲"
        )
        ClassStudent.objects.create(classroom=cls.room, student=cls.student, learn_status="active")

    def test_my_course_ids_for_teacher_only_lists_own_courses(self):
        client = APIClient()
        client.force_authenticate(self.teacher_a)
        resp = client.get(f"/api/classes/{self.room.id}/")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["data"]["my_course_ids"], [self.course_a.id])

    def test_my_course_ids_for_admin_lists_all(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        resp = client.get(f"/api/classes/{self.room.id}/")
        self.assertEqual(sorted(resp.data["data"]["my_course_ids"]),
                         sorted([self.course_a.id, self.course_b.id]))

    def test_detail_without_course_falls_back_to_my_course(self):
        """不传 course：后端落「我在该班的第一门课」，不再 403（前端修好后的请求形态）。"""
        client = APIClient()
        client.force_authenticate(self.teacher_a)
        resp = client.get(f"/api/analytics/class/{self.room.id}/students/{self.student.id}/")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["data"]["course_id"], self.course_a.id)

    def test_detail_with_others_course_still_rejected(self):
        """不变量：传别人的课仍 403（越权防护不受影响）。"""
        client = APIClient()
        client.force_authenticate(self.teacher_a)
        resp = client.get(
            f"/api/analytics/class/{self.room.id}/students/{self.student.id}/",
            {"course": self.course_b.id},
        )
        self.assertEqual(resp.status_code, 403, resp.data)
        self.assertIn("未关联", resp.data["message"])
