#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
A3 Agent 运行轨迹构造工具。
@Project : adaptive-edu
@File : trace.py
@Author : Qintsg
@Date : 2026-06-05 00:00
'''

from __future__ import annotations

from typing import Any


def build_trace_item(
    agent: str,
    status: str,
    summary: str,
    *,
    detail: dict[str, Any] | None = None,
    duration_ms: int = 0,
    error: str = "",
) -> dict[str, Any]:
    """
    构造前端可直接展示的 Agent trace 项。

    :param agent: 智能体标识。
    :param status: pending/running/completed/failed/warning 等状态。
    :param summary: 阶段摘要。
    :param detail: 结构化补充信息。
    :param duration_ms: 阶段耗时。
    :param error: 失败原因。
    :return: trace 字典。
    """
    item: dict[str, Any] = {
        "agent": agent,
        "status": status,
        "summary": summary,
        "duration_ms": duration_ms,
    }
    if detail:
        item["detail"] = detail
    if error:
        item["error"] = error
    return item


def build_default_agent_trace(
    *,
    profile_complete: bool,
    evidence_count: int,
    resource_count: int,
    warnings: list[str],
) -> list[dict[str, Any]]:
    """
    构造 M2 同步编排默认轨迹。

    :param profile_complete: 画像字段是否达到最小演示要求。
    :param evidence_count: 证据数量。
    :param resource_count: 资源数量。
    :param warnings: 警告列表。
    :return: trace 项列表。
    """
    evidence_status = "completed" if evidence_count else "warning"
    return [
        build_trace_item(
            "profile_agent",
            "completed" if profile_complete else "warning",
            "已抽取学习画像字段" if profile_complete else "已生成画像草稿，仍需补充信息",
        ),
        build_trace_item(
            "knowledge_agent",
            evidence_status,
            f"已收集 {evidence_count} 条课程证据" if evidence_count else "未检索到课程证据，使用模板兜底",
        ),
        build_trace_item(
            "path_agent",
            "completed",
            "已生成资源学习顺序建议",
        ),
        build_trace_item(
            "resource_agent",
            "completed" if resource_count >= 5 else "warning",
            f"已生成 {resource_count} 类个性化资源",
        ),
        build_trace_item(
            "multimodal_agent",
            "completed",
            "已生成思维导图和视频脚本等多模态表达",
        ),
        build_trace_item(
            "evaluation_agent",
            "warning" if warnings else "completed",
            "已完成质量校验并输出风险提示" if warnings else "已完成质量校验",
            detail={"warnings": warnings} if warnings else None,
        ),
    ]
