#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT-NG 逐事件评价与可重新分析的验证预测输出。
@Project : adaptive-edu
@File : metrics.py
@Author : Qintsg
@Date : 2026-09-24
'''

from __future__ import annotations

import csv
import gzip
import math
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import Tensor, nn
from torch.utils.data import DataLoader

from mefkt_ng.data import sha256_file


def summarize_predictions(logits: np.ndarray, labels: np.ndarray) -> dict[str, float | int | None]:
    """计算固定快照的二元预测指标。

    :param logits: 一维原始预测 logits。
    :param labels: 对齐的 0/1 结果。
    :returns: NLL、AUC、Brier、ECE、准确率和样本计数。
    :raises ValueError: 数组不对齐或预测非有限值。
    """
    if logits.ndim != 1 or labels.ndim != 1 or logits.shape != labels.shape:
        raise ValueError("logits 与 labels 须为等长一维数组")
    if not np.isfinite(logits).all():
        raise ValueError("预测中存在非有限 logit")
    count = int(labels.size)
    if not count:
        return {"nll": None, "auc": None, "brier": None, "ece": None,
                "accuracy": None, "samples": 0, "positives": 0, "positive_rate": None}
    gold = labels.astype(np.int64, copy=False)
    if not np.isin(gold, (0, 1)).all():
        raise ValueError("评价标签必须为 0/1")
    probabilities = 1.0 / (1.0 + np.exp(-np.clip(logits.astype(np.float64), -80.0, 80.0)))
    nll = float(np.mean(np.logaddexp(0.0, logits) - gold * logits))
    auc: float | None = None
    positives = int(gold.sum())
    if 0 < positives < count:
        order = np.argsort(probabilities, kind="mergesort")
        sorted_scores = probabilities[order]
        ranks = np.empty(count, dtype=np.float64)
        start = 0
        while start < count:
            end = start + 1
            while end < count and sorted_scores[end] == sorted_scores[start]:
                end += 1
            ranks[order[start:end]] = (start + 1 + end) / 2.0
            start = end
        auc = float((ranks[gold == 1].sum() - positives * (positives + 1) / 2.0) / (positives * (count - positives)))
    ece = 0.0
    for index in range(10):
        lower, upper = index / 10.0, (index + 1) / 10.0
        selected = (probabilities >= lower) & (probabilities < upper if index < 9 else probabilities <= upper)
        if selected.any():
            ece += float(selected.mean() * abs(probabilities[selected].mean() - gold[selected].mean()))
    return {
        "nll": nll,
        "auc": auc,
        "brier": float(np.mean((probabilities - gold) ** 2)),
        "ece": ece,
        "accuracy": float(np.mean((probabilities >= 0.5) == gold)),
        "samples": count,
        "positives": positives,
        "positive_rate": float(gold.mean()),
    }


def _move_batch(batch: dict[str, Tensor], device: torch.device) -> dict[str, Tensor]:
    """搬运事件 batch。

    :param batch: CPU 张量字典。
    :param device: 目标设备。
    :returns: 设备上的字典。
    """
    return {name: value.to(device, non_blocking=True) for name, value in batch.items()}


def _prediction_rows(
    batch: dict[str, Tensor], logits: Tensor, selected: Tensor,
    item_ids: tuple[str, ...], subject_ids: tuple[str, ...], item_subjects: Tensor,
) -> Iterable[tuple[object, ...]]:
    """生成可按原始行号回连的逐题预测记录。

    :param batch: 包含 source_rows 的设备 batch。
    :param logits: 本次作答前 logits。
    :param selected: 唯一计分的目标掩码。
    :param item_ids: 题目目录。
    :param subject_ids: 学科目录。
    :param item_subjects: 题目到学科的映射。
    :returns: 适合 CSV 写入的行。
    """
    sources = batch["source_rows"][selected].detach().cpu().tolist()
    items = batch["items"][selected].detach().cpu().tolist()
    labels = batch["correct"][selected].detach().cpu().tolist()
    values = logits[selected].detach().float().cpu().tolist()
    for source, item, label, value in zip(sources, items, labels, values, strict=True):
        probability = 1.0 / (1.0 + math.exp(-max(-80.0, min(80.0, float(value)))))
        subject = subject_ids[int(item_subjects[item])]
        yield int(source), item_ids[item], subject, int(label), float(value), probability


def evaluate_split(
    model: nn.Module, loader: DataLoader, device: torch.device,
    item_subjects: Tensor, item_ids: tuple[str, ...], subject_ids: tuple[str, ...],
    prediction_file: Path | None = None,
) -> dict[str, Any]:
    """评估整个固定切分，并可持久保存每个目标预测。

    :param model: 模型或 DDP 原始模块。
    :param loader: 完整评估切分。
    :param device: 推理设备。
    :param item_subjects: 题目到学科的索引。
    :param item_ids: 题目名称目录。
    :param subject_ids: 学科名称目录。
    :param prediction_file: 可选 gzip CSV 产物。
    :returns: 总体、分学科指标和预测产物摘要。
    """
    model.eval()
    logits_parts: list[np.ndarray] = []
    label_parts: list[np.ndarray] = []
    subject_parts: list[np.ndarray] = []
    writer = None
    handle = None
    temporary = None
    if prediction_file is not None:
        prediction_file.parent.mkdir(parents=True, exist_ok=True)
        if prediction_file.exists():
            raise FileExistsError(f"不能覆盖已有验证预测: {prediction_file}")
        temporary = prediction_file.with_name(prediction_file.name + f".{os.getpid()}.tmp")
        handle = gzip.open(temporary, "wt", encoding="utf-8", newline="")
        writer = csv.writer(handle)
        writer.writerow(("source_row", "item_id", "subject_id", "correct", "logit", "p_core"))
    try:
        with torch.inference_mode():
            for cpu_batch in loader:
                batch = _move_batch(cpu_batch, device)
                logits, valid = model(batch)
                selected = valid & batch["target"]
                if not bool(selected.any()):
                    continue
                selected_logits = logits[selected].detach().float().cpu().numpy().astype(np.float64)
                selected_labels = batch["correct"][selected].detach().cpu().numpy().astype(np.int64)
                selected_subjects = item_subjects[batch["items"][selected].detach().cpu()].numpy()
                logits_parts.append(selected_logits)
                label_parts.append(selected_labels)
                subject_parts.append(selected_subjects)
                if writer is not None:
                    writer.writerows(_prediction_rows(batch, logits, selected, item_ids, subject_ids, item_subjects))
    finally:
        if handle is not None:
            handle.close()
    if temporary is not None and prediction_file is not None:
        os.replace(temporary, prediction_file)
    values = np.concatenate(logits_parts) if logits_parts else np.empty(0, dtype=np.float64)
    labels = np.concatenate(label_parts) if label_parts else np.empty(0, dtype=np.int64)
    subjects = np.concatenate(subject_parts) if subject_parts else np.empty(0, dtype=np.int64)
    result: dict[str, Any] = {"overall": summarize_predictions(values, labels), "subjects": {}}
    for index, name in enumerate(subject_ids):
        matching = subjects == index
        if matching.any():
            result["subjects"][name] = summarize_predictions(values[matching], labels[matching])
    if prediction_file is not None:
        result["predictions"] = {"file": prediction_file.name, "sha256": sha256_file(prediction_file),
                                  "rows": int(labels.size)}
    return result
