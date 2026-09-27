#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT-NG canonical 数据校验、分组与可追溯缓存。
@Project : adaptive-edu
@File : data.py
@Author : Qintsg
@Date : 2026-09-24
'''

from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import Tensor
from torch.utils.data import Dataset

from mefkt_ng import SCHEMA_VERSION

SPLITS = ("train", "validation", "test")
ARRAY_FIELDS = ("items", "correct", "gaps", "time_known", "source_rows", "episodes")


def sha256_file(path: Path) -> str:
    """计算源文件摘要。

    :param path: 文件路径。
    :returns: SHA-256 十六进制字符串。
    :raises FileNotFoundError: 文件不存在。
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _split_user(user_id: str) -> str:
    """按稳定用户哈希分配切分。

    :param user_id: 源用户 ID。
    :returns: train、validation 或 test。
    """
    bucket = int.from_bytes(hashlib.sha256(user_id.encode("utf-8")).digest()[:8], "big") % 10
    return "train" if bucket < 8 else "validation" if bucket == 8 else "test"


def _parse_time(value: object) -> float | None:
    """解析时间并保留缺失状态。

    :param value: Unix 秒、毫秒或 ISO-8601。
    :returns: Unix 秒；缺失或无效时返回 None。
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        numeric = float(raw)
        return numeric / 1000.0 if numeric > 10_000_000_000 else numeric
    except ValueError:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).timestamp()
        except ValueError:
            return None


def _parse_correct(row: dict[str, str]) -> int | None:
    """只接受明确的二元结果。

    :param row: CSV 事件行。
    :returns: 0/1；未评分时返回 None。
    """
    value = str(row.get("correct") or "").strip().lower()
    if value in {"1", "true", "yes", "correct", "right"}:
        return 1
    if value in {"0", "false", "no", "incorrect", "wrong"}:
        return 0
    answer = str(row.get("user_answer") or "").strip()
    expected = str(row.get("correct_answer") or "").strip()
    return int(answer == expected) if answer and expected else None


def _skill_tokens(value: object) -> tuple[str, ...]:
    """解析并去重知识点 ID。

    :param value: 多知识点字符串。
    :returns: 有序且唯一的 ID 元组。
    """
    raw = str(value or "").replace(",", ";").replace(" ", ";")
    return tuple(dict.fromkeys(part.strip() for part in raw.split(";") if part.strip()))


def _difficulty(value: object) -> tuple[float, float]:
    """编码教师难度及其是否存在。

    :param value: 题目难度字段。
    :returns: 难度先验和存在掩码。
    """
    raw = str(value or "").strip().lower()
    labels = {"easy": -1.0, "medium": 0.0, "hard": 1.0, "简单": -1.0, "中等": 0.0, "困难": 1.0}
    if raw in labels:
        return labels[raw], 1.0
    try:
        return float(np.clip(float(raw), -3.0, 3.0)), 1.0
    except ValueError:
        return 0.0, 0.0


def _save_array(path: Path, values: np.ndarray) -> None:
    """原子写入 numpy 数组。

    :param path: 目标文件。
    :param values: 数组内容。
    :returns: None。
    """
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        np.save(handle, values, allow_pickle=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


@dataclass(frozen=True)
class PreparedData:
    """可直接加载的训练数据描述。"""

    root: Path
    manifest: dict[str, Any]


class _SplitBuilder:
    """累计带重叠上下文的事件窗口。"""

    def __init__(self) -> None:
        """初始化切分数组。

        :returns: None。
        """
        self.values: dict[str, list[int | float]] = {name: [] for name in ARRAY_FIELDS}
        self.offsets = [0]
        self.target_starts: list[int] = []

    def add_user(self, events: list[tuple[int, int, float, int, int, int]], length: int, context: int) -> None:
        """完整覆盖用户事件，窗口只在测验边界截断。

        :param events: 同一用户的事件序列。
        :param length: 最大窗口长度。
        :param context: 仅恢复状态、不计入目标的历史长度。
        :returns: None。
        :raises ValueError: 单场测验长度超出窗口容量。
        """
        start, previous_end = 0, 0
        while start < len(events):
            end = min(start + length, len(events))
            if end < len(events):
                while end > previous_end and events[end][5] == events[end - 1][5]:
                    end -= 1
            if end <= previous_end and start < previous_end:
                start = previous_end
                end = min(start + length, len(events))
                if end < len(events):
                    while end > previous_end and events[end][5] == events[end - 1][5]:
                        end -= 1
            if end <= previous_end:
                raise ValueError("单场测验超过 sequence-length 可用目标容量；请增大窗口")
            target_start = previous_end - start
            for event in events[start:end]:
                for key, value in zip(ARRAY_FIELDS, event, strict=True):
                    self.values[key].append(value)
            self.offsets.append(len(self.values["items"]))
            self.target_starts.append(target_start)
            if end == len(events):
                break
            previous_end = end
            start = max(0, end - context)
            while start > 0 and events[start][5] == events[start - 1][5]:
                start -= 1
            if end - start >= length:
                start = end

    def save(self, root: Path, split: str) -> dict[str, int]:
        """保存本切分数组。

        :param root: 输出目录。
        :param split: 切分名称。
        :returns: 窗口与目标事件数。
        """
        dtypes = {"items": np.int32, "correct": np.uint8, "gaps": np.float32,
                  "time_known": np.uint8, "source_rows": np.int64, "episodes": np.int64}
        for name in ARRAY_FIELDS:
            _save_array(root / f"{split}_{name}.npy", np.asarray(self.values[name], dtype=dtypes[name]))
        _save_array(root / f"{split}_offsets.npy", np.asarray(self.offsets, dtype=np.int64))
        _save_array(root / f"{split}_target_starts.npy", np.asarray(self.target_starts, dtype=np.int32))
        targets = sum(self.offsets[index + 1] - self.offsets[index] - offset
                      for index, offset in enumerate(self.target_starts))
        return {"windows": len(self.target_starts), "target_events": int(targets)}


def _load_content(path: Path, item_ids: list[str]) -> tuple[np.ndarray, dict[str, Any]]:
    """读取并严格检查冻结题目向量。

    :param path: 项目现有 NPZ sidecar。
    :param item_ids: 数据集题目 ID。
    :returns: 按目录对齐的 384 维向量和覆盖摘要。
    :raises ValueError: 维度或内容覆盖不足。
    """
    with np.load(path, allow_pickle=False) as archive:
        source_ids = [str(value) for value in archive["item_ids"].tolist()]
        vectors = np.asarray(archive["embeddings"], dtype=np.float32)
        model_name = str(archive["model_name"].item()) if "model_name" in archive else "unknown"
    if vectors.ndim != 2 or vectors.shape != (len(source_ids), 384):
        raise ValueError("内容向量 sidecar 必须包含 [N,384] embeddings")
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("内容向量 sidecar 中存在重复 item_id")
    lookup = {item_id: index for index, item_id in enumerate(source_ids)}
    result = np.zeros((len(item_ids), 384), dtype=np.float32)
    present = 0
    for index, item_id in enumerate(item_ids):
        source_index = lookup.get(item_id)
        if source_index is None:
            continue
        vector = vectors[source_index]
        if np.isfinite(vector).all() and np.linalg.norm(vector) > 1e-8:
            result[index] = vector
            present += 1
    if present < len(item_ids):
        raise ValueError(f"缺少有效内容向量: {len(item_ids) - present}/{len(item_ids)}；请重新生成 sidecar")
    return result, {"model": model_name, "items": len(item_ids), "coverage": 1.0}


def prepare_data(
    events_file: Path, content_file: Path, root: Path, length: int, context: int,
    graph_file: Path | None = None,
) -> PreparedData:
    """从 canonical CSV 建立无标签泄漏的数据目录。

    :param events_file: 原始事件 CSV。
    :param content_file: 冻结题目向量 NPZ。
    :param root: 缓存输出目录。
    :param length: 窗口长度。
    :param context: 上下文长度。
    :param graph_file: 可选课程知识关系 JSON。
    :returns: 数据目录和 manifest。
    :raises ValueError: 源数据不满足格式或排序要求。
    """
    if length < 2 or context < 0 or context >= length:
        raise ValueError("sequence-length >= 2 且 0 <= context < sequence-length")
    events_file, content_file, root = events_file.resolve(), content_file.resolve(), root.resolve()
    source_hash, content_hash = sha256_file(events_file), sha256_file(content_file)
    graph_hash = sha256_file(graph_file.resolve()) if graph_file else ""
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = (SCHEMA_VERSION, source_hash, content_hash, graph_hash, length, context)
        actual = tuple(manifest.get(key) for key in ("schema", "source_sha256", "content_sha256", "graph_sha256", "sequence_length", "context_length"))
        if actual != expected:
            raise ValueError("数据缓存与输入/配置不一致；请使用新的 data-root，不能覆盖旧数据")
        required_files = [root / f"{split}_{field}.npy" for split in SPLITS for field in (*ARRAY_FIELDS, "offsets", "target_starts")]
        required_files += [root / f"{name}.npy" for name in ("item_content", "item_skills", "item_subjects", "item_difficulty", "skill_content", "graph_edges")]
        if any(not path.is_file() for path in required_files):
            raise ValueError("数据缓存不完整；请使用新的 data-root")
        return PreparedData(root, manifest)
    if root.exists() and any(root.iterdir()):
        raise ValueError("data-root 已有文件且无可复用 manifest，不能覆盖")
    root.mkdir(parents=True, exist_ok=True)
    item_rows: dict[str, dict[str, str]] = {}
    item_to_index: dict[str, int] = {}
    skill_to_index: dict[str, int] = {}
    subject_to_index: dict[str, int] = {}
    buffers = {split: _SplitBuilder() for split in SPLITS}
    current_user: str | None = None
    previous_time: float | None = None
    previous_episode: str | None = None
    episode_number = 0
    user_events: list[tuple[int, int, float, int, int, int]] = []
    seen_users: set[str] = set()
    invalid_labels = 0
    unknown_times = 0
    source_rows = 0

    def flush_user() -> None:
        """将当前用户全部有效事件写入所属切分。

        :returns: None。
        """
        if current_user and user_events:
            buffers[_split_user(current_user)].add_user(user_events, length, context)

    with events_file.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"user_id", "item_id", "timestamp", "skill_ids"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"canonical CSV 缺少列: {sorted(required - set(reader.fieldnames or []))}")
        for row_number, row in enumerate(reader, start=2):
            source_rows += 1
            user_id, item_id = str(row.get("user_id") or "").strip(), str(row.get("item_id") or "").strip()
            if not user_id or not item_id:
                raise ValueError(f"第 {row_number} 行缺少 user_id/item_id")
            if user_id != current_user:
                flush_user()
                if user_id in seen_users:
                    raise ValueError("canonical CSV 必须按用户连续分组，避免跨窗口漏算")
                seen_users.add(user_id)
                current_user, previous_time, previous_episode = user_id, None, None
                user_events = []
            tags = _skill_tokens(row.get("skill_ids"))
            if item_id not in item_rows:
                item_rows[item_id] = dict(row)
                item_to_index[item_id] = len(item_to_index)
                subject = str(row.get("subject_id") or "unknown").strip() or "unknown"
                subject_to_index.setdefault(subject, len(subject_to_index))
                for tag in tags:
                    skill_to_index.setdefault(tag, len(skill_to_index))
            elif tags != _skill_tokens(item_rows[item_id].get("skill_ids")):
                raise ValueError(f"题目 {item_id} 的知识点映射在同一数据集中变化；需提供版本化 item_id")
            result = _parse_correct(row)
            if result is None:
                invalid_labels += 1
                continue
            timestamp = _parse_time(row.get("timestamp"))
            known = previous_time is not None and timestamp is not None
            if known and timestamp < previous_time:
                raise ValueError(f"第 {row_number} 行时间早于同一用户上一条记录")
            gap = (timestamp - previous_time) / 3600.0 if known else 0.0
            explicit_episode = str(row.get("episode_id") or row.get("submission_id") or "").strip()
            if explicit_episode:
                episode_key = "submission:" + explicit_episode
            elif known and timestamp == previous_time:
                episode_key = "time:" + str(timestamp)
            else:
                episode_key = "row:" + str(row_number)
            if episode_key != previous_episode:
                episode_number += 1
            user_events.append((item_to_index[item_id], result, float(gap), int(known), row_number, episode_number))
            if timestamp is None:
                unknown_times += 1
            previous_time = timestamp
            previous_episode = episode_key
    flush_user()
    item_ids = list(item_to_index)
    if not item_ids or not buffers["train"].target_starts:
        raise ValueError("没有可用的训练事件")
    content, content_info = _load_content(content_file, item_ids)
    max_skills = max(1, max((len(_skill_tokens(row.get("skill_ids"))) for row in item_rows.values()), default=1))
    if max_skills > 16:
        raise ValueError("单题知识点超过 16 个；请检查题目映射")
    item_skills = np.full((len(item_ids), max_skills), -1, dtype=np.int32)
    item_subjects = np.zeros(len(item_ids), dtype=np.int32)
    item_difficulty = np.zeros((len(item_ids), 2), dtype=np.float32)
    skill_content = np.zeros((len(skill_to_index), 384), dtype=np.float32)
    skill_counts = np.zeros(len(skill_to_index), dtype=np.int32)
    for item_id, index in item_to_index.items():
        row = item_rows[item_id]
        subject = str(row.get("subject_id") or "unknown").strip() or "unknown"
        item_subjects[index] = subject_to_index[subject]
        item_difficulty[index] = _difficulty(row.get("difficulty"))
        for position, tag in enumerate(_skill_tokens(row.get("skill_ids"))):
            skill = skill_to_index[tag]
            item_skills[index, position] = skill
            skill_content[skill] += content[index]
            skill_counts[skill] += 1
    if len(skill_to_index):
        skill_content /= np.maximum(skill_counts[:, None], 1)
        norms = np.linalg.norm(skill_content, axis=1, keepdims=True)
        skill_content /= np.maximum(norms, 1e-8)
    graph_edges = np.empty((0, 3), dtype=np.int32)
    if graph_file:
        relations = json.loads(graph_file.read_text(encoding="utf-8"))
        if not isinstance(relations, list):
            raise ValueError("知识图谱 JSON 须为关系列表")
        relation_types = {"prerequisite": 0, "part_of": 1, "includes": 2, "related": 3}
        parsed_edges: list[tuple[int, int, int]] = []
        for relation in relations:
            if not isinstance(relation, dict):
                raise ValueError("知识图谱关系须为对象")
            source = str(relation.get("from") or "")
            target = str(relation.get("to") or "")
            edge_type = str(relation.get("type") or "")
            if source not in skill_to_index or target not in skill_to_index or edge_type not in relation_types:
                raise ValueError(f"未知知识点或关系类型: {relation}")
            parsed_edges.append((skill_to_index[source], skill_to_index[target], relation_types[edge_type]))
        graph_edges = np.asarray(parsed_edges, dtype=np.int32).reshape(-1, 3)
    for name, values in (("item_content", content), ("item_skills", item_skills),
                         ("item_subjects", item_subjects), ("item_difficulty", item_difficulty),
                         ("skill_content", skill_content), ("graph_edges", graph_edges)):
        _save_array(root / f"{name}.npy", values)
    split_sizes = {split: builder.save(root, split) for split, builder in buffers.items()}
    manifest: dict[str, Any] = {
        "schema": SCHEMA_VERSION, "source_file": str(events_file), "source_sha256": source_hash,
        "content_file": str(content_file), "content_sha256": content_hash, "content": content_info,
        "graph_file": str(graph_file.resolve()) if graph_file else "", "graph_sha256": graph_hash,
        "graph_edges": int(graph_edges.shape[0]),
        "sequence_length": length, "context_length": context, "split_strategy": "sha256_user_80_10_10",
        "availability_assumption": "canonical 无 available_at 时假设每题结果立即可见；需另行评估真实业务日志",
        "source_rows": source_rows, "ungraded_rows": invalid_labels, "unknown_time_rows": unknown_times,
        "users": len(seen_users), "items": len(item_ids), "skills": len(skill_to_index),
        "splits": split_sizes, "item_ids": item_ids, "skill_ids": list(skill_to_index),
        "subject_ids": list(subject_to_index),
    }
    temporary = manifest_path.with_name("manifest.json.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, manifest_path)
    return PreparedData(root, manifest)


class WindowDataset(Dataset[int]):
    """内存映射的训练窗口索引。"""

    def __init__(self, root: Path, split: str) -> None:
        """加载单个切分的索引和事件数组。

        :param root: 数据目录。
        :param split: 切分名称。
        :returns: None。
        """
        if split not in SPLITS:
            raise ValueError(f"未知切分: {split}")
        self.values = {name: np.load(root / f"{split}_{name}.npy", mmap_mode="r") for name in ARRAY_FIELDS}
        self.offsets = np.load(root / f"{split}_offsets.npy", mmap_mode="r")
        self.target_starts = np.load(root / f"{split}_target_starts.npy", mmap_mode="r")

    def __len__(self) -> int:
        """返回窗口数。

        :returns: 窗口数。
        """
        return len(self.target_starts)

    def __getitem__(self, index: int) -> int:
        """返回窗口索引。

        :param index: 窗口位置。
        :returns: 索引原值。
        """
        return index

    def close(self) -> None:
        """显式释放内存映射，供 Windows 测试和长期进程清理。

        :returns: None。
        """
        for array in (*self.values.values(), self.offsets, self.target_starts):
            if isinstance(array, np.memmap):
                array._mmap.close()

    def __enter__(self) -> WindowDataset:
        """进入数据集上下文。

        :returns: 当前数据集。
        """
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        """释放数据集映射。

        :param _type: 异常类型。
        :param _value: 异常对象。
        :param _traceback: 异常栈。
        :returns: None。
        """
        self.close()


def collate_windows(indices: list[int], dataset: WindowDataset) -> dict[str, Tensor]:
    """将变长窗口变为 batch，保留目标和场次掩码。

    :param indices: 窗口索引。
    :param dataset: 事件数据。
    :returns: 模型需要的张量字典。
    """
    ranges = [(int(dataset.offsets[i]), int(dataset.offsets[i + 1])) for i in indices]
    width = max(end - start for start, end in ranges)
    dtypes = {"items": torch.long, "correct": torch.float32, "gaps": torch.float32,
              "time_known": torch.bool, "source_rows": torch.long, "episodes": torch.long}
    batch = {name: torch.zeros((len(indices), width), dtype=dtype) for name, dtype in dtypes.items()}
    batch["items"].fill_(-1)
    batch["valid"] = torch.zeros((len(indices), width), dtype=torch.bool)
    batch["target"] = torch.zeros((len(indices), width), dtype=torch.bool)
    for batch_index, (start, end) in enumerate(ranges):
        size = end - start
        for name in ARRAY_FIELDS:
            batch[name][batch_index, :size] = torch.from_numpy(np.asarray(dataset.values[name][start:end]).copy())
        batch["valid"][batch_index, :size] = True
        batch["target"][batch_index, int(dataset.target_starts[indices[batch_index]]):size] = True
    return batch
