#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
为本地 MEFKT-NG 浏览器联调准备独立学生账号和课程凭据。
@Project : adaptive-edu
@File : prepare_mefkt_ng_local_e2e.py
@Author : Qintsg
@Date : 2026-09-25
'''

from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "adaptive_edu_api.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from assessments.models import Question, SurveyQuestion  # noqa: E402
from courses.models import ClassCourse, Course, Enrollment  # noqa: E402
from users.models import User, UserCourseContext  # noqa: E402


def main() -> None:
    """建立一次性本地学生账号和可复现联调输入。

    :returns: None。
    :raises RuntimeError: 当前并非本地开发数据库或缺少测试课程。
    """
    db_host = settings.DATABASES["default"].get("HOST", "")
    if not settings.DEBUG or db_host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("本脚本仅可用于本机开发数据库")

    course = Course.objects.filter(name="数据可视化基础").first()
    if course is None:
        raise RuntimeError("Docker 开发库缺少“数据可视化基础”课程")
    publication = ClassCourse.objects.filter(
        course=course, is_active=True, class_obj__is_active=True,
    ).select_related("class_obj").first()
    question = Question.objects.filter(
        course=course, is_visible=True, question_type="single_choice",
        knowledge_points__isnull=False,
    ).distinct().first()
    if publication is None or question is None:
        raise RuntimeError("联调课程缺少已发布班级或可见单选题")
    point = question.knowledge_points.first()
    ability_count = SurveyQuestion.objects.filter(survey_type="ability").count()
    habit_count = SurveyQuestion.objects.filter(survey_type="habit").count()
    if not ability_count or not habit_count:
        raise RuntimeError("Docker 开发库缺少能力或习惯问卷")

    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    username = f"mefkt_ng_e2e_{suffix}_{secrets.token_hex(3)}"
    password = "Dev-" + secrets.token_urlsafe(18)
    user = User.objects.create_user(
        username=username, password=password, role="student",
    )
    Enrollment.objects.create(user=user, class_obj=publication.class_obj)
    UserCourseContext.objects.create(
        user=user, current_course=course, current_class=publication.class_obj,
    )
    credential_path = Path(tempfile.gettempdir()) / "mefkt_ng_e2e_credentials.json"
    credential_path.write_text(json.dumps({
        "username": username,
        "password": password,
        "course_id": course.id,
        "course_name": course.name,
        "question_id": question.id,
        "question_content": question.content,
        "knowledge_point_id": point.id,
        "knowledge_point_name": point.name,
        "ability_question_count": ability_count,
        "habit_question_count": habit_count,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"测试用户：{username}；凭据文件：{credential_path}")


if __name__ == "__main__":
    main()
