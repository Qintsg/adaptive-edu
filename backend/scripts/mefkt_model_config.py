#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT / MEFKT-Lite 模型结构配置。
@Project : adaptive-edu
@File : mefkt_model_config.py
@Author : Qintsg
@Date : 2026-08-24
'''

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MEFKTConfig:
    """MEFKT 模型结构配置。"""

    profile: str
    item_embedding_dim: int
    subject_embedding_dim: int
    skill_embedding_dim: int
    feature_embedding_dim: int
    item_view_dim: int
    answer_embedding_dim: int
    gap_embedding_dim: int
    response_time_embedding_dim: int
    state_dim: int
    dropout: float
    content_embedding_dim: int = 384
    transformer_layers: int = 0
    transformer_heads: int = 0
    transformer_feedforward_dim: int = 0
    memory_size: int = 0

    def to_dict(self) -> dict[str, object]:
        """
        返回可写入 checkpoint 的配置字典。

        :returns: 模型结构配置字典。
        """
        return asdict(self)


def lite_config() -> MEFKTConfig:
    """
    返回低核心 CPU 推理配置。

    :returns: MEFKT-Lite 配置。
    """
    return MEFKTConfig(
        profile="lite",
        item_embedding_dim=64,
        subject_embedding_dim=16,
        skill_embedding_dim=32,
        feature_embedding_dim=32,
        item_view_dim=128,
        answer_embedding_dim=16,
        gap_embedding_dim=16,
        response_time_embedding_dim=16,
        state_dim=128,
        dropout=0.10,
        content_embedding_dim=384,
    )


def full_config() -> MEFKTConfig:
    """
    返回正常 GPU 推理配置。

    :returns: MEFKT Full 配置。
    """
    return MEFKTConfig(
        profile="full",
        item_embedding_dim=192,
        subject_embedding_dim=64,
        skill_embedding_dim=128,
        feature_embedding_dim=64,
        item_view_dim=384,
        answer_embedding_dim=32,
        gap_embedding_dim=32,
        response_time_embedding_dim=32,
        state_dim=384,
        dropout=0.15,
        content_embedding_dim=384,
        transformer_layers=6,
        transformer_heads=8,
        transformer_feedforward_dim=1536,
        memory_size=64,
    )


__all__ = ["MEFKTConfig", "full_config", "lite_config"]
