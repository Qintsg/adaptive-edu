#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
独立验证 MEFKT checkpoint 的 CPU/GPU 运行时门禁。
@Project : adaptive-edu
@File : validate_mefkt_checkpoint.py
@Author : Qintsg
@Date : 2026-08-25
'''

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from mefkt_lite_data import _load_prepared
from mefkt_models import build_model, model_config_from_checkpoint
from mefkt_runtime import runtime_validate


def _parse_args() -> argparse.Namespace:
    """
    解析 checkpoint 运行时验证参数。

    :returns: 命令行参数命名空间。
    """
    parser = argparse.ArgumentParser(description="验证 MEFKT checkpoint 的 CPU/GPU 运行时门禁")
    parser.add_argument("--profile", choices=("full", "lite"), required=True)
    parser.add_argument("--data-root", required=True, help="包含 processed/manifest.json 的预处理数据目录")
    parser.add_argument("--checkpoint", required=True, help="best.pt 或 last.pt")
    parser.add_argument("--output", default="", help="可选的 JSON 结果输出路径")
    parser.add_argument("--cpu-threads", type=int, default=2)
    parser.add_argument("--max-parameters", type=int, default=50_000_000)
    parser.add_argument("--max-gpu-memory-gb", type=float, default=8.0)
    parser.add_argument("--sequence-length", type=int, default=96)
    parser.add_argument("--require-gpu", action="store_true", help="CUDA 不可用时令验证失败")
    return parser.parse_args()


def validate_checkpoint(
    profile: str,
    data_root: Path,
    checkpoint_path: Path,
    cpu_threads: int,
    max_parameters: int,
    max_gpu_memory_gb: float,
    sequence_length: int,
    require_gpu: bool,
) -> dict[str, object]:
    """
    加载 checkpoint 并运行 CPU 与可用 GPU 的前向门禁。

    :param profile: `full` 或 `lite`。
    :param data_root: 预处理数据根目录。
    :param checkpoint_path: checkpoint 文件路径。
    :param cpu_threads: CPU 验证使用的线程数。
    :param max_parameters: 参数量上限。
    :param max_gpu_memory_gb: GPU 峰值显存上限。
    :param sequence_length: 验证序列长度。
    :param require_gpu: 是否要求 CUDA 可用。
    :returns: 运行时门禁结果。
    :raises FileNotFoundError: 数据或 checkpoint 不存在时抛出。
    :raises RuntimeError: 预处理数据无效时抛出。
    """
    prepared = _load_prepared(data_root / "processed") or _load_prepared(data_root)
    if prepared is None:
        raise RuntimeError(f"找不到有效预处理缓存: {data_root / 'processed'}")
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    config = model_config_from_checkpoint(checkpoint, profile)
    model = build_model(
        profile,
        prepared.item_count,
        prepared.item_features,
        prepared.item_subjects,
        prepared.item_skills,
        len(prepared.subject_vocab),
        len(prepared.skill_vocab),
        config,
    )
    model.load_state_dict(checkpoint["model_state_dict"])
    result = runtime_validate(
        model,
        prepared,
        cpu_threads,
        max_parameters,
        max_gpu_memory_gb,
        sequence_length,
    )
    result.update(
        {
            "profile": profile,
            "checkpoint": str(checkpoint_path),
            "checkpoint_epoch": checkpoint.get("epoch"),
            "require_gpu": require_gpu,
        }
    )
    if require_gpu and not bool(result.get("gpu_available")):
        result["passed"] = False
        result["gpu_passed"] = False
        result["reason"] = "CUDA 不可用"
    return result


def main() -> int:
    """
    执行 checkpoint 验证并打印 JSON。

    :returns: 进程退出码。
    """
    args = _parse_args()
    result = validate_checkpoint(
        args.profile,
        Path(args.data_root),
        Path(args.checkpoint),
        args.cpu_threads,
        args.max_parameters,
        args.max_gpu_memory_gb,
        args.sequence_length,
        args.require_gpu,
    )
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if bool(result["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
