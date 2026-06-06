#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
A3 Agent 课程上下文和权限校验。
@Project : adaptive-edu
@File : context.py
@Author : Qintsg
@Date : 2026-06-05 00:00
'''

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q

from courses.models import Course, Enrollment


@dataclass(frozen=True)
class CourseAccessResult:
    """
    学生课程访问校验结果。

    :param course: 通过权限校验的课程。
    :param error_message: 校验失败时的用户可读消息。
    :param status_code: 校验失败时的 HTTP 状态码。
    """

    course: Course | None
    error_message: str
    status_code: int


def resolve_student_course(user: object, course_id: object) -> CourseAccessResult:
    """
    校验学生是否可访问指定课程。

    :param user: 当前请求用户。
    :param course_id: 请求中的课程 ID。
    :return: 课程访问结果。
    """
    if getattr(user, "role", "") != "student":
        return CourseAccessResult(None, "仅学生可以访问个性化智能体接口", 403)
    if not course_id:
        return CourseAccessResult(None, "缺少 course_id 参数", 400)

    try:
        parsed_course_id = int(course_id)
    except (TypeError, ValueError):
        return CourseAccessResult(None, "course_id 参数格式错误", 400)

    try:
        course = Course.objects.get(id=parsed_course_id)
    except Course.DoesNotExist:
        return CourseAccessResult(None, "课程不存在", 404)

    has_enrollment = Enrollment.objects.filter(user=user).filter(
        Q(class_obj__course_id=course.id)
        | Q(class_obj__class_courses__course_id=course.id, class_obj__class_courses__is_active=True)
    ).exists()
    if not has_enrollment:
        return CourseAccessResult(None, "您未选修该课程", 403)

    return CourseAccessResult(course, "", 200)
