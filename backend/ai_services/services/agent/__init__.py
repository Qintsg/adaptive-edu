#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
A3 多智能体服务包。
@Project : adaptive-edu
@File : __init__.py
@Author : Qintsg
@Date : 2026-06-05 00:00
'''

from ai_services.services.agent.context import resolve_student_course
from ai_services.services.agent.profile_dialog import ProfileDialogService
from ai_services.services.agent.resource_generation import ResourceGenerationService

__all__ = [
    "ProfileDialogService",
    "ResourceGenerationService",
    "resolve_student_course",
]
