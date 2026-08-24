#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
从新课程少量标注交互拟合 MEFKT 两参数课程适配器。
@Project : adaptive-edu
@File : fit_mefkt_course_adapter.py
@Author : Qintsg
@Date : 2026-08-24
'''

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import torch
from evaluate_mefkt_unseen_course import _metric
from mefkt_course_adapter import CourseLogitAdapter
from torch.nn import functional


def _parse_args() -> argparse.Namespace:
    """
    解析课程适配器拟合参数。

    :returns: 命令行参数命名空间。
    """
    parser = argparse.ArgumentParser(description="拟合 MEFKT 新课程两参数校准器")
    parser.add_argument("--predictions-file", required=True, help="未见课程评估器导出的 CSV")
    parser.add_argument("--output", required=True, help="适配器 JSON 输出")
    parser.add_argument("--course-id", required=True)
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--min-samples", type=int, default=200)
    return parser.parse_args()


def _validation_user(user_id: str) -> bool:
    """
    用稳定用户 hash 选择约 20% 校准验证用户。

    :param user_id: 学习者 ID。
    :returns: 是否属于验证切分。
    """
    digest = hashlib.blake2b(user_id.encode("utf-8"), digest_size=2).digest()
    return int.from_bytes(digest, "big") % 5 == 0


def _load_predictions(path: Path) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """
    读取基础模型预测并构造学习者级 train/validation mask。

    :param path: 包含 user_id、logit、correct 的 CSV。
    :returns: logits、标签和验证 mask。
    """
    logits: list[float] = []
    targets: list[float] = []
    validation: list[bool] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            logits.append(float(row["logit"]))
            targets.append(float(int(row["correct"])))
            validation.append(_validation_user(str(row["user_id"])))
    return (
        torch.tensor(logits, dtype=torch.float32),
        torch.tensor(targets, dtype=torch.float32),
        torch.tensor(validation, dtype=torch.bool),
    )


def fit_adapter(
    logits: torch.Tensor,
    targets: torch.Tensor,
    validation_mask: torch.Tensor,
    *,
    steps: int,
    learning_rate: float,
    min_samples: int,
) -> tuple[CourseLogitAdapter, dict[str, object]]:
    """
    只优化温度和偏置，并按验证 NLL 选择最佳状态。

    :param logits: 冻结基础模型 logits。
    :param targets: 0/1 正确性标签。
    :param validation_mask: 学习者级验证 mask。
    :param steps: 最大优化步数。
    :param learning_rate: Adam 学习率。
    :param min_samples: 允许拟合的最小标注数。
    :returns: 最佳适配器和拟合统计。
    """
    if logits.ndim != 1 or targets.shape != logits.shape or validation_mask.shape != logits.shape:
        raise ValueError("logits、targets 和 validation_mask 必须是一维等长张量")
    if logits.numel() < min_samples:
        raise ValueError(f"课程交互不足: samples={logits.numel()} min_samples={min_samples}")
    train_mask = ~validation_mask
    if not bool(train_mask.any()) or not bool(validation_mask.any()):
        raise ValueError("课程适配器需要非空的学习者级训练和验证切分")
    adapter = CourseLogitAdapter()
    optimizer = torch.optim.Adam(adapter.parameters(), lr=learning_rate)
    best_loss = float("inf")
    best_state: dict[str, torch.Tensor] | None = None
    for _ in range(max(steps, 1)):
        optimizer.zero_grad(set_to_none=True)
        loss = functional.binary_cross_entropy_with_logits(adapter(logits[train_mask]), targets[train_mask])
        loss.backward()
        optimizer.step()
        with torch.no_grad():
            validation_loss = float(
                functional.binary_cross_entropy_with_logits(
                    adapter(logits[validation_mask]),
                    targets[validation_mask],
                )
            )
        if validation_loss < best_loss:
            best_loss = validation_loss
            best_state = {name: value.detach().clone() for name, value in adapter.state_dict().items()}
    if best_state is not None:
        adapter.load_state_dict(best_state)
    with torch.no_grad():
        base_probabilities = torch.sigmoid(logits[validation_mask]).tolist()
        adapted_probabilities = torch.sigmoid(adapter(logits[validation_mask])).tolist()
    validation_targets = targets[validation_mask].int().tolist()
    return adapter, {
        "samples": int(logits.numel()),
        "train_samples": int(train_mask.sum()),
        "validation_samples": int(validation_mask.sum()),
        "base_validation": _metric(base_probabilities, validation_targets),
        "adapted_validation": _metric(adapted_probabilities, validation_targets),
        "best_validation_nll": best_loss,
    }


def main() -> int:
    """
    拟合适配器并写出 JSON artifact。

    :returns: 进程退出码。
    """
    args = _parse_args()
    predictions_path = Path(args.predictions_file).resolve()
    logits, targets, validation_mask = _load_predictions(predictions_path)
    adapter, metrics = fit_adapter(
        logits,
        targets,
        validation_mask,
        steps=args.steps,
        learning_rate=args.learning_rate,
        min_samples=args.min_samples,
    )
    artifact = {
        "schema": "mefkt_course_logit_adapter_v1",
        "course_id": args.course_id,
        "parameters": adapter.config().to_dict(),
        "trainable_parameters": sum(parameter.numel() for parameter in adapter.parameters()),
        "predictions_file": predictions_path.name,
        "metrics": metrics,
    }
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(artifact, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
