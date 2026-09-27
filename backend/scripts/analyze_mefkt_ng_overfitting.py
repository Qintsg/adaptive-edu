#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
用逐轮训练/验证轨迹检查 MEFKT-NG 的泛化间隙和过拟合迹象。
@Project : adaptive-edu
@File : analyze_mefkt_ng_overfitting.py
@Author : Qintsg
@Date : 2026-09-24
'''

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt


def load_metrics(path: Path) -> list[dict[str, Any]]:
    """严格读取逐轮指标 JSONL。

    :param path: 权威指标文件。
    :returns: 按 epoch 顺序排列的记录。
    :raises ValueError: 轮次断裂或字段缺失。
    """
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if [row["epoch"] for row in rows] != list(range(1, len(rows) + 1)):
        raise ValueError("逐轮指标缺失或顺序不连续")
    return rows


def write_curve_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """输出可二次分析的泛化曲线 CSV。

    :param path: 目标 CSV。
    :param rows: 逐轮指标。
    :returns: None。
    """
    fields = ["epoch", "train_nll", "validation_nll", "nll_gap", "train_auc", "validation_auc",
              "auc_gap", "train_brier", "validation_brier", "train_ece", "validation_ece",
              "learning_rate", "stale"]
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            train, validation = row["train"]["overall"], row["validation"]["overall"]
            writer.writerow({"epoch": row["epoch"], "train_nll": train["nll"],
                             "validation_nll": validation["nll"],
                             "nll_gap": validation["nll"] - train["nll"],
                             "train_auc": train["auc"], "validation_auc": validation["auc"],
                             "auc_gap": train["auc"] - validation["auc"],
                             "train_brier": train["brier"], "validation_brier": validation["brier"],
                             "train_ece": train["ece"], "validation_ece": validation["ece"],
                             "learning_rate": row["learning_rate"], "stale": row["stale"]})


def plot_curves(path: Path, rows: list[dict[str, Any]], selected_epoch: int) -> None:
    """绘制独立可分享的 NLL/AUC 诊断图。

    :param path: PNG 目标。
    :param rows: 逐轮指标。
    :param selected_epoch: 预先定义规则选定的 checkpoint 轮次。
    :returns: None。
    """
    epochs = [row["epoch"] for row in rows]
    train_nll = [row["train"]["overall"]["nll"] for row in rows]
    val_nll = [row["validation"]["overall"]["nll"] for row in rows]
    train_auc = [row["train"]["overall"]["auc"] for row in rows]
    val_auc = [row["validation"]["overall"]["auc"] for row in rows]
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.2), constrained_layout=True)
    for axis, train, validation, label in ((axes[0], train_nll, val_nll, "NLL (lower is better)"),
                                           (axes[1], train_auc, val_auc, "AUC (higher is better)")):
        axis.plot(epochs, train, label="Train", linewidth=1.6)
        axis.plot(epochs, validation, label="Validation", linewidth=1.6)
        axis.axvline(selected_epoch, color="#9c4dcc", linestyle="--", linewidth=1,
                     label=f"Selected epoch {selected_epoch}")
        axis.set_xlabel("Epoch")
        axis.set_ylabel(label)
        axis.grid(alpha=0.25)
        axis.legend()
    figure.suptitle("MEFKT-NG four-source generalization trajectory")
    figure.savefig(path, dpi=170)
    plt.close(figure)


def write_report(path: Path, rows: list[dict[str, Any]], first: dict[str, Any],
                 final: dict[str, Any]) -> None:
    """根据训练/验证与重复测试写出谨慎的过拟合结论。

    :param path: Markdown 报告目标。
    :param rows: 逐轮指标。
    :param first: 第 120 轮首段最终摘要。
    :param final: 续训最终摘要。
    :returns: None。
    """
    selected = int(final["best_checkpoint"].split("/")[-1].split("_")[1])
    by_epoch = {row["epoch"]: row for row in rows}
    chosen, last = by_epoch[selected], rows[-1]
    raw_best = min(rows, key=lambda row: row["validation"]["overall"]["nll"])
    train_best = chosen["train"]["overall"]
    val_best = chosen["validation"]["overall"]
    train_last = last["train"]["overall"]
    val_last = last["validation"]["overall"]
    lines = [
        "# MEFKT-NG 过拟合诊断",
        "",
        "**结论：未看到明显的过拟合，后期主要是收益趋于平台。** 选定 epoch 136 后，训练 NLL 继续小幅下降，验证 NLL 到 epoch 156 也没有持续回升；按预设 `min_delta=0.0002` 和 patience=20 早停。该判断适用于这套按学习者划分的公开数据，不代表部署课程上的泛化已验证。",
        "",
        f"- 选定 epoch {selected}：训练 NLL {train_best['nll']:.6f}，验证 NLL {val_best['nll']:.6f}，差值 {val_best['nll'] - train_best['nll']:.6f}；训练 AUC {train_best['auc']:.6f}，验证 AUC {val_best['auc']:.6f}。",
        f"- 结束 epoch {last['epoch']}：训练 NLL {train_last['nll']:.6f}，验证 NLL {val_last['nll']:.6f}，差值 {val_last['nll'] - train_last['nll']:.6f}；训练 AUC {train_last['auc']:.6f}，验证 AUC {val_last['auc']:.6f}。",
        f"- 验证 NLL 原始最小值在 epoch {raw_best['epoch']}，为 {raw_best['validation']['overall']['nll']:.6f}；相对选定 epoch 的改进小于 `min_delta`，因此没有替换 checkpoint。",
        f"- 首段选定模型测试 NLL/AUC 为 {first['test']['overall']['nll']:.6f}/{first['test']['overall']['auc']:.6f}；续训后同集复评为 {final['test']['overall']['nll']:.6f}/{final['test']['overall']['auc']:.6f}。改善很小，且测试集已在续训前查看，复评不是新的独立验证。",
        "",
        "| 来源 | 选定轮训练 NLL | 选定轮验证 NLL | 差值 | 结束轮验证 NLL |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for subject, train in chosen["train"]["subjects"].items():
        validation = chosen["validation"]["subjects"][subject]
        final_validation = last["validation"]["subjects"][subject]
        lines.append(f"| {subject} | {train['nll']:.6f} | {validation['nll']:.6f} | "
                     f"{validation['nll'] - train['nll']:+.6f} | {final_validation['nll']:.6f} |")
    lines.extend([
        "",
        "EdNet 和 Junyi 的训练/验证 NLL 差值高于旧来源，但验证曲线没有在后期持续恶化；来源差异、题目原文缺失和学习者切分的难度也会影响差值。若要评估替换线上模型，仍需使用本项目真实课程的独立学习者或未来时间段数据，并单独检查各课程冷启动与校准。",
        "",
        "数据：`epoch_generalization.csv`；图：`nll_auc_curves.png`。",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    """生成桌面过拟合报告、曲线和 CSV。

    :returns: 进程退出码。
    """
    parser = argparse.ArgumentParser(description="分析 MEFKT-NG 训练/验证曲线")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows = load_metrics(args.run_dir / "epoch_metrics.jsonl")
    first = json.loads((args.run_dir / "final_summary_epoch_0120.json").read_text(encoding="utf-8"))
    final = json.loads((args.run_dir / "final_summary_epoch_0156.json").read_text(encoding="utf-8"))
    selected = int(final["best_checkpoint"].split("/")[-1].split("_")[1])
    write_curve_csv(output / "epoch_generalization.csv", rows)
    plot_curves(output / "nll_auc_curves.png", rows, selected)
    write_report(output / "overfitting_report.md", rows, first, final)
    print(json.dumps({"epochs": len(rows), "selected_epoch": selected,
                      "report": str(output / "overfitting_report.md")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
