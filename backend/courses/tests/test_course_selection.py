#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
同一课程发布到多个班级时的课程上下文回归测试。
@Project : adaptive-edu
@File : test_course_selection.py
@Author : Qintsg
@Date : 2026-09-24 20:00
'''

from rest_framework.test import APITestCase

from courses.models import Class, Course, Enrollment
from users.models import User, UserCourseContext


class CourseSelectionTests(APITestCase):
    """验证课程与班级组成的选择上下文。"""

    def setUp(self) -> None:
        """
        创建同一课程下的两个班级及学生选课记录。

        :returns: 无。
        """
        self.teacher = User.objects.create_user(
            username="course_context_teacher",
            password="Test123456",
            role="teacher",
        )
        self.student = User.objects.create_user(
            username="course_context_student",
            password="Test123456",
            role="student",
        )
        self.course = Course.objects.create(
            name="共享课程",
            created_by=self.teacher,
        )
        self.first_class = Class.objects.create(
            name="第一班",
            teacher=self.teacher,
            course=self.course,
        )
        self.second_class = Class.objects.create(
            name="第二班",
            teacher=self.teacher,
            course=self.course,
        )
        Enrollment.objects.create(user=self.student, class_obj=self.first_class)
        Enrollment.objects.create(user=self.student, class_obj=self.second_class)

    def test_student_selects_requested_class_for_shared_course(self) -> None:
        """
        学生选择第二班时，响应与持久化上下文都应指向第二班。

        :returns: 无。
        """
        self.client.force_authenticate(user=self.student)

        response = self.client.post(
            "/api/courses/select",
            {"course_id": self.course.id, "class_id": self.second_class.id},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["class_id"], self.second_class.id)
        context = UserCourseContext.objects.get(user=self.student)
        self.assertEqual(context.current_class_id, self.second_class.id)

    def test_student_cannot_select_unenrolled_class(self) -> None:
        """
        学生不能借同一课程选择尚未加入的班级。

        :returns: 无。
        """
        unavailable_class = Class.objects.create(
            name="未加入班级",
            teacher=self.teacher,
            course=self.course,
        )
        self.client.force_authenticate(user=self.student)

        response = self.client.post(
            "/api/courses/select",
            {"course_id": self.course.id, "class_id": unavailable_class.id},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(UserCourseContext.objects.filter(user=self.student).exists())

    def test_teacher_cannot_select_class_without_course(self) -> None:
        """
        教师不能为课程指定未发布该课程的班级。

        :returns: 无。
        """
        unrelated_class = Class.objects.create(
            name="未发布课程班级",
            teacher=self.teacher,
        )
        self.client.force_authenticate(user=self.teacher)

        response = self.client.post(
            "/api/courses/select",
            {"course_id": self.course.id, "class_id": unrelated_class.id},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(UserCourseContext.objects.filter(user=self.teacher).exists())
