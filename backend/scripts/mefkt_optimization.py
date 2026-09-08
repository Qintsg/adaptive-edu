#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT 优化器和学习率调度器构造工具。
@Project : adaptive-edu
@File : mefkt_optimization.py
@Author : Qintsg
@Date : 2026-08-30
'''

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import torch
from torch import nn


class WarmupPiecewiseScheduler:
    """固定完成 warmup、高学习率和中学习率阶段的可恢复调度器。"""

    def __init__(
        self,
        optimizer: torch.optim.Optimizer,
        base_learning_rate: float,
        min_learning_rate: float,
        warmup_epochs: int,
        high_lr_epochs: int,
        mid_lr_epochs: int,
        middle_factor: float,
    ) -> None:
        """
        初始化分段调度并设置第一个 epoch 的学习率。

        :param optimizer: AdamW 优化器。
        :param base_learning_rate: warmup 后的峰值学习率。
        :param min_learning_rate: 最低学习率。
        :param warmup_epochs: 线性 warmup 轮数。
        :param high_lr_epochs: 从训练开始计的高学习率结束轮数。
        :param mid_lr_epochs: 中学习率持续轮数。
        :param middle_factor: 中学习率相对峰值比例。
        :returns: None。
        """
        if warmup_epochs < 0 or high_lr_epochs < warmup_epochs or mid_lr_epochs < 0:
            raise ValueError("warmup/high/mid epoch 配置不合法")
        self.optimizer = optimizer
        self.base_learning_rate = base_learning_rate
        self.min_learning_rate = min_learning_rate
        self.warmup_epochs = warmup_epochs
        self.high_lr_epochs = high_lr_epochs
        self.mid_lr_epochs = mid_lr_epochs
        self.middle_factor = middle_factor
        self.completed_epochs = 0
        set_learning_rate(self.optimizer, self._learning_rate_for_epoch(1))

    def _learning_rate_for_epoch(self, epoch: int) -> float:
        """
        计算指定一基 epoch 的学习率。

        :param epoch: 一基 epoch。
        :returns: 该 epoch 使用的学习率。
        """
        if self.warmup_epochs > 0 and epoch <= self.warmup_epochs:
            return self.base_learning_rate * epoch / self.warmup_epochs
        if epoch <= self.high_lr_epochs:
            return self.base_learning_rate
        if epoch <= self.high_lr_epochs + self.mid_lr_epochs:
            return max(self.base_learning_rate * self.middle_factor, self.min_learning_rate)
        return self.min_learning_rate

    def step(self) -> None:
        """
        完成当前 epoch，并设置下一 epoch 学习率。

        :returns: None。
        """
        self.completed_epochs += 1
        set_learning_rate(self.optimizer, self._learning_rate_for_epoch(self.completed_epochs + 1))

    def state_dict(self) -> dict[str, object]:
        """
        返回可写入 checkpoint 的状态。

        :returns: 调度器状态。
        """
        return {
            "base_learning_rate": self.base_learning_rate,
            "min_learning_rate": self.min_learning_rate,
            "warmup_epochs": self.warmup_epochs,
            "high_lr_epochs": self.high_lr_epochs,
            "mid_lr_epochs": self.mid_lr_epochs,
            "middle_factor": self.middle_factor,
            "completed_epochs": self.completed_epochs,
        }

    def load_state_dict(self, state: Mapping[str, object]) -> None:
        """
        恢复 checkpoint 中的调度阶段。

        :param state: 调度器状态。
        :returns: None。
        """
        self.completed_epochs = int(state.get("completed_epochs", 0))
        set_learning_rate(self.optimizer, self._learning_rate_for_epoch(self.completed_epochs + 1))


Scheduler = (
    torch.optim.lr_scheduler.LRScheduler
    | torch.optim.lr_scheduler.ReduceLROnPlateau
    | WarmupPiecewiseScheduler
    | None
)


def build_optimizer(
    model: nn.Module,
    learning_rate: float,
    weight_decay: float,
    scheduler_name: str,
    scheduler_factor: float,
    scheduler_patience: int,
    min_learning_rate: float,
    total_epochs: int,
    warmup_epochs: int = 0,
    high_lr_epochs: int = 0,
    mid_lr_epochs: int = 0,
) -> tuple[torch.optim.Optimizer, Scheduler]:
    """
    构造 AdamW 和可选的 epoch 级学习率调度器。

    :param model: 待优化模型。
    :param learning_rate: 初始学习率。
    :param weight_decay: AdamW 权重衰减。
    :param scheduler_name: none、plateau、cosine 或 warmup-piecewise。
    :param scheduler_factor: plateau 降学习率比例。
    :param scheduler_patience: plateau 连续无改善轮数。
    :param min_learning_rate: 学习率下限。
    :param total_epochs: cosine 调度的总轮数。
    :param warmup_epochs: warmup-piecewise 线性 warmup 轮数。
    :param high_lr_epochs: warmup-piecewise 高学习率阶段结束轮数。
    :param mid_lr_epochs: warmup-piecewise 中学习率阶段轮数。
    :returns: 优化器和调度器。
    :raises ValueError: 调度器参数不合法时抛出。
    """
    if learning_rate <= 0.0 or weight_decay < 0.0 or min_learning_rate < 0.0:
        raise ValueError("learning_rate 必须为正数，weight_decay 和 min_learning_rate 不能为负数")
    if scheduler_name not in {"none", "plateau", "cosine", "warmup-piecewise"}:
        raise ValueError(f"未知学习率调度器: {scheduler_name}")
    if not 0.0 < scheduler_factor < 1.0:
        raise ValueError("scheduler_factor 必须在 0 和 1 之间")
    if scheduler_patience < 0 or total_epochs < 1:
        raise ValueError("scheduler_patience 不能为负数，total_epochs 必须为正数")
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    if scheduler_name == "none":
        scheduler = None
    elif scheduler_name == "plateau":
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer,
            mode="min",
            factor=scheduler_factor,
            patience=scheduler_patience,
            threshold=1e-3,
            threshold_mode="abs",
            min_lr=min_learning_rate,
        )
    elif scheduler_name == "cosine":
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer,
            T_max=max(total_epochs, 1),
            eta_min=min_learning_rate,
        )
    else:
        scheduler = WarmupPiecewiseScheduler(
            optimizer,
            learning_rate,
            min_learning_rate,
            warmup_epochs,
            high_lr_epochs,
            mid_lr_epochs,
            scheduler_factor,
        )
    return optimizer, scheduler


def step_scheduler(
    scheduler: Scheduler,
    validation_loss: float,
) -> None:
    """
    在完成一轮验证后推进学习率调度器。

    :param scheduler: 学习率调度器。
    :param validation_loss: 当前 validation loss；plateau 调度器使用该值。
    :returns: None。
    """
    if scheduler is None:
        return
    if isinstance(scheduler, torch.optim.lr_scheduler.ReduceLROnPlateau):
        scheduler.step(validation_loss)
    else:
        scheduler.step()


def current_learning_rate(optimizer: torch.optim.Optimizer) -> float:
    """
    读取第一个参数组的当前学习率。

    :param optimizer: 优化器。
    :returns: 当前学习率。
    """
    return float(optimizer.param_groups[0]["lr"])


def set_learning_rate(optimizer: torch.optim.Optimizer, learning_rate: float) -> None:
    """
    将所有参数组同步到同一个学习率。

    :param optimizer: 优化器。
    :param learning_rate: 目标学习率。
    :returns: None。
    """
    for parameter_group in optimizer.param_groups:
        parameter_group["lr"] = learning_rate


def save_checkpoint(
    path: str | Path,
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    epoch: int,
    metadata: dict[str, object],
) -> None:
    """
    原子保存可恢复 checkpoint。

    :param path: checkpoint 输出路径。
    :param model: 原始模型或 DDP 包装模型。
    :param optimizer: 待保存优化器。
    :param epoch: 当前 epoch。
    :param metadata: 模型、数据和指标元数据。
    :returns: None。
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    base_model = model.module if hasattr(model, "module") else model
    torch.save(
        {
            "model_state_dict": base_model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "epoch": epoch,
            "metadata": metadata,
        },
        temporary,
    )
    os.replace(temporary, output_path)


def scheduler_state_dict(
    scheduler: Scheduler,
) -> dict[str, object]:
    """
    返回可放入 checkpoint metadata 的调度器状态。

    :param scheduler: 学习率调度器。
    :returns: 调度器类型和状态字典。
    """
    if scheduler is None:
        return {"name": "none", "state": {}}
    if isinstance(scheduler, torch.optim.lr_scheduler.ReduceLROnPlateau):
        name = "plateau"
    elif isinstance(scheduler, WarmupPiecewiseScheduler):
        name = "warmup-piecewise"
    else:
        name = "cosine"
    return {"name": name, "state": scheduler.state_dict()}


def restore_scheduler_state(
    scheduler: Scheduler,
    payload: object,
) -> bool:
    """
    尝试从 checkpoint metadata 恢复调度器状态。

    :param scheduler: 当前配置生成的调度器。
    :param payload: checkpoint 中的调度器 payload。
    :returns: 是否成功恢复。
    """
    if scheduler is None or not isinstance(payload, Mapping):
        return False
    state = payload.get("state")
    name = payload.get("name")
    if isinstance(scheduler, torch.optim.lr_scheduler.ReduceLROnPlateau):
        expected_name = "plateau"
    elif isinstance(scheduler, WarmupPiecewiseScheduler):
        expected_name = "warmup-piecewise"
    else:
        expected_name = "cosine"
    if name != expected_name or not isinstance(state, Mapping):
        return False
    scheduler.load_state_dict(dict(state))
    return True


__all__ = [
    "build_optimizer",
    "current_learning_rate",
    "restore_scheduler_state",
    "scheduler_state_dict",
    "save_checkpoint",
    "set_learning_rate",
    "step_scheduler",
    "WarmupPiecewiseScheduler",
]
