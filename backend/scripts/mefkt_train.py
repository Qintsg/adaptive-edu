#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT 与 MEFKT-Lite 统一训练入口。
@Project : adaptive-edu
@File : mefkt_train.py
@Author : Qintsg
@Date : 2026-08-25
'''

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import torch
from mefkt_early_stopping import ValidationLossEarlyStopping
from mefkt_evaluation import evaluate as _evaluate
from mefkt_lite_data import SequenceStore
from mefkt_model_config import full_config, legacy_config, lite_config
from mefkt_models import build_model
from mefkt_optimization import (
    build_optimizer,
    current_learning_rate,
    restore_scheduler_state,
    save_checkpoint,
    scheduler_state_dict,
    set_learning_rate,
    step_scheduler,
)
from mefkt_reporting import append_epoch_metrics, jsonable_args, load_validation_loss_history, write_run_config
from mefkt_runtime import runtime_validate
from mefkt_training_core import train_epoch
from mefkt_training_args import parse_training_args
from mefkt_training_runtime import (
    finish_distributed,
    initialize_distributed,
    make_loader,
    prepare_dataset,
    seed_everything,
    unwrap_model,
)
from torch import distributed
from torch.nn.parallel import DistributedDataParallel

LOGGER = logging.getLogger("mefkt.train")


def main() -> int:
    """
    执行数据准备、训练、评估、checkpoint 和运行时验证。

    :returns: 进程退出码。
    """
    args = parse_training_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    context = initialize_distributed()
    seed_everything(args.seed, context.rank)
    try:
        prepared = prepare_dataset(args, context)
        config = legacy_config(args.profile) if args.architecture_version == 2 else (
            lite_config() if args.profile == "lite" else full_config()
        )
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
            write_run_config(
                output_dir,
                {
                    "arguments": jsonable_args(args),
                    "profile": args.profile,
                    "dataset": args.dataset,
                    "world_size": context.world_size,
                    "device": str(context.device),
                    "parameter_count": parameter_count,
                    "torch_version": torch.__version__,
                    "torch_cuda_version": torch.version.cuda,
                    "cuda_available": torch.cuda.is_available(),
                },
            )
        model = model.to(context.device)
        optimizer, scheduler = build_optimizer(
            model,
            args.learning_rate,
            args.weight_decay,
            args.lr_scheduler,
            args.lr_scheduler_factor,
            args.lr_scheduler_patience,
            args.min_learning_rate,
            args.epochs,
            args.warmup_epochs,
            args.high_lr_epochs,
            args.mid_lr_epochs,
        )
        last_checkpoint = output_dir / "last.pt"
        start_epoch = 0
        best_auc = -1.0
        best_checkpoint_loss = float("inf")
        stale = 0
        validation_loss_state = ValidationLossEarlyStopping(
            args.validation_loss_patience,
            args.validation_loss_min_delta,
            args.validation_loss_plateau_patience,
        )
        resumed_checkpoint: dict[str, object] | None = None
        resume_metadata: dict[str, object] = {}
        resume_has_validation_loss_state = False
        preflight_stop = False
        if args.resume and last_checkpoint.exists():
            resumed_checkpoint = torch.load(last_checkpoint, map_location="cpu", weights_only=False)
            model.load_state_dict(resumed_checkpoint["model_state_dict"])
            optimizer.load_state_dict(resumed_checkpoint["optimizer_state_dict"])
            start_epoch = int(resumed_checkpoint.get("epoch", -1)) + 1
            checkpoint_metadata = resumed_checkpoint.get("metadata", {})
            if not isinstance(checkpoint_metadata, dict):
                checkpoint_metadata = {}
            resume_metadata = checkpoint_metadata
            restore_scheduler_state(scheduler, checkpoint_metadata.get("scheduler"))
            early_stopping = resume_metadata.get("early_stopping", {})
            if not isinstance(early_stopping, dict):
                early_stopping = {}
            best_auc = float(early_stopping.get("best_auc", -1.0))
            best_checkpoint_loss = float(
                early_stopping.get("best_checkpoint_loss", early_stopping.get("best_validation_loss", float("inf")))
            )
            stale = int(early_stopping.get("stale", 0))
            resume_has_validation_loss_state = validation_loss_state.restore(early_stopping)
        if context.world_size > 1:
            model = DistributedDataParallel(model, device_ids=[context.local_rank] if context.device.type == "cuda" else None)
        train_loader, train_sampler = make_loader(
            SequenceStore(prepared.root, "train"), context, args.batch_size, args.sequence_length, args.num_workers, True
        )
        validation_loader, _ = make_loader(
            SequenceStore(prepared.root, "validation"), context, args.batch_size, args.sequence_length, args.num_workers, False
        )
        test_loader, _ = make_loader(
            SequenceStore(prepared.root, "test"), context, args.batch_size, args.sequence_length, args.num_workers, False
        )
        if resumed_checkpoint is not None and context.is_main:
            # 旧 checkpoint 没有可靠的 validation loss 状态时，使用当前权重重新评估建立续训基线。
            if not validation_loss_state.history:
                validation_loss_state.extend_history(
                    load_validation_loss_history(output_dir, args.validation_loss_patience)
                )
            resume_validation = _evaluate(
                unwrap_model(model),
                validation_loader,
                context.device,
                args.eval_max_batches,
                prepared.item_subjects,
                prepared.subject_vocab,
            )
            validation_loss_state.establish_baseline(
                float(resume_validation["loss"]),
                resume_has_validation_loss_state,
            )
            checkpoint_validation = resume_metadata.get("validation", {})
            if not isinstance(checkpoint_validation, dict):
                checkpoint_validation = {}
            checkpoint_validation_auc = float(checkpoint_validation.get("auc", -1.0))
            if checkpoint_validation_auc >= best_auc:
                # 当前项目 epoch 12 的 last.pt 同时也是历史最佳；原子重写可修复旧 best.pt 分片损坏。
                repaired_metadata = dict(resume_metadata)
                repaired_early_stopping = dict(
                    resume_metadata.get("early_stopping", {})
                    if isinstance(resume_metadata.get("early_stopping"), dict)
                    else {}
                )
                repaired_early_stopping.update(validation_loss_state.to_metadata())
                repaired_metadata["early_stopping"] = repaired_early_stopping
                save_checkpoint(output_dir / "best.pt", model, optimizer, start_epoch - 1, repaired_metadata)
                LOGGER.info("resume checkpoint is historical best; best.pt rewritten atomically")
            LOGGER.info(
                "resume epoch=%d validation baseline loss=%.6f auc=%.6f trend_delta=%.6f",
                start_epoch,
                validation_loss_state.previous_loss,
                resume_validation["auc"],
                validation_loss_state.trend_delta,
            )
            preflight_stop = validation_loss_state.should_stop()
            if preflight_stop:
                stopped_metadata = dict(resume_metadata)
                stopped_early_stopping = dict(
                    resume_metadata.get("early_stopping", {})
                    if isinstance(resume_metadata.get("early_stopping"), dict)
                    else {}
                )
                stopped_early_stopping.update(
                    {
                        "best_auc": best_auc,
                        "stale": stale,
                        **validation_loss_state.to_metadata(validation_loss_state.reason()),
                    }
                )
                stopped_metadata["early_stopping"] = stopped_early_stopping
                save_checkpoint(last_checkpoint, model, optimizer, start_epoch - 1, stopped_metadata)
                LOGGER.warning(
                    "resume preflight early stop: validation loss trend_delta=%.6f bad_streak=%d",
                    validation_loss_state.trend_delta,
                    validation_loss_state.bad_streak,
                )
        if context.world_size > 1:
            preflight_flag = torch.tensor([int(preflight_stop)], device=context.device)
            distributed.broadcast(preflight_flag, src=0)
            distributed.barrier()
            preflight_stop = bool(preflight_flag.item())
        training_end_epoch = start_epoch if preflight_stop else args.epochs
        item_subjects_device = prepared.item_subjects.to(context.device)
        for epoch in range(start_epoch, training_end_epoch):
            epoch_started = time.perf_counter()
            if train_sampler is not None:
                train_sampler.set_epoch(epoch)
            loss = train_epoch(
                model,
                train_loader,
                optimizer,
                context.device,
                args.amp,
                item_subjects_device,
                args.subject_balance_alpha,
            )
            if context.world_size > 1:
                loss_tensor = torch.tensor([loss], device=context.device)
                distributed.all_reduce(loss_tensor, op=distributed.ReduceOp.SUM)
                loss = float((loss_tensor / context.world_size).item())
                distributed.barrier()
            stop = False
            stop_reason = ""
            if context.is_main:
                epoch_learning_rate = current_learning_rate(optimizer)
                validation = _evaluate(
                    unwrap_model(model), validation_loader, context.device, args.eval_max_batches,
                    prepared.item_subjects, prepared.subject_vocab,
                )
                test = _evaluate(
                    unwrap_model(model), test_loader, context.device, args.eval_max_batches,
                    prepared.item_subjects, prepared.subject_vocab,
                )
                is_best = validation["auc"] >= best_auc
                if is_best:
                    best_auc, stale = validation["auc"], 0
                else:
                    stale += 1
                validation_loss = float(validation["loss"])
                is_best_loss = validation_loss < best_checkpoint_loss
                if is_best_loss:
                    best_checkpoint_loss = validation_loss
                loss_stop = validation_loss_state.update(validation_loss)
                auc_stop = args.patience > 0 and stale >= args.patience
                if loss_stop:
                    stop_reason = validation_loss_state.reason()
                elif auc_stop:
                    stop_reason = "validation_auc_patience"
                elif epoch == args.epochs - 1:
                    stop_reason = "max_epochs_reached"
                step_scheduler(scheduler, float(validation["loss"]))
                next_learning_rate = current_learning_rate(optimizer)
                metadata = {
                    "model_name": "MEFKT" if args.profile == "full" else "MEFKT-Lite",
                    "runtime_schema": "mefkt_v3",
                    "profile": args.profile,
                    "epoch": epoch,
                    "dataset": prepared.metadata,
                    "model": {"config": unwrap_model(model).config.to_dict(), "parameters": parameter_count},
                    "artifacts": {
                        "item_vocab": "item_vocab.json",
                        "subject_vocab": "subject_vocab.json",
                        "skill_vocab": "skill_vocab.json",
                        "run_config": "run_config.json",
                        "training_metrics_jsonl": "training_metrics.jsonl",
                        "training_metrics_csv": "training_metrics.csv",
                        "train_log": "train.log",
                        "best_auc_checkpoint": "best_auc.pt",
                        "best_loss_checkpoint": "best_loss.pt",
                    },
                    "validation": validation,
                    "test": test,
                    "scheduler": scheduler_state_dict(scheduler),
                    "early_stopping": {
                        "best_auc": best_auc,
                        "best_checkpoint_loss": best_checkpoint_loss,
                        "stale": stale,
                        **validation_loss_state.to_metadata(stop_reason),
                    },
                }
                append_epoch_metrics(
                    output_dir,
                    {
                        "epoch": epoch + 1,
                        "epoch_index": epoch,
                        "loss": loss,
                        "learning_rate": epoch_learning_rate,
                        "next_learning_rate": next_learning_rate,
                        "elapsed_seconds": time.perf_counter() - epoch_started,
                        "validation": validation,
                        "test": test,
                        "is_best": is_best,
                        "is_best_loss": is_best_loss,
                        "stale": stale,
                        "validation_loss_best": validation_loss_state.best_loss,
                        "validation_loss_bad_streak": validation_loss_state.bad_streak,
                        "validation_loss_rise_streak": validation_loss_state.rise_streak,
                        "validation_loss_trend_delta": validation_loss_state.trend_delta,
                        "stop_reason": stop_reason,
                    },
                )
                LOGGER.info(
                    "epoch=%d loss=%.5f lr=%.2e val_loss=%.6f val_auc=%.6f test_loss=%.6f test_auc=%.6f "
                    "val_loss_best=%.6f val_loss_bad_streak=%d val_loss_rise_streak=%d/%d "
                    "val_loss_trend_delta=%.6f stop_reason=%s",
                    epoch + 1,
                    loss,
                    epoch_learning_rate,
                    validation["loss"],
                    validation["auc"],
                    test["loss"],
                    test["auc"],
                    validation_loss_state.best_loss,
                    validation_loss_state.bad_streak,
                    validation_loss_state.rise_streak,
                    args.validation_loss_patience,
                    validation_loss_state.trend_delta,
                    stop_reason or "none",
                )
                save_checkpoint(last_checkpoint, model, optimizer, epoch, metadata)
                if is_best:
                    save_checkpoint(output_dir / "best.pt", model, optimizer, epoch, metadata)
                    save_checkpoint(output_dir / "best_auc.pt", model, optimizer, epoch, metadata)
                if is_best_loss:
                    save_checkpoint(output_dir / "best_loss.pt", model, optimizer, epoch, metadata)
                stop = bool(stop_reason and stop_reason != "max_epochs_reached")
            if context.world_size > 1:
                learning_rate_tensor = torch.tensor(
                    [next_learning_rate if context.is_main else 0.0],
                    device=context.device,
                )
                distributed.broadcast(learning_rate_tensor, src=0)
                set_learning_rate(optimizer, float(learning_rate_tensor.item()))
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
            unwrap_model(model).load_state_dict(best_checkpoint["model_state_dict"])
            result = runtime_validate(
                unwrap_model(model),
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
        finish_distributed(context)


if __name__ == "__main__":
    raise SystemExit(main())
