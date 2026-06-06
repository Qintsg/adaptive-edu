#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
A3 Agent 服务常量和轻量 schema。
@Project : adaptive-edu
@File : schemas.py
@Author : Qintsg
@Date : 2026-06-05 00:00
'''

from __future__ import annotations

PROFILE_FIELDS = [
    "major_or_background",
    "course_goal",
    "knowledge_foundation",
    "weaknesses",
    "preferred_resource",
    "learning_style",
    "pace",
    "available_time",
    "practice_preference",
    "motivation",
]

RESOURCE_TYPES = [
    "explanation",
    "mindmap",
    "quiz",
    "reading",
    "coding_case",
    "video_script",
]

DEFAULT_RESOURCE_TYPES = [
    "explanation",
    "mindmap",
    "quiz",
    "reading",
    "coding_case",
]

RESOURCE_TYPE_LABELS = {
    "explanation": "讲解文档",
    "mindmap": "思维导图",
    "quiz": "练习题",
    "reading": "拓展阅读",
    "coding_case": "代码实操案例",
    "video_script": "视频脚本",
}
