#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""大模型文本流的逐块转发与中断恢复。"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ai_services.services.demo_fallback import demo_mode_enabled
from ai_services.services.demo_presets import load_verified_answer, record_verified_answer
from ai_services.services.llm.error_details import summarize_exception_chain
from common.core.logging_utils import build_log_message

logger = logging.getLogger(__name__)


class LLMStreamInterrupted(RuntimeError):
    """模型中断或空流时，通知调用方用完整答案完成本次回复。"""

    def __init__(self, fallback_text: str, generation_source: str = "course_rules") -> None:
        """保存可替换已输出片段的完整答案。

        :param fallback_text: 同请求预置答案或调用方的规则答案。
        :param generation_source: 完整答案的来源。
        :returns: None。
        """
        super().__init__("模型文本流中断")
        self.fallback_text = fallback_text
        self.generation_source = generation_source


class LLMTextStreamMixin:
    """向调用方逐块提供模型输出，并在调用中断时提供恢复答案。"""

    def stream_text_with_fallback(
        self,
        *,
        prompt: str,
        call_type: str,
        fallback_text: str,
        temperature: float = None,
        extra_body_overrides: Optional[Dict[str, Any]] = None,
    ):
        """逐块输出模型文本，首块前异常则直接输出可用的完整答案。

        :param prompt: 学生问答的原始提示词。
        :param call_type: 调用类型，用于模型策略和预置答案匹配。
        :param fallback_text: 调用方提供的完整规则答案。
        :param temperature: 可选温度覆盖。
        :param extra_body_overrides: 可选的模型请求参数覆盖。
        :returns: 模型文本片段的迭代器。
        :raises LLMStreamInterrupted: 模型未给出完整回答，调用方须发送替代答案。
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        start_time, execution_policy, prepared_prompt = self._prepare_structured_call(
            prompt, call_type,
        )
        llm = self._get_llm_for_policy(
            execution_policy,
            call_type=call_type,
            extra_body_overrides=extra_body_overrides,
        )
        if llm is None:
            verified = load_verified_answer("text", call_type, prepared_prompt)
            if verified and not fallback_text:
                raise LLMStreamInterrupted(verified, "verified_ai_preset")
            if verified or fallback_text:
                yield verified or fallback_text
            return

        emitted = False
        completed_without_content = False
        buffered_chunks: list[str] = []
        original_temp = self._apply_temperature_override(llm, temperature)
        try:
            for chunk in llm.stream(
                [
                    SystemMessage(content=self._TEXT_STREAM_SYSTEM_CONTENT),
                    HumanMessage(content=prepared_prompt),
                ]
            ):
                chunk_text = self._coerce_stream_chunk_text(chunk)
                if not chunk_text:
                    continue
                emitted = True
                buffered_chunks.append(chunk_text)
                yield chunk_text

            if emitted:
                record_verified_answer("text", call_type, prepared_prompt, "".join(buffered_chunks))
                logger.debug(
                    build_log_message(
                        "llm.stream.success",
                        call_type=call_type,
                        duration_ms=int((time.time() - start_time) * 1000),
                        model=self.model_name,
                    )
                )
            else:
                completed_without_content = True
        except Exception as error:  # noqa: BLE001
            logger.error(
                build_log_message(
                    "llm.stream.fail",
                    call_type=call_type,
                    model=self.model_name,
                    provider=self.provider_name,
                    base_url=self.resolved_base_url,
                    proxy_enabled=bool(self.resolved_proxy_url),
                    error=error,
                    error_detail=summarize_exception_chain(error),
                )
            )
            verified = (
                load_verified_answer("text", call_type, prepared_prompt)
                if demo_mode_enabled() else None
            )
            replacement = verified or fallback_text
            if emitted:
                source = "verified_ai_preset" if verified else "course_rules"
                raise LLMStreamInterrupted(replacement, source) from error
            if verified and not fallback_text:
                raise LLMStreamInterrupted(verified, "verified_ai_preset") from error
            if replacement:
                yield replacement
        finally:
            self._restore_temperature(llm, original_temp)

        if completed_without_content:
            logger.warning(build_log_message(
                "llm.stream.empty", call_type=call_type, model=self.model_name,
            ))
            verified = load_verified_answer("text", call_type, prepared_prompt)
            if verified and not fallback_text:
                raise LLMStreamInterrupted(verified, "verified_ai_preset")
            if verified or fallback_text:
                yield verified or fallback_text
