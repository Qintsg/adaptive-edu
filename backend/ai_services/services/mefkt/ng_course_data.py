#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
把项目课程、题目与知识点冻结为 MEFKT-NG 可缓存的静态目录输入。
@Project : adaptive-edu
@File : ng_course_data.py
@Author : Qintsg
@Date : 2026-09-25
'''

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NGPointSpec:
    """一条课程知识点静态记录。"""

    id: int
    name: str
    description: str
    updated_at: str = ""


@dataclass(frozen=True)
class NGQuestionSpec:
    """一条课程题目静态记录，不含标准答案或解析。"""

    id: int
    content: str
    options: tuple[str, ...]
    question_type: str
    difficulty: str
    point_ids: tuple[int, ...]
    updated_at: str = ""


@dataclass(frozen=True)
class NGCourseSpec:
    """一次查询得到的课程题目和知识点快照。"""

    course_id: int
    name: str
    points: tuple[NGPointSpec, ...]
    questions: tuple[NGQuestionSpec, ...]
    revision: str


def _option_texts(value: object) -> tuple[str, ...]:
    """只提取学生可见选项文本，不读取标准答案。

    :param value: Question.options JSON。
    :returns: 有序的选项文本。
    """
    if not isinstance(value, list):
        return ()
    texts: list[str] = []
    for option in value:
        if isinstance(option, dict):
            text = str(option.get("content") or option.get("label") or "").strip()
        else:
            text = str(option or "").strip()
        if text:
            texts.append(text)
    return tuple(texts)


def course_revision(name: str, points: tuple[NGPointSpec, ...],
                    questions: tuple[NGQuestionSpec, ...]) -> str:
    """对实际编码输入生成稳定摘要，避免题库变动后复用旧缓存。

    :param name: 课程名称。
    :param points: 知识点快照。
    :param questions: 题目快照。
    :returns: SHA-256 十六进制值。
    """
    payload: dict[str, Any] = {
        "course": name,
        "points": [(point.id, point.name, point.description, point.updated_at) for point in points],
        "questions": [(question.id, question.content, question.options,
                       question.question_type, question.difficulty, question.point_ids,
                       question.updated_at) for question in questions],
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_course_spec(course_id: int) -> NGCourseSpec:
    """只读取一门课程的可见题目及课程知识点。

    :param course_id: 业务课程 ID。
    :returns: 不含标准答案的静态快照。
    :raises ValueError: 课程不存在或没有可建模题目。
    """
    from assessments.models import Question
    from courses.models import Course
    from knowledge.models import KnowledgePoint

    course = Course.objects.filter(pk=course_id).only("id", "name").first()
    if course is None:
        raise ValueError(f"课程不存在：{course_id}")
    point_rows = list(KnowledgePoint.objects.filter(course_id=course_id).order_by("id"))
    points = tuple(NGPointSpec(int(row.id), str(row.name or ""), str(row.description or ""),
                               row.updated_at.isoformat() if row.updated_at else "")
                   for row in point_rows)
    known_points = {point.id for point in points}
    question_rows = Question.objects.filter(course_id=course_id, is_visible=True).prefetch_related(
        "knowledge_points"
    ).order_by("id")
    questions: list[NGQuestionSpec] = []
    for row in question_rows:
        point_ids = tuple(sorted(int(point.id) for point in row.knowledge_points.all()
                                 if int(point.id) in known_points))
        if not point_ids:
            continue
        questions.append(NGQuestionSpec(
            id=int(row.id), content=str(row.content or ""), options=_option_texts(row.options),
            question_type=str(row.question_type or ""), difficulty=str(row.difficulty or ""),
            point_ids=point_ids, updated_at=row.updated_at.isoformat() if row.updated_at else "",
        ))
    if not points or not questions:
        raise ValueError(f"课程 {course_id} 缺少关联知识点的可见题目")
    frozen_questions = tuple(questions)
    return NGCourseSpec(int(course_id), str(course.name), points, frozen_questions,
                        course_revision(str(course.name), points, frozen_questions))
