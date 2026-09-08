#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT 题目、时间与自适应遗忘编码器。
@Project : adaptive-edu
@File : mefkt_encoders.py
@Author : Qintsg
@Date : 2026-08-24
'''

from __future__ import annotations

import torch
from mefkt_model_config import MEFKTConfig
from torch import Tensor, nn
from torch.nn import functional


class LogTimeEncoder(nn.Module):
    """将跨度很大的正时间值编码为稳定表示。"""

    def __init__(self, output_dim: int) -> None:
        """
        初始化时间编码器。

        :param output_dim: 输出维度。
        :returns: None。
        """
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(3, output_dim),
            nn.GELU(),
            nn.LayerNorm(output_dim),
        )

    def forward(self, values: Tensor) -> Tensor:
        """
        编码小时或秒时间值。

        :param values: 任意形状的正时间张量。
        :returns: 在末尾增加 output_dim 的编码张量。
        """
        log_value = torch.log1p(values.float().clamp_min(1e-4))
        inputs = torch.stack(
            [log_value, torch.sqrt(log_value + 1e-6), torch.reciprocal(log_value + 1.0)],
            dim=-1,
        )
        return self.network(inputs)


class MultiViewItemEncoder(nn.Module):
    """融合封闭记忆分支与开放课程内容分支。"""

    def __init__(
        self,
        item_count: int,
        item_features: Tensor,
        item_subjects: Tensor,
        item_skills: Tensor,
        subject_count: int,
        skill_count: int,
        config: MEFKTConfig,
    ) -> None:
        """
        初始化多视角题目编码器。

        :param item_count: 已知题目数量。
        :param item_features: 每道题的通用数值特征和固定内容向量。
        :param item_subjects: 每道题的学科索引。
        :param item_skills: 每道题的多个知识点索引，-1 表示 padding。
        :param subject_count: 学科词表大小。
        :param skill_count: 知识点词表大小。
        :param config: 模型结构配置。
        :returns: None。
        """
        super().__init__()
        self.config = config
        self.item_count = item_count
        self.subject_count = subject_count
        self.skill_count = skill_count
        self.item_embedding = nn.Embedding(item_count + 1, config.item_embedding_dim)
        self.subject_embedding = nn.Embedding(
            subject_count + 1,
            config.subject_embedding_dim,
            padding_idx=subject_count,
        )
        self.skill_embedding = nn.Embedding(
            skill_count + 1,
            config.skill_embedding_dim,
            padding_idx=skill_count,
        )
        raw_feature_dim = int(item_features.size(1))
        content_source_dim = max(raw_feature_dim - 7, 0)
        self.feature_encoder = nn.Sequential(
            nn.Linear(7, config.feature_embedding_dim),
            nn.GELU(),
            nn.LayerNorm(config.feature_embedding_dim),
        )
        self.content_encoder = nn.Sequential(
            nn.Linear(config.content_embedding_dim, config.feature_embedding_dim),
            nn.GELU(),
            nn.LayerNorm(config.feature_embedding_dim),
        )
        fusion_dim = (
            config.item_embedding_dim
            + config.subject_embedding_dim
            + config.skill_embedding_dim
            + config.feature_embedding_dim * 2
        )
        self.fusion = nn.Sequential(
            nn.Linear(fusion_dim, config.item_view_dim),
            nn.GELU(),
            nn.LayerNorm(config.item_view_dim),
            nn.Dropout(config.dropout),
        )
        numeric_catalog = item_features.float()[:, :7]
        if numeric_catalog.size(1) < 7:
            numeric_catalog = functional.pad(numeric_catalog, (0, 7 - numeric_catalog.size(1)))
        content_catalog = item_features.float()[:, 7 : 7 + content_source_dim]
        if content_catalog.size(1) < config.content_embedding_dim:
            content_catalog = functional.pad(content_catalog, (0, config.content_embedding_dim - content_catalog.size(1)))
        else:
            content_catalog = content_catalog[:, : config.content_embedding_dim]
        unknown_features = torch.zeros((1, 7), dtype=torch.float32)
        unknown_content = torch.zeros((1, config.content_embedding_dim), dtype=torch.float32)
        subject_catalog = torch.cat(
            [item_subjects.long().clamp(0, max(subject_count - 1, 0)), torch.tensor([subject_count])]
        )
        safe_skills = item_skills.long().clone()
        safe_skills[(safe_skills < 0) | (safe_skills >= skill_count)] = skill_count
        unknown_skills = torch.full((1, safe_skills.size(1)), skill_count, dtype=torch.long)
        self.register_buffer("feature_catalog", torch.cat([numeric_catalog, unknown_features]), persistent=True)
        self.register_buffer("content_catalog", torch.cat([content_catalog, unknown_content]), persistent=True)
        self.register_buffer("subject_catalog", subject_catalog, persistent=True)
        self.register_buffer("skill_catalog", torch.cat([safe_skills, unknown_skills]), persistent=True)

    def forward(
        self,
        item_indices: Tensor,
        external_features: Tensor | None = None,
        external_content_features: Tensor | None = None,
        apply_item_id_dropout: bool = False,
    ) -> Tensor:
        """
        编码题目索引；未知索引可以使用外部开放世界元数据。

        :param item_indices: 题目索引张量。
        :param external_features: 未知题目的 7 维数值特征。
        :param external_content_features: 未知题目的固定内容向量。
        :param apply_item_id_dropout: 是否随机屏蔽已知题目的 ID embedding。
        :returns: 多视角题目表示。
        """
        known = (item_indices >= 0) & (item_indices < self.item_count)
        safe_items = torch.where(known, item_indices.long(), torch.full_like(item_indices.long(), self.item_count))
        embedding_items = safe_items
        if apply_item_id_dropout and self.training and self.config.item_id_dropout > 0.0:
            dropped = known & (torch.rand(item_indices.shape, device=item_indices.device) < self.config.item_id_dropout)
            embedding_items = torch.where(dropped, torch.full_like(safe_items, self.item_count), safe_items)
        item_view = self.item_embedding(embedding_items)
        subject_view = self.subject_embedding(self.subject_catalog[safe_items])
        skill_indices = self.skill_catalog[safe_items]
        skill_mask = skill_indices != self.skill_count
        skill_values = self.skill_embedding(skill_indices)
        skill_view = (skill_values * skill_mask.unsqueeze(-1)).sum(dim=-2)
        skill_view = skill_view / skill_mask.sum(dim=-1, keepdim=True).clamp_min(1)
        numeric_features = self.feature_catalog[safe_items]
        content_features = self.content_catalog[safe_items]
        if external_features is not None:
            if external_features.shape != (*item_indices.shape, 7):
                raise ValueError("未知题目外部数值特征必须为 [..., 7]")
            numeric_features = torch.where(known.unsqueeze(-1), numeric_features, external_features.float())
        if external_content_features is not None:
            if external_content_features.shape != (*item_indices.shape, self.config.content_embedding_dim):
                raise ValueError(f"未知题目内容特征必须为 [..., {self.config.content_embedding_dim}]")
            content_features = torch.where(
                known.unsqueeze(-1),
                content_features,
                external_content_features.float(),
            )
        feature_view = self.feature_encoder(numeric_features)
        content_view = self.content_encoder(content_features)
        return self.fusion(torch.cat([item_view, subject_view, skill_view, feature_view, content_view], dim=-1))

    def resolve_subject_indices(self, item_indices: Tensor) -> Tensor:
        """
        将题目解析为已知学科索引，未知题目使用共享未知学科槽。

        :param item_indices: 任意形状题目索引。
        :returns: 与输入同形状的学科索引。
        """
        known = (item_indices >= 0) & (item_indices < self.item_count)
        safe_items = torch.where(known, item_indices.long(), torch.full_like(item_indices.long(), self.item_count))
        return self.subject_catalog[safe_items]

    def resolve_skill_indices(
        self,
        item_indices: Tensor,
        external_skill_indices: Tensor | None = None,
    ) -> Tensor:
        """
        将题目解析为知识状态槽；未知题目可使用课程内外部 skill 槽。

        外部 skill 索引是课程内稳定的非负整数，并会映射到专门的开放课程槽，
        不与训练词表中的已知 skill 冲突。负数表示 padding。

        :param item_indices: 任意形状题目索引。
        :param external_skill_indices: `[*item_shape, max_skills]` 外部 skill 索引。
        :returns: `[*item_shape, max_skills]` 状态槽索引。
        :raises ValueError: 外部 skill 形状不匹配时抛出。
        """
        known = (item_indices >= 0) & (item_indices < self.item_count)
        safe_items = torch.where(known, item_indices.long(), torch.full_like(item_indices.long(), self.item_count))
        resolved = self.skill_catalog[safe_items].clone()
        padding_slot = self.skill_count + self.config.external_skill_slots
        resolved[resolved == self.skill_count] = padding_slot
        if external_skill_indices is None:
            return resolved
        if external_skill_indices.shape != resolved.shape:
            raise ValueError(f"外部 skill 索引必须为 {list(resolved.shape)}")
        if self.config.external_skill_slots <= 0:
            external = torch.full_like(external_skill_indices.long(), padding_slot)
        else:
            external = torch.where(
                external_skill_indices >= 0,
                self.skill_count + external_skill_indices.long().remainder(self.config.external_skill_slots),
                torch.full_like(external_skill_indices.long(), padding_slot),
            )
        return torch.where(known.unsqueeze(-1), resolved, external)


class AdaptiveForgetGate(nn.Module):
    """为每个知识状态维度学习条件化遗忘速度。"""

    def __init__(self, condition_dim: int, state_dim: int) -> None:
        """
        初始化遗忘门。

        :param condition_dim: 题目和时间条件维度。
        :param state_dim: 学习者状态维度。
        :returns: None。
        """
        super().__init__()
        self.base_log_rate = nn.Parameter(torch.full((state_dim,), -3.0))
        self.condition_rate = nn.Sequential(
            nn.Linear(condition_dim, state_dim),
            nn.Tanh(),
        )

    def forward(self, hidden: Tensor, conditions: Tensor, gaps: Tensor) -> Tensor:
        """
        根据题目语义与间隔衰减旧状态。

        :param hidden: 旧学习者状态。
        :param conditions: 当前题目、间隔和答题耗时表示。
        :param gaps: 当前交互前的小时间隔。
        :returns: 衰减后的学习者状态。
        """
        rates = functional.softplus(self.base_log_rate + 0.5 * self.condition_rate(conditions)) + 1e-5
        decay = torch.exp(-rates * torch.log1p(gaps.float().clamp_min(1e-4)).unsqueeze(-1))
        return hidden * decay


__all__ = ["AdaptiveForgetGate", "LogTimeEncoder", "MultiViewItemEncoder"]
