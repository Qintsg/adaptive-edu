#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT 数据缓存、序列存储和 batch 整理核心模块。
@Project : adaptive-edu
@File : mefkt_data_core.py
@Author : Qintsg
@Date : 2026-08-24
'''

from __future__ import annotations

from array import array
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import Tensor
from torch.utils.data import Dataset

SPLITS = ("train", "validation", "test")
PREPROCESS_VERSION = 6


@dataclass
class SplitBuffer:
    """保存一个数据切分的紧凑变长序列。"""

    items: array
    correct: bytearray
    gaps: array
    response_times: array
    offsets: array
    target_starts: array

    @classmethod
    def create(cls) -> SplitBuffer:
        """
        创建空的切分缓冲区。

        :returns: 新的空缓冲区。
        """
        return cls(array("i"), bytearray(), array("f"), array("f"), array("q", [0]), array("i"))

    def append(
        self,
        items: list[int],
        correct: list[int],
        gaps: list[float],
        response_times: list[float],
        target_start: int = 0,
    ) -> None:
        """
        追加一道完整序列。

        :param items: 题目连续索引。
        :param correct: 作答正确标记。
        :param gaps: 当前交互距离上一交互的小时数。
        :param response_times: 当前题目答题耗时，单位为秒。
        :param target_start: 当前窗口中开始计算损失的相对位置。
        :returns: None。
        """
        if len(items) < 2 or len(items) != len(correct) or len(items) != len(gaps) or len(items) != len(response_times):
            return
        if target_start < 0 or target_start >= len(items):
            raise ValueError("target_start 超出窗口范围")
        self.items.extend(items)
        self.correct.extend(1 if value else 0 for value in correct)
        self.gaps.extend(float(max(value, 1.0 / 3600.0)) for value in gaps)
        self.response_times.extend(float(min(max(value, 0.1), 3600.0)) for value in response_times)
        self.offsets.append(len(self.items))
        self.target_starts.append(target_start)

    def __len__(self) -> int:
        """
        返回已经追加的序列数量。

        :returns: 序列数量。
        """
        return max(len(self.offsets) - 1, 0)


@dataclass(frozen=True)
class PreparedDataset:
    """预处理后可直接训练的数据集描述。"""

    root: Path
    item_count: int
    feature_dim: int
    item_features: Tensor
    split_sizes: dict[str, int]
    metadata: dict[str, object]
    item_ids: tuple[str, ...]
    item_subjects: Tensor
    item_skills: Tensor
    subject_vocab: tuple[str, ...]
    skill_vocab: tuple[str, ...]


@dataclass(frozen=True)
class QuestionMetadata:
    """题目、学科和知识点词表。"""

    item_to_index: dict[str, int]
    answers: dict[str, str]
    raw_features: np.ndarray
    item_subjects: np.ndarray
    item_skills: np.ndarray
    subject_vocab: tuple[str, ...]
    skill_vocab: tuple[str, ...]


class SequenceStore:
    """通过 numpy mmap 读取紧凑序列，避免把 EdNet 全量载入内存。"""

    def __init__(self, root: Path, split: str) -> None:
        """
        打开一个数据切分。

        :param root: 预处理数据目录。
        :param split: train、validation 或 test。
        :returns: None。
        """
        if split not in SPLITS:
            raise ValueError(f"未知数据切分: {split}")
        self.split = split
        self.items = np.load(root / f"{split}_items.npy", mmap_mode="r")
        self.correct = np.load(root / f"{split}_correct.npy", mmap_mode="r")
        self.gaps = np.load(root / f"{split}_gaps.npy", mmap_mode="r")
        self.response_times = np.load(root / f"{split}_response_times.npy", mmap_mode="r")
        self.offsets = np.load(root / f"{split}_offsets.npy", mmap_mode="r")
        self.target_starts = np.load(root / f"{split}_target_starts.npy", mmap_mode="r")

    def __len__(self) -> int:
        """
        返回序列数量。

        :returns: 序列数量。
        """
        return max(int(self.offsets.shape[0]) - 1, 0)

    def get(self, index: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
        """
        读取单条序列。

        :param index: 序列索引。
        :returns: 题目、正确性、时间间隔、答题耗时和目标起始位置。
        """
        start = int(self.offsets[index])
        end = int(self.offsets[index + 1])
        return self.items[start:end], self.correct[start:end], self.gaps[start:end], self.response_times[start:end], int(self.target_starts[index])


class SequenceIndexDataset(Dataset[int]):
    """DataLoader 使用的轻量序列索引数据集。"""

    def __init__(self, store: SequenceStore) -> None:
        """
        初始化序列索引数据集。

        :param store: 提供序列数量和内容的 mmap 存储。
        :returns: None。
        """
        self.store = store

    def __len__(self) -> int:
        """
        返回序列数量。

        :returns: 序列数量。
        """
        return len(self.store)

    def __getitem__(self, index: int) -> int:
        """
        返回序列索引。

        :param index: DataLoader 请求的索引。
        :returns: 原样返回的序列索引。
        """
        return index


def collate_sequence_indices(
    indices: list[int],
    store: SequenceStore,
    max_length: int,
) -> tuple[Tensor, Tensor, Tensor, Tensor, Tensor]:
    """
    将变长序列整理为 padding batch。

    :param indices: 序列索引列表。
    :param store: mmap 序列存储。
    :param max_length: 单条序列最大长度。
    :returns: 题目、正确性、时间间隔、答题耗时和目标 mask。
    """
    rows = [store.get(index) for index in indices]
    length = min(max((len(row[0]) for row in rows), default=2), max_length)
    item_tensor = torch.full((len(rows), length), -1, dtype=torch.long)
    correct_tensor = torch.zeros((len(rows), length), dtype=torch.long)
    gap_tensor = torch.ones((len(rows), length), dtype=torch.float32)
    response_time_tensor = torch.full((len(rows), length), 10.0, dtype=torch.float32)
    target_mask = torch.zeros((len(rows), length), dtype=torch.bool)
    for row_index, (items, correct, gaps, response_times, target_start) in enumerate(rows):
        row_length = min(len(items), length)
        item_tensor[row_index, :row_length] = torch.from_numpy(np.array(items[:row_length], dtype=np.int64, copy=True))
        correct_tensor[row_index, :row_length] = torch.from_numpy(np.array(correct[:row_length], dtype=np.int64, copy=True))
        gap_tensor[row_index, :row_length] = torch.from_numpy(np.array(gaps[:row_length], dtype=np.float32, copy=True))
        response_time_tensor[row_index, :row_length] = torch.from_numpy(np.array(response_times[:row_length], dtype=np.float32, copy=True))
        target_mask[row_index, min(target_start, row_length) : row_length] = True
    return item_tensor, correct_tensor, gap_tensor, response_time_tensor, target_mask
