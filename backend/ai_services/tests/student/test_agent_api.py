#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
学生端 A3 Agent API 回归测试。
@Project : adaptive-edu
@File : test_agent_api.py
@Author : Qintsg
@Date : 2026-06-05 00:00
'''

from __future__ import annotations

from rest_framework.test import APITestCase

from ai_services.models import (
    AgentRun,
    GeneratedLearningResource,
    GeneratedResourceFeedback,
    ProfileDialogTurn,
)
from courses.models import Class, Course, Enrollment
from knowledge.models import KnowledgeMastery, KnowledgePoint, Resource
from users.models import HabitPreference, User


class StudentAgentModelTests(APITestCase):
    """A3 Agent 数据模型测试。"""

    def setUp(self) -> None:
        """
        创建用户、课程和知识点。

        :return: None。
        """
        self.teacher = User.objects.create_user(
            username="agent_model_teacher",
            password="Test123456",
            role="teacher",
        )
        self.student = User.objects.create_user(
            username="agent_model_student",
            password="Test123456",
            role="student",
        )
        self.course = Course.objects.create(name="Agent模型课程", created_by=self.teacher)
        self.point = KnowledgePoint.objects.create(course=self.course, name="Spark SQL")

    def test_agent_models_should_save_json_defaults_and_relations(self) -> None:
        """
        Agent 模型应能保存 JSON 字段和级联关系。

        :return: None。
        """
        run = AgentRun.objects.create(
            user=self.student,
            course=self.course,
            run_type="resource_generation",
            input_text="学习 Spark SQL",
        )
        resource = GeneratedLearningResource.objects.create(
            user=self.student,
            course=self.course,
            knowledge_point=self.point,
            agent_run=run,
            resource_type="explanation",
            title="Spark SQL 讲解",
            content="## Spark SQL",
            evidence=[{"source_type": "knowledge_point", "id": self.point.id}],
            profile_snapshot={"preferred_resource": "document"},
            metadata={"recommendation_reason": "匹配画像"},
        )
        feedback = GeneratedResourceFeedback.objects.create(
            resource=resource,
            user=self.student,
            completed=True,
            rating=4,
            usefulness="useful",
        )

        self.assertEqual(run.status, "pending")
        self.assertEqual(resource.status, "completed")
        self.assertEqual(resource.evidence[0]["id"], self.point.id)
        self.assertEqual(feedback.resource.agent_run, run)


class StudentAgentApiTests(APITestCase):
    """学生端 A3 Agent API 测试。"""

    def setUp(self) -> None:
        """
        创建学生选课上下文和课程证据。

        :return: None。
        """
        self.teacher = User.objects.create_user(
            username="agent_api_teacher",
            password="Test123456",
            role="teacher",
        )
        self.student = User.objects.create_user(
            username="agent_api_student",
            password="Test123456",
            role="student",
        )
        self.other_student = User.objects.create_user(
            username="agent_api_other_student",
            password="Test123456",
            role="student",
        )
        self.course = Course.objects.create(name="大数据技术与应用", created_by=self.teacher)
        self.other_course = Course.objects.create(name="未选课程", created_by=self.teacher)
        self.class_obj = Class.objects.create(
            name="Agent测试班级",
            course=self.course,
            teacher=self.teacher,
        )
        Enrollment.objects.create(user=self.student, class_obj=self.class_obj)
        self.point = KnowledgePoint.objects.create(
            course=self.course,
            name="Spark SQL",
            description="Spark SQL 查询与 DataFrame 操作",
            is_published=True,
        )
        self.resource = Resource.objects.create(
            course=self.course,
            title="Spark SQL 课程讲义",
            resource_type="document",
            description="讲解 Spark SQL 基础查询",
            uploaded_by=self.teacher,
            is_visible=True,
        )
        self.resource.knowledge_points.add(self.point)
        KnowledgeMastery.objects.create(
            user=self.student,
            course=self.course,
            knowledge_point=self.point,
            mastery_rate=0.4,
        )
        HabitPreference.objects.create(
            user=self.student,
            preferred_resource="video",
            learning_style="kinesthetic",
            study_pace="moderate",
        )
        self.client.force_authenticate(user=self.student)

    def test_profile_dialog_should_extract_slots_and_save_turns(self) -> None:
        """
        画像对话接口应抽取字段并保存对话轮次。

        :return: None。
        """
        response = self.client.post(
            "/api/student/agent/profile-dialog",
            {
                "course_id": self.course.id,
                "message": "我是软件专业学生，想两周内掌握 Spark SQL，但 HDFS 和 MapReduce 基础不太好，喜欢视频和案例。",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.data["data"]
        self.assertIn("course_goal", payload["profile"])
        self.assertIn("weaknesses", payload["profile"])
        self.assertGreaterEqual(len([value for value in payload["profile"].values() if value]), 6)
        self.assertTrue(ProfileDialogTurn.objects.filter(user=self.student, course=self.course).exists())
        self.assertTrue(AgentRun.objects.filter(id=payload["run_id"], run_type="profile_dialog").exists())

    def test_profile_dialog_should_reject_empty_message(self) -> None:
        """
        画像对话接口应拒绝空输入。

        :return: None。
        """
        response = self.client.post(
            "/api/student/agent/profile-dialog",
            {"course_id": self.course.id, "message": ""},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["msg"], "请输入画像对话内容")

    def test_agent_api_should_reject_unenrolled_course(self) -> None:
        """
        学生不能访问未选课程的 Agent 接口。

        :return: None。
        """
        response = self.client.post(
            "/api/student/agent/generate-resources",
            {"course_id": self.other_course.id, "target": "学习 Spark SQL"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["msg"], "您未选修该课程")

    def test_generate_resources_should_create_five_types_with_evidence(self) -> None:
        """
        资源生成接口应生成至少 5 类资源并保存证据。

        :return: None。
        """
        response = self.client.post(
            "/api/student/agent/generate-resources",
            {
                "course_id": self.course.id,
                "knowledge_point_id": self.point.id,
                "target": "掌握 Spark SQL 基础查询与 DataFrame 操作",
                "profile": {"course_goal": "两周内掌握 Spark SQL"},
                "resource_types": ["explanation", "mindmap", "quiz", "reading", "coding_case"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.data["data"]
        resource_types = {resource["resource_type"] for resource in payload["resources"]}
        self.assertGreaterEqual(len(payload["resources"]), 5)
        self.assertSetEqual(
            resource_types,
            {"explanation", "mindmap", "quiz", "reading", "coding_case"},
        )
        self.assertGreaterEqual(len(payload["agent_trace"]), 5)
        self.assertTrue(payload["resources"][0]["evidence"])
        self.assertEqual(GeneratedLearningResource.objects.filter(user=self.student, course=self.course).count(), 5)

    def test_generate_resources_should_warn_when_evidence_missing(self) -> None:
        """
        证据为空时接口应返回 warning 而不是伪造来源。

        :return: None。
        """
        empty_course = Course.objects.create(name="空证据课程", created_by=self.teacher)
        empty_class = Class.objects.create(
            name="空证据班级",
            course=empty_course,
            teacher=self.teacher,
        )
        Enrollment.objects.create(user=self.student, class_obj=empty_class)

        response = self.client.post(
            "/api/student/agent/generate-resources",
            {"course_id": empty_course.id, "target": "学习未知主题"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.data["data"]
        self.assertTrue(payload["warnings"])
        self.assertEqual(payload["resources"][0]["evidence"], [])

    def test_generate_resources_should_reject_point_from_other_course(self) -> None:
        """
        资源生成接口应拒绝非当前课程知识点。

        :return: None。
        """
        other_point = KnowledgePoint.objects.create(
            course=self.other_course,
            name="其他课程知识点",
        )

        response = self.client.post(
            "/api/student/agent/generate-resources",
            {
                "course_id": self.course.id,
                "knowledge_point_id": other_point.id,
                "target": "学习 Spark SQL",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["msg"], "知识点不存在或不属于当前课程")

    def test_generate_resources_should_reject_teacher_user(self) -> None:
        """
        非学生角色不能访问学生端 Agent 接口。

        :return: None。
        """
        self.client.force_authenticate(user=self.teacher)

        response = self.client.post(
            "/api/student/agent/generate-resources",
            {"course_id": self.course.id, "target": "学习 Spark SQL"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["msg"], "仅学生可以访问个性化智能体接口")
