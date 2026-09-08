#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT 二分类评估指标和数据切分评估。
@Project : adaptive-edu
@File : mefkt_evaluation.py
@Author : Qintsg
@Date : 2026-08-30
'''

from __future__ import annotations

import numpy as np
import torch
from torch import nn
from torch.nn import functional
from torch.utils.data import DataLoader


def _average_ranks(values: np.ndarray) -> np.ndarray:
    """
    为可能包含并列值的预测分配一基平均秩。

    :param values: 一维预测值。
    :returns: 与输入顺序一致的平均秩。
    """
    order = np.argsort(values, kind="mergesort")
    sorted_values = values[order]
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and sorted_values[end] == sorted_values[start]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    return ranks


def calculate_metrics(probabilities: list[float], targets: list[int]) -> dict[str, float]:
    """
    计算 AUC、ACC、Brier、ECE 和标签比例。

    :param probabilities: 答对预测概率。
    :param targets: 真实 0/1 标签。
    :returns: 评估指标字典。
    """
    if not targets:
        return {"auc": 0.5, "acc": 0.0, "brier": 0.0, "ece": 0.0, "samples": 0.0, "positive_rate": 0.0}
    prediction = np.asarray(probabilities, dtype=np.float64)
    gold = np.asarray(targets, dtype=np.int64)
    positive = int(gold.sum())
    negative = len(gold) - positive
    if positive and negative:
        ranks = _average_ranks(prediction)
        auc = float((ranks[gold == 1].sum() - positive * (positive + 1) / 2) / (positive * negative))
    else:
        auc = 0.5
    labels = (prediction >= 0.5).astype(np.int64)
    ece = 0.0
    for lower in np.linspace(0.0, 0.9, 10):
        upper = lower + 0.1
        mask = (prediction >= lower) & ((prediction < upper) if upper < 1.0 else (prediction <= upper))
        if mask.any():
            ece += float(mask.mean()) * abs(float(prediction[mask].mean()) - float(gold[mask].mean()))
    return {
        "auc": auc,
        "acc": float((labels == gold).mean()),
        "brier": float(np.mean((prediction - gold) ** 2)),
        "ece": ece,
        "samples": float(len(gold)),
        "positive_rate": float(gold.mean()),
    }


def evaluate(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
    max_batches: int = 0,
    item_subjects: torch.Tensor | None = None,
    subject_names: tuple[str, ...] | None = None,
) -> dict[str, object]:
    """
    在一个切分上评估每次交互的答对预测。

    :param model: 待评估模型。
    :param loader: 评估 DataLoader。
    :param device: 评估设备。
    :param max_batches: 最大 batch 数，0 表示不限制。
    :param item_subjects: 可选的题目学科索引表。
    :param subject_names: 可选的学科名称。
    :returns: 评估指标字典。
    """
    model.eval()
    probabilities: list[float] = []
    targets: list[int] = []
    subject_ids: list[int] = []
    total_loss = 0.0
    total_targets = 0
    subject_lookup = item_subjects.to(device) if item_subjects is not None else None
    with torch.no_grad():
        for batch_index, batch in enumerate(loader):
            if max_batches and batch_index >= max_batches:
                break
            items, correct, gaps, response_times, target_mask = (value.to(device, non_blocking=True) for value in batch)
            logits, mask, _ = model(items, correct, gaps, response_times)
            effective_mask = mask & target_mask
            if bool(effective_mask.any()):
                total_loss += float(
                    functional.binary_cross_entropy_with_logits(
                        logits[effective_mask],
                        correct.float()[effective_mask],
                        reduction="sum",
                    ).item()
                )
                total_targets += int(effective_mask.sum().item())
            probabilities.extend(torch.sigmoid(logits[effective_mask]).cpu().tolist())
            targets.extend(correct[effective_mask].cpu().tolist())
            if subject_lookup is not None:
                subject_ids.extend(subject_lookup[items[effective_mask]].cpu().tolist())
    metrics = calculate_metrics(probabilities, targets)
    metrics["loss"] = total_loss / max(total_targets, 1)
    if subject_lookup is not None and subject_names is not None:
        prediction_array = np.asarray(probabilities, dtype=np.float64)
        target_array = np.asarray(targets, dtype=np.int64)
        subject_array = np.asarray(subject_ids, dtype=np.int64)
        subject_metrics: dict[str, dict[str, float]] = {}
        for subject_index, name in enumerate(subject_names):
            selected = subject_array == subject_index
            if not selected.any():
                continue
            values = calculate_metrics(prediction_array[selected].tolist(), target_array[selected].tolist())
            clipped = np.clip(prediction_array[selected], 1e-7, 1.0 - 1e-7)
            gold = target_array[selected].astype(np.float64)
            values["loss"] = float(-np.mean(gold * np.log(clipped) + (1.0 - gold) * np.log1p(-clipped)))
            subject_metrics[name] = values
        metrics["subjects"] = subject_metrics
    return metrics
