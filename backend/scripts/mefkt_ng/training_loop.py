#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT-NG 每步、每轮训练与完整指标归档。
@Project : adaptive-edu
@File : training_loop.py
@Author : Qintsg
@Date : 2026-09-24
'''

from __future__ import annotations

import argparse
import json
import math
import os
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import Tensor, distributed, nn
from torch.nn import functional
from torch.utils.data import DataLoader, DistributedSampler

from mefkt_ng.artifacts import DurableJsonl, atomic_json, save_checkpoint, utc_now, write_epoch_csv
from mefkt_ng.data import PreparedData, sha256_file
from mefkt_ng.metrics import evaluate_split, summarize_predictions
from mefkt_ng.model import MEFKTNG
from mefkt_ng.training_runtime import Context, capture_rng, configure_torch_cache, make_loader, restore_rng


def _move_batch(batch: dict[str, Tensor], device: torch.device) -> dict[str, Tensor]:
    """将 DataLoader 结果搬运到训练设备。

    :param batch: CPU 事件 batch。
    :param device: 目标设备。
    :returns: 同结构 GPU/CPU 字典。
    """
    return {name: value.to(device, non_blocking=True) for name, value in batch.items()}


def _balanced_loss(logits: Tensor, labels: Tensor, subjects: Tensor, alpha: float) -> tuple[Tensor, Tensor]:
    """计算主 BCE 和等学科混合目标。

    :param logits: 有效目标 logits。
    :param labels: 对应二元结果。
    :param subjects: 题目学科 ID。
    :param alpha: 等学科权重。
    :returns: 优化目标和纯 BCE。
    """
    values = functional.binary_cross_entropy_with_logits(logits.float(), labels.float(), reduction="none")
    event_loss = values.mean()
    if alpha == 0:
        return event_loss, event_loss
    groups = [values[subjects == subject].mean() for subject in torch.unique(subjects)]
    return (1.0 - alpha) * event_loss + alpha * torch.stack(groups).mean(), event_loss


def _train_epoch(
    model: nn.Module, loader: DataLoader, sampler: DistributedSampler,
    optimizer: torch.optim.Optimizer, device: torch.device, item_subjects: Tensor,
    args: argparse.Namespace, epoch: int, global_step: int, context: Context,
    segment_id: str, writer: DurableJsonl,
) -> tuple[float, int]:
    """训练一轮，并立即落盘每个 optimizer step。

    :param model: 原始或 DDP 模型。
    :param loader: 当前 rank 数据。
    :param sampler: 可按 epoch 固定的随机采样器。
    :param optimizer: 优化器。
    :param device: 训练设备。
    :param item_subjects: 设备上的题目学科 ID。
    :param args: 训练参数。
    :param epoch: 零基轮次。
    :param global_step: 已完成的本 rank 步数。
    :param context: 分布式 rank 信息。
    :param segment_id: 本次启动唯一标识。
    :param writer: 只追加逐步记录。
    :returns: 全 rank 加权平均目标和本 rank 新步数。
    """
    model.train()
    sampler.set_epoch(epoch)
    weighted_loss = 0.0
    target_count = 0
    for batch_index, cpu_batch in enumerate(loader):
        started = time.perf_counter()
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
        batch = _move_batch(cpu_batch, device)
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16,
                            enabled=args.amp and device.type == "cuda"):
            logits, valid = model(batch)
            selected = valid & batch["target"]
            if not bool(selected.any()):
                raise RuntimeError("训练窗口没有新的目标事件；检查 context-length")
            selected_items = batch["items"][selected]
            loss, bce = _balanced_loss(logits[selected], batch["correct"][selected],
                                       item_subjects[selected_items], args.subject_balance_alpha)
        if not bool(torch.isfinite(loss)):
            raise FloatingPointError(f"第 {epoch + 1} 轮 batch {batch_index} 损失非有限值")
        loss.backward()
        norm = nn.utils.clip_grad_norm_(model.parameters(), args.max_grad_norm)
        if not bool(torch.isfinite(norm)):
            raise FloatingPointError(f"第 {epoch + 1} 轮 batch {batch_index} 梯度非有限值")
        optimizer.step()
        global_step += 1
        samples = int(selected.sum().item())
        stream_metrics = summarize_predictions(
            logits[selected].detach().float().cpu().numpy().astype(np.float64),
            batch["correct"][selected].detach().cpu().numpy().astype(np.int64),
        )
        weighted_loss += float(loss.detach().item()) * samples
        target_count += samples
        writer.append({
            "recorded_at_utc": utc_now(), "segment_id": segment_id, "rank": context.rank,
            "epoch": epoch + 1, "batch_index": batch_index, "optimizer_step": global_step,
            "objective_loss": float(loss.detach().item()), "bce_loss": float(bce.detach().item()),
            "targets": samples, "learning_rate": float(optimizer.param_groups[0]["lr"]),
            "gradient_norm_before_clip": float(norm.item()), "elapsed_seconds": time.perf_counter() - started,
            "stream_batch_metrics": stream_metrics,
            "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else None,
        })
    totals = torch.tensor([weighted_loss, float(target_count)], dtype=torch.float64, device=device)
    if context.world_size > 1:
        distributed.all_reduce(totals, op=distributed.ReduceOp.SUM)
    if totals[1].item() <= 0:
        raise RuntimeError("训练切分没有目标事件")
    return float((totals[0] / totals[1]).item()), global_step


def _checkpoint_path(output: Path, epoch: int, segment_id: str) -> Path:
    """生成不可覆盖的轮次 checkpoint 路径。

    :param output: 运行根目录。
    :param epoch: 一基轮次。
    :param segment_id: 当前启动唯一标识。
    :returns: 文件路径。
    """
    return output / "checkpoints" / f"epoch_{epoch:04d}_{segment_id}.pt"


def _rng_path(output: Path, epoch: int, rank: int, segment_id: str) -> Path:
    """生成每个 rank 独立的 RNG 保存路径。

    :param output: 运行根目录。
    :param epoch: 一基轮次。
    :param rank: 当前 rank。
    :param segment_id: 本次启动唯一标识。
    :returns: 文件路径。
    """
    return output / "rng" / f"epoch_{epoch:04d}_rank_{rank:03d}_{segment_id}.pt"


def _resume(
    output: Path, model: MEFKTNG, optimizer: torch.optim.Optimizer,
    scheduler: torch.optim.lr_scheduler.ReduceLROnPlateau,
    context: Context, run_config: dict[str, Any], epoch_file: Path,
) -> tuple[int, int, float, float | None, int]:
    """从最新完整 checkpoint 恢复并修复缺失的指标末行。

    :param output: 运行目录。
    :param model: 原始模型。
    :param optimizer: 训练优化器。
    :param scheduler: 验证损失调度器。
    :param context: 当前 rank。
    :param run_config: 冻结运行配置。
    :param epoch_file: 权威逐轮指标日志。
    :returns: 下一轮、步数、最佳 NLL/AUC、早停计数。
    """
    checkpoints = sorted((output / "checkpoints").glob("epoch_*.pt"))
    if not checkpoints:
        raise ValueError("找不到可恢复的 epoch checkpoint")
    latest = max(checkpoints, key=lambda path: int(path.name.split("_")[1]))
    state = torch.load(latest, map_location="cpu", weights_only=False)
    if state["run_id"] != run_config["run_id"] or state["data_sha256"] != run_config["data_sha256"]:
        raise ValueError("checkpoint 与当前运行目录或数据不匹配")
    epoch = int(state["epoch"])
    rng_file = _rng_path(output, epoch, context.rank, state["segment_id"])
    if not rng_file.exists():
        raise ValueError(f"续训缺少本 rank 的随机状态: {rng_file}")
    model.load_state_dict(state["model_state"])
    optimizer.load_state_dict(state["optimizer_state"])
    scheduler.load_state_dict(state["scheduler_state"])
    restore_rng(torch.load(rng_file, map_location="cpu", weights_only=False)["rng"])
    if context.is_main:
        recorded: set[int] = set()
        if epoch_file.exists():
            for line in epoch_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    recorded.add(int(json.loads(line)["epoch"]))
        if recorded and max(recorded) > epoch:
            raise ValueError("逐轮指标记录超前于最新 checkpoint，拒绝不一致续训")
        if epoch not in recorded:
            recovered = dict(state["epoch_metrics"])
            recovered["checkpoint_sha256"] = sha256_file(latest)
            with DurableJsonl(epoch_file) as writer:
                writer.append(recovered)
            write_epoch_csv(epoch_file, output / "epoch_metrics.csv")
    if context.world_size > 1:
        distributed.barrier()
    best_auc = state["best_auc"]
    return epoch, int(state["global_step"]), float(state["best_nll"]), float(best_auc) if best_auc is not None else None, int(state["stale"])


def _finish_test(
    output: Path, model: MEFKTNG, test_loader: DataLoader, device: torch.device,
    item_subjects: Tensor, item_ids: tuple[str, ...], subject_ids: tuple[str, ...],
    best_checkpoint: Path, trained_epochs: int, run_config: dict[str, Any],
) -> dict[str, Any]:
    """只在训练完成后评价预先留出的 test 切分。

    :param output: 运行目录。
    :param model: 原始模型。
    :param test_loader: 全量测试切分。
    :param device: 推理设备。
    :param item_subjects: CPU 题目学科映射。
    :param item_ids: 题目目录。
    :param subject_ids: 学科目录。
    :param best_checkpoint: 验证 NLL 最佳 checkpoint。
    :param trained_epochs: 已完成轮次。
    :param run_config: 运行配置。
    :returns: 测试总结。
    """
    final_path = output / f"final_summary_epoch_{trained_epochs:04d}.json"
    if final_path.exists():
        return json.loads(final_path.read_text(encoding="utf-8"))
    state = torch.load(best_checkpoint, map_location="cpu", weights_only=False)
    model.load_state_dict(state["model_state"])
    prediction_path = output / "predictions" / f"test_final_epoch_{trained_epochs:04d}.csv.gz"
    test = evaluate_split(model, test_loader, device, item_subjects, item_ids, subject_ids, prediction_path)
    result = {"run_id": run_config["run_id"], "completed_epochs": trained_epochs,
              "best_checkpoint": best_checkpoint.relative_to(output).as_posix(),
              "best_checkpoint_sha256": sha256_file(best_checkpoint),
              "best_validation": state["epoch_metrics"]["validation"], "test": test,
              "source_sha256": run_config["data_sha256"], "recorded_at_utc": utc_now()}
    atomic_json(final_path, result)
    return result


def run_training(
    args: argparse.Namespace, context: Context, data: PreparedData,
    raw_model: MEFKTNG, train_model: nn.Module,
    run_config: dict[str, Any],
) -> dict[str, Any] | None:
    """执行可恢复、逐步记录的 MEFKT-NG 首阶段训练。

    :param args: 训练参数。
    :param context: 当前 rank。
    :param data: 冻结数据目录。
    :param raw_model: 不带 DDP 的模型。
    :param train_model: DDP 包装或原模型。
    :param run_config: 不可变运行配置。
    :returns: rank 0 的最终总结，其余 rank 返回 None。
    """
    output = Path(args.output_dir).resolve()
    configure_torch_cache(output, context.rank)
    train_loader, train_sampler = make_loader(data, "train", context, args)
    assert train_sampler is not None
    train_eval_loader, _ = make_loader(data, "train", context, args, for_evaluation=True) if context.is_main else (None, None)
    validation_loader, _ = make_loader(data, "validation", context, args)
    test_loader, _ = make_loader(data, "test", context, args)
    subjects_cpu = torch.from_numpy(np.array(np.load(data.root / "item_subjects.npy"), copy=True)).long()
    subjects_device = subjects_cpu.to(context.device)
    item_ids = tuple(data.manifest["item_ids"])
    subject_ids = tuple(data.manifest["subject_ids"])
    optimizer = torch.optim.AdamW(raw_model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=args.scheduler_patience,
        min_lr=args.min_learning_rate,
    )
    epoch_file = output / "epoch_metrics.jsonl"
    start_epoch, global_step, best_nll, best_auc, stale = (0, 0, math.inf, None, 0)
    if args.resume:
        start_epoch, global_step, best_nll, best_auc, stale = _resume(
            output, raw_model, optimizer, scheduler, context, run_config, epoch_file,
        )
    segment_box = [uuid.uuid4().hex if context.is_main else ""]
    if context.world_size > 1:
        distributed.broadcast_object_list(segment_box, src=0, device=context.device)
    segment_id = segment_box[0]
    if context.is_main:
        with DurableJsonl(output / "segments.jsonl") as segment_writer:
            segment_writer.append({"event": "started", "recorded_at_utc": utc_now(),
                                   "segment_id": segment_id, "start_epoch": start_epoch + 1,
                                   "requested_epochs": args.epochs, "world_size": context.world_size})
    trained_epochs = start_epoch
    with DurableJsonl(output / "steps" / f"rank_{context.rank:03d}_{segment_id}.jsonl") as step_writer:
        for epoch_index in range(start_epoch, args.epochs):
            started = time.perf_counter()
            stream_loss, global_step = _train_epoch(
                train_model, train_loader, train_sampler, optimizer, context.device, subjects_device,
                args, epoch_index, global_step, context, segment_id, step_writer,
            )
            epoch_number = epoch_index + 1
            rng_file = _rng_path(output, epoch_number, context.rank, segment_id)
            save_checkpoint(rng_file, {"rng": capture_rng(), "rank": context.rank, "epoch": epoch_number})
            if context.world_size > 1:
                distributed.barrier()
            stop = False
            if context.is_main:
                assert train_eval_loader is not None
                train_metrics = evaluate_split(raw_model, train_eval_loader, context.device, subjects_cpu,
                                               item_ids, subject_ids)
                val_file = output / "predictions" / f"validation_epoch_{epoch_number:04d}_{segment_id}.csv.gz"
                validation = evaluate_split(raw_model, validation_loader, context.device, subjects_cpu,
                                            item_ids, subject_ids, val_file)
                val_nll = validation["overall"]["nll"]
                if val_nll is None:
                    raise ValueError("验证切分为空，不能进行模型选择")
                improved_nll = float(val_nll) < best_nll - args.min_delta
                if improved_nll:
                    best_nll, stale = float(val_nll), 0
                else:
                    stale += 1
                val_auc = validation["overall"]["auc"]
                improved_auc = val_auc is not None and (best_auc is None or float(val_auc) > best_auc)
                if improved_auc:
                    best_auc = float(val_auc)
                learning_rate = float(optimizer.param_groups[0]["lr"])
                scheduler.step(float(val_nll))
                next_lr = float(optimizer.param_groups[0]["lr"])
                stop = args.patience > 0 and stale >= args.patience
                record = {
                    "epoch": epoch_number, "segment_id": segment_id, "recorded_at_utc": utc_now(),
                    "learning_rate": learning_rate, "next_learning_rate": next_lr,
                    "optimizer_steps": global_step, "train_stream_loss": stream_loss,
                    "elapsed_seconds": time.perf_counter() - started,
                    "train": train_metrics, "validation": validation,
                    "best_nll": best_nll, "best_auc": best_auc, "stale": stale,
                    "improved_nll": improved_nll, "improved_auc": improved_auc,
                    "stop_reason": "validation_nll_patience" if stop else "max_epochs" if epoch_number == args.epochs else "",
                }
                checkpoint = _checkpoint_path(output, epoch_number, segment_id)
                state = {
                    "schema": "mefkt-ng-checkpoint-v1", "run_id": run_config["run_id"],
                    "data_sha256": run_config["data_sha256"], "epoch": epoch_number,
                    "segment_id": segment_id, "global_step": global_step,
                    "model_config": raw_model.config.to_dict(),
                    "model_state": raw_model.state_dict(), "optimizer_state": optimizer.state_dict(),
                    "scheduler_state": scheduler.state_dict(),
                    "best_nll": best_nll, "best_auc": best_auc, "stale": stale,
                    "rng_files": [_rng_path(output, epoch_number, rank, segment_id).relative_to(output).as_posix()
                                  for rank in range(context.world_size)],
                    "epoch_metrics": record,
                }
                checkpoint_hash = save_checkpoint(checkpoint, state)
                record["checkpoint_sha256"] = checkpoint_hash
                with DurableJsonl(epoch_file) as epoch_writer:
                    epoch_writer.append(record)
                write_epoch_csv(epoch_file, output / "epoch_metrics.csv")
                pointer = {"epoch": epoch_number, "file": checkpoint.relative_to(output).as_posix(),
                           "sha256": checkpoint_hash, "segment_id": segment_id}
                atomic_json(output / "latest.json", pointer)
                if improved_nll:
                    atomic_json(output / "best_nll.json", pointer)
                if improved_auc:
                    atomic_json(output / "best_auc.json", pointer)
                print(f"epoch={epoch_number} train_nll={train_metrics['overall']['nll']:.6f} "
                      f"val_nll={val_nll:.6f} val_auc={val_auc} lr={next_lr:.3g} "
                      f"best_nll={best_nll:.6f} stop={stop}", flush=True)
            if context.world_size > 1:
                values = torch.tensor([float(optimizer.param_groups[0]["lr"]) if context.is_main else 0.0,
                                       float(stop)], device=context.device)
                distributed.broadcast(values, src=0)
                for group in optimizer.param_groups:
                    group["lr"] = float(values[0].item())
                stop = bool(values[1].item())
                distributed.barrier()
            trained_epochs = epoch_number
            if stop:
                break
    if context.world_size > 1:
        distributed.barrier()
    result = None
    if context.is_main:
        best_pointer = json.loads((output / "best_nll.json").read_text(encoding="utf-8"))
        result = _finish_test(output, raw_model, test_loader, context.device, subjects_cpu,
                              item_ids, subject_ids, output / best_pointer["file"], trained_epochs, run_config)
        with DurableJsonl(output / "segments.jsonl") as segment_writer:
            segment_writer.append({"event": "finished", "recorded_at_utc": utc_now(),
                                   "segment_id": segment_id, "completed_epochs": trained_epochs,
                                   "best_nll": best_nll, "best_auc": best_auc})
    if context.world_size > 1:
        distributed.barrier()
    return result
