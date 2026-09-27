"""学生端 AI 聊天与 GraphRAG 问答接口。"""

from __future__ import annotations

import json
import logging
from typing import Any

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from common.core.logging_utils import build_log_message
from common.http.responses import error_response, success_response
from ai_services.services.demo_fallback import (
    build_demo_chat,
    build_demo_search,
    demo_mode_enabled,
)
from ai_services.services.demo_presets import load_verified_answer, record_verified_answer
from platform_ai.llm import llm_facade
from ai_services.services.student.graph_rag_service import student_graph_rag_service

logger = logging.getLogger(__name__)


def _chat_request_fingerprint(course_id: object, question: str, point_id: object) -> str:
    """构造课程问答彩排结果的稳定请求文本。

    :param course_id: 课程 ID。
    :param question: 学生问题。
    :param point_id: 可选知识点 ID。
    :returns: 用于计算指纹的 JSON 文本。
    """
    return json.dumps(
        {"course_id": str(course_id), "question": question, "point_id": str(point_id or "")},
        ensure_ascii=False,
        sort_keys=True,
    )


def build_chat_response(
    *,
    user,
    question: str,
    course_id: int | str | None = None,
    point_id: int | str | None = None,
    knowledge_point: str = "",
    course_name: str = "",
) -> dict[str, Any]:
    """统一生成 AI 助手回复，供 HTTP 与 WebSocket 共用。"""
    normalized_question = (question or "").strip()
    if not normalized_question:
        return {"reply": "请输入问题", "sources": [], "mode": "error"}

    if course_id:
        preset_prompt = _chat_request_fingerprint(course_id, normalized_question, point_id)
        if demo_mode_enabled() and not llm_facade.is_available:
            verified = load_verified_answer("api_json", "student_chat", preset_prompt)
            if isinstance(verified, dict):
                return {**verified, "demo_fallback": True, "generation_source": "verified_ai_preset"}
        try:
            result = student_graph_rag_service.ask(
                user=user,
                course_id=int(course_id),
                question=normalized_question,
                point_id=int(point_id) if point_id else None,
            )
            if not result.get("demo_fallback"):
                record_verified_answer("api_json", "student_chat", preset_prompt, result)
            return result
        except Exception as exc:
            logger.error(build_log_message("chat.graph_rag.fail", course_id=course_id, error=exc))
            if demo_mode_enabled():
                verified = load_verified_answer("api_json", "student_chat", preset_prompt)
                if isinstance(verified, dict):
                    return {**verified, "demo_fallback": True, "generation_source": "verified_ai_preset"}
                return build_demo_chat(
                    int(course_id),
                    normalized_question,
                    int(point_id) if point_id else None,
                )
            return {"reply": "服务暂时不可用，请稍后重试。", "sources": [], "mode": "error"}

    fallback = {
        "reply": (
            f"当前问题是“{normalized_question}”。"
            f"{' 你正在学习“' + knowledge_point + '”。' if knowledge_point else ''}"
            f"{' 所属课程为“' + course_name + '”。' if course_name else ''}"
            "当前未提供可定位的课程图谱上下文，我会先给出通用解答，建议在知识图谱或学习路径页面中带上具体知识点继续追问。"
        ),
        "sources": [],
        "mode": "llm_fallback",
    }
    if llm_facade.is_available:
        result = llm_facade.call_with_fallback(
            prompt=(
                "请用中文回答学生的学习问题，保持内容简洁、准确、适合教学场景。"
                f"\n课程：{course_name or '未提供'}"
                f"\n知识点：{knowledge_point or '未提供'}"
                f"\n问题：{normalized_question}"
            ),
            call_type="chat",
            fallback_response=fallback,
        )
        payload = {"reply": result.get("reply", result.get("answer", "")), "sources": [], "mode": "llm_fallback"}
        if result.get("demo_fallback"):
            payload["demo_fallback"] = True
            payload["generation_source"] = result.get("generation_source")
        return payload
    return fallback


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ai_chat(request):
    """Course-grounded chat with optional knowledge-point focus."""
    return handle_chat_request(request)


def handle_chat_request(request: Request) -> Response:
    """
    处理学生 AI 聊天请求并返回统一响应。

    :param request: DRF 请求对象。
    :return: 统一格式的聊天响应。
    """
    question = (request.data.get("question") or request.data.get("message") or "").strip()
    course_id = request.data.get("course_id")
    point_id = request.data.get("point_id")
    knowledge_point = (request.data.get("knowledge_point") or "").strip()
    course_name = (request.data.get("course_name") or "").strip()
    if not question:
        return error_response(msg="请输入问题", code=400)
    if len(question) > 1000:
        return error_response(msg="问题内容过长，请限制在1000字以内", code=400)

    result = build_chat_response(
        user=request.user,
        question=question,
        course_id=course_id,
        point_id=point_id,
        knowledge_point=knowledge_point,
        course_name=course_name,
    )
    return success_response(data=result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ai_knowledge_graph_query(request):
    """Dedicated alias for graph-grounded student Q&A."""
    return handle_chat_request(request)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ai_graph_rag_search(request):
    """Search graph knowledge points under the current course."""
    course_id = request.data.get("course_id")
    query = (request.data.get("query") or request.data.get("keyword") or "").strip()
    limit = int(request.data.get("limit") or 8)
    if not course_id:
        return error_response(msg="缺少课程ID", code=400)
    if not query:
        return error_response(msg="请输入检索内容", code=400)
    bounded_limit = max(1, min(limit, 20))
    try:
        result = student_graph_rag_service.search_points(
            user=request.user,
            course_id=int(course_id),
            query=query,
            limit=bounded_limit,
        )
    except Exception:
        if not demo_mode_enabled():
            raise
        logger.exception("演示模式 GraphRAG 检索失败，使用课程知识点检索")
        result = build_demo_search(request.user, int(course_id), query, bounded_limit)
    return success_response(data=result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ai_graph_rag_ask(request):
    """Ask a graph-grounded question under the current course."""
    course_id = request.data.get("course_id")
    question = (request.data.get("question") or request.data.get("message") or "").strip()
    point_id = request.data.get("point_id")
    if not course_id:
        return error_response(msg="缺少课程ID", code=400)
    if not question:
        return error_response(msg="请输入问题", code=400)
    preset_prompt = _chat_request_fingerprint(course_id, question, point_id)
    if demo_mode_enabled() and not llm_facade.is_available:
        verified = load_verified_answer("api_json", "graph_rag_ask", preset_prompt)
        if isinstance(verified, dict):
            return success_response(data={**verified, "demo_fallback": True, "generation_source": "verified_ai_preset"})
    try:
        result = student_graph_rag_service.ask(
            user=request.user,
            course_id=int(course_id),
            question=question,
            point_id=int(point_id) if point_id else None,
        )
        if not result.get("demo_fallback"):
            record_verified_answer("api_json", "graph_rag_ask", preset_prompt, result)
    except Exception:
        if not demo_mode_enabled():
            raise
        logger.exception("演示模式 GraphRAG 问答失败，使用课程内容回答")
        verified = load_verified_answer("api_json", "graph_rag_ask", preset_prompt)
        result = (
            {**verified, "demo_fallback": True, "generation_source": "verified_ai_preset"}
            if isinstance(verified, dict)
            else build_demo_chat(int(course_id), question, int(point_id) if point_id else None)
        )
    return success_response(data=result)
