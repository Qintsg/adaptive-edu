#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT 与 MEFKT-Lite 统一训练入口。
@Project : adaptive-edu
@File : mefkt_train.py
@Author : Qintsg
@Date : 2026-08-24
'''

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import time
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
import torch
import torch.distributed as distributed
import torch.nn.functional as functional
from torch import Tensor, nn
from torch.nn.parallel import DistributedDataParallel
from torch.utils.data import DataLoader, DistributedSampler, SequentialSampler

from mefkt_lite_data import (
    PreparedDataset,
    SequenceIndexDataset,
    SequenceStore,
    collate_sequence_indices,
    prepare_ednet,
    prepare_synthetic,
)
from mefkt_canonical_data import prepare_canonical_csv
from mefkt_models import BaseMEFKT, SequenceState, build_model


LOGGER = logging.getLogger("mefkt.train")


@dataclass(frozen=True)
class DistributedContext:
    """封装单进程和 torchrun 多进程运行状态。"""

    rank: int
    local_rank: int
    world_size: int
    device: torch.device

    @property
    def is_main(self) -> bool:
        """判断当前进程是否是 rank 0。"""
        return self.rank == 0


def _init_distributed() -> DistributedContext:
    """初始化 torchrun 提供的分布式环境。"""
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    rank = int(os.environ.get("RANK", "0"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    use_cuda = torch.cuda.is_available()
    if world_size > 1:
        distributed.init_process_group(backend="nccl" if use_cuda else "gloo")
    device = torch.device("cuda", local_rank) if use_cuda else torch.device("cpu")
    if use_cuda:
        torch.cuda.set_device(device)
        torch.backends.cuda.matmul.allow_tf32 = True
    return DistributedContext(rank, local_rank, world_size, device)


def _finish_distributed(context: DistributedContext) -> None:
    """销毁分布式进程组。"""
    if context.world_size > 1 and distributed.is_initialized():
        distributed.destroy_process_group()


def _seed_everything(seed: int, rank: int) -> None:
    """固定训练随机性。"""
    actual_seed = seed + rank
    random.seed(actual_seed)
    np.random.seed(actual_seed)
    torch.manual_seed(actual_seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(actual_seed)


def _prepare_dataset(args: argparse.Namespace, context: DistributedContext) -> PreparedDataset:
    """由 rank 0 准备数据，其余 rank 等待缓存完成。"""
    root = Path(args.data_root)
    if context.is_main or context.world_size == 1:
        if args.dataset == "synthetic":
            prepared = prepare_synthetic(
                root,
                args.synthetic_users,
                args.synthetic_items,
                args.synthetic_sequence_length,
                args.seed,
                args.window_context_length,
                args.sequence_length,
                args.min_sequence_length,
            )
        elif args.dataset == "ednet-kt1":
            prepared = prepare_ednet(
                root,
                max_users=args.max_users,
                max_interactions=args.max_interactions,
                max_length=args.sequence_length,
                min_length=args.min_sequence_length,
                context_length=args.window_context_length,
                force=args.force_preprocess,
            )
        else:
            prepared = prepare_canonical_csv(
                root,
                Path(args.events_file),
                max_users=args.max_users,
                max_interactions=args.max_interactions,
                max_length=args.sequence_length,
                min_length=args.min_sequence_length,
                context_length=args.window_context_length,
                force=args.force_preprocess,
            )
    else:
        prepared = None
    if context.world_size > 1:
        distributed.barrier()
        if not context.is_main:
            if args.dataset == "synthetic":
                prepared = prepare_synthetic(
                    root,
                    args.synthetic_users,
                    args.synthetic_items,
                    args.synthetic_sequence_length,
                    args.seed,
                    args.window_context_length,
                    args.sequence_length,
                    args.min_sequence_length,
                )
            elif args.dataset == "ednet-kt1":
                prepared = prepare_ednet(
                    root,
                    max_users=args.max_users,
                    max_interactions=args.max_interactions,
                    max_length=args.sequence_length,
                    min_length=args.min_sequence_length,
                    context_length=args.window_context_length,
                    force=False,
                )
            else:
                prepared = prepare_canonical_csv(
                    root,
                    Path(args.events_file),
                    max_users=args.max_users,
                    max_interactions=args.max_interactions,
                    max_length=args.sequence_length,
                    min_length=args.min_sequence_length,
                    context_length=args.window_context_length,
                    force=False,
                )
    assert prepared is not None
    return prepared


def _make_loader(
    store: SequenceStore,
    context: DistributedContext,
    batch_size: int,
    sequence_length: int,
    workers: int,
    train: bool,
) -> tuple[DataLoader, DistributedSampler | None]:
    """创建训练或评估 DataLoader。"""
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


def _metrics(probabilities: list[float], targets: list[int]) -> dict[str, float]:
    """计算 AUC、ACC、Brier、ECE 和标签比例。"""
    if not targets:
        return {"auc": 0.5, "acc": 0.0, "brier": 0.0, "ece": 0.0, "samples": 0.0, "positive_rate": 0.0}
    prediction = np.asarray(probabilities, dtype=np.float64)
    gold = np.asarray(targets, dtype=np.int64)
    positive = int(gold.sum())
    negative = len(gold) - positive
    if positive and negative:
        order = np.argsort(prediction, kind="mergesort")
        ranks = np.empty_like(order, dtype=np.float64)
        ranks[order] = np.arange(1, len(order) + 1, dtype=np.float64)
        auc = float((ranks[gold == 1].sum() - positive * (positive + 1) / 2) / (positive * negative))
    else:
        auc = 0.5
    labels = (prediction >= 0.5).astype(np.int64)
    ece = 0.0
    for lower in np.linspace(0.0, 0.9, 10):
        upper = lower + 0.1
        mask = (prediction >= lower) & ((prediction < upper) if upper < 1.0 else (prediction <= upper))
        if mask.any():
            ece += float(mask.mean()) * abs(float(prediction[mask].mean()) - float(gold[mask].mean()))
    return {
        "auc": auc,
        "acc": float((labels == gold).mean()),
        "brier": float(np.mean((prediction - gold) ** 2)),
        "ece": ece,
        "samples": float(len(gold)),
        "positive_rate": float(gold.mean()),
    }


def _evaluate(model: nn.Module, loader: DataLoader, device: torch.device, max_batches: int = 0) -> dict[str, float]:
    """在一个切分上评估每次交互的答对预测。"""
    model.eval()
    probabilities: list[float] = []
    targets: list[int] = []
    with torch.no_grad():
        for batch_index, batch in enumerate(loader):
            if max_batches and batch_index >= max_batches:
                break
            items, correct, gaps, response_times, target_mask = (value.to(device, non_blocking=True) for value in batch)
            logits, mask, _ = model(items, correct, gaps, response_times)
            effective_mask = mask & target_mask
            probabilities.extend(torch.sigmoid(logits[effective_mask]).cpu().tolist())
            targets.extend(correct[effective_mask].cpu().tolist())
    return _metrics(probabilities, targets)


def _train_epoch(
    model: nn.Module,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
    amp: bool,
) -> float:
    """训练一个 epoch。"""
    model.train()
    total_loss = 0.0
    batches = 0
    for batch in loader:
        items, correct, gaps, response_times, target_mask = (value.to(device, non_blocking=True) for value in batch)
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(
            device_type="cuda",
            dtype=torch.bfloat16,
            enabled=amp and device.type == "cuda",
        ):
            logits, mask, _ = model(items, correct, gaps, response_times)
            effective_mask = mask & target_mask
            if not bool(effective_mask.any()):
                continue
            loss = functional.binary_cross_entropy_with_logits(logits[effective_mask], correct.float()[effective_mask])
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        total_loss += float(loss.detach().item())
        batches += 1
    return total_loss / max(batches, 1)


def _unwrap(model: nn.Module) -> BaseMEFKT:
    """取出 DDP 包装内的模型。"""
    return model.module if isinstance(model, DistributedDataParallel) else model  # type: ignore[return-value]


def _save_checkpoint(
    path: Path,
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    epoch: int,
    metadata: dict[str, object],
) -> None:
    """原子保存可恢复 checkpoint。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    torch.save(
        {
            "model_state_dict": _unwrap(model).state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "epoch": epoch,
            "metadata": metadata,
        },
        temporary,
    )
    os.replace(temporary, path)


def _runtime_validate(
    model: BaseMEFKT,
    prepared: PreparedDataset,
    threads: int,
    max_parameters: int,
    max_gpu_memory_gb: float,
    sequence_length: int,
) -> dict[str, object]:
    """验证 CPU 加载推理，并在有 CUDA 时检查 GPU 峰值显存。"""
    parameters = sum(parameter.numel() for parameter in model.parameters())
    original_threads = torch.get_num_threads()
    torch.set_num_threads(max(1, threads))
    try:
        model = model.to("cpu").eval()
        store = SequenceStore(prepared.root, "test")
        if len(store) == 0:
            return {"passed": False, "reason": "test split empty", "parameters": parameters}
        batch = collate_sequence_indices([0], store, max(sequence_length, 64))
        start = time.perf_counter()
        with torch.no_grad():
            logits, mask, state = model(*batch[:4])
        elapsed = time.perf_counter() - start
        effective_mask = mask & batch[4]
        finite = bool(torch.isfinite(logits).all()) and bool(torch.isfinite(state.context).all())
        cpu_passed = finite and bool(effective_mask.any()) and parameters <= max_parameters
        gpu_result: dict[str, object] = {"gpu_available": False, "gpu_passed": None}
        if torch.cuda.is_available():
            gpu_device = torch.device("cuda")
            gpu_model = model.to(gpu_device).eval()
            gpu_batch = tuple(value.to(gpu_device, non_blocking=True) for value in batch[:4])
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats(gpu_device)
            with torch.no_grad():
                gpu_model(*gpu_batch)
            peak_allocated_gb = torch.cuda.max_memory_allocated(gpu_device) / (1024 ** 3)
            peak_reserved_gb = torch.cuda.max_memory_reserved(gpu_device) / (1024 ** 3)
            peak_memory_gb = max(peak_allocated_gb, peak_reserved_gb)
            gpu_passed = peak_memory_gb <= max_gpu_memory_gb
            gpu_result = {
                "gpu_available": True,
                "gpu_passed": gpu_passed,
                "gpu_peak_memory_gb": peak_memory_gb,
                "gpu_peak_allocated_gb": peak_allocated_gb,
                "gpu_peak_reserved_gb": peak_reserved_gb,
                "gpu_device": torch.cuda.get_device_name(gpu_device),
            }
            model = gpu_model.to("cpu").eval()
        else:
            gpu_passed = None
        passed = cpu_passed and gpu_passed is not False
        return {
            "passed": passed,
            "cpu_passed": cpu_passed,
            "parameters": parameters,
            "max_parameters": max_parameters,
            "threads": threads,
            "cpu_seconds": elapsed,
            "finite": finite,
            "output_shape": list(logits.shape),
            "memory_shape": list(state.memory.shape) if state.memory is not None else [0],
            "max_gpu_memory_gb": max_gpu_memory_gb,
            **gpu_result,
        }
    finally:
        torch.set_num_threads(original_threads)


def _parse_args() -> argparse.Namespace:
    """解析训练命令行参数。"""
    parser = argparse.ArgumentParser(description="MEFKT / MEFKT-Lite 统一训练器")
    parser.add_argument("--profile", choices=("full", "lite"), default="full")
    parser.add_argument("--dataset", choices=("ednet-kt1", "canonical-csv", "synthetic"), default="ednet-kt1")
    parser.add_argument("--events-file", default="", help="canonical-csv 数据文件")
    parser.add_argument("--data-root", default="runtime_data/ednet-kt1")
    parser.add_argument("--output-dir", default="models/MEFKT/mefkt_v3")
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--sequence-length", type=int, default=200)
    parser.add_argument("--min-sequence-length", type=int, default=20)
    parser.add_argument("--window-context-length", type=int, default=-1, help="窗口重叠历史长度，-1 按 profile 选择")
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--patience", type=int, default=3)
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
    return parser.parse_args()


def main() -> int:
    """执行数据准备、训练、评估、checkpoint 和运行时验证。"""
    args = _parse_args()
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
    if args.min_sequence_length > args.sequence_length or args.window_context_length >= args.sequence_length:
        raise ValueError("窗口上下文长度必须小于 sequence-length，且最小序列长度不能超过 sequence-length")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    context = _init_distributed()
    _seed_everything(args.seed, context.rank)
    try:
        prepared = _prepare_dataset(args, context)
        model = build_model(
            args.profile,
            prepared.item_count,
            prepared.item_features,
            prepared.item_subjects,
            prepared.item_skills,
            len(prepared.subject_vocab),
            len(prepared.skill_vocab),
        )
        parameter_count = sum(parameter.numel() for parameter in model.parameters())
        if parameter_count > args.max_parameters:
            raise RuntimeError(f"{args.profile} 模型参数量 {parameter_count} 超过门槛 {args.max_parameters}")
        output_dir = Path(args.output_dir)
        if context.is_main:
            output_dir.mkdir(parents=True, exist_ok=True)
            for name, values in {
                "item_vocab.json": prepared.item_ids,
                "subject_vocab.json": prepared.subject_vocab,
                "skill_vocab.json": prepared.skill_vocab,
            }.items():
                (output_dir / name).write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
            LOGGER.info(
                "profile=%s dataset=%s items=%d subjects=%d skills=%d parameters=%d device=%s world=%d",
                args.profile,
                args.dataset,
                prepared.item_count,
                len(prepared.subject_vocab),
                len(prepared.skill_vocab),
                parameter_count,
                context.device,
                context.world_size,
            )
        model = model.to(context.device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
        last_checkpoint = output_dir / "last.pt"
        start_epoch = 0
        best_auc = -1.0
        stale = 0
        if args.resume and last_checkpoint.exists():
            checkpoint = torch.load(last_checkpoint, map_location="cpu", weights_only=False)
            model.load_state_dict(checkpoint["model_state_dict"])
            optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
            start_epoch = int(checkpoint.get("epoch", -1)) + 1
            early_stopping = checkpoint.get("metadata", {}).get("early_stopping", {})
            best_auc = float(early_stopping.get("best_auc", -1.0))
            stale = int(early_stopping.get("stale", 0))
        if context.world_size > 1:
            model = DistributedDataParallel(model, device_ids=[context.local_rank] if context.device.type == "cuda" else None)
        train_loader, train_sampler = _make_loader(
            SequenceStore(prepared.root, "train"), context, args.batch_size, args.sequence_length, args.num_workers, True
        )
        validation_loader, _ = _make_loader(
            SequenceStore(prepared.root, "validation"), context, args.batch_size, args.sequence_length, args.num_workers, False
        )
        test_loader, _ = _make_loader(
            SequenceStore(prepared.root, "test"), context, args.batch_size, args.sequence_length, args.num_workers, False
        )
        for epoch in range(start_epoch, args.epochs):
            if train_sampler is not None:
                train_sampler.set_epoch(epoch)
            loss = _train_epoch(model, train_loader, optimizer, context.device, args.amp)
            if context.world_size > 1:
                loss_tensor = torch.tensor([loss], device=context.device)
                distributed.all_reduce(loss_tensor, op=distributed.ReduceOp.SUM)
                loss = float((loss_tensor / context.world_size).item())
                distributed.barrier()
            stop = False
            if context.is_main:
                validation = _evaluate(_unwrap(model), validation_loader, context.device, args.eval_max_batches)
                test = _evaluate(_unwrap(model), test_loader, context.device, args.eval_max_batches)
                is_best = validation["auc"] >= best_auc
                if is_best:
                    best_auc, stale = validation["auc"], 0
                else:
                    stale += 1
                metadata = {
                    "model_name": "MEFKT" if args.profile == "full" else "MEFKT-Lite",
                    "runtime_schema": "mefkt_v3",
                    "profile": args.profile,
                    "epoch": epoch,
                    "dataset": prepared.metadata,
                    "model": {"config": _unwrap(model).config.to_dict(), "parameters": parameter_count},
                    "artifacts": {"item_vocab": "item_vocab.json", "subject_vocab": "subject_vocab.json", "skill_vocab": "skill_vocab.json"},
                    "validation": validation,
                    "test": test,
                    "early_stopping": {"best_auc": best_auc, "stale": stale},
                }
                LOGGER.info("epoch=%d loss=%.5f val=%s test=%s", epoch + 1, loss, json.dumps(validation), json.dumps(test))
                _save_checkpoint(last_checkpoint, model, optimizer, epoch, metadata)
                if is_best:
                    _save_checkpoint(output_dir / "best.pt", model, optimizer, epoch, metadata)
                stop = args.patience > 0 and stale >= args.patience
            if context.world_size > 1:
                flag = torch.tensor([int(stop)], device=context.device)
                distributed.broadcast(flag, src=0)
                distributed.barrier()
                stop = bool(flag.item())
            if stop:
                break
        if context.world_size > 1:
            distributed.barrier()
        result: dict[str, object] = {"passed": True}
        if context.is_main:
            best_checkpoint = torch.load(output_dir / "best.pt", map_location="cpu", weights_only=False)
            _unwrap(model).load_state_dict(best_checkpoint["model_state_dict"])
            result = _runtime_validate(
                _unwrap(model),
                prepared,
                args.cpu_threads,
                args.max_parameters,
                args.max_gpu_memory_gb,
                args.sequence_length,
            )
            (output_dir / "runtime_validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            LOGGER.info("运行时验证: %s", json.dumps(result, ensure_ascii=False))
        if context.world_size > 1:
            flag = torch.tensor([int(bool(result["passed"]))], device=context.device)
            distributed.broadcast(flag, src=0)
            passed = bool(flag.item())
        else:
            passed = bool(result["passed"])
        if not passed:
            raise RuntimeError(f"运行时验证未通过: {result if context.is_main else '见 rank 0 日志'}")
        return 0
    finally:
        _finish_distributed(context)


if __name__ == "__main__":
    raise SystemExit(main())
