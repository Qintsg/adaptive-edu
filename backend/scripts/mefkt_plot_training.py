#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
绘制 MEFKT 训练总曲线、最近 epoch 曲线并输出数值摘要。
@Project : adaptive-edu
@File : mefkt_plot_training.py
@Author : Qintsg
@Date : 2026-08-25
'''

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

METRIC_NAMES = (
    "loss",
    "validation_loss",
    "test_loss",
    "validation_auc",
    "test_auc",
    "validation_acc",
    "test_acc",
    "validation_brier",
    "test_brier",
    "validation_ece",
    "test_ece",
)


def _number(value: object) -> float | None:
    """
    将文本指标安全转换为浮点数。

    :param value: 原始值。
    :returns: 浮点数或空值。
    """
    if value is None or value == "":
        return None
    return float(value)


def _normalise_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    统一 JSONL 嵌套记录和 CSV 扁平记录格式。

    :param record: 原始指标记录。
    :returns: 扁平记录。
    """
    if isinstance(record.get("validation"), dict):
        for name, value in record["validation"].items():
            record[f"validation_{name}"] = value
    if isinstance(record.get("test"), dict):
        for name, value in record["test"].items():
            record[f"test_{name}"] = value
    for name in ("epoch", "epoch_index", *METRIC_NAMES):
        if name in record:
            record[name] = _number(record[name]) if name != "epoch" else int(float(record[name]))
    return record


def load_metrics(path: Path) -> list[dict[str, Any]]:
    """
    读取 JSONL 或 CSV 训练指标并按 epoch 去重。

    :param path: `training_metrics.jsonl` 或 `training_metrics.csv` 路径。
    :returns: 按 epoch 排序且每个 epoch 保留最后记录的指标。
    :raises ValueError: 文件格式不支持或没有有效记录时抛出。
    """
    if path.suffix.lower() == ".jsonl":
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    elif path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            records = list(csv.DictReader(handle))
    else:
        raise ValueError("指标文件必须是 .jsonl 或 .csv")
    deduplicated: dict[int, dict[str, Any]] = {}
    for raw_record in records:
        record = _normalise_record(dict(raw_record))
        if record.get("epoch") is not None:
            deduplicated[int(record["epoch"])] = record
    result = [deduplicated[epoch] for epoch in sorted(deduplicated)]
    if not result:
        raise ValueError(f"指标文件没有有效 epoch: {path}")
    return result


def _value(record: dict[str, Any], key: str) -> float | None:
    """
    获取一个可绘制指标。

    :param record: epoch 指标记录。
    :param key: 指标字段名。
    :returns: 浮点数或空值。
    """
    return _number(record.get(key))


def _print_summary(records: list[dict[str, Any]], recent_epochs: int) -> None:
    """
    打印最佳、最后和最近若干轮的具体数值。

    :param records: 去重后的指标记录。
    :param recent_epochs: 最近轮数，0 表示全部。
    :returns: None。
    """
    best = max(records, key=lambda row: _value(row, "validation_auc") or float("-inf"))
    print(f"epochs={len(records)} first={records[0]['epoch']} last={records[-1]['epoch']}")
    print(
        "best_validation_auc="
        f"{_value(best, 'validation_auc'):.6f} epoch={best['epoch']} "
        f"test_auc={_value(best, 'test_auc') or 0.0:.6f}"
    )
    print("epoch,lr,next_lr,loss,val_loss,test_loss,val_auc,test_auc,val_brier,test_brier,val_ece,test_ece")
    selected = records[-recent_epochs:] if recent_epochs > 0 else records
    for record in selected:
        values = [
            record.get("epoch"),
            _value(record, "learning_rate"),
            _value(record, "next_learning_rate"),
            _value(record, "loss"),
            _value(record, "validation_loss"),
            _value(record, "test_loss"),
            _value(record, "validation_auc"),
            _value(record, "test_auc"),
            _value(record, "validation_brier"),
            _value(record, "test_brier"),
            _value(record, "validation_ece"),
            _value(record, "test_ece"),
        ]
        print(",".join("" if value is None else f"{value:.6f}" if isinstance(value, float) else str(value) for value in values))


def _plot(records: list[dict[str, Any]], output: Path, recent_epochs: int, title_suffix: str = "") -> None:
    """
    绘制 loss、AUC、Brier/ECE 和 ACC 四组曲线。

    :param records: 去重后的指标记录。
    :param output: PNG 输出路径。
    :param recent_epochs: 高亮最近轮数，0 表示不高亮。
    :param title_suffix: 图标题后缀。
    :returns: None。
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError as error:
        raise RuntimeError("绘图需要 matplotlib，请执行 uv sync --extra plot") from error

    epochs = [int(record["epoch"]) for record in records]
    recent = set(epochs[-recent_epochs:]) if recent_epochs > 0 else set()
    figure, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
    groups = (
        ("loss", ("loss", "validation_loss", "test_loss"), "Loss"),
        ("auc", ("validation_auc", "test_auc"), "AUC"),
        ("calibration", ("validation_brier", "test_brier", "validation_ece", "test_ece"), "Brier / ECE"),
        ("accuracy", ("validation_acc", "test_acc"), "Accuracy"),
    )
    labels = {
        "loss": "train loss",
        "validation_loss": "validation loss",
        "test_loss": "test loss",
        "validation_auc": "validation AUC",
        "test_auc": "test AUC",
        "validation_brier": "validation Brier",
        "test_brier": "test Brier",
        "validation_ece": "validation ECE",
        "test_ece": "test ECE",
        "validation_acc": "validation ACC",
        "test_acc": "test ACC",
    }
    for axis, (_, keys, name) in zip(axes.flat, groups):
        for key in keys:
            values = [_value(record, key) for record in records]
            axis.plot(epochs, values, marker="o", linewidth=1.8, label=labels[key])
        if recent:
            axis.axvspan(min(recent) - 0.5, max(recent) + 0.5, color="orange", alpha=0.12, label="recent window")
        axis.set_title(name)
        axis.set_xlabel("epoch")
        axis.grid(True, alpha=0.25)
        axis.legend(fontsize=8)
    figure.suptitle(f"MEFKT training curves{title_suffix}")
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=150)
    plt.close(figure)
    print(f"saved_plot={output}")


def _parse_args() -> argparse.Namespace:
    """
    解析训练曲线参数。

    :returns: 命令行参数命名空间。
    """
    parser = argparse.ArgumentParser(description="绘制 MEFKT 总训练曲线和最近 epoch 曲线")
    parser.add_argument("--metrics-file", required=True, help="training_metrics.jsonl 或 training_metrics.csv")
    parser.add_argument("--output", default="training_curves.png", help="总曲线 PNG 输出路径")
    parser.add_argument("--recent-output", default="", help="最近窗口曲线 PNG 输出路径；为空时不额外输出")
    parser.add_argument("--recent-epochs", type=int, default=10, help="高亮/绘制最近多少轮；0 表示全部")
    parser.add_argument("--summary-only", action="store_true", help="只打印指标，不生成图片")
    return parser.parse_args()


def main() -> int:
    """
    读取指标、打印摘要并生成曲线。

    :returns: 进程退出码。
    """
    args = _parse_args()
    if args.recent_epochs < 0:
        raise ValueError("--recent-epochs 不能为负数")
    records = load_metrics(Path(args.metrics_file))
    _print_summary(records, args.recent_epochs)
    if not args.summary_only:
        _plot(records, Path(args.output), args.recent_epochs)
        if args.recent_output:
            recent = records[-args.recent_epochs :] if args.recent_epochs else records
            _plot(recent, Path(args.recent_output), 0, " (recent)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
