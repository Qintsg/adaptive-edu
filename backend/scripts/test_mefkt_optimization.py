#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT v3 学习率调度回归测试。
@Project : adaptive-edu
@File : test_mefkt_optimization.py
@Author : Qintsg
@Date : 2026-09-01
'''

from __future__ import annotations

import torch

from mefkt_early_stopping import ValidationLossEarlyStopping
from mefkt_optimization import build_optimizer, current_learning_rate, step_scheduler
from mefkt_training_core import balanced_binary_loss


def test_warmup_piecewise_scheduler_does_not_decay_too_early() -> None:
    """v3 调度器应完成 warmup、高学习率和中学习率阶段后才到最低学习率。"""
    model = torch.nn.Linear(2, 1)
    optimizer, scheduler = build_optimizer(
        model,
        learning_rate=1e-4,
        weight_decay=5e-4,
        scheduler_name="warmup-piecewise",
        scheduler_factor=0.3,
        scheduler_patience=3,
        min_learning_rate=1e-5,
        total_epochs=100,
        warmup_epochs=5,
        high_lr_epochs=15,
        mid_lr_epochs=20,
    )
    rates = [current_learning_rate(optimizer)]
    for _ in range(40):
        step_scheduler(scheduler, 0.5)
        rates.append(current_learning_rate(optimizer))

    assert rates[0] == 2e-5
    assert rates[4] == 1e-4
    assert rates[14] == 1e-4
    assert rates[15] == 3e-5
    assert rates[34] == 3e-5
    assert rates[35] == 1e-5


def test_validation_plateau_stops_without_waiting_for_monotonic_rise() -> None:
    """长期无改善即使有微小噪声，也必须在 plateau patience 后早停。"""
    state = ValidationLossEarlyStopping(8, 0.001, plateau_patience=5)

    assert not state.update(0.5000)
    assert not state.update(0.5002)
    assert not state.update(0.4998)
    assert not state.update(0.5001)
    assert not state.update(0.4999)
    assert state.update(0.5003)


def test_subject_balanced_loss_prevents_majority_domain_from_hiding_failure() -> None:
    """少数学科的严重错误不能被多数域容易样本淹没。"""
    logits = torch.cat([torch.full((100,), 8.0), torch.tensor([-8.0])])
    targets = torch.ones(101)
    subjects = torch.cat([torch.zeros(100, dtype=torch.long), torch.ones(1, dtype=torch.long)])

    event_loss = balanced_binary_loss(logits, targets, subjects, alpha=0.0)
    domain_loss = balanced_binary_loss(logits, targets, subjects, alpha=1.0)

    assert domain_loss.item() > event_loss.item() * 20
