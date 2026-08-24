#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT 通用 canonical CSV 数据适配器。
@Project : adaptive-edu
@File : mefkt_canonical_data.py
@Author : Qintsg
@Date : 2026-08-24
'''

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from mefkt_data_core import PREPROCESS_VERSION, PreparedDataset, SPLITS
from mefkt_lite_data import (
    _append_user_sequences,
    _normalize_features,
    _parse_response_time,
    _save_prepared,
    _safe_float,
    _split_for_user,
    SplitBuffer,
)


def _parse_timestamp(value: object) -> float:
    """
    将 canonical 时间字段解析为 Unix 秒。

    :param value: 秒、毫秒或 ISO-8601 时间。
    :returns: Unix 秒；缺失值返回 0。
    """
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        numeric = float(text)
        return numeric / 1000.0 if numeric > 10_000_000_000 else numeric
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0


def _split_tokens(value: object) -> list[str]:
    """兼容分号、逗号和空格分隔的知识点字段。"""
    text = str(value or "").replace(",", ";").replace(" ", ";")
    return [token.strip() for token in text.split(";") if token.strip()]


def _parse_correct(row: dict[str, str]) -> int:
    """解析 canonical 正确性或答案字段。"""
    value = str(row.get("correct", "")).strip().lower()
    if value in {"1", "true", "yes", "correct", "right"}:
        return 1
    if value in {"0", "false", "no", "incorrect", "wrong"}:
        return 0
    answer = str(row.get("user_answer", "")).strip().lower()
    expected = str(row.get("correct_answer", "")).strip().lower()
    return int(bool(answer) and answer == expected)


def prepare_canonical_csv(
    root: Path,
    events_file: Path,
    *,
    max_users: int,
    max_interactions: int,
    max_length: int,
    min_length: int,
    context_length: int,
    force: bool,
) -> PreparedDataset:
    """
    从按 user_id、timestamp 排序的 canonical CSV 构建通用训练缓存。

    必需字段：`user_id,item_id,timestamp,correct,response_time_seconds,subject_id,skill_ids`。
    `correct` 可以替换为 `user_answer,correct_answer`。

    :param root: 预处理缓存根目录。
    :param events_file: canonical CSV 文件。
    :param max_users: 最大学习者数，0 为全量。
    :param max_interactions: 最大交互数，0 为全量。
    :param max_length: 窗口最大长度。
    :param min_length: 最短序列长度。
    :param context_length: 窗口重叠上下文长度。
    :param force: 是否强制重建。
    :returns: 可直接训练的数据集描述。
    """
    events_file = events_file.resolve()
    if not events_file.is_file():
        raise FileNotFoundError(f"找不到 canonical CSV: {events_file}")
    cache_root = root.resolve() / "processed"
    expected = {
        "dataset": "canonical-csv",
        "preprocess_version": PREPROCESS_VERSION,
        "source_file": events_file.name,
        "source_size": events_file.stat().st_size,
        "max_users": max_users,
        "max_interactions": max_interactions,
        "max_sequence_length": max_length,
        "min_sequence_length": min_length,
        "window_context_length": context_length,
    }
    if not force and (cache_root / "manifest.json").exists():
        metadata = json.loads((cache_root / "manifest.json").read_text(encoding="utf-8"))
        if all(metadata.get(key) == value for key, value in expected.items()):
            from mefkt_lite_data import _load_prepared

            cached = _load_prepared(cache_root, expected)
            if cached is not None:
                return cached
    if force and cache_root.exists():
        import shutil

        shutil.rmtree(cache_root)

    item_rows: dict[str, dict[str, str]] = {}
    with events_file.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            item_id = str(row.get("item_id", "")).strip()
            if item_id:
                item_rows.setdefault(item_id, row)
    if not item_rows:
        raise RuntimeError("canonical CSV 中没有有效 item_id")
    item_ids = tuple(sorted(item_rows))
    item_to_index = {item_id: index for index, item_id in enumerate(item_ids)}
    subject_values = tuple(sorted({str(row.get("subject_id") or "unknown").strip() for row in item_rows.values()}))
    subject_to_index = {value: index for index, value in enumerate(subject_values)}
    skill_values = tuple(sorted({token for row in item_rows.values() for token in _split_tokens(row.get("skill_ids"))}))
    skill_to_index = {value: index for index, value in enumerate(skill_values)}
    max_skills = min(max(max((len(_split_tokens(row.get("skill_ids"))) for row in item_rows.values()), default=1), 1), 8)
    item_subjects = np.asarray(
        [subject_to_index[str(item_rows[item_id].get("subject_id") or "unknown").strip()] for item_id in item_ids],
        dtype=np.int64,
    )
    item_skills = np.full((len(item_ids), max_skills), -1, dtype=np.int64)
    raw = np.zeros((len(item_ids), 4), dtype=np.float32)
    for item_id, index in item_to_index.items():
        row = item_rows[item_id]
        tags = _split_tokens(row.get("skill_ids"))
        raw[index, 0] = _safe_float(row.get("part"), 0.0)
        raw[index, 1] = len(tags)
        raw[index, 2] = _safe_float(row.get("deployed_at"), 0.0)
        raw[index, 3] = len(str(row.get("bundle_id", "")))
        for skill_index, tag in enumerate(tags[:max_skills]):
            item_skills[index, skill_index] = skill_to_index[tag]

    buffers = {split: SplitBuffer.create() for split in SPLITS}
    attempts = np.zeros(len(item_ids), dtype=np.float32)
    correct_counts = np.zeros(len(item_ids), dtype=np.float32)
    gap_elapsed = np.zeros(len(item_ids), dtype=np.float32)
    response_elapsed = np.zeros(len(item_ids), dtype=np.float32)
    current_user: str | None = None
    previous_timestamp = 0.0
    items: list[int] = []
    correct: list[int] = []
    gaps: list[float] = []
    response_times: list[float] = []
    selected_users = 0
    selected_interactions = 0

    def flush_user() -> None:
        """写入当前学习者序列并更新训练集统计。"""
        nonlocal selected_users, selected_interactions
        if current_user is None or len(items) < min_length:
            return
        split = _split_for_user(current_user)
        _append_user_sequences(
            buffers,
            split,
            items,
            correct,
            gaps,
            response_times,
            max_length,
            min_length,
            context_length,
        )
        selected_users += 1
        selected_interactions += len(items)
        if split == "train":
            for item, flag, gap, response_time in zip(items, correct, gaps, response_times, strict=True):
                attempts[item] += 1.0
                correct_counts[item] += flag
                gap_elapsed[item] += gap
                response_elapsed[item] += response_time

    with events_file.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            user_id = str(row.get("user_id", "")).strip()
            item_id = str(row.get("item_id", "")).strip()
            if not user_id or item_id not in item_to_index:
                continue
            if current_user is None:
                current_user = user_id
            if user_id != current_user:
                flush_user()
                if max_users and selected_users >= max_users:
                    break
                current_user = user_id
                items, correct, gaps, response_times = [], [], [], []
                previous_timestamp = 0.0
            timestamp = _parse_timestamp(row.get("timestamp"))
            gap = 1.0 if previous_timestamp <= 0 else max((timestamp - previous_timestamp) / 3600.0, 1.0 / 3600.0)
            items.append(item_to_index[item_id])
            correct.append(_parse_correct(row))
            gaps.append(min(gap, 24.0 * 365.0))
            response_times.append(_parse_response_time(row.get("response_time_seconds", row.get("elapsed_time", 10))))
            previous_timestamp = timestamp
            if max_interactions and selected_interactions + len(items) >= max_interactions:
                break
        flush_user()
    if len(buffers["train"]) == 0:
        raise RuntimeError("canonical CSV 预处理后没有训练序列")
    features = _normalize_features(raw, attempts, correct_counts, gap_elapsed, response_elapsed)
    metadata = {
        **expected,
        "selected_users": selected_users,
        "selected_interactions": selected_interactions,
        "split_strategy": "stable_user_hash_80_10_10",
        "source": str(events_file),
    }
    return _save_prepared(
        cache_root,
        features,
        buffers,
        metadata,
        item_ids,
        item_subjects,
        item_skills,
        subject_values,
        skill_values,
        context_length,
    )


__all__ = ["prepare_canonical_csv"]
