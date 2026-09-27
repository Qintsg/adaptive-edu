#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
能力评测提交与已选课程上下文的回归测试。
@Project : adaptive-edu
@File : test_ability_selected_course.py
@Author : Qintsg
@Date : 2026-09-25
'''

from __future__ import annotations

from rest_framework.test import APITestCase

from assessments.models import AbilityScore, AssessmentStatus, SurveyQuestion
from courses.models import Class, ClassCourse, Course, Enrollment
from users.models import User, UserCourseContext


class AbilitySelectedCourseTests(APITestCase):
    """验证旧客户端不传课程时也能正确归属当前课程。"""

    def test_omitted_course_id_uses_selected_course(self) -> None:
        """班级第一门课与当前课不同时，成绩归属当前课。"""
        student = User.objects.create_user(
            username="ability_selected_student", password="Test123456", role="student",
        )
        first_course = Course.objects.create(name="首门课程")
        selected_course = Course.objects.create(name="当前课程")
        class_obj = Class.objects.create(name="多课程班级")
        ClassCourse.objects.create(class_obj=class_obj, course=first_course)
        ClassCourse.objects.create(class_obj=class_obj, course=selected_course)
        Enrollment.objects.create(user=student, class_obj=class_obj)
        UserCourseContext.objects.create(
            user=student, current_course=selected_course, current_class=class_obj,
        )
        question = SurveyQuestion.objects.create(
            survey_type="ability", text="能力问题", question_type="single_select",
            options=[{"value": "A", "label": "较好", "score": 4}], dimension="理解",
        )
        self.client.force_authenticate(user=student)

        response = self.client.post(
            "/api/student/assessments/initial/ability/submit",
            {"answers": [{"question_id": question.id, "answer": "A"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(AbilityScore.objects.filter(user=student, course=selected_course).exists())
        self.assertFalse(AbilityScore.objects.filter(user=student, course=first_course).exists())
        self.assertTrue(AssessmentStatus.objects.get(
            user=student, course=selected_course,
        ).ability_done)
