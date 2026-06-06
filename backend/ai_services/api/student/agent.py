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


__all__ = [
    "generate_resources",
    "profile_dialog",
]
