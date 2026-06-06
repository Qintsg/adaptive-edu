#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
学生端 A3 Agent API。
@Project : adaptive-edu
@File : agent.py
@Author : Qintsg
@Date : 2026-06-05 00:00
'''

from __future__ import annotations

from typing import Any

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from ai_services.services.agent import (
    GeneratedResourceFeedbackService,
    LearningPackageService,
    ProfileDialogService,
    ResourceGenerationService,
    resolve_student_course,
)
from common.http.responses import error_response, success_response
from knowledge.models import KnowledgePoint


def _resolve_course_or_response(user: object, course_id: object) -> tuple[object | None, object | None]:
    """
    解析学生课程上下文，失败时返回统一错误响应。

    :param user: 当前请求用户。
    :param course_id: 请求课程 ID。
    :return: 课程与可选错误响应。
    """
    access_result = resolve_student_course(user, course_id)
    if access_result.course is None:
        return None, error_response(
            msg=access_result.error_message,
            code=access_result.status_code,
        )
    return access_result.course, None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def profile_dialog(request):
    """
    对话式学习画像抽取。

    :param request: DRF 请求。
    :return: 画像字段、缺失字段、追问和 Agent trace。
    """
    course, error = _resolve_course_or_response(request.user, request.data.get("course_id"))
    if error is not None:
        return error

    message = str(request.data.get("message") or "").strip()
    if not message:
        return error_response(msg="请输入画像对话内容", code=400)
    if len(message) > 2000:
        return error_response(msg="画像对话内容过长，请控制在 2000 字以内", code=400)

    result = ProfileDialogService(request.user, course).extract_profile(message)
    return success_response(data=result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def generate_resources(request):
    """
    生成个性化学习资源。

    :param request: DRF 请求。
    :return: 运行记录、Agent trace、生成资源和 warnings。
    """
    course, error = _resolve_course_or_response(request.user, request.data.get("course_id"))
    if error is not None:
        return error

    target = str(request.data.get("target") or "").strip()
    knowledge_point_id = request.data.get("knowledge_point_id")
    if not target and not knowledge_point_id:
        return error_response(msg="请输入学习目标或选择知识点", code=400)
    if len(target) > 1000:
        return error_response(msg="学习目标过长，请控制在 1000 字以内", code=400)
    if knowledge_point_id:
        try:
            parsed_point_id = int(knowledge_point_id)
        except (TypeError, ValueError):
            return error_response(msg="knowledge_point_id 参数格式错误", code=400)
        if not KnowledgePoint.objects.filter(id=parsed_point_id, course=course).exists():
            return error_response(msg="知识点不存在或不属于当前课程", code=404)

    profile = request.data.get("profile") or {}
    if not isinstance(profile, dict):
        return error_response(msg="profile 参数必须是对象", code=400)

    resource_types = request.data.get("resource_types")
    if resource_types is not None and not isinstance(resource_types, list):
        return error_response(msg="resource_types 参数必须是数组", code=400)

    result = ResourceGenerationService(request.user, course).generate_resources(
        target=target,
        knowledge_point_id=knowledge_point_id,
        profile=profile,
        resource_types=resource_types,
    )
    return success_response(data=result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def generate_learning_package(request):
    """
    生成学习资源包并给出路径绑定建议。

    :param request: DRF 请求。
    :return: 学习包、质量报告、进度事件和路径建议。
    """
    course, error = _resolve_course_or_response(request.user, request.data.get("course_id"))
    if error is not None:
        return error

    target = str(request.data.get("target") or "").strip()
    knowledge_point_id = request.data.get("knowledge_point_id")
    if not target and not knowledge_point_id:
        return error_response(msg="请输入学习目标或选择知识点", code=400)
    if len(target) > 1000:
        return error_response(msg="学习目标过长，请控制在 1000 字以内", code=400)
    point_error = _validate_knowledge_point(course, knowledge_point_id)
    if point_error is not None:
        return point_error

    profile = request.data.get("profile") or {}
    if not isinstance(profile, dict):
        return error_response(msg="profile 参数必须是对象", code=400)

    resource_types = request.data.get("resource_types")
    if resource_types is not None and not isinstance(resource_types, list):
        return error_response(msg="resource_types 参数必须是数组", code=400)

    result = LearningPackageService(request.user, course).generate_learning_package(
        target=target,
        knowledge_point_id=knowledge_point_id,
        profile=profile,
        resource_types=resource_types,
    )
    return success_response(data=result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def apply_resources_to_path(request):
    """
    将生成资源包应用到学习路径。

    :param request: DRF 请求。
    :return: 路径绑定结果。
    """
    course, error = _resolve_course_or_response(request.user, request.data.get("course_id"))
    if error is not None:
        return error

    resource_ids = request.data.get("resource_ids")
    if resource_ids is not None and not isinstance(resource_ids, list):
        return error_response(msg="resource_ids 参数必须是数组", code=400)

    result = LearningPackageService(request.user, course).apply_resources_to_path(
        run_id=request.data.get("run_id"),
        resource_ids=resource_ids,
    )
    if not result.get("ok"):
        return error_response(msg=str(result.get("error") or "路径绑定失败"), code=int(result.get("status_code") or 400))
    return success_response(data=result)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_agent_run(request, run_id):
    """
    查询 Agent 运行详情。

    :param request: DRF 请求。
    :param run_id: AgentRun ID。
    :return: 运行详情。
    """
    course, error = _resolve_course_or_response(request.user, request.query_params.get("course_id"))
    if error is not None:
        return error

    result = LearningPackageService(request.user, course).get_run_detail(run_id)
    if result is None:
        return error_response(msg="运行记录不存在或无权访问", code=404)
    return success_response(data=result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def complete_agent_run(request, run_id):
    """
    标记 Agent 运行完成。

    :param request: DRF 请求。
    :param run_id: AgentRun ID。
    :return: 运行详情。
    """
    course, error = _resolve_course_or_response(request.user, request.data.get("course_id"))
    if error is not None:
        return error

    result = LearningPackageService(request.user, course).complete_run(run_id)
    if result is None:
        return error_response(msg="运行记录不存在或无权访问", code=404)
    return success_response(data=result)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_generated_resources(request):
    """
    查询当前学生课程下的生成资源。

    :param request: DRF 请求。
    :return: 生成资源列表。
    """
    course, error = _resolve_course_or_response(request.user, request.query_params.get("course_id"))
    if error is not None:
        return error

    try:
        limit = int(request.query_params.get("limit") or 30)
    except (TypeError, ValueError):
        return error_response(msg="limit 参数格式错误", code=400)

    result = LearningPackageService(request.user, course).list_resources(
        limit=limit,
        resource_type=str(request.query_params.get("resource_type") or ""),
    )
    return success_response(data=result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def submit_resource_feedback(request, resource_id):
    """
    提交生成资源学习反馈。

    :param request: DRF 请求。
    :param resource_id: 生成资源 ID。
    :return: 反馈和画像/路径更新摘要。
    """
    course, error = _resolve_course_or_response(request.user, request.data.get("course_id"))
    if error is not None:
        return error

    result = GeneratedResourceFeedbackService(request.user, course).submit_feedback(
        resource_id=resource_id,
        completed=bool(request.data.get("completed", False)),
        rating=request.data.get("rating"),
        usefulness=str(request.data.get("usefulness") or "neutral"),
        difficulty=str(request.data.get("difficulty") or "moderate"),
        feedback=str(request.data.get("feedback") or ""),
        quiz_result=request.data.get("quiz_result") if isinstance(request.data.get("quiz_result"), dict) else {},
        time_spent_seconds=request.data.get("time_spent_seconds"),
    )
    if result is None:
        return error_response(msg="生成资源不存在或无权访问", code=404)
    return success_response(data=result)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_effect_summary(request):
    """
    查询生成资源学习效果摘要。

    :param request: DRF 请求。
    :return: 效果摘要。
    """
    course, error = _resolve_course_or_response(request.user, request.query_params.get("course_id"))
    if error is not None:
        return error

    result = GeneratedResourceFeedbackService(request.user, course).get_effect_summary()
    return success_response(data=result)


def _validate_knowledge_point(course: object, knowledge_point_id: object) -> object | None:
    """
    校验知识点归属。

    :param course: 当前课程。
    :param knowledge_point_id: 知识点 ID。
    :return: 可选错误响应。
    """
    if not knowledge_point_id:
        return None
    try:
        parsed_point_id = int(knowledge_point_id)
    except (TypeError, ValueError):
        return error_response(msg="knowledge_point_id 参数格式错误", code=400)
    if not KnowledgePoint.objects.filter(id=parsed_point_id, course=course).exists():
        return error_response(msg="知识点不存在或不属于当前课程", code=404)
    return None


__all__ = [
    "apply_resources_to_path",
    "complete_agent_run",
    "generate_resources",
    "generate_learning_package",
    "get_agent_run",
    "get_effect_summary",
    "list_generated_resources",
    "profile_dialog",
    "submit_resource_feedback",
]
