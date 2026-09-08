#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT 训练命令行 interface 与参数门禁。
@Project : adaptive-edu
@File : mefkt_training_args.py
@Author : Qintsg
@Date : 2026-09-01
'''

from __future__ import annotations

import argparse


def parse_training_args() -> argparse.Namespace:
    """
    解析、补全并验证统一训练参数。

    :returns: 可直接进入训练主流程的参数。
    :raises ValueError: 参数组合不合法时抛出。
    """
    parser = argparse.ArgumentParser(description="MEFKT / MEFKT-Lite 统一训练器")
    parser.add_argument("--profile", choices=("full", "lite"), default="full")
    parser.add_argument("--architecture-version", choices=(2, 3), type=int, default=3)
    parser.add_argument("--dataset", choices=("ednet-kt1", "canonical-csv", "synthetic"), default="ednet-kt1")
    parser.add_argument("--events-file", default="", help="canonical-csv 数据文件")
    parser.add_argument(
        "--content-embeddings-file",
        default="",
        help="可选的题目内容向量 .npz/.json；新课程冷启动依赖固定内容编码",
    )
    parser.add_argument("--data-root", default="runtime_data/ednet-kt1")
    parser.add_argument("--output-dir", default="models/MEFKT/mefkt_v3")
    parser.add_argument("--epochs", type=int, default=250)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--sequence-length", type=int, default=200)
    parser.add_argument("--min-sequence-length", type=int, default=20)
    parser.add_argument("--window-context-length", type=int, default=-1, help="窗口重叠历史长度，-1 按 profile 选择")
    parser.add_argument("--learning-rate", type=float, default=6e-5)
    parser.add_argument("--weight-decay", type=float, default=5e-4)
    parser.add_argument(
        "--lr-scheduler",
        choices=("none", "plateau", "cosine", "warmup-piecewise"),
        default="warmup-piecewise",
    )
    parser.add_argument("--lr-scheduler-factor", type=float, default=0.5)
    parser.add_argument("--lr-scheduler-patience", type=int, default=3)
    parser.add_argument("--min-learning-rate", type=float, default=1e-5)
    parser.add_argument("--warmup-epochs", type=int, default=3)
    parser.add_argument("--high-lr-epochs", type=int, default=15)
    parser.add_argument("--mid-lr-epochs", type=int, default=20)
    parser.add_argument("--subject-balance-alpha", type=float, default=0.5)
    parser.add_argument("--patience", type=int, default=0, help="validation AUC 早停轮数，0 表示禁用")
    parser.add_argument("--validation-loss-patience", type=int, default=12)
    parser.add_argument("--validation-loss-min-delta", type=float, default=2e-4)
    parser.add_argument("--validation-loss-plateau-patience", type=int, default=60)
    parser.add_argument("--num-workers", type=int, default=2)
    parser.add_argument("--cpu-threads", type=int, default=2)
    parser.add_argument("--max-users", type=int, default=0)
    parser.add_argument("--max-interactions", type=int, default=0)
    parser.add_argument("--eval-max-batches", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260824)
    parser.add_argument("--max-parameters", type=int, default=50_000_000)
    parser.add_argument("--max-gpu-memory-gb", type=float, default=8.0)
    parser.add_argument("--synthetic-users", type=int, default=240)
    parser.add_argument("--synthetic-items", type=int, default=96)
    parser.add_argument("--synthetic-sequence-length", type=int, default=48)
    parser.add_argument("--force-preprocess", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--amp", action="store_true", help="CUDA 上使用 bfloat16 autocast")
    args = parser.parse_args()
    if args.profile == "lite" and args.max_parameters == 50_000_000:
        args.max_parameters = 5_000_000
    if args.window_context_length < 0:
        args.window_context_length = 32 if args.profile == "lite" else 64
    if args.dataset == "canonical-csv" and not args.events_file:
        raise ValueError("--dataset canonical-csv 必须提供 --events-file")
    if args.output_dir == "models/MEFKT/mefkt_v3" and args.profile == "lite":
        args.output_dir = "models/MEFKT/mefkt_lite_v3"
    if args.epochs < 1 or args.batch_size < 1 or args.sequence_length < 1 or args.min_sequence_length < 1:
        raise ValueError("训练轮数、batch 和序列长度必须为正数")
    invalid_control = (
        args.patience < 0
        or args.validation_loss_patience < 0
        or args.validation_loss_min_delta < 0
        or args.lr_scheduler_patience < 0
        or args.warmup_epochs < 0
        or args.high_lr_epochs < args.warmup_epochs
        or args.mid_lr_epochs < 0
        or not 0.0 <= args.subject_balance_alpha <= 1.0
        or args.validation_loss_plateau_patience < 0
        or not 0.0 < args.lr_scheduler_factor < 1.0
        or args.min_learning_rate < 0.0
    )
    if invalid_control:
        raise ValueError("早停和学习率调度参数不合法")
    if args.min_sequence_length > args.sequence_length or args.window_context_length >= args.sequence_length:
        raise ValueError("窗口上下文长度必须小于 sequence-length，且最小序列长度不能超过 sequence-length")
    return args


__all__ = ["parse_training_args"]
