#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
验证 MEFKT / MEFKT-Lite 新课程未知题目冷启动接口。
@Project : adaptive-edu
@File : validate_mefkt_open_world.py
@Author : Qintsg
@Date : 2026-08-24
'''

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from mefkt_lite_data import _load_prepared
from mefkt_models import build_model


def _parse_args() -> argparse.Namespace:
    """
    解析开放世界验证参数。

    :returns: 命令行参数命名空间。
    """
    parser = argparse.ArgumentParser(description="验证 MEFKT 未知题目动态元数据输入")
    parser.add_argument("--profile", choices=("full", "lite"), required=True)
    parser.add_argument("--data-root", required=True, help="包含 processed/manifest.json 的数据根目录")
    parser.add_argument("--checkpoint", required=True, help="best.pt 或 last.pt")
    parser.add_argument("--cpu-threads", type=int, default=2)
    return parser.parse_args()


def validate(profile: str, data_root: Path, checkpoint_path: Path, cpu_threads: int) -> dict[str, object]:
    """
    加载 checkpoint 并验证未知历史题目和未知候选题。

    :param profile: `full` 或 `lite`。
    :param data_root: 预处理数据根目录。
    :param checkpoint_path: 模型 checkpoint 路径。
    :param cpu_threads: 本次验证使用的 CPU 线程数。
    :returns: 可写入日志的验证结果。
    :raises RuntimeError: 数据、checkpoint 或前向输出不符合契约时抛出。
    """
    prepared = _load_prepared(data_root / "processed")
    if prepared is None:
        raise RuntimeError(f"找不到有效预处理缓存: {data_root / 'processed'}")
    if prepared.item_count < 3 or prepared.item_features.size(1) < 391:
        raise RuntimeError("开放世界验证需要至少 3 道题和 7+384 维题目特征")
    model = build_model(
        profile,
        prepared.item_count,
        prepared.item_features,
        prepared.item_subjects,
        prepared.item_skills,
        len(prepared.subject_vocab),
        len(prepared.skill_vocab),
    )
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    torch.set_num_threads(max(cpu_threads, 1))

    history_items = torch.tensor([[-1, 0]], dtype=torch.long)
    history_correct = torch.tensor([[0, 1]], dtype=torch.long)
    history_gaps = torch.tensor([[1.0, 3.0]], dtype=torch.float32)
    history_response_times = torch.tensor([[18.0, 26.0]], dtype=torch.float32)
    history_features = torch.stack([prepared.item_features[1, :7], prepared.item_features[0, :7]])
    history_content = torch.stack([prepared.item_features[1, 7:], prepared.item_features[0, 7:]])
    candidate_features = prepared.item_features[2:3, :7]
    candidate_content = prepared.item_features[2:3, 7:]
    with torch.no_grad():
        logits, valid_mask, forward_state = model(
            history_items,
            history_correct,
            history_gaps,
            history_response_times,
            sequence_features=history_features.unsqueeze(0),
            sequence_content_features=history_content.unsqueeze(0),
            sequence_valid_mask=torch.tensor([[True, True]]),
        )
        probabilities, state = model.predict_next(
            history_items,
            history_correct,
            history_gaps,
            history_response_times,
            torch.tensor([-1], dtype=torch.long),
            torch.tensor([2.0], dtype=torch.float32),
            history_features=history_features,
            history_content_features=history_content,
            history_valid_mask=torch.tensor([[True, True]]),
            candidate_features=candidate_features,
            candidate_content_features=candidate_content,
        )
        next_logits, next_valid_mask, next_state = model(
            torch.tensor([[-1]], dtype=torch.long),
            torch.tensor([[1]], dtype=torch.long),
            torch.tensor([[4.0]], dtype=torch.float32),
            torch.tensor([[21.0]], dtype=torch.float32),
            initial_state=forward_state,
            sequence_features=candidate_features.unsqueeze(0),
            sequence_content_features=candidate_content.unsqueeze(0),
            sequence_valid_mask=torch.tensor([[True]]),
        )
    finite = (
        bool(torch.isfinite(logits).all())
        and bool(torch.isfinite(forward_state.context).all())
        and bool(torch.isfinite(probabilities).all())
        and bool(torch.isfinite(state.context).all())
        and bool(torch.isfinite(next_logits).all())
        and bool(torch.isfinite(next_state.context).all())
    )
    result = {
        "passed": (
            finite
            and probabilities.shape == (1,)
            and valid_mask.tolist() == [[True, True]]
            and next_valid_mask.tolist() == [[True]]
        ),
        "profile": profile,
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "probability": float(probabilities[0]),
        "state_shape": list(state.context.shape),
        "forward_shape": list(logits.shape),
        "next_window_shape": list(next_logits.shape),
        "state_transfer_shape": list(next_state.context.shape),
        "content_feature_shape": list(candidate_content.shape),
        "finite": finite,
    }
    if not result["passed"]:
        raise RuntimeError(f"开放世界前向验证失败: {result}")
    return result


def main() -> int:
    """
    执行开放世界前向验证并打印 JSON。

    :returns: 进程退出码。
    """
    args = _parse_args()
    result = validate(args.profile, Path(args.data_root), Path(args.checkpoint), args.cpu_threads)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
