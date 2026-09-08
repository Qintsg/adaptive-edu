#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT 训练 batch 优化深模块。
@Project : adaptive-edu
@File : mefkt_training_core.py
@Author : Qintsg
@Date : 2026-09-01
'''

from __future__ import annotations

import torch
from torch import Tensor, nn
from torch.nn import functional
from torch.utils.data import DataLoader


def balanced_binary_loss(
    logits: Tensor,
    targets: Tensor,
    subjects: Tensor,
    alpha: float,
) -> Tensor:
    """
    混合逐事件 BCE 和等学科 BCE，避免大领域淹没小领域。

    :param logits: 一维预测 logits。
    :param targets: 一维 0/1 标签。
    :param subjects: 一维学科索引。
    :param alpha: 等学科 loss 比例，0 为普通 BCE，1 为完全等学科。
    :returns: 标量 loss。
    :raises ValueError: 输入形状或 alpha 不合法时抛出。
    """
    if logits.ndim != 1 or targets.shape != logits.shape or subjects.shape != logits.shape:
        raise ValueError("logits、targets 和 subjects 必须是等长一维张量")
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("subject balance alpha 必须在 0 和 1 之间")
    sample_losses = functional.binary_cross_entropy_with_logits(logits, targets.float(), reduction="none")
    event_loss = sample_losses.mean()
    subject_losses = [
        sample_losses[subjects == subject].mean()
        for subject in torch.unique(subjects)
    ]
    domain_loss = torch.stack(subject_losses).mean()
    return (1.0 - alpha) * event_loss + alpha * domain_loss


def train_epoch(
    model: nn.Module,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
    amp: bool,
    item_subjects: Tensor,
    subject_balance_alpha: float,
) -> float:
    """
    使用领域平衡 BCE 和梯度裁剪训练一个 epoch。

    :param model: 待训练模型。
    :param loader: 训练 DataLoader。
    :param optimizer: AdamW 优化器。
    :param device: 训练设备。
    :param amp: 是否启用 CUDA bfloat16 autocast。
    :param item_subjects: 设备上的题目学科索引。
    :param subject_balance_alpha: 等学科 loss 比例。
    :returns: 平均 batch loss。
    """
    model.train()
    total_loss = 0.0
    batches = 0
    for batch in loader:
        items, correct, gaps, response_times, target_mask = (
            value.to(device, non_blocking=True) for value in batch
        )
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
            selected_subjects = item_subjects[items[effective_mask]]
            loss = balanced_binary_loss(
                logits[effective_mask],
                correct[effective_mask],
                selected_subjects,
                subject_balance_alpha,
            )
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        total_loss += float(loss.detach().item())
        batches += 1
    return total_loss / max(batches, 1)


__all__ = ["balanced_binary_loss", "train_epoch"]
