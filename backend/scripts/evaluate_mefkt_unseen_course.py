#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
评估 MEFKT 在未见题目/未见课程 CSV 上的冷启动能力。
@Project : adaptive-edu
@File : evaluate_mefkt_unseen_course.py
@Author : Qintsg
@Date : 2026-08-24
'''

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from mefkt_canonical_data import _parse_correct, _parse_timestamp
from mefkt_lite_data import _load_prepared
from mefkt_models import build_model, model_config_from_checkpoint


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


def _parse_args() -> argparse.Namespace:
    """
    解析冷启动评估参数。

    :returns: 命令行参数命名空间。
    """
    parser = argparse.ArgumentParser(description="评估 MEFKT 未见课程冷启动")
    parser.add_argument("--profile", choices=("full", "lite"), required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--events-file", required=True)
    parser.add_argument("--content-embeddings-file", required=True)
    parser.add_argument("--max-users", type=int, default=0)
    parser.add_argument("--sequence-length", type=int, default=200)
    parser.add_argument("--cpu-threads", type=int, default=2)
    parser.add_argument("--predictions-output", default="", help="可选：导出 user_id,logit,correct CSV")
    return parser.parse_args()


def _metric(probabilities: list[float], targets: list[int]) -> dict[str, float]:
    """
    计算冷启动评估指标。

    :param probabilities: 预测为正确的概率。
    :param targets: 真实 0/1 标签。
    :returns: AUC、准确率、Brier、ECE 与常数 baseline。
    """
    values = np.asarray(probabilities, dtype=np.float64)
    labels = np.asarray(targets, dtype=np.int64)
    if labels.size == 0:
        return {
            "auc": 0.5,
            "acc": 0.0,
            "brier": 0.0,
            "ece": 0.0,
            "samples": 0.0,
            "positive_rate": 0.0,
            "majority_acc": 0.0,
            "constant_rate_brier": 0.0,
        }
    ranks = _average_ranks(values)
    positive = int(labels.sum())
    negative = len(labels) - positive
    auc = 0.5 if not positive or not negative else float(
        (ranks[labels == 1].sum() - positive * (positive + 1) / 2) / (positive * negative)
    )
    ece = 0.0
    for lower in np.linspace(0.0, 0.9, 10):
        upper = lower + 0.1
        mask = (values >= lower) & ((values < upper) if upper < 1.0 else (values <= upper))
        if mask.any():
            ece += float(mask.mean()) * abs(float(values[mask].mean()) - float(labels[mask].mean()))
    positive_rate = float(labels.mean())
    return {
        "auc": auc,
        "acc": float(((values >= 0.5).astype(np.int64) == labels).mean()),
        "brier": float(np.mean((values - labels) ** 2)),
        "ece": ece,
        "samples": float(labels.size),
        "positive_rate": positive_rate,
        "majority_acc": max(positive_rate, 1.0 - positive_rate),
        "constant_rate_brier": positive_rate * (1.0 - positive_rate),
    }


def _bucket_metrics(
    values: list[float],
    probabilities: list[float],
    targets: list[int],
    boundaries: tuple[float, ...],
    names: tuple[str, ...],
) -> dict[str, dict[str, float]]:
    """
    按固定时间边界计算分桶指标。

    :param values: gap 或 response time 数值。
    :param probabilities: 对应预测概率。
    :param targets: 对应 0/1 标签。
    :param boundaries: 递增分桶上界。
    :param names: 比上界多一个的分桶名称。
    :returns: 每个非空分桶的指标。
    """
    if len(names) != len(boundaries) + 1:
        raise ValueError("分桶名称数量必须比边界数量多 1")
    buckets: dict[str, tuple[list[float], list[int]]] = {
        name: ([], []) for name in names
    }
    for value, probability, target in zip(values, probabilities, targets, strict=True):
        index = next((position for position, upper in enumerate(boundaries) if value <= upper), len(boundaries))
        buckets[names[index]][0].append(probability)
        buckets[names[index]][1].append(target)
    return {
        name: _metric(bucket_probabilities, bucket_targets)
        for name, (bucket_probabilities, bucket_targets) in buckets.items()
        if bucket_targets
    }


def _load_events(path: Path, max_users: int) -> dict[str, list[dict[str, str]]]:
    """
    读取并按学习者整理 canonical CSV。

    :param path: canonical CSV 路径。
    :param max_users: 最大学习者数，0 表示不限制。
    :returns: 按学习者 ID 分组且按时间排序的交互。
    """
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            user_id = str(row.get("user_id") or "").strip()
            if not user_id:
                continue
            if max_users and user_id not in grouped and len(grouped) >= max_users:
                continue
            grouped[user_id].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: _parse_timestamp(row.get("timestamp")))
    return grouped


def _external_skill_mapping(groups: dict[str, list[dict[str, str]]]) -> dict[str, int]:
    """
    为未见课程知识点生成课程内稳定索引。

    :param groups: 按学习者分组的 canonical 交互。
    :returns: skill token 到课程内连续索引的映射。
    """
    tokens = {
        token.strip()
        for rows in groups.values()
        for row in rows
        for token in str(row.get("skill_ids") or "").replace(";", "|").replace(",", "|").split("|")
        if token.strip()
    }
    return {token: index for index, token in enumerate(sorted(tokens))}


def _window_skill_indices(
    window: list[dict[str, str]],
    skill_mapping: dict[str, int],
    max_skills: int,
) -> torch.Tensor:
    """
    将一个未见课程窗口编码为外部 skill 索引张量。

    :param window: canonical 交互窗口。
    :param skill_mapping: 课程内稳定 skill 映射。
    :param max_skills: 模型每题支持的最大知识点数量。
    :returns: `[1, length, max_skills]` 索引，-1 表示 padding。
    """
    result = torch.full((1, len(window), max_skills), -1, dtype=torch.long)
    for row_index, row in enumerate(window):
        tokens = str(row.get("skill_ids") or "").replace(";", "|").replace(",", "|").split("|")
        indices = [skill_mapping[token.strip()] for token in tokens if token.strip() in skill_mapping]
        if indices:
            result[0, row_index, : min(len(indices), max_skills)] = torch.tensor(indices[:max_skills])
    return result


def evaluate(
    profile: str,
    data_root: Path,
    checkpoint: Path,
    events_file: Path,
    content_file: Path,
    max_users: int,
    sequence_length: int,
    cpu_threads: int,
    predictions_output: Path | None = None,
) -> dict[str, object]:
    """
    以所有题目为 OOV，使用外部内容向量与课程内稳定 skill 索引进行评估。

    :param profile: `full` 或 `lite`。
    :param data_root: 训练集预处理根目录。
    :param checkpoint: 基础模型 checkpoint。
    :param events_file: 未见课程 canonical CSV。
    :param content_file: 全部题目的内容向量 sidecar。
    :param max_users: 学习者上限。
    :param sequence_length: 单个评估窗口长度。
    :param cpu_threads: CPU 线程数。
    :param predictions_output: 可选的基础 logits CSV 输出。
    :returns: 评估指标。
    """
    prepared = _load_prepared(data_root / "processed")
    if prepared is None:
        raise RuntimeError("训练数据缓存不存在")
    checkpoint_data = torch.load(checkpoint, map_location="cpu", weights_only=False)
    config = model_config_from_checkpoint(checkpoint_data, profile)
    model = build_model(profile, prepared.item_count, prepared.item_features, prepared.item_subjects, prepared.item_skills, len(prepared.subject_vocab), len(prepared.skill_vocab), config)
    model.load_state_dict(checkpoint_data["model_state_dict"])
    model.eval()
    torch.set_num_threads(max(cpu_threads, 1))
    groups = _load_events(events_file, max_users)
    skill_mapping = _external_skill_mapping(groups)
    with np.load(content_file, allow_pickle=False) as archive:
        content_ids = [str(value) for value in archive["item_ids"].tolist()]
        content_values = np.asarray(archive["embeddings"], dtype=np.float32)
    content_map = dict(zip(content_ids, content_values, strict=True))
    probabilities: list[float] = []
    raw_logits: list[float] = []
    targets: list[int] = []
    prediction_users: list[str] = []
    evaluated_gaps: list[float] = []
    evaluated_response_times: list[float] = []
    with torch.no_grad():
        for user_id, rows in groups.items():
            state = None
            for start in range(0, len(rows), sequence_length):
                window = rows[start : start + sequence_length]
                if len(window) < 2:
                    continue
                item_count = len(window)
                items = torch.full((1, item_count), -1, dtype=torch.long)
                correct = torch.tensor([[_parse_correct(row) for row in window]], dtype=torch.long)
                timestamps = [_parse_timestamp(row.get("timestamp")) for row in window]
                gaps = []
                for index, timestamp in enumerate(timestamps):
                    absolute_index = start + index
                    if absolute_index == 0:
                        gaps.append(1.0)
                        continue
                    previous_timestamp = _parse_timestamp(rows[absolute_index - 1].get("timestamp"))
                    gaps.append(max((timestamp - previous_timestamp) / 3600.0, 1 / 3600))
                response = [max(0.1, min(float(row.get("response_time_seconds") or 10.0), 3600.0)) for row in window]
                numeric = torch.full((1, item_count, 7), 0.5, dtype=torch.float32)
                content = torch.stack([
                    torch.from_numpy(content_map.get(str(row.get("item_id")), np.zeros(384, dtype=np.float32)))
                    for row in window
                ]).unsqueeze(0)
                external_skills = _window_skill_indices(
                    window,
                    skill_mapping,
                    int(prepared.item_skills.size(1)),
                )
                logits, mask, state = model(
                    items,
                    correct,
                    torch.tensor([gaps], dtype=torch.float32),
                    torch.tensor([response], dtype=torch.float32),
                    initial_state=state,
                    sequence_features=numeric,
                    sequence_content_features=content,
                    sequence_valid_mask=torch.ones((1, item_count), dtype=torch.bool),
                    sequence_skill_indices=external_skills if config.architecture_version >= 3 else None,
                )
                state = state.detach()
                selected_logits = logits[mask].cpu().tolist()
                selected_targets = correct[mask].cpu().tolist()
                raw_logits.extend(selected_logits)
                probabilities.extend(torch.sigmoid(logits[mask]).cpu().tolist())
                targets.extend(selected_targets)
                prediction_users.extend([user_id] * len(selected_targets))
                evaluated_gaps.extend(gaps)
                evaluated_response_times.extend(response)
    if predictions_output is not None:
        predictions_output.parent.mkdir(parents=True, exist_ok=True)
        with predictions_output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=("user_id", "logit", "correct"))
            writer.writeheader()
            writer.writerows(
                {"user_id": user_id, "logit": logit, "correct": target}
                for user_id, logit, target in zip(prediction_users, raw_logits, targets, strict=True)
            )
    return {
        "profile": profile,
        "users": len(groups),
        "unseen_item_mode": True,
        "external_skill_count": len(skill_mapping),
        **_metric(probabilities, targets),
        "gap_buckets": _bucket_metrics(
            evaluated_gaps,
            probabilities,
            targets,
            (1.0, 24.0, 168.0),
            ("le_1h", "1h_to_24h", "24h_to_7d", "gt_7d"),
        ),
        "response_time_buckets": _bucket_metrics(
            evaluated_response_times,
            probabilities,
            targets,
            (10.0, 30.0, 60.0),
            ("le_10s", "10s_to_30s", "30s_to_60s", "gt_60s"),
        ),
    }


def main() -> int:
    """
    执行冷启动评估并打印 JSON。

    :returns: 进程退出码。
    """
    args = _parse_args()
    result = evaluate(
        args.profile,
        Path(args.data_root),
        Path(args.checkpoint),
        Path(args.events_file),
        Path(args.content_embeddings_file),
        args.max_users,
        args.sequence_length,
        args.cpu_threads,
        Path(args.predictions_output).resolve() if args.predictions_output else None,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
