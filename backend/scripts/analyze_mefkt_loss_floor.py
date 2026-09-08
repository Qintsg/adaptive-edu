#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
分析 MEFKT 数据标签熵、先验基线和在线能力模型的 BCE 下界。
@Project : adaptive-edu
@File : analyze_mefkt_loss_floor.py
@Author : Qintsg
@Date : 2026-09-01
'''

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class SplitArrays:
    """一个预处理数据切分的紧凑序列数组。"""

    items: np.ndarray
    correct: np.ndarray
    offsets: np.ndarray
    target_starts: np.ndarray


def _parse_args() -> argparse.Namespace:
    """
    解析 loss 下界分析参数。

    :returns: 命令行参数。
    """
    parser = argparse.ArgumentParser(description="分析 MEFKT 的可学习 BCE 空间")
    parser.add_argument("--data-root", required=True, help="包含 processed/manifest.json 的预处理数据根目录")
    parser.add_argument("--metrics-file", default="", help="可选的 MEFKT training_metrics.csv")
    parser.add_argument("--output", default="", help="可选的 JSON 诊断输出")
    parser.add_argument("--target-loss", type=float, default=0.45, help="用户期望达到的 validation BCE")
    return parser.parse_args()


def _load_split(root: Path, split: str) -> SplitArrays:
    """
    通过 mmap 加载一个切分。

    :param root: processed 目录。
    :param split: train、validation 或 test。
    :returns: 紧凑序列数组。
    """
    return SplitArrays(
        items=np.load(root / f"{split}_items.npy", mmap_mode="r"),
        correct=np.load(root / f"{split}_correct.npy", mmap_mode="r"),
        offsets=np.load(root / f"{split}_offsets.npy", mmap_mode="r"),
        target_starts=np.load(root / f"{split}_target_starts.npy", mmap_mode="r"),
    )


def _target_vectors(split: SplitArrays) -> tuple[np.ndarray, np.ndarray]:
    """
    提取不重复计权的目标题目和标签。

    :param split: 紧凑序列数据。
    :returns: 题目索引和 0/1 标签。
    """
    item_parts: list[np.ndarray] = []
    correct_parts: list[np.ndarray] = []
    for sequence_index in range(len(split.offsets) - 1):
        start = int(split.offsets[sequence_index])
        end = int(split.offsets[sequence_index + 1])
        target_start = min(int(split.target_starts[sequence_index]), end - start)
        item_parts.append(np.asarray(split.items[start + target_start : end], dtype=np.int64))
        correct_parts.append(np.asarray(split.correct[start + target_start : end], dtype=np.float64))
    return np.concatenate(item_parts), np.concatenate(correct_parts)


def _safe_logit(probabilities: np.ndarray) -> np.ndarray:
    """
    将概率转换为有限 logit。

    :param probabilities: 概率数组。
    :returns: logit 数组。
    """
    clipped = np.clip(probabilities, 1e-6, 1.0 - 1e-6)
    return np.log(clipped) - np.log1p(-clipped)


def _sigmoid(values: np.ndarray | float) -> np.ndarray | float:
    """
    数值稳定地计算 sigmoid。

    :param values: 标量或数组 logit。
    :returns: 概率。
    """
    clipped = np.clip(values, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _binary_metrics(probabilities: np.ndarray, targets: np.ndarray) -> dict[str, float]:
    """
    计算 BCE、Brier、准确率和正例比例。

    :param probabilities: 预测概率。
    :param targets: 0/1 标签。
    :returns: 指标字典。
    """
    clipped = np.clip(probabilities.astype(np.float64), 1e-7, 1.0 - 1e-7)
    gold = targets.astype(np.float64)
    loss = -np.mean(gold * np.log(clipped) + (1.0 - gold) * np.log1p(-clipped))
    return {
        "loss": float(loss),
        "brier": float(np.mean((clipped - gold) ** 2)),
        "accuracy": float(np.mean((clipped >= 0.5) == gold)),
        "positive_rate": float(np.mean(gold)),
        "samples": int(len(gold)),
    }


def _group_metrics(
    probabilities: np.ndarray,
    targets: np.ndarray,
    items: np.ndarray,
    item_subjects: np.ndarray,
    subject_names: tuple[str, ...],
) -> dict[str, dict[str, float]]:
    """
    计算总体和分学科指标。

    :param probabilities: 预测概率。
    :param targets: 标签。
    :param items: 题目索引。
    :param item_subjects: 题目学科索引。
    :param subject_names: 学科名称。
    :returns: 总体及各学科指标。
    """
    result = {"overall": _binary_metrics(probabilities, targets)}
    subjects = item_subjects[items]
    for subject_index, name in enumerate(subject_names):
        mask = subjects == subject_index
        if np.any(mask):
            result[name] = _binary_metrics(probabilities[mask], targets[mask])
    return result


def _counts(items: np.ndarray, correct: np.ndarray, item_count: int) -> tuple[np.ndarray, np.ndarray]:
    """
    统计每道题的目标次数和答对次数。

    :param items: 题目索引。
    :param correct: 0/1 标签。
    :param item_count: 题目总数。
    :returns: 次数和答对次数。
    """
    attempts = np.bincount(items, minlength=item_count).astype(np.float64)
    successes = np.bincount(items, weights=correct, minlength=item_count).astype(np.float64)
    return attempts, successes


def _subject_priors(
    train_items: np.ndarray,
    train_correct: np.ndarray,
    item_subjects: np.ndarray,
    subject_count: int,
) -> np.ndarray:
    """
    计算训练集分学科正例先验。

    :param train_items: 训练题目索引。
    :param train_correct: 训练标签。
    :param item_subjects: 题目学科索引。
    :param subject_count: 学科数量。
    :returns: 每个学科的正例先验。
    """
    subjects = item_subjects[train_items]
    attempts = np.bincount(subjects, minlength=subject_count).astype(np.float64)
    successes = np.bincount(subjects, weights=train_correct, minlength=subject_count).astype(np.float64)
    global_prior = float(np.mean(train_correct))
    return np.divide(
        successes,
        attempts,
        out=np.full(subject_count, global_prior, dtype=np.float64),
        where=attempts > 0,
    )


def _smoothed_item_probabilities(
    attempts: np.ndarray,
    successes: np.ndarray,
    item_subjects: np.ndarray,
    subject_priors: np.ndarray,
    strength: float,
) -> np.ndarray:
    """
    使用分学科先验平滑题目答对率。

    :param attempts: 每题训练次数。
    :param successes: 每题训练答对次数。
    :param item_subjects: 题目学科索引。
    :param subject_priors: 学科正例先验。
    :param strength: 先验等效样本数。
    :returns: 平滑后的题目答对概率。
    """
    priors = subject_priors[item_subjects]
    return (successes + strength * priors) / (attempts + strength)


def _online_ability_probabilities(
    split: SplitArrays,
    item_logits: np.ndarray,
    learning_rate: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    用题目难度和序列内在线能力残差预测目标。

    :param split: validation 或 test 紧凑序列。
    :param item_logits: 训练集题目先验 logit。
    :param learning_rate: 每次作答后的能力更新速度。
    :returns: 目标概率、目标标签和题目索引。
    """
    probabilities: list[float] = []
    targets: list[int] = []
    target_items: list[int] = []
    for sequence_index in range(len(split.offsets) - 1):
        start = int(split.offsets[sequence_index])
        end = int(split.offsets[sequence_index + 1])
        target_start = min(int(split.target_starts[sequence_index]), end - start)
        ability = 0.0
        for position, absolute_index in enumerate(range(start, end)):
            item = int(split.items[absolute_index])
            target = int(split.correct[absolute_index])
            probability = float(_sigmoid(float(item_logits[item]) + ability))
            if position >= target_start:
                probabilities.append(probability)
                targets.append(target)
                target_items.append(item)
            ability = float(np.clip(ability + learning_rate * (target - probability), -3.0, 3.0))
    return (
        np.asarray(probabilities, dtype=np.float64),
        np.asarray(targets, dtype=np.float64),
        np.asarray(target_items, dtype=np.int64),
    )


def _leave_one_out_item_oracle(
    items: np.ndarray,
    targets: np.ndarray,
    item_subjects: np.ndarray,
    subject_priors: np.ndarray,
    strength: float,
    item_count: int,
) -> np.ndarray:
    """
    构造使用同切分其他标签的 leave-one-out 题目概率上界。

    该指标不可部署，只用于估计题目标识本身能解释多少标签熵。

    :param items: 当前切分题目索引。
    :param targets: 当前切分标签。
    :param item_subjects: 题目学科索引。
    :param subject_priors: 训练集学科先验。
    :param strength: 先验等效样本数。
    :param item_count: 题目数。
    :returns: leave-one-out 概率。
    """
    attempts, successes = _counts(items, targets, item_count)
    priors = subject_priors[item_subjects[items]]
    numerator = successes[items] - targets + strength * priors
    denominator = attempts[items] - 1.0 + strength
    return numerator / np.maximum(denominator, 1e-6)


def _model_metrics(metrics_file: Path) -> dict[str, object]:
    """
    提取 MEFKT 最佳 loss、最佳 AUC 和停止轮指标。

    :param metrics_file: training_metrics.csv。
    :returns: 模型指标摘要。
    """
    with metrics_file.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    valid = [row for row in rows if row.get("validation_loss")]
    best_loss = min(valid, key=lambda row: float(row["validation_loss"]))
    best_auc = max(valid, key=lambda row: float(row["validation_auc"]))
    return {
        "epochs": len(rows),
        "best_loss": {
            "epoch": int(best_loss["epoch"]),
            "validation_loss": float(best_loss["validation_loss"]),
            "validation_auc": float(best_loss["validation_auc"]),
            "test_loss": float(best_loss["test_loss"]),
            "test_auc": float(best_loss["test_auc"]),
        },
        "best_auc": {
            "epoch": int(best_auc["epoch"]),
            "validation_loss": float(best_auc["validation_loss"]),
            "validation_auc": float(best_auc["validation_auc"]),
            "test_loss": float(best_auc["test_loss"]),
            "test_auc": float(best_auc["test_auc"]),
        },
        "last": {
            "epoch": int(rows[-1]["epoch"]),
            "train_loss": float(rows[-1]["loss"]),
            "validation_loss": float(rows[-1]["validation_loss"]),
            "stop_reason": rows[-1].get("stop_reason", ""),
        },
    }


def main() -> int:
    """
    运行全部 BCE 基线并输出 JSON。

    :returns: 当前模型未达到目标 loss 时返回 1，否则返回 0。
    """
    args = _parse_args()
    processed = Path(args.data_root) / "processed"
    manifest = json.loads((processed / "manifest.json").read_text(encoding="utf-8"))
    subject_names = tuple(json.loads((processed / "subject_vocab.json").read_text(encoding="utf-8")))
    item_subjects = np.load(processed / "item_subjects.npy").astype(np.int64)
    item_count = int(manifest["item_count"])
    train = _load_split(processed, "train")
    validation = _load_split(processed, "validation")
    test = _load_split(processed, "test")
    train_items, train_correct = _target_vectors(train)
    validation_items, validation_correct = _target_vectors(validation)
    test_items, test_correct = _target_vectors(test)

    subject_priors = _subject_priors(train_items, train_correct, item_subjects, len(subject_names))
    global_prior = float(np.mean(train_correct))
    train_attempts, train_successes = _counts(train_items, train_correct, item_count)

    global_validation_probabilities = np.full(len(validation_correct), global_prior)
    global_test_probabilities = np.full(len(test_correct), global_prior)
    subject_validation_probabilities = subject_priors[item_subjects[validation_items]]
    subject_test_probabilities = subject_priors[item_subjects[test_items]]

    strength_candidates = (1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0)
    item_trials: list[dict[str, float]] = []
    best_item_loss = math.inf
    best_strength = strength_candidates[0]
    best_item_probabilities = np.empty(item_count)
    for strength in strength_candidates:
        item_probabilities = _smoothed_item_probabilities(
            train_attempts,
            train_successes,
            item_subjects,
            subject_priors,
            strength,
        )
        loss = _binary_metrics(item_probabilities[validation_items], validation_correct)["loss"]
        item_trials.append({"strength": strength, "validation_loss": loss})
        if loss < best_item_loss:
            best_item_loss = loss
            best_strength = strength
            best_item_probabilities = item_probabilities

    item_logits = _safe_logit(best_item_probabilities)
    ability_candidates = (0.02, 0.05, 0.1, 0.2, 0.4, 0.8)
    ability_trials: list[dict[str, float]] = []
    best_ability_loss = math.inf
    best_ability_rate = ability_candidates[0]
    best_ability_validation: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
    for learning_rate in ability_candidates:
        prediction = _online_ability_probabilities(validation, item_logits, learning_rate)
        loss = _binary_metrics(prediction[0], prediction[1])["loss"]
        ability_trials.append({"learning_rate": learning_rate, "validation_loss": loss})
        if loss < best_ability_loss:
            best_ability_loss = loss
            best_ability_rate = learning_rate
            best_ability_validation = prediction
    assert best_ability_validation is not None
    best_ability_test = _online_ability_probabilities(test, item_logits, best_ability_rate)

    oracle_validation = _leave_one_out_item_oracle(
        validation_items,
        validation_correct,
        item_subjects,
        subject_priors,
        best_strength,
        item_count,
    )
    oracle_test = _leave_one_out_item_oracle(
        test_items,
        test_correct,
        item_subjects,
        subject_priors,
        best_strength,
        item_count,
    )

    result: dict[str, object] = {
        "schema": "mefkt-loss-floor-analysis-v1",
        "target_loss": args.target_loss,
        "data": {
            "items": item_count,
            "subjects": subject_names,
            "train_targets": len(train_correct),
            "validation_targets": len(validation_correct),
            "test_targets": len(test_correct),
            "train_positive_rate": global_prior,
            "subject_priors": {
                name: float(subject_priors[index]) for index, name in enumerate(subject_names)
            },
            "items_unseen_in_train": int(np.sum(train_attempts == 0)),
        },
        "baselines": {
            "global_prior": {
                "validation": _group_metrics(
                    global_validation_probabilities,
                    validation_correct,
                    validation_items,
                    item_subjects,
                    subject_names,
                ),
                "test": _group_metrics(
                    global_test_probabilities,
                    test_correct,
                    test_items,
                    item_subjects,
                    subject_names,
                ),
            },
            "subject_prior": {
                "validation": _group_metrics(
                    subject_validation_probabilities,
                    validation_correct,
                    validation_items,
                    item_subjects,
                    subject_names,
                ),
                "test": _group_metrics(
                    subject_test_probabilities,
                    test_correct,
                    test_items,
                    item_subjects,
                    subject_names,
                ),
            },
            "smoothed_item_prior": {
                "selected_strength": best_strength,
                "trials": item_trials,
                "validation": _group_metrics(
                    best_item_probabilities[validation_items],
                    validation_correct,
                    validation_items,
                    item_subjects,
                    subject_names,
                ),
                "test": _group_metrics(
                    best_item_probabilities[test_items],
                    test_correct,
                    test_items,
                    item_subjects,
                    subject_names,
                ),
            },
            "item_plus_online_ability": {
                "selected_learning_rate": best_ability_rate,
                "trials": ability_trials,
                "validation": _group_metrics(
                    best_ability_validation[0],
                    best_ability_validation[1],
                    best_ability_validation[2],
                    item_subjects,
                    subject_names,
                ),
                "test": _group_metrics(
                    best_ability_test[0],
                    best_ability_test[1],
                    best_ability_test[2],
                    item_subjects,
                    subject_names,
                ),
            },
            "leave_one_out_item_oracle": {
                "note": "不可部署；使用同切分其他标签估计题目概率",
                "validation": _group_metrics(
                    oracle_validation,
                    validation_correct,
                    validation_items,
                    item_subjects,
                    subject_names,
                ),
                "test": _group_metrics(
                    oracle_test,
                    test_correct,
                    test_items,
                    item_subjects,
                    subject_names,
                ),
            },
        },
    }
    if args.metrics_file:
        result["model"] = _model_metrics(Path(args.metrics_file))
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized, encoding="utf-8")
    print(serialized)
    model = result.get("model")
    if isinstance(model, dict):
        best_loss = model.get("best_loss")
        if isinstance(best_loss, dict) and float(best_loss["validation_loss"]) > args.target_loss:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
