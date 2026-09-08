#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT 训练运行配置和 epoch 指标持久化工具。
@Project : adaptive-edu
@File : mefkt_reporting.py
@Author : Qintsg
@Date : 2026-08-25
'''

from __future__ import annotations

import csv
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

METRIC_FIELDS = (
    "recorded_at_utc",
    "epoch",
    "epoch_index",
    "loss",
    "learning_rate",
    "next_learning_rate",
    "elapsed_seconds",
    "validation_loss",
    "validation_auc",
    "validation_acc",
    "validation_brier",
    "validation_ece",
    "validation_samples",
    "validation_positive_rate",
    "test_loss",
    "test_auc",
    "test_acc",
    "test_brier",
    "test_ece",
    "test_samples",
    "test_positive_rate",
    "is_best",
    "is_best_loss",
    "stale",
    "validation_loss_best",
    "validation_loss_bad_streak",
    "validation_loss_rise_streak",
    "validation_loss_trend_delta",
    "stop_reason",
)


def _as_float(value: object) -> float | None:
    """
    将指标值转换为 CSV 兼容的浮点数。

    :param value: 原始值。
    :returns: 浮点数或空值。
    """
    if value is None:
        return None
    return float(value)


def _flatten_metric(record: dict[str, object]) -> dict[str, object]:
    """
    将嵌套 validation/test 指标展开为稳定 CSV 行。

    :param record: epoch 指标记录。
    :returns: 扁平化指标记录。
    """
    flattened: dict[str, object] = {
        "recorded_at_utc": record.get("recorded_at_utc", ""),
        "epoch": record.get("epoch"),
        "epoch_index": record.get("epoch_index"),
        "loss": _as_float(record.get("loss")),
        "learning_rate": _as_float(record.get("learning_rate")),
        "next_learning_rate": _as_float(record.get("next_learning_rate")),
        "elapsed_seconds": _as_float(record.get("elapsed_seconds")),
        "validation_loss_best": _as_float(record.get("validation_loss_best")),
        "validation_loss_bad_streak": record.get("validation_loss_bad_streak", 0),
        "validation_loss_rise_streak": record.get("validation_loss_rise_streak", 0),
        "validation_loss_trend_delta": _as_float(record.get("validation_loss_trend_delta")),
        "stop_reason": record.get("stop_reason", ""),
        "is_best": record.get("is_best", False),
        "is_best_loss": record.get("is_best_loss", False),
        "stale": record.get("stale", 0),
    }
    for split in ("validation", "test"):
        metrics = record.get(split, {})
        if not isinstance(metrics, dict):
            metrics = {}
        for name in ("loss", "auc", "acc", "brier", "ece", "samples", "positive_rate"):
            flattened[f"{split}_{name}"] = _as_float(metrics.get(name))
    return {field: flattened.get(field) for field in METRIC_FIELDS}


def write_run_config(output_dir: Path, config: dict[str, object]) -> None:
    """
    保存本次训练的参数、环境和数据配置。

    :param output_dir: 训练输出目录。
    :param config: 可 JSON 序列化的配置。
    :returns: None。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        **config,
    }
    temporary = output_dir / ".run_config.json.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, output_dir / "run_config.json")


def append_epoch_metrics(output_dir: Path, record: dict[str, object]) -> None:
    """
    追加一轮训练指标到 JSONL 和 CSV 文件。

    JSONL 保留完整嵌套指标，CSV 方便 Excel、命令行和绘图工具读取。恢复训练时允许
    同一 epoch 出现多条记录，分析脚本会按最后一条记录去重。

    :param output_dir: 训练输出目录。
    :param record: 当前 epoch 指标。
    :returns: None。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    enriched = {
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        **record,
    }
    jsonl_path = output_dir / "training_metrics.jsonl"
    with jsonl_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(enriched, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    csv_path = output_dir / "training_metrics.csv"
    row = _flatten_metric(enriched)
    needs_header = _ensure_csv_schema(csv_path)
    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(METRIC_FIELDS))
        if needs_header:
            writer.writeheader()
        writer.writerow(row)
        handle.flush()
        os.fsync(handle.fileno())


def _ensure_csv_schema(csv_path: Path) -> bool:
    """
    确保 CSV 使用当前指标字段，并兼容旧版本训练记录。

    :param csv_path: 训练指标 CSV 路径。
    :returns: 是否需要写入表头。
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return True
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames == list(METRIC_FIELDS):
            return False
        rows = list(reader)
    temporary = csv_path.with_name(f".{csv_path.name}.migrating")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(METRIC_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in METRIC_FIELDS})
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, csv_path)
    return False


def jsonable_args(args: Any) -> dict[str, object]:
    """
    将 argparse Namespace 或普通对象转换为 JSON 配置字典。

    :param args: 参数对象。
    :returns: JSON 可序列化字典。
    """
    values = vars(args) if hasattr(args, "__dict__") else dict(args)
    return {str(key): value for key, value in values.items()}


def load_validation_loss_history(output_dir: Path, limit: int) -> list[float]:
    """
    从既有 JSONL 指标恢复最近若干轮 validation loss。

    :param output_dir: 训练输出目录。
    :param limit: 最多返回的轮数。
    :returns: 按 epoch 排序且去重后的 validation loss。
    """
    if limit <= 0:
        return []
    path = output_dir / "training_metrics.jsonl"
    if not path.exists():
        return []
    by_epoch: dict[int, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        validation = record.get("validation", {})
        if not isinstance(validation, dict) or validation.get("loss") is None:
            continue
        by_epoch[int(record["epoch"])] = float(validation["loss"])
    return [by_epoch[epoch] for epoch in sorted(by_epoch)[-limit:]]
