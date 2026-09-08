#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
诊断 MEFKT checkpoint 的因果性和分学科泛化指标。
@Project : adaptive-edu
@File : diagnose_mefkt_checkpoint.py
@Author : Qintsg
@Date : 2026-08-30
'''

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from functools import partial
from pathlib import Path

import torch
from mefkt_data_core import SequenceIndexDataset, SequenceStore, collate_sequence_indices
from mefkt_evaluation import calculate_metrics
from mefkt_lite_data import _load_prepared
from mefkt_models import BaseMEFKT, build_model, model_config_from_checkpoint
from torch import Tensor
from torch.nn import functional
from torch.utils.data import DataLoader


def _parse_args() -> argparse.Namespace:
    """
    解析 checkpoint 诊断参数。

    :returns: 命令行参数命名空间。
    """
    parser = argparse.ArgumentParser(description="诊断 MEFKT checkpoint 的因果性和分学科指标")
    parser.add_argument("--profile", choices=("full", "lite"), required=True)
    parser.add_argument("--data-root", required=True, help="包含 processed/manifest.json 的预处理数据目录")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--splits", nargs="+", choices=("validation", "test"), default=("validation", "test"))
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--sequence-length", type=int, default=200)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--output", default="", help="可选的 JSON 输出文件")
    return parser.parse_args()


def _resolve_device(requested: str) -> torch.device:
    """
    解析诊断设备。

    :param requested: auto、cpu 或 cuda。
    :returns: PyTorch 设备。
    :raises RuntimeError: 明确要求 CUDA 但本机不可用时抛出。
    """
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("明确要求 CUDA，但当前环境不可用")
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(requested)


def _make_loader(
    store: SequenceStore,
    batch_size: int,
    sequence_length: int,
    num_workers: int,
) -> DataLoader:
    """
    创建确定性的诊断 DataLoader。

    :param store: 预处理序列存储。
    :param batch_size: batch 大小。
    :param sequence_length: 最大序列长度。
    :param num_workers: 数据加载进程数。
    :returns: 不打乱顺序的 DataLoader。
    """
    return DataLoader(
        SequenceIndexDataset(store),
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=torch.cuda.is_available(),
        collate_fn=partial(collate_sequence_indices, store=store, max_length=sequence_length),
    )


def _prior_bce(positive_rate: float) -> float:
    """
    计算仅预测固定正例率时的最优 BCE。

    :param positive_rate: 数据正例比例。
    :returns: 固定先验 BCE。
    """
    probability = min(max(positive_rate, 1e-12), 1.0 - 1e-12)
    return -(probability * math.log(probability) + (1.0 - probability) * math.log(1.0 - probability))


def _finalize_metrics(probabilities: list[float], targets: list[int], losses: list[float]) -> dict[str, float]:
    """
    汇总一个学科的预测指标和先验基线。

    :param probabilities: 答对概率。
    :param targets: 真实标签。
    :param losses: 单样本 BCE。
    :returns: 带 loss 和固定先验对比的指标。
    """
    metrics = calculate_metrics(probabilities, targets)
    metrics["loss"] = float(sum(losses) / max(len(losses), 1))
    baseline = _prior_bce(metrics["positive_rate"])
    metrics["fixed_prior_loss"] = baseline
    metrics["loss_improvement_over_prior"] = (
        (baseline - metrics["loss"]) / baseline if baseline > 0.0 else 0.0
    )
    return metrics


def evaluate_by_subject(
    model: BaseMEFKT,
    loader: DataLoader,
    device: torch.device,
    item_subjects: Tensor,
    subject_names: Sequence[str],
) -> dict[str, dict[str, float]]:
    """
    计算总指标和每个学科的二分类指标。

    :param model: 待评估 MEFKT 模型。
    :param loader: 数据切分加载器。
    :param device: 模型设备。
    :param item_subjects: 每道题的学科索引。
    :param subject_names: 学科索引对应名称。
    :returns: overall 和每个学科的指标。
    """
    buckets = {
        "overall": {"probabilities": [], "targets": [], "losses": []},
        **{
            str(name): {"probabilities": [], "targets": [], "losses": []}
            for name in subject_names
        },
    }
    subject_lookup = item_subjects.long().to(device)
    model.eval()
    with torch.no_grad():
        for batch in loader:
            items, correct, gaps, response_times, target_mask = (
                value.to(device, non_blocking=True) for value in batch
            )
            logits, valid_mask, _ = model(items, correct, gaps, response_times)
            effective_mask = valid_mask & target_mask
            if not bool(effective_mask.any()):
                continue
            selected_logits = logits[effective_mask]
            selected_targets = correct[effective_mask]
            selected_items = items[effective_mask]
            selected_subjects = subject_lookup[selected_items]
            selected_probabilities = torch.sigmoid(selected_logits)
            selected_losses = functional.binary_cross_entropy_with_logits(
                selected_logits,
                selected_targets.float(),
                reduction="none",
            )
            for name, group_index in (("overall", None), *zip(subject_names, range(len(subject_names)), strict=True)):
                group_mask = (
                    torch.ones_like(selected_targets, dtype=torch.bool)
                    if group_index is None
                    else selected_subjects == group_index
                )
                if not bool(group_mask.any()):
                    continue
                bucket = buckets[str(name)]
                bucket["probabilities"].extend(selected_probabilities[group_mask].cpu().tolist())
                bucket["targets"].extend(selected_targets[group_mask].cpu().tolist())
                bucket["losses"].extend(selected_losses[group_mask].cpu().tolist())
    return {
        name: _finalize_metrics(bucket["probabilities"], bucket["targets"], bucket["losses"])
        for name, bucket in buckets.items()
    }


def check_current_step_causality(
    model: BaseMEFKT,
    batch: tuple[Tensor, Tensor, Tensor, Tensor, Tensor],
    device: torch.device,
) -> dict[str, object]:
    """
    检查当前答案和当前答题耗时是否会影响当前预测。

    :param model: 待检查模型。
    :param batch: 单个真实数据 batch。
    :param device: 模型设备。
    :returns: 最大 logit 差异和是否通过门禁。
    """
    items, correct, gaps, response_times, target_mask = (value.to(device) for value in batch)
    positions = torch.nonzero(target_mask[0] & (items[0] >= 0), as_tuple=False).flatten()
    if positions.numel() == 0:
        raise RuntimeError("诊断 batch 没有有效目标位置")
    sampled_positions = sorted({int(positions[0]), int(positions[len(positions) // 2]), int(positions[-1])})
    answer_deltas: list[float] = []
    response_time_deltas: list[float] = []
    model.eval()
    with torch.no_grad():
        baseline = model(items, correct, gaps, response_times)[0]
        for position in sampled_positions:
            changed_correct = correct.clone()
            changed_correct[0, position] = 1 - changed_correct[0, position]
            changed_answer_logits = model(items, changed_correct, gaps, response_times)[0]
            answer_deltas.append(float((baseline[0, position] - changed_answer_logits[0, position]).abs().item()))

            changed_response_times = response_times.clone()
            changed_response_times[0, position] = changed_response_times[0, position] * 10.0 + 1.0
            changed_time_logits = model(items, correct, gaps, changed_response_times)[0]
            response_time_deltas.append(float((baseline[0, position] - changed_time_logits[0, position]).abs().item()))
    tolerance = 1e-6
    answer_max = max(answer_deltas, default=0.0)
    response_time_max = max(response_time_deltas, default=0.0)
    return {
        "sampled_positions": sampled_positions,
        "current_answer_logit_max_abs_delta": answer_max,
        "current_response_time_logit_max_abs_delta": response_time_max,
        "tolerance": tolerance,
        "passed": answer_max <= tolerance and response_time_max <= tolerance,
    }


def main() -> int:
    """
    加载 checkpoint 并输出诊断结果。

    :returns: 诊断通过时返回 0，否则返回 1。
    """
    args = _parse_args()
    if args.batch_size < 1 or args.sequence_length < 1 or args.num_workers < 0:
        raise ValueError("batch-size 和 sequence-length 必须为正数，num-workers 不能为负数")
    data_root = Path(args.data_root)
    prepared = _load_prepared(data_root / "processed") or _load_prepared(data_root)
    if prepared is None:
        raise RuntimeError(f"找不到有效预处理缓存: {data_root / 'processed'}")
    checkpoint = torch.load(Path(args.checkpoint), map_location="cpu", weights_only=False)
    config = model_config_from_checkpoint(checkpoint, args.profile)
    model = build_model(
        args.profile,
        prepared.item_count,
        prepared.item_features,
        prepared.item_subjects,
        prepared.item_skills,
        len(prepared.subject_vocab),
        len(prepared.skill_vocab),
        config,
    )
    model.load_state_dict(checkpoint["model_state_dict"])
    device = _resolve_device(args.device)
    model = model.to(device)

    first_store = SequenceStore(prepared.root, args.splits[0])
    first_batch = collate_sequence_indices([0], first_store, args.sequence_length)
    causality = check_current_step_causality(model, first_batch, device)
    split_metrics = {}
    for split in args.splits:
        store = SequenceStore(prepared.root, split)
        loader = _make_loader(store, args.batch_size, args.sequence_length, args.num_workers)
        split_metrics[split] = evaluate_by_subject(
            model,
            loader,
            device,
            prepared.item_subjects,
            prepared.subject_vocab,
        )
    result = {
        "schema": "mefkt-checkpoint-diagnosis-v1",
        "checkpoint": str(Path(args.checkpoint).resolve()),
        "checkpoint_epoch_index": checkpoint.get("epoch"),
        "device": str(device),
        "causality": causality,
        "metrics": split_metrics,
    }
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized, encoding="utf-8")
    print(serialized)
    return 0 if bool(causality["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
