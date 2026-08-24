#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT-Lite 公开数据下载、预处理和序列存储模块。
@Project : adaptive-edu
@File : mefkt_lite_data.py
@Author : Qintsg
'''

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import random
import shutil
import urllib.request
import zipfile
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import numpy as np
import torch
from mefkt_data_core import (
    PREPROCESS_VERSION,
    SPLITS,
    PreparedDataset,
    QuestionMetadata,
    SequenceIndexDataset,
    SequenceStore,
    SplitBuffer,
    collate_sequence_indices,
)
from mefkt_open_world import (
    append_content_features,
    content_embeddings_metadata,
    load_content_embeddings,
)

LOGGER = logging.getLogger("mefkt_lite.data")
EDNET_KT1_URL = (
    "https://drive.usercontent.google.com/download?"
    "id=1AmGcOs5U31wIIqvthn9ARqJMrMTFTcaw&export=download&confirm=t"
)
EDNET_CONTENT_URL = (
    "https://drive.usercontent.google.com/download?"
    "id=117aYJAWG3GU48suS66NPaB82HwFj6xWS&export=download&confirm=t"
)
def _download_file(url: str, destination: Path) -> None:
    """
    断点下载公开数据文件。

    :param url: 下载地址。
    :param destination: 目标文件。
    :returns: None。
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        LOGGER.info("复用已下载文件: %s", destination)
        return
    partial = destination.with_suffix(destination.suffix + ".part")
    downloaded = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "AdaptiveEdu-MEFKT/2.0"}
    if downloaded:
        headers["Range"] = f"bytes={downloaded}-"
    request = urllib.request.Request(url, headers=headers)
    LOGGER.info("开始下载: url=%s destination=%s resume=%d", url, destination, downloaded)
    with urllib.request.urlopen(request, timeout=120) as response:
        accepts_range = getattr(response, "status", 200) == 206
        mode = "ab" if downloaded and accepts_range else "wb"
        with partial.open(mode) as handle:
            while True:
                block = response.read(16 * 1024 * 1024)
                if not block:
                    break
                handle.write(block)
    os.replace(partial, destination)
    LOGGER.info("下载完成: bytes=%d path=%s", destination.stat().st_size, destination)


def _extract_zip(zip_path: Path, target: Path) -> None:
    """
    安全解压公开数据压缩包。

    :param zip_path: 输入 ZIP 文件。
    :param target: 解压目标目录。
    :returns: None。
    """
    marker = target / ".extracted"
    if marker.exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        root = target.resolve()
        for member in archive.infolist():
            member_path = (target / member.filename).resolve()
            if root not in member_path.parents and member_path != root:
                raise ValueError(f"压缩包包含越界路径: {member.filename}")
        archive.extractall(target)
    marker.write_text("ok\n", encoding="utf-8")


def _first_file(root: Path, name: str) -> Path:
    """
    在数据根目录下定位指定文件。

    :param root: 搜索根目录。
    :param name: 目标文件名。
    :returns: 第一个匹配文件。
    """
    matches = sorted(root.rglob(name))
    if not matches:
        raise FileNotFoundError(f"找不到数据文件: root={root} name={name}")
    return matches[0]


def _safe_float(value: object, default: float = 0.0) -> float:
    """
    安全解析数值字段。

    :param value: 原始值。
    :param default: 解析失败时的默认值。
    :returns: 浮点数。
    """
    try:
        return float(str(value or "").strip())
    except (TypeError, ValueError):
        return default


def _question_metadata(content_root: Path) -> QuestionMetadata:
    """
    读取 EdNet 题目答案和多视角静态属性。

    :param content_root: EdNet Contents 解压目录。
    :returns: 题目索引、正确答案、数值属性、学科和知识点信息。
    """
    question_file = _first_file(content_root, "questions.csv")
    rows: list[dict[str, str]] = []
    with question_file.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            question_id = str(row.get("question_id", "")).strip()
            if question_id:
                rows.append(row)
    rows.sort(key=lambda row: row["question_id"])
    item_to_index = {row["question_id"]: index for index, row in enumerate(rows)}
    answers = {row["question_id"]: str(row.get("correct_answer", "")).strip().lower() for row in rows}
    subject_values = [
        str(row.get("subject_id") or row.get("subject") or row.get("part") or "unknown").strip()
        for row in rows
    ]
    subject_vocab = tuple(sorted(set(subject_values)))
    subject_to_index = {value: index for index, value in enumerate(subject_vocab)}
    tag_values = {
        tag.strip()
        for row in rows
        for tag in str(row.get("tags") or row.get("skill_ids") or "").split(";")
        if tag.strip()
    }
    skill_vocab = tuple(sorted(tag_values))
    skill_to_index = {value: index for index, value in enumerate(skill_vocab)}
    max_skills = max((len(str(row.get("tags") or row.get("skill_ids") or "").split(";")) for row in rows), default=1)
    max_skills = min(max(max_skills, 1), 8)
    item_subjects = np.asarray([subject_to_index[value] for value in subject_values], dtype=np.int64)
    item_skills = np.full((len(rows), max_skills), -1, dtype=np.int64)
    raw = np.zeros((len(rows), 4), dtype=np.float32)
    for index, row in enumerate(rows):
        raw[index, 0] = _safe_float(row.get("part", 0))
        tags = [tag.strip() for tag in str(row.get("tags") or row.get("skill_ids") or "").split(";") if tag.strip()]
        raw[index, 1] = float(len(tags))
        for skill_index, tag in enumerate(tags[:max_skills]):
            item_skills[index, skill_index] = skill_to_index[tag]
        raw[index, 2] = _parse_deployed_at(row.get("deployed_at", ""))
        raw[index, 3] = float(len(str(row.get("bundle_id", ""))))
    return QuestionMetadata(item_to_index, answers, raw, item_subjects, item_skills, subject_vocab, skill_vocab)


def _parse_deployed_at(value: object) -> float:
    """
    将 EdNet 题目发布时间兼容解析为 Unix 秒。

    :param value: CSV 中的数字时间戳或 ISO-8601 日期字符串。
    :returns: 可用于归一化的非负时间数值。
    """
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return max(float(text), 0.0)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return 0.0
        return max(parsed.timestamp(), 0.0)


def _parse_response_time(value: object) -> float:
    """
    将 EdNet 的答题耗时统一转换为秒。

    :param value: 原始 elapsed_time 或 response_time 字段。
    :returns: 经过截断的答题耗时，范围为 0.1 到 3600 秒。
    """
    numeric = _safe_float(value, 10.0)
    if numeric <= 0:
        return 10.0
    # EdNet 常见格式使用毫秒；小数值格式则按秒兼容处理。
    seconds = numeric / 1000.0 if numeric > 3600.0 else numeric
    return float(min(max(seconds, 0.1), 3600.0))


def _split_for_user(user_id: str) -> str:
    """
    按照稳定 hash 进行学习者级切分。

    :param user_id: 学习者 ID。
    :returns: train、validation 或 test。
    """
    digest = hashlib.blake2b(user_id.encode("utf-8"), digest_size=2).digest()
    bucket = int.from_bytes(digest, "big") % 10
    return "train" if bucket < 8 else "validation" if bucket == 8 else "test"


def _normalize_features(
    raw: np.ndarray,
    attempts: np.ndarray,
    correct: np.ndarray,
    gap_elapsed: np.ndarray,
    response_elapsed: np.ndarray,
) -> np.ndarray:
    """
    用训练集统计构造不泄漏的题目多视角属性。

    :param raw: 题目静态原始特征。
    :param attempts: 训练切分作答次数。
    :param correct: 训练切分答对次数。
    :param gap_elapsed: 训练切分累计时间间隔。
    :param response_elapsed: 训练切分累计答题耗时。
    :returns: 归一化后的七维题目特征。
    """
    train_attempts = np.maximum(attempts, 1.0)
    observed_difficulty = 1.0 - correct / train_attempts
    difficulty = np.where(attempts > 0, observed_difficulty, 0.5)
    mean_gap = np.log1p(gap_elapsed / train_attempts)
    mean_response = np.log1p(response_elapsed / train_attempts)
    frequency = np.log1p(attempts)
    part = raw[:, 0] / 7.0
    tag_count = np.minimum(raw[:, 1], 8.0) / 8.0
    deployed = raw[:, 2]
    positive_deployed = deployed[deployed > 0]
    deployed_baseline = float(positive_deployed.min()) if positive_deployed.size else 0.0
    deployed = np.log1p(np.maximum(deployed - deployed_baseline, 0.0))
    features = np.stack([difficulty, mean_gap, mean_response, frequency, part, tag_count, deployed], axis=1).astype(np.float32)
    lower = features.min(axis=0)
    upper = features.max(axis=0)
    return ((features - lower) / np.maximum(upper - lower, 1e-6)).astype(np.float32)


def _append_user_sequences(
    buffers: dict[str, SplitBuffer],
    split: str,
    items: list[int],
    correct: list[int],
    gaps: list[float],
    response_times: list[float],
    max_length: int,
    min_length: int,
    context_length: int,
) -> None:
    """
    将学习者序列切成带重叠历史上下文的模型窗口。

    :param buffers: 各数据切分的输出缓冲区。
    :param split: 当前用户所属切分。
    :param items: 题目索引序列。
    :param correct: 正确性序列。
    :param gaps: 时间间隔序列。
    :param response_times: 答题耗时序列。
    :param max_length: 单窗口最大长度。
    :param min_length: 最短有效窗口长度。
    :param context_length: 相邻窗口重叠历史长度。
    :returns: None。
    """
    context_length = min(max(context_length, 0), max_length - 1)
    stride = max(max_length - context_length, 1)
    target_starts = [0]
    target_starts.extend(range(max_length, len(items), stride))
    for target_start in target_starts:
        context_start = max(target_start - context_length, 0)
        target_length = max_length if target_start == 0 else stride
        end = min(target_start + target_length, len(items))
        if end - target_start < 2:
            break
        if end - context_start >= min_length:
            buffers[split].append(
                items[context_start:end],
                correct[context_start:end],
                gaps[context_start:end],
                response_times[context_start:end],
                target_start - context_start,
            )
        if end >= len(items):
            break


def _write_buffer(root: Path, split: str, buffer: SplitBuffer) -> None:
    """
    将内存缓冲区写为 mmap 友好的 numpy 文件。

    :param root: 输出目录。
    :param split: 数据切分名称。
    :param buffer: 待写出的序列缓冲区。
    :returns: None。
    """
    np.save(root / f"{split}_items.npy", np.frombuffer(buffer.items, dtype=np.int32))
    np.save(root / f"{split}_correct.npy", np.frombuffer(buffer.correct, dtype=np.uint8))
    np.save(root / f"{split}_gaps.npy", np.frombuffer(buffer.gaps, dtype=np.float32))
    np.save(root / f"{split}_response_times.npy", np.frombuffer(buffer.response_times, dtype=np.float32))
    np.save(root / f"{split}_offsets.npy", np.frombuffer(buffer.offsets, dtype=np.int64))
    np.save(root / f"{split}_target_starts.npy", np.frombuffer(buffer.target_starts, dtype=np.int32))


def _save_prepared(
    root: Path,
    features: np.ndarray,
    buffers: dict[str, SplitBuffer],
    metadata: dict[str, object],
    item_ids: Iterable[str],
    item_subjects: np.ndarray,
    item_skills: np.ndarray,
    subject_vocab: Iterable[str],
    skill_vocab: Iterable[str],
    context_length: int,
) -> PreparedDataset:
    """
    持久化预处理数据并返回描述。

    :param root: 预处理输出目录。
    :param features: 题目特征矩阵。
    :param buffers: 各切分序列缓冲区。
    :param metadata: 数据来源和预处理元数据。
    :param item_ids: 题目词表。
    :param item_subjects: 每道题的学科索引。
    :param item_skills: 每道题的知识点索引。
    :param subject_vocab: 学科词表。
    :param skill_vocab: 知识点词表。
    :param context_length: 窗口重叠上下文长度。
    :returns: 可供训练器加载的数据集描述。
    """
    root.mkdir(parents=True, exist_ok=True)
    np.save(root / "item_features.npy", features)
    for split, buffer in buffers.items():
        _write_buffer(root, split, buffer)
    item_ids = tuple(str(item_id) for item_id in item_ids)
    subject_vocab = tuple(str(value) for value in subject_vocab)
    skill_vocab = tuple(str(value) for value in skill_vocab)
    if len(item_ids) != features.shape[0]:
        raise ValueError("题目词表长度与题目特征数量不一致")
    if item_subjects.shape != (features.shape[0],):
        raise ValueError("题目学科索引形状错误")
    if item_skills.shape[0] != features.shape[0]:
        raise ValueError("题目知识点索引数量错误")
    np.save(root / "item_subjects.npy", item_subjects.astype(np.int64, copy=False))
    np.save(root / "item_skills.npy", item_skills.astype(np.int64, copy=False))
    (root / "item_vocab.json").write_text(json.dumps(item_ids, ensure_ascii=False), encoding="utf-8")
    (root / "subject_vocab.json").write_text(json.dumps(subject_vocab, ensure_ascii=False), encoding="utf-8")
    (root / "skill_vocab.json").write_text(json.dumps(skill_vocab, ensure_ascii=False), encoding="utf-8")
    metadata = {
        **metadata,
        "preprocess_version": PREPROCESS_VERSION,
        "item_count": int(features.shape[0]),
        "feature_dim": int(features.shape[1]),
        "item_vocab_file": "item_vocab.json",
        "feature_names": [
            "difficulty",
            "mean_gap",
            "mean_response_time",
            "frequency",
            "part",
            "tag_count",
            "deployed_at",
            *[f"content_embedding_{index:03d}" for index in range(max(features.shape[1] - 7, 0))],
        ],
        "content_embedding_dim": max(int(features.shape[1]) - 7, 0),
        "subject_count": len(subject_vocab),
        "skill_count": len(skill_vocab),
        "max_item_skills": int(item_skills.shape[1]),
        "window_context_length": context_length,
    }
    (root / "manifest.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return PreparedDataset(
        root,
        features.shape[0],
        features.shape[1],
        torch.from_numpy(features),
        {split: len(buffers[split]) for split in SPLITS},
        metadata,
        item_ids,
        torch.from_numpy(item_subjects.astype(np.int64, copy=True)),
        torch.from_numpy(item_skills.astype(np.int64, copy=True)),
        subject_vocab,
        skill_vocab,
    )


def _load_prepared(root: Path, expected_metadata: dict[str, object] | None = None) -> PreparedDataset | None:
    """
    读取已经存在且配置匹配的预处理缓存。

    :param root: 预处理缓存目录。
    :param expected_metadata: 必须与 manifest 相等的配置字段。
    :returns: 匹配时返回数据集描述，否则返回 None。
    """
    manifest = root / "manifest.json"
    if not manifest.exists():
        return None
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    if expected_metadata and any(metadata.get(key) != value for key, value in expected_metadata.items()):
        LOGGER.info("预处理缓存配置不匹配，将重建: root=%s", root)
        return None
    features = np.load(root / "item_features.npy", mmap_mode="r")
    sizes = {split: len(SequenceStore(root, split)) for split in SPLITS}
    vocab_path = root / str(metadata.get("item_vocab_file", "item_vocab.json"))
    if vocab_path.exists():
        item_ids = tuple(str(item_id) for item_id in json.loads(vocab_path.read_text(encoding="utf-8")))
    else:
        item_ids = tuple(str(index) for index in range(int(features.shape[0])))
    if len(item_ids) != int(features.shape[0]):
        raise ValueError(f"题目词表长度错误: path={vocab_path}")
    item_subjects = np.load(root / "item_subjects.npy", mmap_mode="r")
    item_skills = np.load(root / "item_skills.npy", mmap_mode="r")
    subject_vocab = tuple(str(value) for value in json.loads((root / "subject_vocab.json").read_text(encoding="utf-8")))
    skill_vocab = tuple(str(value) for value in json.loads((root / "skill_vocab.json").read_text(encoding="utf-8")))
    feature_array = np.asarray(features).copy()
    return PreparedDataset(
        root,
        int(feature_array.shape[0]),
        int(feature_array.shape[1]),
        torch.from_numpy(feature_array),
        sizes,
        metadata,
        item_ids,
        torch.from_numpy(np.asarray(item_subjects).copy()),
        torch.from_numpy(np.asarray(item_skills).copy()),
        subject_vocab,
        skill_vocab,
    )


def prepare_synthetic(
    root: Path,
    users: int,
    items: int,
    sequence_length: int,
    seed: int,
    context_length: int = 0,
    max_length: int | None = None,
    min_length: int = 2,
) -> PreparedDataset:
    """
    生成本机 smoke test 使用的可重复数据。

    :param root: 输出数据目录。
    :param users: 模拟学习者数。
    :param items: 模拟题目数。
    :param sequence_length: 每名学习者交互长度。
    :param seed: 随机种子。
    :param context_length: 相邻窗口重叠历史长度。
    :param max_length: 单窗口最大长度。
    :param min_length: 最短有效窗口长度。
    :returns: 可供训练器加载的数据集描述。
    """
    max_length = max_length or sequence_length
    expected = {
        "dataset": "synthetic",
        "preprocess_version": PREPROCESS_VERSION,
        "seed": seed,
        "users": users,
        "items": items,
        "sequence_length": sequence_length,
        "max_sequence_length": max_length,
        "min_sequence_length": min_length,
        "window_context_length": context_length,
    }
    cached = _load_prepared(root, expected)
    if cached is not None:
        return cached
    rng = random.Random(seed)
    buffers = {split: SplitBuffer.create() for split in SPLITS}
    attempts = np.zeros(items, dtype=np.float32)
    correct_count = np.zeros(items, dtype=np.float32)
    gap_elapsed = np.zeros(items, dtype=np.float32)
    response_elapsed = np.zeros(items, dtype=np.float32)
    item_subjects = np.asarray([index % 4 for index in range(items)], dtype=np.int64)
    item_skills = np.asarray([[index % 8, (index * 3) % 8] for index in range(items)], dtype=np.int64)
    for user in range(users):
        split = "train" if user % 10 < 8 else "validation" if user % 10 == 8 else "test"
        user_items = [rng.randrange(items) for _ in range(sequence_length)]
        user_correct = [1 if rng.random() < 0.55 + (user % 5) * 0.03 - item / max(items, 1) * 0.08 else 0 for item in user_items]
        gaps = [1.0 if index == 0 else float(1 + rng.randrange(72)) for index in range(sequence_length)]
        response_times = [float(5 + rng.randrange(120)) for _ in range(sequence_length)]
        _append_user_sequences(
            buffers,
            split,
            user_items,
            user_correct,
            gaps,
            response_times,
            max_length,
            min_length,
            context_length,
        )
        if split == "train":
            for item, flag, gap, response_time in zip(user_items, user_correct, gaps, response_times, strict=True):
                attempts[item] += 1
                correct_count[item] += flag
                gap_elapsed[item] += gap
                response_elapsed[item] += response_time
    raw = np.stack([np.zeros(items), np.zeros(items), np.zeros(items), np.ones(items)], axis=1).astype(np.float32)
    features = _normalize_features(raw, attempts, correct_count, gap_elapsed, response_elapsed)
    return _save_prepared(
        root,
        features,
        buffers,
        expected,
        (str(index) for index in range(items)),
        item_subjects,
        item_skills,
        (str(index) for index in range(4)),
        (str(index) for index in range(8)),
        context_length,
    )


def prepare_ednet(
    root: Path,
    *,
    max_users: int,
    max_interactions: int,
    max_length: int,
    min_length: int,
    context_length: int,
    force: bool,
    content_embeddings_file: Path | None = None,
    kt1_url: str = EDNET_KT1_URL,
    content_url: str = EDNET_CONTENT_URL,
) -> PreparedDataset:
    """
    下载并构建 EdNet-KT1 学习者级切分缓存。

    :param root: 数据缓存根目录。
    :param max_users: 最大学习者数，0 表示全量。
    :param max_interactions: 最大交互数，0 表示全量。
    :param max_length: 序列窗口长度。
    :param min_length: 最短序列长度。
    :param force: 是否重建缓存。
    :returns: 预处理数据集描述。
    """
    root = root.resolve()
    cache_root = root / "processed"
    content_metadata = content_embeddings_metadata(content_embeddings_file)
    expected_metadata = {
        "dataset": "ednet-kt1",
        "preprocess_version": PREPROCESS_VERSION,
        "max_users": max_users,
        "max_interactions": max_interactions,
        "max_sequence_length": max_length,
        "min_sequence_length": min_length,
        "window_context_length": context_length,
        **content_metadata,
    }
    if not force:
        cached = _load_prepared(cache_root, expected_metadata)
        if cached is not None:
            return cached
    if force and cache_root.exists():
        shutil.rmtree(cache_root)
    kt_zip = root / "EdNet-KT1.zip"
    content_zip = root / "EdNet-Contents.zip"
    _download_file(kt1_url, kt_zip)
    _download_file(content_url, content_zip)
    _extract_zip(kt_zip, root / "kt1")
    _extract_zip(content_zip, root / "contents")
    question_metadata = _question_metadata(root / "contents")
    item_to_index = question_metadata.item_to_index
    answers = question_metadata.answers
    raw = question_metadata.raw_features
    item_ids = tuple(item_id for item_id, _ in sorted(item_to_index.items(), key=lambda pair: pair[1]))
    buffers = {split: SplitBuffer.create() for split in SPLITS}
    attempts = np.zeros(len(item_to_index), dtype=np.float32)
    correct_count = np.zeros(len(item_to_index), dtype=np.float32)
    gap_elapsed = np.zeros(len(item_to_index), dtype=np.float32)
    response_elapsed = np.zeros(len(item_to_index), dtype=np.float32)
    user_files = sorted(path for path in (root / "kt1").rglob("u*.csv") if path.is_file())
    selected_users = 0
    selected_interactions = 0
    for user_file in user_files:
        if max_users and selected_users >= max_users:
            break
        split = _split_for_user(user_file.stem)
        items: list[int] = []
        correct: list[int] = []
        gaps: list[float] = []
        response_times: list[float] = []
        previous_timestamp: int | None = None
        with user_file.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                question_id = str(row.get("question_id", "")).strip()
                answer = str(row.get("user_answer", "")).strip().lower()
                if question_id not in item_to_index or answer not in {"a", "b", "c", "d"}:
                    continue
                item = item_to_index[question_id]
                timestamp = int(float(row.get("timestamp", 0) or 0))
                if previous_timestamp is None:
                    gap_hours = 1.0
                else:
                    gap_hours = max((timestamp - previous_timestamp) / 3_600_000.0, 1.0 / 3600.0)
                flag = int(answer == answers.get(question_id, ""))
                response_time = _parse_response_time(row.get("elapsed_time", row.get("response_time", 0)))
                items.append(item)
                correct.append(flag)
                gaps.append(min(gap_hours, 24.0 * 365.0))
                response_times.append(response_time)
                previous_timestamp = timestamp
        if len(items) < min_length:
            continue
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
                correct_count[item] += flag
                gap_elapsed[item] += gap
                response_elapsed[item] += response_time
        if max_interactions and selected_interactions >= max_interactions:
            break
        if selected_users % 10_000 == 0:
            LOGGER.info("预处理进度: users=%d interactions=%d", selected_users, selected_interactions)
    if not buffers["train"].offsets or len(buffers["train"]) < 1:
        raise RuntimeError("EdNet 预处理后没有训练序列，请检查下载文件和参数")
    features = _normalize_features(raw, attempts, correct_count, gap_elapsed, response_elapsed)
    if content_embeddings_file is not None:
        content_features = load_content_embeddings(content_embeddings_file, item_ids)
        features = append_content_features(features, content_features)
    metadata = {
        **expected_metadata,
        "license": "CC BY-NC 4.0",
        "selected_users": selected_users,
        "selected_interactions": selected_interactions,
        "split_strategy": "stable_user_hash_80_10_10",
        "source": "https://github.com/riiid/ednet",
    }
    return _save_prepared(
        cache_root,
        features,
        buffers,
        metadata,
        item_ids,
        question_metadata.item_subjects,
        question_metadata.item_skills,
        question_metadata.subject_vocab,
        question_metadata.skill_vocab,
        context_length,
    )


__all__ = [
    "EDNET_CONTENT_URL",
    "EDNET_KT1_URL",
    "PreparedDataset",
    "SequenceIndexDataset",
    "SequenceStore",
    "collate_sequence_indices",
    "prepare_ednet",
    "prepare_synthetic",
]
