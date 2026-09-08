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

from dataclasses import asdict, dataclass, fields, replace


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
    architecture_version: int = 2
    skill_memory_dim: int = 0
    external_skill_slots: int = 0
    item_id_dropout: float = 0.0
    irt_residual_scale: float = 0.0
    online_feature_dim: int = 0

    def to_dict(self) -> dict[str, object]:
        """
        返回可写入 checkpoint 的配置字典。

        :returns: 模型结构配置字典。
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict[str, object]) -> MEFKTConfig:
        """
        从 checkpoint 字典恢复配置，并忽略未来版本的未知字段。

        :param values: checkpoint 中保存的模型配置。
        :returns: 与保存版本兼容的模型配置。
        """
        allowed = {field.name for field in fields(cls)}
        payload = {key: value for key, value in values.items() if key in allowed}
        return cls(**payload)  # type: ignore[arg-type]


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
        architecture_version=3,
        skill_memory_dim=16,
        external_skill_slots=32,
        item_id_dropout=0.20,
        irt_residual_scale=0.25,
        online_feature_dim=7,
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
        # Full 模型在百万级交互上容易依赖题目 ID，稍强正则化有助于跨课程泛化。
        dropout=0.20,
        content_embedding_dim=384,
        transformer_layers=6,
        transformer_heads=8,
        transformer_feedforward_dim=1536,
        memory_size=64,
        architecture_version=3,
        skill_memory_dim=32,
        external_skill_slots=64,
        item_id_dropout=0.35,
        irt_residual_scale=0.25,
        online_feature_dim=7,
    )


def legacy_config(profile: str) -> MEFKTConfig:
    """
    返回缺少模型配置元数据时使用的 v2 兼容配置。

    :param profile: full 或 lite。
    :returns: 关闭 v3 扩展的结构配置。
    :raises ValueError: profile 不合法时抛出。
    """
    if profile == "lite":
        current = lite_config()
    elif profile == "full":
        current = full_config()
    else:
        raise ValueError(f"未知模型 profile: {profile}")
    return replace(
        current,
        architecture_version=2,
        skill_memory_dim=0,
        external_skill_slots=0,
        item_id_dropout=0.0,
        irt_residual_scale=0.0,
        online_feature_dim=0,
    )


__all__ = ["MEFKTConfig", "full_config", "legacy_config", "lite_config"]
