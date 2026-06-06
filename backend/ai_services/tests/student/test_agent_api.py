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
from learning.models import LearningPath, NodeProgress, PathNode
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

    def test_learning_package_should_return_quality_progress_and_path_suggestion(self) -> None:
        """
        学习包接口应返回质量报告、进度事件和路径绑定建议。

        :return: None。
        """
        path = LearningPath.objects.create(user=self.student, course=self.course)
        PathNode.objects.create(
            path=path,
            knowledge_point=self.point,
            title="Spark SQL 基础",
            goal="掌握 Spark SQL 基础查询",
            status="active",
            order_index=0,
        )

        response = self.client.post(
            "/api/student/agent/learning-package",
            {
                "course_id": self.course.id,
                "knowledge_point_id": self.point.id,
                "target": "补齐 Spark SQL 查询和 DataFrame 操作",
                "profile": {"course_goal": "完成项目作业"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.data["data"]
        self.assertEqual(payload["status"], "completed")
        self.assertGreaterEqual(len(payload["resources"]), 5)
        self.assertIn("quality_report", payload)
        self.assertGreaterEqual(payload["quality_report"]["score"], 0.8)
        self.assertEqual(payload["progress_events"][-1]["percent"], 100)
        self.assertEqual(payload["path_suggestion"]["suggested_bindings"][0]["suggested_node_id"], path.nodes.first().id)
        self.assertTrue(AgentRun.objects.filter(id=payload["run_id"], run_type="learning_package").exists())

    def test_apply_resources_to_path_should_bind_metadata_and_node_progress(self) -> None:
        """
        应用到路径接口应写入资源 metadata 和节点进度扩展数据。

        :return: None。
        """
        path = LearningPath.objects.create(user=self.student, course=self.course)
        node = PathNode.objects.create(
            path=path,
            knowledge_point=self.point,
            title="Spark SQL 基础",
            goal="掌握 Spark SQL 基础查询",
            status="active",
            order_index=0,
        )
        package_response = self.client.post(
            "/api/student/agent/learning-package",
            {
                "course_id": self.course.id,
                "knowledge_point_id": self.point.id,
                "target": "补齐 Spark SQL 查询",
            },
            format="json",
        )
        run_id = package_response.data["data"]["run_id"]

        response = self.client.post(
            "/api/student/agent/apply-to-path",
            {"course_id": self.course.id, "run_id": run_id},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.data["data"]
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["path_id"], path.id)
        self.assertGreaterEqual(len(payload["bindings"]), 5)
        bound_resource = GeneratedLearningResource.objects.filter(agent_run_id=run_id).first()
        self.assertEqual(bound_resource.metadata["path_binding"]["node_id"], node.id)
        progress = NodeProgress.objects.get(node=node, user=self.student)
        self.assertGreaterEqual(len(progress.extra_data["generated_resources"]), 5)

    def test_run_resources_feedback_and_effect_summary_should_enforce_student_scope(self) -> None:
        """
        运行查询、资源列表、反馈和效果摘要应限定当前学生课程。

        :return: None。
        """
        package_response = self.client.post(
            "/api/student/agent/learning-package",
            {
                "course_id": self.course.id,
                "knowledge_point_id": self.point.id,
                "target": "补齐 Spark SQL 查询",
            },
            format="json",
        )
        run_id = package_response.data["data"]["run_id"]
        resource_id = package_response.data["data"]["resources"][0]["resource_id"]

        run_response = self.client.get(
            f"/api/student/agent/runs/{run_id}",
            {"course_id": self.course.id},
        )
        list_response = self.client.get(
            "/api/student/agent/resources",
            {"course_id": self.course.id, "limit": 3},
        )
        feedback_response = self.client.post(
            f"/api/student/agent/resources/{resource_id}/feedback",
            {
                "course_id": self.course.id,
                "completed": True,
                "rating": 5,
                "usefulness": "useful",
                "difficulty": "moderate",
                "feedback": "讲解和练习很有帮助",
                "time_spent_seconds": 600,
            },
            format="json",
        )
        summary_response = self.client.get(
            "/api/student/agent/effect-summary",
            {"course_id": self.course.id},
        )

        self.assertEqual(run_response.status_code, 200)
        self.assertEqual(len(run_response.data["data"]["resources"]), 5)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data["data"]["count"], 3)
        self.assertEqual(feedback_response.status_code, 200)
        self.assertEqual(feedback_response.data["data"]["feedback"]["rating"], 5)
        self.assertTrue(GeneratedResourceFeedback.objects.filter(resource_id=resource_id, user=self.student).exists())
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(summary_response.data["data"]["feedback_count"], 1)

        self.client.force_authenticate(user=self.other_student)
        forbidden_response = self.client.get(
            f"/api/student/agent/runs/{run_id}",
            {"course_id": self.course.id},
        )
        self.assertEqual(forbidden_response.status_code, 403)

    def test_complete_agent_run_should_mark_student_completion(self) -> None:
        """
        完成运行接口应记录学生侧完成时间。

        :return: None。
        """
        package_response = self.client.post(
            "/api/student/agent/learning-package",
            {
                "course_id": self.course.id,
                "knowledge_point_id": self.point.id,
                "target": "补齐 Spark SQL 查询",
            },
            format="json",
        )
        run_id = package_response.data["data"]["run_id"]

        response = self.client.post(
            f"/api/student/agent/runs/{run_id}/complete",
            {"course_id": self.course.id},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], "completed")
        self.assertIn("student_completed_at", response.data["data"]["result_payload"])
