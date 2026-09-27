#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
能力评测评分及内置问卷初始化回归测试。
@Project : adaptive-edu
@File : test_ability_scoring_and_seed.py
@Author : Qintsg
@Date : 2026-09-25
'''

from __future__ import annotations

from rest_framework.test import APITestCase

from assessments.models import AbilityScore, Assessment, AssessmentQuestion, Question, SurveyQuestion
from courses.models import Course
from tools.db_seed_support import _seed_survey_questions
from users.models import User


class AbilityAssessmentScoringTests(APITestCase):
    """课程能力评测仅保存有题目证据支持的维度。"""

    def setUp(self) -> None:
        """建立只有一题的能力评测。"""
        self.student = User.objects.create_user(
            username="ability_student", password="Test123456", role="student",
        )
        self.teacher = User.objects.create_user(
            username="ability_teacher", password="Test123456", role="teacher",
        )
        self.course = Course.objects.create(name="能力评测课程", created_by=self.teacher)
        self.assessment = Assessment.objects.create(
            course=self.course, title="课程能力评测",
            assessment_type="ability", is_active=True,
        )
        self.question = Question.objects.create(
            course=self.course, content="能力题目", question_type="single_choice",
            options=[{"value": "A", "label": "正确"},
                     {"value": "B", "label": "错误"}],
            answer={"answer": "A"}, score=5, is_visible=True,
            created_by=self.teacher,
        )
        AssessmentQuestion.objects.create(
            assessment=self.assessment, question=self.question, order=0,
        )
        self.client.force_authenticate(user=self.student)

    def test_submit_ability_assessment_should_not_fabricate_dimension_scores(self) -> None:
        """没有维度证据的课程试卷不能伪造能力分析。"""
        response = self.client.post(
            "/api/student/assessments/initial/ability/submit",
            {"course_id": self.course.id,
             "answers": [{"question_id": self.question.id, "answer": "A"}]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["ability_analysis"], {})
        ability_score = AbilityScore.objects.get(user=self.student, course=self.course)
        self.assertEqual(ability_score.scores, {})


class SurveyQuestionSeedTests(APITestCase):
    """基础种子数据应补齐全局能力与习惯问卷。"""

    def test_seed_survey_questions_should_use_builtin_defaults_when_config_empty(self) -> None:
        """空问卷配置仍应生成两类内置题。"""
        _seed_survey_questions({"survey_questions": {"habit": [], "ability": []}}, [])

        self.assertGreater(SurveyQuestion.objects.filter(survey_type="habit").count(), 0)
        self.assertGreater(SurveyQuestion.objects.filter(survey_type="ability").count(), 0)
        self.assertFalse(SurveyQuestion.objects.filter(
            survey_type="ability", is_global=False,
        ).exists())
