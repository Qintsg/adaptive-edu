#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT-NG 首阶段训练入口；运行前明确提供 canonical 数据和内容向量。
@Project : adaptive-edu
@File : mefkt_ng_train.py
@Author : Qintsg
@Date : 2026-09-24
'''

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from mefkt_ng.training_loop import run_training
from mefkt_ng.training_runtime import (
    build_model, finish_context, initialize_context, load_initial_checkpoint, prepare_run_directory,
    prepare_shared_data, seed_process, wrap_distributed,
)


def parse_args() -> argparse.Namespace:
    """解析可供集群和本地复用的训练配置。

    :returns: 已校验参数。
    :raises ValueError: 参数越界时抛出。
    """
    parser = argparse.ArgumentParser(description="MEFKT-NG 首阶段训练与完整指标留存")
    parser.add_argument("--events-file", required=True, help="canonical CSV 原始事件")
    parser.add_argument("--content-embeddings-file", required=True, help="项目现有 384 维题目 NPZ")
    parser.add_argument("--graph-file", default="", help="可选有类型知识关系 JSON")
    parser.add_argument("--data-root", required=True, help="持久化预处理数组的独立目录")
    parser.add_argument("--output-dir", required=True, help="独立运行目录；推荐数据 PVC")
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--batch-size", type=int, default=128, help="每 GPU/进程的 batch")
    parser.add_argument("--sequence-length", type=int, default=200)
    parser.add_argument("--context-length", type=int, default=64)
    parser.add_argument("--hidden-dim", type=int, default=384)
    parser.add_argument("--graph-layers", type=int, default=2)
    parser.add_argument("--bottleneck-mix", type=float, default=0.5)
    parser.add_argument("--bottleneck-temperature", type=float, default=0.7)
    parser.add_argument("--dropout", type=float, default=0.10)
    parser.add_argument("--prior-variance", type=float, default=1.5)
    parser.add_argument("--process-noise", type=float, default=0.03)
    parser.add_argument("--max-update", type=float, default=1.0)
    parser.add_argument("--repeat-weight", type=float, default=0.5)
    parser.add_argument("--max-parameters", type=int, default=30_000_000)
    parser.add_argument("--learning-rate", type=float, default=0.0001)
    parser.add_argument("--weight-decay", type=float, default=0.0001)
    parser.add_argument("--subject-balance-alpha", type=float, default=0.5)
    parser.add_argument("--scheduler-patience", type=int, default=5)
    parser.add_argument("--min-learning-rate", type=float, default=0.000001)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--min-delta", type=float, default=0.0002)
    parser.add_argument("--max-grad-norm", type=float, default=1.0)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--amp", action="store_true", help="CUDA 上使用 bfloat16 混合精度")
    parser.add_argument("--resume", action="store_true", help="从最新完整 epoch 续训；保留旧轨迹")
    parser.add_argument("--initial-checkpoint", default="", help="从另一运行的 checkpoint 仅迁移模型参数；新数据单独训练")
    parser.add_argument("--dry-run", action="store_true", help="只检查输入/参数和输出规划，不训练也不写文件")
    args = parser.parse_args()
    if args.epochs < 1 or args.batch_size < 1 or args.sequence_length < 2:
        raise ValueError("epochs/batch-size/sequence-length 不合法")
    if not 0 <= args.context_length < args.sequence_length or args.num_workers < 0:
        raise ValueError("context-length 或 num-workers 不合法")
    if not 0 <= args.subject_balance_alpha <= 1 or not 0 <= args.bottleneck_mix <= 1:
        raise ValueError("领域平衡或瓶颈混合权重不合法")
    if not 0 <= args.repeat_weight <= 1 or not 0 <= args.dropout < 1:
        raise ValueError("重复题权重或 dropout 不合法")
    if min(args.learning_rate, args.min_learning_rate, args.bottleneck_temperature,
           args.prior_variance, args.max_grad_norm) <= 0 or args.weight_decay < 0:
        raise ValueError("正数超参数不合法")
    if args.patience < 0 or args.scheduler_patience < 0 or args.max_parameters < 1:
        raise ValueError("patience 或参数预算不合法")
    if args.graph_layers not in (0, 1, 2) or args.hidden_dim < 32:
        raise ValueError("graph-layers 或 hidden-dim 不合法")
    if args.resume and args.initial_checkpoint:
        raise ValueError("--resume 与 --initial-checkpoint 不能同时使用")
    return args


def main() -> None:
    """执行只读检查或可恢复的正式训练入口。

    :returns: None。
    """
    args = parse_args()
    if args.dry_run:
        events, content = Path(args.events_file), Path(args.content_embeddings_file)
        if not events.is_file() or not content.is_file():
            raise FileNotFoundError("事件 CSV 或内容向量 NPZ 不存在")
        if args.graph_file and not Path(args.graph_file).is_file():
            raise FileNotFoundError("知识关系 JSON 不存在")
        with np.load(content, allow_pickle=False) as archive:
            shape = archive["embeddings"].shape
            if len(shape) != 2 or shape[1] != 384:
                raise ValueError("题目内容向量必须是 [N,384]")
        print(json.dumps({"mode": "dry-run", "events_size": events.stat().st_size,
                          "content_shape": shape, "output_dir": args.output_dir,
                          "data_root": args.data_root, "epochs": args.epochs,
                          "batch_size_per_gpu": args.batch_size, "hidden_dim": args.hidden_dim,
                          "amp": args.amp, "graph_file": args.graph_file}, ensure_ascii=False))
        return
    context = initialize_context(args.device)
    try:
        seed_process(args.seed, context.rank)
        if args.amp and context.device.type == "cuda" and not torch.cuda.is_bf16_supported():
            raise RuntimeError("当前 GPU 不支持 bfloat16 AMP；请去掉 --amp")
        data = prepare_shared_data(args, context)
        if data.manifest["splits"]["validation"]["target_events"] == 0 or data.manifest["splits"]["test"]["target_events"] == 0:
            raise ValueError("validation/test 缺少独立目标事件；需要更多用户")
        raw_model = build_model(data, args, context.device)
        lineage = load_initial_checkpoint(raw_model, Path(args.initial_checkpoint)) if args.initial_checkpoint else None
        run_config = prepare_run_directory(args, context, data, raw_model, lineage)
        model = wrap_distributed(raw_model, context)
        result = run_training(args, context, data, raw_model, model, run_config)
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
    finally:
        finish_context(context)


if __name__ == "__main__":
    main()
