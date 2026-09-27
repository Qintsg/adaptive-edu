#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
将业务答题历史和同场候选题转换为 MEFKT-NG 的因果序列输入。
@Project : adaptive-edu
@File : ng_sequence.py
@Author : Qintsg
@Date : 2026-09-25
'''

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import torch

from ai_services.services.mefkt.ng_catalog import NGCourseCatalog


@dataclass(frozen=True)
class NGHistory:
    """已经评分且可供模型更新状态的事件序列。"""

    items: tuple[int, ...]
    correct: tuple[float, ...]
    gaps: tuple[float, ...]
    time_known: tuple[bool, ...]
    episodes: tuple[int, ...]
    last_time: datetime | None
    recognized_count: int


def _int_id(value: object) -> int | None:
    """解析正整数业务标识。

    :param value: 原始标识。
    :returns: 正整数或 None。
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _correct(value: object) -> float | None:
    """只接受明确的二元评分。

    :param value: 作答结果。
    :returns: 0.0、1.0 或 None。
    """
    if isinstance(value, bool):
        return float(value)
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "1.0", "true"}:
        return 1.0
    if normalized in {"0", "0.0", "false"}:
        return 0.0
    return None


def _timestamp(value: object) -> datetime | None:
    """解析并统一答题时间到 UTC。

    :param value: datetime、ISO-8601 或 Unix 秒/毫秒。
    :returns: UTC 时间，无法解析则为 None。
    """
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC)
    raw = "" if value is None else str(value).strip()
    if not raw:
        return None
    try:
        numeric = float(raw)
        return datetime.fromtimestamp(numeric / 1000.0 if numeric > 10_000_000_000 else numeric, UTC)
    except (ValueError, OverflowError, OSError):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)
        except ValueError:
            return None


def _point_ids(record: dict[str, Any]) -> list[int]:
    """读取知识点级历史的一个或多个 ID。

    :param record: 业务答题记录。
    :returns: 去重后的知识点 ID。
    """
    values = record.get("knowledge_point_ids")
    raw = values if isinstance(values, (list, tuple, set)) else [record.get("knowledge_point_id")]
    return list(dict.fromkeys(point_id for value in raw if (point_id := _int_id(value)) is not None))


def _item_index(record: dict[str, Any], catalog: NGCourseCatalog) -> int | None:
    """优先使用原题目，知识点级旧历史采用稳定代表题。

    :param record: 业务答题记录。
    :param catalog: 当前课程目录。
    :returns: 目录题目索引或 None。
    """
    raw_question_id = record.get("question_id")
    if raw_question_id is not None and str(raw_question_id).strip():
        return catalog.question_index.get(_int_id(raw_question_id))
    for point_id in _point_ids(record):
        indices = catalog.point_to_questions.get(point_id, ())
        if indices:
            return indices[0]
    return None


def prepare_history(
    answer_history: list[dict[str, Any]], catalog: NGCourseCatalog, max_events: int,
) -> NGHistory:
    """恢复评分、时间间隔及同场测验边界。

    :param answer_history: 已评分业务历史。
    :param catalog: 当前课程题目映射。
    :param max_events: 截取的最近事件数。
    :returns: 可直接送入模型的历史序列。
    """
    if max_events < 0:
        raise ValueError("max_events 不能为负")
    parsed = [(order, _timestamp(row.get("timestamp") or row.get("answered_at")), row)
              for order, row in enumerate(answer_history)]
    if parsed and all(timestamp is not None for _, timestamp, _ in parsed):
        parsed.sort(key=lambda entry: (entry[1], entry[0]))
    recognized = [(order, timestamp, row, index, label)
                  for order, timestamp, row in parsed
                  if (index := _item_index(row, catalog)) is not None
                  and (label := _correct(row.get("correct", row.get("is_correct")))) is not None]
    selected = recognized[-max_events:] if max_events else []
    items: list[int] = []
    correct: list[float] = []
    gaps: list[float] = []
    known: list[bool] = []
    episodes: list[int] = []
    previous_time: datetime | None = None
    previous_key: tuple[object, ...] | None = None
    episode_index = -1
    for order, timestamp, row, index, label in selected:
        explicit = row.get("episode_id") or row.get("submission_id") or row.get("exam_id")
        if explicit is not None and str(explicit).strip():
            key = ("exam", str(explicit))
        elif timestamp is not None:
            key = ("timestamp", timestamp)
        else:
            key = ("row", order)
        if key != previous_key:
            episode_index += 1
        items.append(index)
        correct.append(label)
        is_known = timestamp is not None and previous_time is not None
        known.append(is_known)
        gaps.append(max((timestamp - previous_time).total_seconds() / 3600.0, 0.0)
                    if is_known else 0.0)
        episodes.append(episode_index)
        previous_time, previous_key = timestamp, key
    return NGHistory(tuple(items), tuple(correct), tuple(gaps), tuple(known),
                     tuple(episodes), previous_time, len(recognized))


def predict_candidates(
    catalog: NGCourseCatalog, history: NGHistory, candidates: list[int],
    now: datetime | None = None,
) -> dict[int, float]:
    """候选题同场预测，虚拟标签在全部预测后才可能提交。

    :param catalog: 当前课程模型目录。
    :param history: 真实已评分历史。
    :param candidates: 本批不超过窗口容量的候选题索引。
    :param now: 预测时刻，测试可显式指定。
    :returns: 题目索引到答对概率。
    :raises ValueError: 空候选或序列超出训练窗口。
    """
    if not candidates or len(history.items) + len(candidates) > 200:
        raise ValueError("候选题为空或序列超过 200")
    current = now or datetime.now(UTC)
    current = (current if current.tzinfo else current.replace(tzinfo=UTC)).astimezone(UTC)
    has_gap = history.last_time is not None
    first_gap = max((current - history.last_time).total_seconds() / 3600.0, 0.0) if has_gap else 0.0
    episode = (max(history.episodes) + 1) if history.episodes else 0
    device = next(catalog.model.parameters()).device
    batch = {
        "items": torch.tensor([history.items + tuple(candidates)], dtype=torch.long, device=device),
        "correct": torch.tensor([history.correct + (0.0,) * len(candidates)], dtype=torch.float32, device=device),
        "gaps": torch.tensor([history.gaps + (first_gap,) + (0.0,) * (len(candidates) - 1)],
                             dtype=torch.float32, device=device),
        "time_known": torch.tensor([history.time_known + (has_gap,) + (False,) * (len(candidates) - 1)],
                                   dtype=torch.bool, device=device),
        "episodes": torch.tensor([history.episodes + (episode,) * len(candidates)],
                                 dtype=torch.long, device=device),
        "valid": torch.ones((1, len(history.items) + len(candidates)), dtype=torch.bool, device=device),
    }
    with torch.inference_mode():
        logits, _ = catalog.model(batch)
        probabilities = torch.sigmoid(logits[0, -len(candidates):]).cpu().tolist()
    return dict(zip(candidates, (float(value) for value in probabilities), strict=True))
