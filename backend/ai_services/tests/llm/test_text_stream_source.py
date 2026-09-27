#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""核对学生文本流在模型未输出时的答案来源。"""

from __future__ import annotations

from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from ai_services.services.llm.service import LLMService
from ai_services.services.llm.text_stream_mixin import LLMStreamInterrupted


class TextStreamSourceTests(SimpleTestCase):
    """预置结果不可作为在线模型 chunk 上报。"""

    @override_settings(DEMO_MODE=True)
    @patch("ai_services.services.llm.text_stream_mixin.load_verified_answer")
    def test_missing_client_raises_preset_source_without_chunks(self, preset: Mock) -> None:
        """模型客户端未建成时把预置答案作为替代完成事件。

        :param preset: 已核对答案的读取函数模拟。
        :returns: None。
        """
        service = LLMService()
        service._api_key = "test-key"
        service._get_llm_for_policy = Mock(return_value=None)
        preset.return_value = "完整预置答案"

        stream = service.stream_text_with_fallback(
            prompt="课程问题", call_type="graph_rag_answer_stream", fallback_text="",
        )
        with self.assertRaises(LLMStreamInterrupted) as raised:
            next(stream)
        self.assertEqual(raised.exception.fallback_text, "完整预置答案")
        self.assertEqual(raised.exception.generation_source, "verified_ai_preset")

    @override_settings(DEMO_MODE=True)
    @patch("ai_services.services.llm.text_stream_mixin.load_verified_answer")
    def test_early_model_error_raises_preset_source_without_chunks(self, preset: Mock) -> None:
        """模型首块前异常时预置答案不能冒充模型文本。

        :param preset: 已核对答案的读取函数模拟。
        :returns: None。
        """
        service = LLMService()
        service._api_key = "test-key"
        model = Mock()
        model.stream.side_effect = RuntimeError("gateway unavailable")
        service._get_llm_for_policy = Mock(return_value=model)
        preset.return_value = "完整预置答案"

        stream = service.stream_text_with_fallback(
            prompt="课程问题", call_type="graph_rag_answer_stream", fallback_text="",
        )
        with self.assertRaises(LLMStreamInterrupted) as raised:
            next(stream)
        self.assertEqual(raised.exception.fallback_text, "完整预置答案")
        self.assertEqual(raised.exception.generation_source, "verified_ai_preset")

    @override_settings(DEMO_MODE=True)
    @patch("ai_services.services.llm.text_stream_mixin.record_verified_answer")
    @patch("ai_services.services.llm.text_stream_mixin.load_verified_answer")
    def test_empty_model_stream_uses_preset_without_claiming_live_source(
        self, preset: Mock, record: Mock,
    ) -> None:
        """模型只给出空块时应读取预置答案，且不可记录为空成功。

        :param preset: 同请求预置答案读取函数模拟。
        :param record: 真实模型答案记录函数模拟。
        :returns: None。
        """
        service = LLMService()
        service._api_key = "test-key"
        model = Mock()
        model.stream.return_value = []
        service._get_llm_for_policy = Mock(return_value=model)
        preset.return_value = "完整预置答案"

        stream = service.stream_text_with_fallback(
            prompt="课程问题", call_type="graph_rag_answer_stream", fallback_text="",
        )
        with self.assertRaises(LLMStreamInterrupted) as raised:
            next(stream)
        self.assertEqual(raised.exception.fallback_text, "完整预置答案")
        self.assertEqual(raised.exception.generation_source, "verified_ai_preset")
        preset.assert_called_once()
        record.assert_not_called()

    @override_settings(DEMO_MODE=True)
    @patch("ai_services.services.llm.text_stream_mixin.load_verified_answer", return_value=None)
    def test_empty_model_stream_without_preset_leaves_rule_answer_to_consumer(
        self, preset: Mock,
    ) -> None:
        """空流且未命中预置时应让 WebSocket 使用课程规则答案。

        :param preset: 同请求预置答案读取函数模拟。
        :returns: None。
        """
        service = LLMService()
        service._api_key = "test-key"
        model = Mock()
        model.stream.return_value = []
        service._get_llm_for_policy = Mock(return_value=model)

        chunks = list(service.stream_text_with_fallback(
            prompt="课程问题", call_type="graph_rag_answer_stream", fallback_text="",
        ))
        self.assertEqual(chunks, [])
        preset.assert_called_once()
