#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
以冻结内容编码器构建 MEFKT-NG 新课程题目与知识点目录。
@Project : adaptive-edu
@File : ng_catalog.py
@Author : Qintsg
@Date : 2026-09-25
'''

from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import torch
from numpy.typing import NDArray

from ai_services.services.mefkt.ng_course_data import NGCourseSpec, NGQuestionSpec
from models.MEFKT_NG.model import MEFKTNG, ModelConfig


CONTENT_DIM = 384
MAX_ITEM_SKILLS = 16
EncodeTexts = Callable[[list[str]], NDArray[np.float32]]


@dataclass(frozen=True)
class NGCourseCatalog:
    """与一个课程修订版本绑定的模型及稳定 ID 映射。"""

    course_id: int
    revision: str
    model: MEFKTNG
    question_ids: tuple[int, ...]
    question_index: dict[int, int]
    question_to_points: dict[int, tuple[int, ...]]
    point_ids: tuple[int, ...]
    point_to_questions: dict[int, tuple[int, ...]]


def _visible_text(value: str) -> str:
    """去掉 HTML 标签并压缩空白，保留学生可见文本。

    :param value: 课程或题目文本。
    :returns: 纯文本。
    """
    without_tags = re.sub(r"<[^>]*>", " ", str(value or ""))
    return " ".join(html.unescape(without_tags).split())


def _question_text(question: NGQuestionSpec, course: NGCourseSpec,
                   point_names: dict[int, str]) -> str:
    """只用静态公开题目属性组成编码文本。

    :param question: 题目快照。
    :param course: 课程快照。
    :param point_names: 课程知识点名称。
    :returns: 与训练内容分支相同语义来源的文本。
    """
    values = (course.name, _visible_text(question.content),
              " ".join(_visible_text(option) for option in question.options),
              ";".join(point_names[point_id] for point_id in question.point_ids),
              question.question_type, question.difficulty)
    return " [SEP] ".join(value for value in values if value)


def _difficulty(value: str) -> tuple[float, float]:
    """按训练阶段相同口径编码静态难度及存在掩码。

    :param value: 课程题目难度。
    :returns: 难度值和是否存在。
    """
    labels = {"easy": -1.0, "medium": 0.0, "hard": 1.0,
              "简单": -1.0, "中等": 0.0, "困难": 1.0}
    normalized = str(value or "").strip().lower()
    return (labels[normalized], 1.0) if normalized in labels else (0.0, 0.0)


def _normalized_vectors(values: NDArray[np.float32], count: int) -> NDArray[np.float32]:
    """严格检查冻结编码器的维度和有限值。

    :param values: 编码器输出。
    :param count: 期望行数。
    :returns: L2 归一化后的 float32 矩阵。
    :raises ValueError: 维度、非有限值或零向量错误。
    """
    vectors = np.asarray(values, dtype=np.float32)
    if vectors.shape != (count, CONTENT_DIM) or not np.isfinite(vectors).all():
        raise ValueError(f"内容编码器输出必须为 [{count},{CONTENT_DIM}] 有限矩阵")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if np.any(norms < 1e-8):
        raise ValueError("内容编码器返回零向量")
    return vectors / norms


def build_course_catalog(
    course: NGCourseSpec, encode: EncodeTexts, parameters: dict[str, torch.Tensor],
    config: ModelConfig, device: torch.device,
) -> NGCourseCatalog:
    """创建仅包含业务课程题目的 MEFKT-NG 实例并迁移共享参数。

    :param course: 课程静态快照。
    :param encode: 与训练相同的冻结多语言内容编码器。
    :param parameters: 已验证模型包的可训练张量。
    :param config: 训练时模型结构配置。
    :param device: 推理目标设备。
    :returns: 可缓存的课程目录和模型。
    :raises ValueError: 课程或权重不符合训练模型结构。
    """
    if not course.points or not course.questions:
        raise ValueError("课程没有知识点或可见题目")
    points = tuple(sorted(course.points, key=lambda point: point.id))
    questions = tuple(sorted(course.questions, key=lambda question: question.id))
    point_ids = tuple(point.id for point in points)
    point_names = {point.id: _visible_text(point.name) for point in points}
    point_index = {point_id: index for index, point_id in enumerate(point_ids)}
    for question in questions:
        if not question.point_ids or len(question.point_ids) > MAX_ITEM_SKILLS:
            raise ValueError(f"题目 {question.id} 的知识点数超出 1..{MAX_ITEM_SKILLS}")
        if any(point_id not in point_index for point_id in question.point_ids):
            raise ValueError(f"题目 {question.id} 引用了课程外知识点")
    item_texts = [_question_text(question, course, point_names) for question in questions]
    point_texts = [" [SEP] ".join(value for value in (course.name, point_names[point.id],
                    _visible_text(point.description)) if value) for point in points]
    vectors = _normalized_vectors(encode(item_texts + point_texts), len(questions) + len(points))
    item_vectors = vectors[:len(questions)]
    fallback_skills = vectors[len(questions):]
    item_skills = np.full((len(questions), max(len(question.point_ids) for question in questions)),
                          -1, dtype=np.int64)
    item_difficulty = np.zeros((len(questions), 2), dtype=np.float32)
    skill_vectors = np.zeros((len(points), CONTENT_DIM), dtype=np.float32)
    skill_counts = np.zeros(len(points), dtype=np.int32)
    point_to_questions: dict[int, list[int]] = {point_id: [] for point_id in point_ids}
    for item_index, question in enumerate(questions):
        item_difficulty[item_index] = _difficulty(question.difficulty)
        for position, point_id in enumerate(question.point_ids):
            skill_index = point_index[point_id]
            item_skills[item_index, position] = skill_index
            skill_vectors[skill_index] += item_vectors[item_index]
            skill_counts[skill_index] += 1
            point_to_questions[point_id].append(item_index)
    for index, count in enumerate(skill_counts):
        skill_vectors[index] = skill_vectors[index] / count if count else fallback_skills[index]
    skill_vectors = _normalized_vectors(skill_vectors, len(points))
    model = MEFKTNG(
        torch.from_numpy(item_vectors.copy()), torch.from_numpy(item_skills),
        torch.from_numpy(item_difficulty), torch.from_numpy(skill_vectors),
        torch.empty((0, 3), dtype=torch.long), config,
    )
    named = dict(model.named_parameters())
    if set(parameters) != set(named) or any(parameters[name].shape != value.shape
                                            for name, value in named.items()):
        raise ValueError("模型包共享参数与课程模型结构不一致")
    with torch.no_grad():
        for name, value in named.items():
            value.copy_(parameters[name].to(dtype=value.dtype))
    model = model.to(device).eval()
    question_ids = tuple(question.id for question in questions)
    return NGCourseCatalog(
        course_id=course.course_id, revision=course.revision, model=model,
        question_ids=question_ids,
        question_index={question_id: index for index, question_id in enumerate(question_ids)},
        question_to_points={question.id: question.point_ids for question in questions},
        point_ids=point_ids,
        point_to_questions={point_id: tuple(indices) for point_id, indices in point_to_questions.items()},
    )
