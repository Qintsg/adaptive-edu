#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT-NG 首阶段的稀疏知识状态、遗忘与因果作答模型。
@Project : adaptive-edu
@File : model.py
@Author : Qintsg
@Date : 2026-09-24
'''

from __future__ import annotations

from dataclasses import asdict, dataclass

import torch
from torch import Tensor, nn
from torch.nn import functional


@dataclass(frozen=True)
class ModelConfig:
    """模型容量和受约束的状态超参数。"""

    hidden_dim: int = 384
    graph_layers: int = 2
    bottleneck_mix: float = 0.5
    bottleneck_temperature: float = 0.7
    dropout: float = 0.10
    prior_variance: float = 1.5
    process_noise: float = 0.03
    max_update: float = 1.0
    repeat_weight: float = 0.5

    def to_dict(self) -> dict[str, int | float]:
        """输出 checkpoint 可序列化配置。

        :returns: 配置字段字典。
        """
        return asdict(self)


class RelationLayer(nn.Module):
    """以方向和边类型区分课程关系。"""

    def __init__(self, hidden_dim: int) -> None:
        """建立四种关系的共享消息参数。

        :param hidden_dim: 概念表示维度。
        :returns: None。
        """
        super().__init__()
        self.projections = nn.ModuleList(nn.Linear(hidden_dim, hidden_dim, bias=False) for _ in range(4))
        self.norm = nn.LayerNorm(hidden_dim)

    def forward(self, concepts: Tensor, edges: Tensor) -> Tensor:
        """执行一层有类型的课程图消息传递。

        :param concepts: `[S,D]` 内容表示。
        :param edges: `[E,3]`，源、目标、关系类型。
        :returns: `[S,D]` 更新表示。
        """
        if edges.numel() == 0:
            return concepts
        messages = torch.zeros_like(concepts)
        counts = concepts.new_zeros((concepts.size(0), 1))
        for relation_type, projection in enumerate(self.projections):
            selected = edges[:, 2] == relation_type
            if not bool(selected.any()):
                continue
            source, target = edges[selected, 0], edges[selected, 1]
            messages = messages.index_add(0, target, projection(concepts[source]))
            counts = counts.index_add(0, target, concepts.new_ones((target.numel(), 1)))
        return self.norm(concepts + functional.silu(messages / counts.clamp_min(1.0)))


class MEFKTNG(nn.Module):
    """内容泛化的显式知识状态模型，预测必经知识点能力。"""

    def __init__(
        self,
        item_content: Tensor,
        item_skills: Tensor,
        item_difficulty: Tensor,
        skill_content: Tensor,
        graph_edges: Tensor,
        config: ModelConfig,
    ) -> None:
        """初始化共享课程编码器和状态读出头。

        :param item_content: `[Q,384]` 冻结内容向量。
        :param item_skills: `[Q,K]` 稳定知识点索引，负数为缺失。
        :param item_difficulty: `[Q,2]` 教师先验与缺失掩码。
        :param skill_content: `[S,384]` 知识点内容向量。
        :param graph_edges: `[E,3]` 已审核类型边。
        :param config: 网络和滤波配置。
        :returns: None。
        :raises ValueError: 输入维度或超参数非法。
        """
        super().__init__()
        if item_content.ndim != 2 or item_content.size(1) != 384 or skill_content.ndim != 2 or skill_content.size(1) != 384:
            raise ValueError("题目与知识点向量必须为 384 维")
        if item_skills.ndim != 2 or item_skills.size(0) != item_content.size(0):
            raise ValueError("item_skills 形状与题目目录不一致")
        if item_difficulty.shape != (item_content.size(0), 2):
            raise ValueError("item_difficulty 必须为 [Q,2]")
        if graph_edges.ndim != 2 or graph_edges.size(1) != 3:
            raise ValueError("graph_edges 必须为 [E,3]")
        if config.hidden_dim < 32 or config.graph_layers not in {0, 1, 2} or not 0 <= config.bottleneck_mix <= 1:
            raise ValueError("模型容量或瓶颈权重不合法")
        if not 0 < config.bottleneck_temperature or not 0 < config.prior_variance or config.max_update <= 0:
            raise ValueError("状态参数必须为正")
        self.config = config
        self.register_buffer("item_content", item_content.float().contiguous())
        self.register_buffer("item_skills", item_skills.long().contiguous())
        self.register_buffer("item_difficulty", item_difficulty.float().contiguous())
        self.register_buffer("skill_content", skill_content.float().contiguous())
        self.register_buffer("graph_edges", graph_edges.long().contiguous())
        dimension = config.hidden_dim
        self.skill_encoder = nn.Sequential(nn.Linear(384, dimension), nn.LayerNorm(dimension), nn.SiLU())
        self.graph_layers = nn.ModuleList(RelationLayer(dimension) for _ in range(config.graph_layers))
        self.item_encoder = nn.Sequential(
            nn.Linear(384 + dimension + 2, dimension * 2), nn.LayerNorm(dimension * 2),
            nn.SiLU(), nn.Dropout(config.dropout), nn.Linear(dimension * 2, dimension),
            nn.LayerNorm(dimension), nn.SiLU(),
        )
        self.difficulty_head = nn.Linear(dimension, 1)
        self.discrimination_head = nn.Linear(dimension, 1)
        self.stability_head = nn.Linear(dimension, 1)
        nn.init.zeros_(self.stability_head.weight)
        nn.init.constant_(self.stability_head.bias, 1.4)

    def _encode_catalog(self, selected_items: Tensor) -> tuple[Tensor, Tensor, Tensor, Tensor]:
        """共享内容与图表示，得到被使用题目的静态参数。

        :param selected_items: 当前 batch 唯一题目索引。
        :returns: 题目难度、区分度、知识点索引、全课程稳定时间尺度。
        """
        concepts = self.skill_encoder(self.skill_content)
        for layer in self.graph_layers:
            concepts = layer(concepts, self.graph_edges)
        skills = self.item_skills[selected_items]
        active = skills >= 0
        if concepts.size(0) == 0:
            pooled = self.item_content.new_zeros((selected_items.numel(), self.config.hidden_dim))
        else:
            selected_concepts = concepts[skills.clamp_min(0)]
            pooled = (selected_concepts * active.unsqueeze(-1)).sum(dim=1) / active.sum(dim=1, keepdim=True).clamp_min(1)
        item_view = self.item_encoder(torch.cat((self.item_content[selected_items], pooled,
                                                  self.item_difficulty[selected_items]), dim=-1))
        difficulty = self.difficulty_head(item_view).squeeze(-1)
        discrimination = (0.05 + functional.softplus(self.discrimination_head(item_view).squeeze(-1))).clamp_max(5.0)
        stability = (24.0 + 168.0 * functional.softplus(self.stability_head(concepts).squeeze(-1))).clamp_max(24.0 * 365.0)
        return difficulty, discrimination, skills, stability

    def _commit(
        self, mu: Tensor, variance: Tensor, gradient: Tensor, information: Tensor, rows: Tensor,
    ) -> tuple[Tensor, Tensor, Tensor, Tensor]:
        """一次性提交一个完整测验场次的证据信息。

        :param mu: 演化到场次时刻的知识能力。
        :param variance: 状态方差。
        :param gradient: 场次梯度和。
        :param information: 场次 Fisher 信息和。
        :param rows: 当前需要提交的 batch 行。
        :returns: 更新状态及清空对应行的待提交量。
        """
        updated_v = (1.0 / (1.0 / variance.clamp_min(1e-4) + information)).clamp(1e-4, 9.0)
        updated_mu = (mu + (updated_v * gradient).clamp(-self.config.max_update, self.config.max_update)).clamp(-8.0, 8.0)
        chosen = rows.unsqueeze(1)
        return (torch.where(chosen, updated_mu, mu), torch.where(chosen, updated_v, variance),
                torch.where(chosen, torch.zeros_like(gradient), gradient),
                torch.where(chosen, torch.zeros_like(information), information))

    def forward(self, batch: dict[str, Tensor]) -> tuple[Tensor, Tensor]:
        """先预测每题，再按场次批量吸收已知结果。

        :param batch: items/correct/gaps/time_known/episodes/valid 张量。
        :returns: 作答前 logits 和有效位置掩码。
        """
        items, labels, gaps = batch["items"], batch["correct"], batch["gaps"]
        time_known, episodes, valid = batch["time_known"], batch["episodes"], batch["valid"]
        if items.ndim != 2 or any(value.shape != items.shape for value in (labels, gaps, time_known, episodes, valid)):
            raise ValueError("所有事件张量必须具有相同 [B,L] 形状")
        unique_items, inverse = torch.unique(items.clamp_min(0), sorted=True, return_inverse=True)
        difficulty, discrimination, unique_item_skills, all_stability = self._encode_catalog(unique_items)
        difficulty, discrimination, all_stability = difficulty.float(), discrimination.float(), all_stability.float()
        item_skills = unique_item_skills[inverse]
        active_skills = torch.unique(item_skills[item_skills >= 0])
        if active_skills.numel() == 0:
            active_skills = torch.zeros(1, device=items.device, dtype=torch.long)
            all_stability = all_stability.new_full((1,), 24.0 * 14.0)
        local_skills = torch.searchsorted(active_skills, item_skills.clamp_min(0))
        local_skills = local_skills.clamp_max(active_skills.numel() - 1)
        stability = all_stability[active_skills]
        item_difficulty = difficulty[inverse]
        item_discrimination = discrimination[inverse]
        batch_size, length = items.shape
        slots = active_skills.numel()
        mu = item_difficulty.new_zeros((batch_size, slots))
        variance = item_difficulty.new_full((batch_size, slots), self.config.prior_variance)
        last_time = item_difficulty.new_zeros((batch_size, slots))
        seen = torch.zeros((batch_size, slots), device=items.device, dtype=torch.bool)
        clock = item_difficulty.new_zeros(batch_size)
        episode_clock = item_difficulty.new_zeros(batch_size)
        pending_gradient = torch.zeros_like(mu)
        pending_information = torch.zeros_like(mu)
        pending_rows = torch.zeros(batch_size, device=items.device, dtype=torch.bool)
        previous_episode = episodes.new_full((batch_size,), -1)
        previous_item = items.new_full((batch_size,), -1)
        predictions: list[Tensor] = []
        for step in range(length):
            current_valid = valid[:, step] & (items[:, step] >= 0)
            boundary = current_valid & pending_rows & (episodes[:, step] != previous_episode)
            mu, variance, pending_gradient, pending_information = self._commit(
                mu, variance, pending_gradient, pending_information, boundary,
            )
            pending_rows = pending_rows & ~boundary
            clock = clock + torch.where(current_valid & time_known[:, step], gaps[:, step].clamp_min(0), 0.0)
            episode_clock = torch.where(current_valid & (episodes[:, step] != previous_episode), clock, episode_clock)
            indices = local_skills[:, step]
            active = (item_skills[:, step] >= 0) & current_valid.unsqueeze(-1)
            old_mu, old_v = mu.gather(1, indices), variance.gather(1, indices)
            elapsed = (episode_clock.unsqueeze(1) - last_time.gather(1, indices)).clamp_min(0)
            elapsed = torch.where(seen.gather(1, indices) & active, elapsed, 0.0)
            current_s = stability[indices].clamp_min(1.0)
            pre_mu = torch.where(active, (old_mu - 0.6931471805599453 * elapsed / current_s).clamp(-8.0, 8.0), old_mu)
            pre_v = torch.where(active, (old_v + self.config.process_noise * elapsed / current_s).clamp(1e-4, 9.0), old_v)
            mu = mu.scatter_add(1, indices, (pre_mu - old_mu) * active)
            variance = variance.scatter_add(1, indices, (pre_v - old_v) * active)
            last_time = last_time.scatter_add(1, indices, (episode_clock.unsqueeze(1) - last_time.gather(1, indices)) * active)
            seen = (seen.long().scatter_add(1, indices, active.long()) > 0)
            count = active.sum(dim=1, keepdim=True)
            weights = active.float() / count.clamp_min(1)
            mean = (pre_mu * weights).sum(dim=1)
            soft_logits = torch.where(active, weights.clamp_min(1e-12).log() - pre_mu / self.config.bottleneck_temperature, -1e9)
            soft_weights = torch.softmax(soft_logits, dim=1) * active
            soft_min = -self.config.bottleneck_temperature * torch.logsumexp(soft_logits, dim=1)
            ability = torch.where(count.squeeze(1) > 0,
                                  (1.0 - self.config.bottleneck_mix) * mean + self.config.bottleneck_mix * soft_min,
                                  torch.zeros_like(mean))
            logit = item_discrimination[:, step] * (ability - item_difficulty[:, step])
            predictions.append(torch.where(current_valid, logit, torch.zeros_like(logit)))
            derivative = item_discrimination[:, step].unsqueeze(1) * (
                (1.0 - self.config.bottleneck_mix) * weights + self.config.bottleneck_mix * soft_weights
            )
            probability = torch.sigmoid(logit)
            repeated = current_valid & (items[:, step] == previous_item)
            evidence_weight = torch.where(repeated, self.config.repeat_weight, 1.0).unsqueeze(1)
            gradient = (labels[:, step].unsqueeze(1) - probability.unsqueeze(1)) * derivative
            information = (probability * (1.0 - probability)).unsqueeze(1) * derivative.square()
            pending_gradient = pending_gradient.scatter_add(1, indices, gradient * active * evidence_weight)
            pending_information = pending_information.scatter_add(1, indices, information * active * evidence_weight)
            pending_rows = pending_rows | current_valid
            previous_episode = torch.where(current_valid, episodes[:, step], previous_episode)
            previous_item = torch.where(current_valid, items[:, step], previous_item)
        mu, variance, _, _ = self._commit(mu, variance, pending_gradient, pending_information, pending_rows)
        return torch.stack(predictions, dim=1), valid & (items >= 0)
