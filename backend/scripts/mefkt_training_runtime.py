#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT 分布式训练环境、数据准备和 DataLoader 深模块。
@Project : adaptive-edu
@File : mefkt_training_runtime.py
@Author : Qintsg
@Date : 2026-09-01
'''

from __future__ import annotations

import argparse
import os
import random
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
import torch
from mefkt_canonical_data import prepare_canonical_csv
from mefkt_lite_data import (
    PreparedDataset,
    SequenceIndexDataset,
    SequenceStore,
    collate_sequence_indices,
    prepare_ednet,
    prepare_synthetic,
)
from mefkt_models import BaseMEFKT
from torch import distributed, nn
from torch.nn.parallel import DistributedDataParallel
from torch.utils.data import DataLoader, DistributedSampler, SequentialSampler


@dataclass(frozen=True)
class DistributedContext:
    """封装单进程和 torchrun 多进程运行状态。"""

    rank: int
    local_rank: int
    world_size: int
    device: torch.device

    @property
    def is_main(self) -> bool:
        """
        判断当前进程是否负责日志、评估和保存。

        :returns: 当前进程是否为 rank 0。
        """
        return self.rank == 0


def initialize_distributed() -> DistributedContext:
    """
    初始化 torchrun 提供的分布式环境和 CUDA 设备。

    :returns: 当前分布式上下文。
    """
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    rank = int(os.environ.get("RANK", "0"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    use_cuda = torch.cuda.is_available()
    device = torch.device("cuda", local_rank) if use_cuda else torch.device("cpu")
    if use_cuda:
        torch.cuda.set_device(device)
        torch.backends.cuda.matmul.allow_tf32 = True
    if world_size > 1:
        distributed.init_process_group(
            backend="nccl" if use_cuda else "gloo",
            device_id=device if use_cuda else None,
        )
    return DistributedContext(rank, local_rank, world_size, device)


def finish_distributed(context: DistributedContext) -> None:
    """
    销毁分布式进程组。

    :param context: 当前分布式上下文。
    :returns: None。
    """
    if context.world_size > 1 and distributed.is_initialized():
        distributed.destroy_process_group()


def seed_everything(seed: int, rank: int) -> None:
    """
    固定训练随机性并让各 rank 使用独立随机流。

    :param seed: 基础随机种子。
    :param rank: 分布式 rank。
    :returns: None。
    """
    actual_seed = seed + rank
    random.seed(actual_seed)
    np.random.seed(actual_seed)
    torch.manual_seed(actual_seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(actual_seed)


def _prepare_once(args: argparse.Namespace, force: bool) -> PreparedDataset:
    """
    按命令行参数准备或加载一次数据缓存。

    :param args: 训练参数。
    :param force: 是否强制重建缓存。
    :returns: 预处理数据集。
    """
    root = Path(args.data_root)
    content_file = Path(args.content_embeddings_file).resolve() if args.content_embeddings_file else None
    if args.dataset == "synthetic":
        return prepare_synthetic(
            root,
            args.synthetic_users,
            args.synthetic_items,
            args.synthetic_sequence_length,
            args.seed,
            args.window_context_length,
            args.sequence_length,
            args.min_sequence_length,
        )
    if args.dataset == "ednet-kt1":
        return prepare_ednet(
            root,
            max_users=args.max_users,
            max_interactions=args.max_interactions,
            max_length=args.sequence_length,
            min_length=args.min_sequence_length,
            context_length=args.window_context_length,
            force=force,
            content_embeddings_file=content_file,
        )
    return prepare_canonical_csv(
        root,
        Path(args.events_file),
        max_users=args.max_users,
        max_interactions=args.max_interactions,
        max_length=args.sequence_length,
        min_length=args.min_sequence_length,
        context_length=args.window_context_length,
        force=force,
        content_embeddings_file=content_file,
    )


def prepare_dataset(args: argparse.Namespace, context: DistributedContext) -> PreparedDataset:
    """
    由 rank 0 准备数据，其余 rank 在 barrier 后加载缓存。

    :param args: 训练命令行参数。
    :param context: 分布式上下文。
    :returns: 所有 rank 一致的预处理数据集。
    """
    prepared = _prepare_once(args, args.force_preprocess) if context.is_main else None
    if context.world_size > 1:
        distributed.barrier()
        if not context.is_main:
            prepared = _prepare_once(args, False)
    assert prepared is not None
    return prepared


def make_loader(
    store: SequenceStore,
    context: DistributedContext,
    batch_size: int,
    sequence_length: int,
    workers: int,
    train: bool,
) -> tuple[DataLoader, DistributedSampler | None]:
    """
    创建训练或评估 DataLoader。

    :param store: mmap 序列存储。
    :param context: 分布式上下文。
    :param batch_size: batch 大小。
    :param sequence_length: 序列截断长度。
    :param workers: DataLoader worker 数量。
    :param train: 是否为训练 loader。
    :returns: DataLoader 和可选的分布式 sampler。
    """
    dataset = SequenceIndexDataset(store)
    sampler: DistributedSampler | SequentialSampler
    if context.world_size > 1 and train:
        sampler = DistributedSampler(dataset, num_replicas=context.world_size, rank=context.rank, shuffle=True)
    else:
        sampler = SequentialSampler(dataset)
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        sampler=sampler,
        num_workers=workers,
        pin_memory=context.device.type == "cuda",
        persistent_workers=workers > 0,
        collate_fn=partial(collate_sequence_indices, store=store, max_length=sequence_length),
    )
    return loader, sampler if isinstance(sampler, DistributedSampler) else None


def unwrap_model(model: nn.Module) -> BaseMEFKT:
    """
    取出 DDP 包装内的 MEFKT 模型。

    :param model: 原始或 DDP 包装模型。
    :returns: 基础 MEFKT 模型。
    """
    return model.module if isinstance(model, DistributedDataParallel) else model  # type: ignore[return-value]


__all__ = [
    "DistributedContext",
    "finish_distributed",
    "initialize_distributed",
    "make_loader",
    "prepare_dataset",
    "seed_everything",
    "unwrap_model",
]
