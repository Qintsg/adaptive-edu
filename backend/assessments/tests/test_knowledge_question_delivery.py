#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
知识测评题目下发不得提前暴露解析或隐藏题。
@Project : adaptive-edu
@File : test_knowledge_question_delivery.py
@Author : Qintsg
@Date : 2026-09-25
'''

from __future__ import annotations

import json
from unittest.mock import patch

from rest_framework.test import APITestCase

from assessments.models import Assessment, AssessmentQuestion, Question
from courses.models import Class, ClassCourse, Course, Enrollment
from users.models import User


class KnowledgeQuestionDeliveryTests(APITestCase):
    """检查学生作答前收到的题目边界。"""

    def setUp(self) -> None:
        """准备独立学生和课程。"""
        self.student = User.objects.create_user(
            username="question_delivery_student", password="Test123456", role="student",
        )
        self.course = Course.objects.create(name="知识测评保密课")
        self.class_obj = Class.objects.create(name="知识测评测试班", course=self.course)
        ClassCourse.objects.create(class_obj=self.class_obj, course=self.course)
        Enrollment.objects.create(user=self.student, class_obj=self.class_obj)
        self.client.force_authenticate(user=self.student)

    def _question(self, *, content: str, analysis: str,
                  is_visible: bool = True) -> Question:
        """创建一条带可识别解析标记的题目。

        :param content: 学生可见题干。
        :param analysis: 仅交卷后可见的解析。
        :param is_visible: 题目是否发布给学生。
        :returns: 已保存题目。
        """
        return Question.objects.create(
            course=self.course, content=content, question_type="single_choice",
            options=[{"label": "A", "content": "选项一"},
                     {"label": "B", "content": "选项二"}],
            answer={"answer": "A"}, analysis=analysis,
            is_visible=is_visible, for_initial_assessment=True,
        )

    def _get_questions(self) -> list[dict[str, object]]:
        """通过学生接口读取试题列表。

        :returns: 接口下发的题目。
        """
        response = self.client.get(
            "/api/student/assessments/initial/knowledge",
            {"course_id": self.course.id},
        )
        self.assertEqual(response.status_code, 200)
        return response.data["data"]["questions"]

    def test_before_submission_excludes_answer_and_analysis(self) -> None:
        """解析和正确答案不能在试卷响应中出现。"""
        self._question(content="正常题干", analysis="保密解析：选 A")

        question = self._get_questions()[0]

        self.assertNotIn("analysis", question)
        self.assertNotIn("answer", question)
        self.assertNotIn("correct_answer", question)
        self.assertNotIn("保密解析", json.dumps(question, ensure_ascii=False))

    def test_missing_stem_does_not_use_private_analysis_as_title(self) -> None:
        """空题干只显示占位提示，不能用解析填充。"""
        self._question(content="", analysis="秘密答案：A")

        question = self._get_questions()[0]

        self.assertNotIn("秘密答案", json.dumps(question, ensure_ascii=False))
        self.assertIn("题干缺失", question["title"])

    def test_auto_assessment_excludes_hidden_questions(self) -> None:
        """自动组卷只选已发布题目。"""
        visible = self._question(content="公开题", analysis="公开题解析")
        self._question(content="隐藏题", analysis="隐藏题解析", is_visible=False)

        questions = self._get_questions()

        self.assertEqual([question["question_id"] for question in questions], [visible.id])

    def test_existing_assessment_excludes_newly_hidden_question(self) -> None:
        """已建试卷也须遵守题目后续的隐藏设置。"""
        visible = self._question(content="公开题", analysis="公开题解析")
        hidden = self._question(content="隐藏题", analysis="隐藏题解析", is_visible=False)
        assessment = Assessment.objects.create(
            course=self.course, title="固定测评", assessment_type="knowledge", is_active=True,
        )
        AssessmentQuestion.objects.create(assessment=assessment, question=visible, order=0)
        AssessmentQuestion.objects.create(assessment=assessment, question=hidden, order=1)

        questions = self._get_questions()

        self.assertEqual([question["question_id"] for question in questions], [visible.id])

    def test_submission_scores_only_visible_questions_and_then_reveals_analysis(self) -> None:
        """隐藏题不参与评分，可见题解析只在提交后返回。"""
        visible = self._question(content="公开题", analysis="交卷后解析：选 A")
        hidden = self._question(content="隐藏题", analysis="隐藏题解析", is_visible=False)
        assessment = Assessment.objects.create(
            course=self.course, title="固定测评", assessment_type="knowledge", is_active=True,
        )
        AssessmentQuestion.objects.create(assessment=assessment, question=visible, order=0)
        AssessmentQuestion.objects.create(assessment=assessment, question=hidden, order=1)
        self.assertNotIn("analysis", self._get_questions()[0])

        with patch("assessments.api.knowledge.blend_mastery_with_kt", return_value={}), \
             patch("assessments.api.knowledge.threading.Thread"):
            response = self.client.post(
                "/api/student/assessments/initial/knowledge/submit",
                {"course_id": self.course.id,
                 "answers": [{"question_id": visible.id, "answer": "A"},
                             {"question_id": hidden.id, "answer": "B"}]},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["total_count"], 1)
        self.assertEqual(response.data["data"]["correct_count"], 1)
        details = response.data["data"]["question_details"]
        self.assertEqual([detail["question_id"] for detail in details], [visible.id])
        self.assertEqual(details[0]["analysis"], "交卷后解析：选 A")

    def test_unenrolled_student_cannot_fetch_or_submit_course_exam(self) -> None:
        """未选修学生不能借课程 ID 读取题库或得到评分反馈。"""
        question = self._question(content="仅班级可见", analysis="保密解析")
        outsider = User.objects.create_user(
            username="question_delivery_outsider", password="Test123456", role="student",
        )
        self.client.force_authenticate(user=outsider)

        fetched = self.client.get(
            "/api/student/assessments/initial/knowledge",
            {"course_id": self.course.id},
        )
        with patch("assessments.api.knowledge.threading.Thread"):
            submitted = self.client.post(
                "/api/student/assessments/initial/knowledge/submit",
                {"course_id": self.course.id,
                 "answers": [{"question_id": question.id, "answer": "A"}]},
                format="json",
            )

        self.assertEqual(fetched.status_code, 403)
        self.assertEqual(submitted.status_code, 403)
        self.assertFalse(Assessment.objects.filter(course=self.course).exists())

    def test_published_course_without_legacy_default_remains_accessible(self) -> None:
        """班级只通过发布关系关联课程时，已选修学生仍可取题。"""
        question = self._question(content="已发布题", analysis="交卷后可见")
        self.class_obj.course = None
        self.class_obj.save(update_fields=["course"])

        questions = self._get_questions()

        self.assertEqual([item["question_id"] for item in questions], [question.id])

    def test_course_owner_can_preview_questions(self) -> None:
        """课程教师保留预览权限，但仍看不到交卷后解析。"""
        teacher = User.objects.create_user(
            username="question_delivery_teacher", password="Test123456", role="teacher",
        )
        self.course.created_by = teacher
        self.course.save(update_fields=["created_by"])
        self._question(content="教师预览题", analysis="保密解析")
        self.client.force_authenticate(user=teacher)

        questions = self._get_questions()

        self.assertEqual(len(questions), 1)
        self.assertNotIn("analysis", questions[0])
