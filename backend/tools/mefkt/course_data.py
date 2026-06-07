#!/user/bin/env python
# -*- coding: UTF-8 -*-
"""MEFKT 课程域训练数据构建。"""

from __future__ import annotations

from collections import defaultdict

from ai_services.services.mefkt.runtime import build_course_runtime_bundle
from models.MEFKT.model import QUESTION_TYPE_VOCAB
from tools.mefkt.public_data import MEFKTTrainingBundle, SequenceRecord, split_sequences


def build_course_bundle(
    course_id: int,
    *,
    validation_ratio: float = 0.2,
    seed: int = 42,
) -> MEFKTTrainingBundle:
    """
    从本地课程题目和答题历史构建 MEFKT 微调训练包。

    :param course_id: 课程 ID。
    :param validation_ratio: 验证集比例。
    :param seed: 划分随机种子。
    :return: 课程域 MEFKT 训练包。
    """
    runtime_bundle = build_course_runtime_bundle(course_id)
    all_sequences = load_course_sequences(
        course_id=course_id,
        question_id_to_index=runtime_bundle.question_id_to_index,
    )
    if len(all_sequences) < 2:
        raise ValueError("课程答题历史不足，无法进行 MEFKT 课程域微调")

    train_sequences, validation_sequences = split_sequences(
        all_sequences,
        validation_ratio=validation_ratio,
        seed=seed,
    )
    return MEFKTTrainingBundle(
        dataset_name=f"course_{course_id}",
        item_ids=runtime_bundle.question_ids,
        item_names=[f"course_question_{question_id}" for question_id in runtime_bundle.question_ids],
        type_mapping={key: value for key, value in QUESTION_TYPE_VOCAB.items()},
        sequences=train_sequences,
        node_feature_matrix=runtime_bundle.node_feature_matrix,
        relation_stats_matrix=runtime_bundle.relation_stats_matrix,
        adjacency_matrix=runtime_bundle.adjacency_matrix,
        difficulty_vector=runtime_bundle.difficulty_vector,
        response_time_vector=runtime_bundle.response_time_vector,
        exercise_type_vector=runtime_bundle.exercise_type_vector,
        training_mode="course_question_finetune",
        training_sources=[f"course_id={course_id}", "answer_histories"],
        validation_sequences=validation_sequences,
        test_sequences=validation_sequences,
        split_policy={
            "strategy": "course_user_sequence_train_validation",
            "validation_ratio": validation_ratio,
            "seed": seed,
            "train_sequences": len(train_sequences),
            "validation_sequences": len(validation_sequences),
            "test_sequences": len(validation_sequences),
        },
        graph_source="course_question_knowledge_resource_graph",
        feature_coverage={
            "real_response_time_ratio": 1.0,
            "real_question_type_ratio": 1.0,
            "difficulty_source": "course_question_difficulty_and_history",
            "response_time_source": "answer_history_gap_hours",
            "question_type_source": "course_question_type",
            "item_count": len(runtime_bundle.question_ids),
            "sequence_count": len(all_sequences),
        },
        paper_reproduction_notes=[
            "课程域微调用于提升本系统在线预测效果，不作为公开数据论文复现指标。",
        ],
    )


def load_course_sequences(
    *,
    course_id: int,
    question_id_to_index: dict[int, int],
) -> list[SequenceRecord]:
    """
    按用户聚合课程答题历史，并转成模型序列。

    :param course_id: 课程 ID。
    :param question_id_to_index: 题目 ID 到连续索引的映射。
    :return: 课程答题序列。
    """
    from assessments.models import AnswerHistory

    grouped_rows: dict[int, list[object]] = defaultdict(list)
    histories = (
        AnswerHistory.objects.filter(course_id=course_id, question_id__in=question_id_to_index)
        .select_related("question")
        .order_by("user_id", "answered_at", "id")
    )
    for history in histories:
        grouped_rows[int(history.user_id)].append(history)

    sequences: list[SequenceRecord] = []
    for rows in grouped_rows.values():
        item_indices: list[int] = []
        correct_flags: list[int] = []
        gap_hours: list[float] = []
        previous_time = None
        for row in rows:
            item_indices.append(question_id_to_index[int(row.question_id)])
            correct_flags.append(1 if row.is_correct else 0)
            if previous_time is None:
                gap_hours.append(1.0)
            else:
                gap_seconds = max((row.answered_at - previous_time).total_seconds(), 60.0)
                gap_hours.append(gap_seconds / 3600.0)
            previous_time = row.answered_at
        if len(item_indices) >= 2:
            sequences.append((item_indices, correct_flags, gap_hours))
    return sequences


__all__ = ["build_course_bundle", "load_course_sequences"]
