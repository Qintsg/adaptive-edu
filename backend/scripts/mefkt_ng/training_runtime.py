#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT-NG 单机与 torchrun 多机训练的环境、数据和续训边界。
@Project : adaptive-edu
@File : training_runtime.py
@Author : Qintsg
@Date : 2026-09-24
'''

from __future__ import annotations

import argparse
import json
import os
import random
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import Tensor, distributed
from torch.nn.parallel import DistributedDataParallel
from torch.utils.data import DataLoader, DistributedSampler, SequentialSampler

from mefkt_ng.artifacts import atomic_json, check_disk_budget, snapshot_source
from mefkt_ng.data import PreparedData, WindowDataset, collate_windows, prepare_data, sha256_file
from mefkt_ng.model import MEFKTNG, ModelConfig


@dataclass(frozen=True)
class Context:
    """当前 torchrun 进程身份和设备。"""

    rank: int
    local_rank: int
    world_size: int
    device: torch.device

    @property
    def is_main(self) -> bool:
        """判断是否负责评估和工件。

        :returns: 是否为 rank 0。
        """
        return self.rank == 0


def initialize_context(device_choice: str) -> Context:
    """初始化 CUDA、CPU 和可选进程组。

    :param device_choice: auto、cpu 或 cuda。
    :returns: 分布式上下文。
    :raises RuntimeError: 请求 CUDA 但设备不可用。
    """
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    rank = int(os.environ.get("RANK", "0"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    use_cuda = device_choice == "cuda" or (device_choice == "auto" and torch.cuda.is_available())
    if use_cuda and not torch.cuda.is_available():
        raise RuntimeError("请求 CUDA 训练，但没有可用 GPU")
    device = torch.device("cuda", local_rank) if use_cuda else torch.device("cpu")
    if use_cuda:
        torch.cuda.set_device(device)
        torch.backends.cuda.matmul.allow_tf32 = True
    if world_size > 1:
        distributed.init_process_group(
            backend="nccl" if use_cuda else "gloo",
            device_id=device if use_cuda else None,
            timeout=timedelta(hours=4),
        )
    return Context(rank, local_rank, world_size, device)


def finish_context(context: Context) -> None:
    """释放本次训练进程组。

    :param context: 分布式上下文。
    :returns: None。
    """
    if context.world_size > 1 and distributed.is_initialized():
        distributed.destroy_process_group()


def seed_process(seed: int, rank: int) -> None:
    """固定每个 rank 可恢复的随机流。

    :param seed: 基础种子。
    :param rank: 当前 rank。
    :returns: None。
    """
    value = seed + rank
    random.seed(value)
    np.random.seed(value)
    torch.manual_seed(value)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(value)


def configure_torch_cache(output: Path, rank: int) -> Path:
    """将 PyTorch 编译缓存定位到可持久写入的运行目录。

    :param output: 当前运行目录。
    :param rank: 当前进程编号。
    :returns: 缓存目录。
    """
    cache = output / "torch_cache" / f"rank_{rank:03d}"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["TORCHINDUCTOR_CACHE_DIR"] = str(cache.resolve())
    return cache


def capture_rng() -> dict[str, Any]:
    """保存续训需要的随机数状态。

    :returns: Python、NumPy、PyTorch 和 CUDA 的 RNG 状态。
    """
    return {"python": random.getstate(), "numpy": np.random.get_state(),
            "torch": torch.get_rng_state(),
            "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None}


def restore_rng(state: dict[str, Any]) -> None:
    """恢复本 rank 的随机数状态。

    :param state: `capture_rng` 的结果。
    :returns: None。
    """
    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.set_rng_state(state["torch"])
    if state.get("cuda") is not None and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(state["cuda"])


def prepare_shared_data(args: argparse.Namespace, context: Context) -> PreparedData:
    """仅主进程写缓存，所有 rank 校验其摘要。

    :param args: 训练命令行配置。
    :param context: 分布式上下文。
    :returns: 可复用的数据目录。
    """
    graph_file = Path(args.graph_file) if args.graph_file else None
    values = (Path(args.events_file), Path(args.content_embeddings_file), Path(args.data_root),
              args.sequence_length, args.context_length, graph_file)
    prepared = prepare_data(*values) if context.is_main else None
    if context.world_size > 1:
        distributed.barrier()
        if not context.is_main:
            prepared = prepare_data(*values)
    assert prepared is not None
    return prepared


def load_initial_checkpoint(model: MEFKTNG, path: Path) -> dict[str, Any]:
    """从旧数据运行只迁移可训练参数，保留新课程目录缓冲区。

    :param model: 用新课程目录构造的模型。
    :param path: 既有可信 MEFKT-NG checkpoint。
    :returns: 来源运行、轮次及 SHA-256 信息。
    :raises ValueError: checkpoint 参数缺失或模型结构不兼容。
    """
    source = path.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"初始 checkpoint 不存在: {source}")
    checkpoint = torch.load(source, map_location="cpu", weights_only=False)
    if checkpoint.get("schema") != "mefkt-ng-checkpoint-v1":
        raise ValueError("初始 checkpoint 的 schema 不兼容")
    state = checkpoint.get("model_state", {})
    parameters = dict(model.named_parameters())
    if not isinstance(state, dict) or any(name not in state or state[name].shape != value.shape
                                           for name, value in parameters.items()):
        raise ValueError("初始 checkpoint 缺少参数或模型容量不同")
    with torch.no_grad():
        for name, parameter in parameters.items():
            parameter.copy_(state[name].to(device=parameter.device, dtype=parameter.dtype))
    return {"path": str(source), "sha256": sha256_file(source),
            "run_id": str(checkpoint.get("run_id", "")), "epoch": int(checkpoint.get("epoch", 0)),
            "data_sha256": str(checkpoint.get("data_sha256", "")),
            "transferred_parameters": sum(value.numel() for value in parameters.values())}


def build_model(data: PreparedData, args: argparse.Namespace, device: torch.device) -> MEFKTNG:
    """从冻结目录构造首阶段 MEFKT-NG。

    :param data: 数据缓存。
    :param args: 模型容量配置。
    :param device: 目标设备。
    :returns: 已加载课程表示的模型。
    :raises ValueError: 模型超出参数预算。
    """
    def load_array(name: str) -> Tensor:
        """将 numpy 目录载入独立 torch 存储。

        :param name: 数组名称。
        :returns: CPU 张量。
        """
        return torch.from_numpy(np.array(np.load(data.root / f"{name}.npy", mmap_mode="r"), copy=True))

    config = ModelConfig(
        hidden_dim=args.hidden_dim, graph_layers=args.graph_layers if data.manifest["graph_edges"] else 0,
        bottleneck_mix=args.bottleneck_mix, bottleneck_temperature=args.bottleneck_temperature,
        dropout=args.dropout, prior_variance=args.prior_variance,
        process_noise=args.process_noise, max_update=args.max_update,
        repeat_weight=args.repeat_weight,
    )
    model = MEFKTNG(load_array("item_content"), load_array("item_skills"),
                    load_array("item_difficulty"), load_array("skill_content"),
                    load_array("graph_edges"), config)
    parameters = sum(param.numel() for param in model.parameters())
    if parameters > args.max_parameters:
        raise ValueError(f"模型参数量 {parameters} 超过预算 {args.max_parameters}")
    return model.to(device)


def make_loader(
    data: PreparedData, split: str, context: Context, args: argparse.Namespace,
    *, for_evaluation: bool = False,
) -> tuple[DataLoader, DistributedSampler | None]:
    """建立每个 rank 的训练或完整评估 loader。

    :param data: 数据目录。
    :param split: train、validation 或 test。
    :param context: 当前 rank。
    :param args: batch 与 worker 参数。
    :param for_evaluation: train 切分也按完整顺序读取，不使用分布式子集。
    :returns: loader 和训练采样器。
    """
    dataset = WindowDataset(data.root, split)
    if split == "train" and not for_evaluation:
        sampler: DistributedSampler | SequentialSampler = DistributedSampler(
            dataset, num_replicas=context.world_size, rank=context.rank,
            shuffle=True, seed=args.seed,
        )
        train_sampler: DistributedSampler | None = sampler
    else:
        sampler = SequentialSampler(dataset)
        train_sampler = None
    loader = DataLoader(
        dataset, batch_size=args.batch_size, sampler=sampler, num_workers=args.num_workers,
        pin_memory=context.device.type == "cuda", persistent_workers=args.num_workers > 0,
        collate_fn=partial(collate_windows, dataset=dataset),
    )
    return loader, train_sampler


def prepare_run_directory(
    args: argparse.Namespace, context: Context, data: PreparedData, model: MEFKTNG,
    lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """创建不可变运行配置或核对旧运行配置。

    :param args: 命令行配置。
    :param context: rank 信息。
    :param data: 数据摘要。
    :param model: 实例化模型。
    :param lineage: 初始 checkpoint 来源信息。
    :returns: 运行配置字典。
    :raises ValueError: 新运行会覆盖旧工件或续训配置不符。
    """
    output = Path(args.output_dir).resolve()
    if context.is_main:
        if not args.resume and output.exists():
            unexpected = [path.name for path in output.iterdir()
                          if path.name != "logs" and not (path.name.startswith("job_manifest_") and path.suffix == ".yaml")]
            if unexpected:
                raise ValueError(f"output-dir 已有训练工件 {unexpected}；新运行需要独立目录，续训使用 --resume")
        output.mkdir(parents=True, exist_ok=True)
        config_path = output / "run_config.json"
        modules = [Path(__file__).resolve().parents[1] / "mefkt_ng_train.py",
                   *sorted(Path(__file__).resolve().parent.glob("*.py"))]
        current_hashes = {path.relative_to(Path(__file__).resolve().parents[1]).as_posix(): sha256_file(path)
                          for path in modules}
        if args.resume:
            if not config_path.exists():
                raise ValueError("找不到 run_config.json，不能续训")
            config = json.loads(config_path.read_text(encoding="utf-8"))
            if config["data_sha256"] != data.manifest["source_sha256"] or config["content_sha256"] != data.manifest["content_sha256"]:
                raise ValueError("续训的事件或内容向量与原运行不同")
            if config["graph_sha256"] != data.manifest["graph_sha256"]:
                raise ValueError("续训的知识图谱与原运行不同")
            if config["source_snapshot"]["modules"] != current_hashes:
                raise ValueError("训练代码与原运行不同；请新建运行，不能悄悄续训")
            immutable = ("batch_size", "sequence_length", "context_length", "hidden_dim", "graph_layers",
                         "bottleneck_mix", "bottleneck_temperature", "dropout", "prior_variance",
                         "process_noise", "max_update", "repeat_weight", "learning_rate", "weight_decay",
                         "subject_balance_alpha", "seed", "amp", "world_size")
            for key in immutable:
                current = context.world_size if key == "world_size" else getattr(args, key)
                if config["arguments"][key] != current:
                    raise ValueError(f"续训配置不一致: {key}")
            if config["model_config"] != model.config.to_dict():
                raise ValueError("续训模型结构与原运行不同")
        else:
            source = snapshot_source(output, Path(__file__).resolve().parents[1])
            arguments = vars(args).copy()
            arguments["world_size"] = context.world_size
            config = {
                "schema": "mefkt-ng-run-v1", "run_id": output.name,
                "data_sha256": data.manifest["source_sha256"],
                "content_sha256": data.manifest["content_sha256"],
                "graph_sha256": data.manifest["graph_sha256"],
                "data_manifest": str(data.root / "manifest.json"),
                "model_config": model.config.to_dict(),
                "trainable_parameters": sum(value.numel() for value in model.parameters()),
                "arguments": arguments, "source_snapshot": source, "initial_checkpoint": lineage,
                "torch_version": torch.__version__,
                "cuda_version": torch.version.cuda,
                "device_name": torch.cuda.get_device_name(context.device) if context.device.type == "cuda" else "CPU",
            }
            atomic_json(config_path, config)
            param_bytes = sum(param.numel() * param.element_size() for param in model.parameters())
            buffer_bytes = sum(buffer.numel() * buffer.element_size() for buffer in model.buffers())
            budget = check_disk_budget(output, int(param_bytes * 4 + buffer_bytes), args.epochs)
            atomic_json(output / "disk_budget.json", budget)
    if context.world_size > 1:
        distributed.barrier()
    return json.loads((output / "run_config.json").read_text(encoding="utf-8"))


def wrap_distributed(model: MEFKTNG, context: Context) -> torch.nn.Module:
    """按需用 DDP 包装模型。

    :param model: 原始 MEFKT-NG。
    :param context: 分布式上下文。
    :returns: 原模型或同步梯度的 DDP 模型。
    """
    if context.world_size == 1:
        return model
    return DistributedDataParallel(model, device_ids=[context.local_rank] if context.device.type == "cuda" else None,
                                   broadcast_buffers=False, find_unused_parameters=True)
