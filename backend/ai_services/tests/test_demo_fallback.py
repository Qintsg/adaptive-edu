#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""答辩演示模式 AI 失败回退测试。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from ai_services.api.kt import kt_predict, kt_recommendations
from ai_services.api.student.chat import build_chat_response
from ai_services.api.student.rag_support import plan_student_path
from ai_services.services.demo_fallback import (
    build_demo_kt_recommendations,
    demo_mode_enabled,
    mark_demo_payload,
)
from ai_services.services.llm.response_mixin import _fallback_with_demo_source
from ai_services.services.demo_presets import load_verified_answer, record_verified_answer
from ai_services.realtime.consumers import _has_verified_chat_for_empty_key
from assessments.services.knowledge_generation import async_generate_after_assessment
from exams.reports.service import generate_feedback_report_sync


class DemoFallbackTests(SimpleTestCase):
    """验证开关隔离、接口兼容和初测异步收尾。"""

    @override_settings(DEMO_MODE=False)
    def test_demo_flag_is_explicit(self) -> None:
        """默认关闭时不修改普通回退结果。"""
        payload = {"summary": "已有建议"}
        self.assertFalse(demo_mode_enabled())
        self.assertIs(_fallback_with_demo_source(payload), payload)

    @override_settings(DEMO_MODE=True)
    def test_demo_payload_marks_course_rule_source(self) -> None:
        """演示结果带来源标记且不污染输入对象。"""
        payload = {"summary": "已有建议"}
        marked = mark_demo_payload(payload)
        self.assertEqual(marked["generation_source"], "demo_course_rules")
        self.assertTrue(_fallback_with_demo_source(payload)["demo_fallback"])
        self.assertNotIn("demo_fallback", payload)

    @override_settings(DEMO_MODE=True)
    def test_verified_preset_requires_exact_request_fingerprint(self) -> None:
        """彩排答案仅匹配相同模型、类型与请求，不保存原始提问。"""
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "answers.jsonl"
            with patch.dict(os.environ, {
                "DEMO_AI_CAPTURE_FILE": str(filename),
                "DEMO_AI_PRESET_FILE": str(filename),
            }):
                record_verified_answer("json", "chat", "课程=大数据；问题=Hadoop", {"reply": "来自真实调用"})
                self.assertEqual(
                    load_verified_answer("json", "chat", "课程=大数据；问题=Hadoop"),
                    {"reply": "来自真实调用"},
                )
                self.assertIsNone(load_verified_answer("json", "chat", "课程=大数据；问题=Spark"))
                self.assertIsNone(load_verified_answer("text", "chat", "课程=大数据；问题=Hadoop"))
            self.assertNotIn("问题=Hadoop", filename.read_text(encoding="utf-8"))
            self.assertIn('"model":"deepseek-flash"', filename.read_text(encoding="utf-8"))

    @override_settings(DEMO_MODE=True)
    @patch("ai_services.api.student.chat.build_demo_chat")
    @patch("ai_services.api.student.chat.student_graph_rag_service.ask", side_effect=RuntimeError("模型不可用"))
    def test_course_chat_uses_demo_fallback(self, _ask: Mock, demo_chat: Mock) -> None:
        """课程问答失败时返回课程回退结果。"""
        demo_chat.return_value = mark_demo_payload({"reply": "根据课程资料复习 Hadoop", "mode": "demo_fallback"})
        result = build_chat_response(user=SimpleNamespace(id=1), question="Hadoop 是什么？", course_id=1)
        self.assertEqual(result["mode"], "demo_fallback")
        demo_chat.assert_called_once_with(1, "Hadoop 是什么？", None)

    @override_settings(DEMO_MODE=True)
    @patch("ai_services.api.student.chat.llm_facade", new=SimpleNamespace(is_available=False))
    @patch("ai_services.api.student.chat.load_verified_answer")
    @patch("ai_services.api.student.chat.student_graph_rag_service.ask")
    def test_empty_key_chat_prefers_exact_verified_answer(self, ask: Mock, preset: Mock) -> None:
        """空 key 时固定问题先命中彩排答案。"""
        preset.return_value = {"reply": "已核实的 Hadoop 解释", "mode": "graph_rag"}
        result = build_chat_response(user=SimpleNamespace(id=1), question="Hadoop 是什么？", course_id=1)
        self.assertEqual(result["reply"], "已核实的 Hadoop 解释")
        self.assertEqual(result["generation_source"], "verified_ai_preset")
        ask.assert_not_called()

    @override_settings(DEMO_MODE=True)
    @patch("ai_services.realtime.consumers.llm_facade", new=SimpleNamespace(is_available=False))
    @patch("ai_services.realtime.consumers.load_verified_answer", return_value={"reply": "真实彩排答案"})
    def test_websocket_uses_verified_answer_before_graph_plan(self, preset: Mock) -> None:
        """空 key 的流式问答先按固定请求查真实彩排答案。"""
        self.assertTrue(_has_verified_chat_for_empty_key(1, 26, "Spark SQL 和 DataFrame 有什么关系？"))
        preset.assert_called_once()

    @override_settings(DEMO_MODE=True)
    @patch("ai_services.services.llm.response_mixin.load_verified_answer")
    @patch("ai_services.services.llm.service.LLMService._get_llm_for_policy", return_value=None)
    def test_empty_key_llm_uses_verified_json(self, _client: Mock, preset: Mock) -> None:
        """结构化 LLM 不可用时读取同指纹结果。"""
        from ai_services.services.llm.service import LLMService

        preset.return_value = {"summary": "真实彩排摘要"}
        result = LLMService().call_with_fallback(
            prompt="固定问题", call_type="profile_analysis", fallback_response={"summary": "规则摘要"},
        )
        self.assertEqual(result["summary"], "真实彩排摘要")
        self.assertEqual(result["generation_source"], "verified_ai_preset")

    @override_settings(DEMO_MODE=False)
    @patch("ai_services.api.student.chat.student_graph_rag_service.ask", side_effect=RuntimeError("模型不可用"))
    def test_course_chat_keeps_normal_error(self, _ask: Mock) -> None:
        """正常模式维持原来的失败响应。"""
        result = build_chat_response(user=SimpleNamespace(id=1), question="Hadoop 是什么？", course_id=1)
        self.assertEqual(result["mode"], "error")

    @override_settings(DEMO_MODE=True)
    @patch("ai_services.api.student.rag_support.build_demo_path_plan")
    @patch("ai_services.api.student.rag_support.student_learning_rag.plan_learning_path", side_effect=RuntimeError("图服务不可用"))
    @patch("ai_services.api.student.rag_support.build_mastery_data", return_value=[])
    def test_path_plan_uses_course_fallback(self, _mastery: Mock, _plan: Mock, demo_plan: Mock) -> None:
        """图服务失败时路径规划仍返回建议。"""
        demo_plan.return_value = {"reason": "按课程掌握度排序", "suggested_nodes": [], "demo_fallback": True}
        payload, error = plan_student_path(
            user=SimpleNamespace(id=1),
            course=SimpleNamespace(id=2),
            course_id=2,
            target="复习",
            constraints={},
        )
        self.assertIsNone(error)
        self.assertTrue(payload["demo_fallback"])

    def test_kt_recommendations_use_real_rates(self) -> None:
        """规则建议只包含低于阈值的知识点。"""
        items = build_demo_kt_recommendations({"1": 0.3, "2": 0.8}, 0.6)
        self.assertEqual([item["knowledge_point_id"] for item in items], [1])
        self.assertEqual(items[0]["generation_source"], "demo_course_rules")

    @override_settings(DEMO_MODE=True)
    @patch("ai_services.api.kt.build_demo_kt_prediction")
    @patch("ai_services.api.kt.knowledge_tracing_facade.predict_mastery", side_effect=RuntimeError("模型不可用"))
    def test_kt_endpoint_returns_marked_rule_prediction(self, _predict: Mock, demo_predict: Mock) -> None:
        """KT 服务异常时接口仍提供明确标记的规则预测。"""
        demo_predict.return_value = mark_demo_payload({"predictions": {1: 0.5}, "model_type": "demo_course_rules"})
        request = APIRequestFactory().post("/api/ai/kt/predict", {"course_id": 2, "answer_history": []}, format="json")
        force_authenticate(request, user=SimpleNamespace(id=7, is_authenticated=True))
        response = kt_predict(request)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["data"]["demo_fallback"])
        demo_predict.assert_called_once_with(7, 2, [], [])

    @override_settings(DEMO_MODE=False)
    def test_kt_recommendation_endpoint_accepts_named_user_and_course(self) -> None:
        """普通模式的 KT 建议接口可以直接使用命名参数。"""
        request = APIRequestFactory().post(
            "/api/ai/kt/recommendations",
            {"course_id": 2, "predictions": {"1": 0.3, "2": 0.8}, "threshold": 0.6},
            format="json",
        )
        force_authenticate(request, user=SimpleNamespace(id=7, is_authenticated=True))
        response = kt_recommendations(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["data"]["recommendations"]), 1)

    @override_settings(DEMO_MODE=True)
    @patch("assessments.services.knowledge_generation.update_generation_status")
    @patch("assessments.services.knowledge_generation.upsert_assessment_feedback_report")
    @patch("assessments.services.knowledge_generation.build_demo_feedback")
    @patch("assessments.services.knowledge_generation.build_demo_profile")
    @patch("assessments.services.knowledge_generation.build_demo_learning_path")
    @patch("assessments.services.knowledge_generation.refresh_learning_path_for_assessment", side_effect=RuntimeError("KT 不可用"))
    @patch("assessments.services.knowledge_generation.refresh_learner_profile_for_assessment", side_effect=RuntimeError("画像不可用"))
    @patch("assessments.services.knowledge_generation.load_assessment_result_snapshot")
    @patch("assessments.services.knowledge_generation.resolve_async_generation_context")
    def test_initial_assessment_finishes_after_ai_failures(
        self,
        context: Mock,
        result_snapshot: Mock,
        _profile: Mock,
        _path: Mock,
        local_path: Mock,
        local_profile: Mock,
        local_feedback: Mock,
        report: Mock,
        status: Mock,
    ) -> None:
        """初测后各 AI 步骤故障时，规则结果仍能完成异步收尾。"""
        user = SimpleNamespace(id=7)
        assessment = SimpleNamespace(id=8, title="大数据知识测评")
        context.return_value = (user, assessment, None)
        result_snapshot.return_value = (SimpleNamespace(id=9), 8.0, 10.0)
        local_feedback.return_value = {"summary": "依据答题生成", "demo_fallback": True}
        with (
            patch("ai_services.services.llm_service.generate_feedback_report", side_effect=RuntimeError("LLM 不可用")),
            patch("courses.models.Course.objects.get", return_value=SimpleNamespace(id=3)),
        ):
            async_generate_after_assessment(7, 3, 8, [])
        local_path.assert_called_once()
        local_profile.assert_called_once_with(user, 3)
        report.assert_called_once()
        self.assertIsNone(status.call_args.kwargs["generation_error"])

    @override_settings(DEMO_MODE=True)
    @patch("exams.reports.service.build_demo_feedback")
    @patch("exams.reports.service.build_report_generation_context", side_effect=RuntimeError("外部分析不可用"))
    @patch("exams.reports.service.load_report_with_dependencies")
    def test_exam_report_finishes_with_actual_score(
        self, load_report: Mock, _context: Mock, local_feedback: Mock,
    ) -> None:
        """作业分析异常时保存实际分数和规则反馈。"""
        report = SimpleNamespace(
            id=4,
            exam_submission=SimpleNamespace(score=72),
            exam=SimpleNamespace(id=5, title="Hadoop 作业", total_score=100),
            user=SimpleNamespace(id=7),
            status="pending",
            overview={},
            save=Mock(),
        )
        load_report.return_value = report
        local_feedback.return_value = mark_demo_payload({
            "summary": "实际得分 72 分",
            "analysis": "先复习错题",
            "recommendations": ["复习 Hadoop"],
            "next_tasks": ["完成练习"],
            "encouragement": "继续练习",
        })
        overview = generate_feedback_report_sync(4)
        self.assertEqual(report.status, "completed")
        self.assertEqual(overview["score"], 72.0)
        self.assertEqual(overview["generation_source"], "demo_course_rules")
