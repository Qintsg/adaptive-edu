#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT validation loss 趋势早停状态机。
@Project : adaptive-edu
@File : mefkt_early_stopping.py
@Author : Qintsg
@Date : 2026-08-30
'''

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass
class ValidationLossEarlyStopping:
    """跟踪 validation loss 的显著改善、逐轮上升和滑动窗口趋势。"""

    patience: int
    min_delta: float
    plateau_patience: int = 0
    best_loss: float = math.inf
    previous_loss: float | None = None
    bad_streak: int = 0
    rise_streak: int = 0
    history: list[float] = field(default_factory=list)

    def restore(self, metadata: dict[str, object]) -> bool:
        """
        从 checkpoint metadata 恢复状态。

        :param metadata: `early_stopping` 元数据。
        :returns: checkpoint 是否包含 validation loss 状态。
        """
        if metadata.get("best_validation_loss") is None:
            return False
        self.best_loss = float(metadata["best_validation_loss"])
        self.previous_loss = float(metadata.get("previous_validation_loss", self.best_loss))
        self.bad_streak = int(metadata.get("validation_loss_bad_streak", 0))
        self.rise_streak = int(metadata.get("validation_loss_rise_streak", 0))
        self.plateau_patience = int(metadata.get("validation_loss_plateau_patience", self.plateau_patience))
        raw_history = metadata.get("validation_loss_history", [])
        if isinstance(raw_history, list):
            self.extend_history(float(value) for value in raw_history)
        return True

    def extend_history(self, losses: Iterable[float]) -> None:
        """
        追加历史 loss，并只保留趋势判断所需窗口。

        :param losses: 可迭代的 validation loss。
        :returns: None。
        """
        for loss in losses:
            value = float(loss)
            if not self.history or not math.isclose(self.history[-1], value, rel_tol=0.0, abs_tol=1e-12):
                self.history.append(value)
        keep = max(self.patience + 1, 2)
        self.history = self.history[-keep:]

    def establish_baseline(self, loss: float, preserve_state: bool) -> None:
        """
        用恢复权重的实测 validation loss 建立续训基线。

        :param loss: 当前 checkpoint 的 validation loss。
        :param preserve_state: 是否保留新版 checkpoint 已记录的状态。
        :returns: None。
        """
        if preserve_state:
            self.best_loss = min(self.best_loss, loss)
        else:
            self.best_loss = loss
            self.bad_streak = 0
            self.rise_streak = 0
        self.previous_loss = loss
        self.extend_history([loss])

    def update(self, loss: float) -> bool:
        """
        记录一轮 validation loss 并判断是否应早停。

        :param loss: 当前 validation loss。
        :returns: 是否检测到持续且明显的恶化趋势。
        """
        improved = loss < self.best_loss - self.min_delta
        if improved:
            self.best_loss = loss
            self.bad_streak = 0
            self.rise_streak = 0
        else:
            self.bad_streak += 1
            if self.previous_loss is not None and loss > self.previous_loss + self.min_delta:
                self.rise_streak += 1
            else:
                self.rise_streak = 0
        self.previous_loss = loss
        self.extend_history([loss])
        return self.should_stop()

    @property
    def trend_delta(self) -> float:
        """
        计算窗口后半段与前半段的平均 loss 差。

        :returns: 正数表示近期 loss 整体更高。
        """
        if self.patience < 4 or len(self.history) < self.patience:
            return 0.0
        window = self.history[-self.patience :]
        midpoint = len(window) // 2
        older = sum(window[:midpoint]) / midpoint
        newer = sum(window[midpoint:]) / (len(window) - midpoint)
        return newer - older

    def should_stop(self) -> bool:
        """
        判断逐轮显著上升或抗噪声滑动趋势是否达到早停门槛。

        :returns: 是否应停止训练。
        """
        if self.patience <= 0 or self.previous_loss is None:
            return False
        exact_rise = self.rise_streak >= self.patience
        plateau = self.plateau_patience > 0 and self.bad_streak >= self.plateau_patience
        trend_rise = (
            self.bad_streak >= self.patience
            and self.trend_delta > self.min_delta
            and self.previous_loss > self.best_loss + self.min_delta
        )
        return exact_rise or trend_rise or plateau

    def reason(self) -> str:
        """
        返回当前早停原因；未达到条件时返回空字符串。

        :returns: validation_loss_plateau、validation_loss_rising 或空字符串。
        """
        if self.plateau_patience > 0 and self.bad_streak >= self.plateau_patience:
            return "validation_loss_plateau"
        if self.should_stop():
            return "validation_loss_rising"
        return ""

    def to_metadata(self, stop_reason: str = "") -> dict[str, object]:
        """
        生成可写入 checkpoint 的状态。

        :param stop_reason: 当前停止原因。
        :returns: 可 JSON 序列化的状态字典。
        """
        return {
            "best_validation_loss": self.best_loss,
            "previous_validation_loss": self.previous_loss,
            "validation_loss_bad_streak": self.bad_streak,
            "validation_loss_rise_streak": self.rise_streak,
            "validation_loss_history": self.history,
            "validation_loss_trend_delta": self.trend_delta,
            "validation_loss_patience": self.patience,
            "validation_loss_plateau_patience": self.plateau_patience,
            "validation_loss_min_delta": self.min_delta,
            "stop_reason": stop_reason,
        }
