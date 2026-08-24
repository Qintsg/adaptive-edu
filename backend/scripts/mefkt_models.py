#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT 完整模型与 MEFKT-Lite 轻量模型模块。
@Project : adaptive-edu
@File : mefkt_models.py
@Author : Qintsg
@Date : 2026-08-24
'''

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import torch
from torch import Tensor, nn
import torch.nn.functional as functional


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
    transformer_layers: int = 0
    transformer_heads: int = 0
    transformer_feedforward_dim: int = 0
    memory_size: int = 0

    def to_dict(self) -> dict[str, object]:
        """返回可写入 checkpoint 的配置字典。"""
        return asdict(self)


@dataclass
class SequenceState:
    """可在相邻窗口之间传递的学习者状态。"""

    recurrent: Tensor
    context: Tensor
    memory: Tensor | None = None
    memory_mask: Tensor | None = None

    def detach(self) -> "SequenceState":
        """截断反向传播图并保留状态值。"""
        return SequenceState(
            self.recurrent.detach(),
            self.context.detach(),
            self.memory.detach() if self.memory is not None else None,
            self.memory_mask.detach() if self.memory_mask is not None else None,
        )


def lite_config() -> MEFKTConfig:
    """返回低核心 CPU 推理配置。"""
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
    )


def full_config() -> MEFKTConfig:
    """返回正常 GPU 推理配置。"""
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
        transformer_layers=6,
        transformer_heads=8,
        transformer_feedforward_dim=1536,
        memory_size=64,
    )


class LogTimeEncoder(nn.Module):
    """将跨度很大的正时间值编码为稳定表示。"""

    def __init__(self, output_dim: int) -> None:
        """
        初始化时间编码器。

        :param output_dim: 输出维度。
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
    """融合题目 ID、学科、知识点和通用数值特征。"""

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
        :param item_features: 每道题的通用数值特征。
        :param item_subjects: 每道题的学科索引。
        :param item_skills: 每道题的多个知识点索引，-1 表示 padding。
        :param subject_count: 学科词表大小。
        :param skill_count: 知识点词表大小。
        :param config: 模型结构配置。
        """
        super().__init__()
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
        self.feature_encoder = nn.Sequential(
            nn.Linear(int(item_features.size(1)), config.feature_embedding_dim),
            nn.GELU(),
            nn.LayerNorm(config.feature_embedding_dim),
        )
        fusion_dim = (
            config.item_embedding_dim
            + config.subject_embedding_dim
            + config.skill_embedding_dim
            + config.feature_embedding_dim
        )
        self.fusion = nn.Sequential(
            nn.Linear(fusion_dim, config.item_view_dim),
            nn.GELU(),
            nn.LayerNorm(config.item_view_dim),
            nn.Dropout(config.dropout),
        )
        unknown_features = torch.zeros((1, item_features.size(1)), dtype=torch.float32)
        subject_catalog = torch.cat(
            [item_subjects.long().clamp(0, max(subject_count - 1, 0)), torch.tensor([subject_count])]
        )
        safe_skills = item_skills.long().clone()
        safe_skills[(safe_skills < 0) | (safe_skills >= skill_count)] = skill_count
        unknown_skills = torch.full((1, safe_skills.size(1)), skill_count, dtype=torch.long)
        self.register_buffer("feature_catalog", torch.cat([item_features.float(), unknown_features]), persistent=True)
        self.register_buffer("subject_catalog", subject_catalog, persistent=True)
        self.register_buffer("skill_catalog", torch.cat([safe_skills, unknown_skills]), persistent=True)

    def forward(self, item_indices: Tensor) -> Tensor:
        """
        编码题目索引；未知索引使用 OOV 题目表示。

        :param item_indices: 题目索引张量。
        :returns: 多视角题目表示。
        """
        known = (item_indices >= 0) & (item_indices < self.item_count)
        safe_items = torch.where(known, item_indices.long(), torch.full_like(item_indices.long(), self.item_count))
        item_view = self.item_embedding(safe_items)
        subject_view = self.subject_embedding(self.subject_catalog[safe_items])
        skill_indices = self.skill_catalog[safe_items]
        skill_mask = skill_indices != self.skill_count
        skill_values = self.skill_embedding(skill_indices)
        skill_view = (skill_values * skill_mask.unsqueeze(-1)).sum(dim=-2)
        skill_view = skill_view / skill_mask.sum(dim=-1, keepdim=True).clamp_min(1)
        feature_view = self.feature_encoder(self.feature_catalog[safe_items])
        return self.fusion(torch.cat([item_view, subject_view, skill_view, feature_view], dim=-1))


class AdaptiveForgetGate(nn.Module):
    """为每个知识状态维度学习条件化遗忘速度。"""

    def __init__(self, condition_dim: int, state_dim: int) -> None:
        """
        初始化遗忘门。

        :param condition_dim: 题目和时间条件维度。
        :param state_dim: 学习者状态维度。
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


class BaseMEFKT(nn.Module):
    """完整模型与 Lite 模型共享的深层模型 interface。"""

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
        """初始化共享的题目、时间、遗忘和预测模块。"""
        super().__init__()
        self.config = config
        self.item_encoder = MultiViewItemEncoder(
            item_count,
            item_features,
            item_subjects,
            item_skills,
            subject_count,
            skill_count,
            config,
        )
        self.answer_embedding = nn.Embedding(2, config.answer_embedding_dim)
        self.gap_encoder = LogTimeEncoder(config.gap_embedding_dim)
        self.response_time_encoder = LogTimeEncoder(config.response_time_embedding_dim)
        interaction_dim = (
            config.item_view_dim
            + config.answer_embedding_dim
            + config.gap_embedding_dim
            + config.response_time_embedding_dim
        )
        self.interaction_projection = nn.Sequential(
            nn.Linear(interaction_dim, config.state_dim),
            nn.GELU(),
            nn.LayerNorm(config.state_dim),
            nn.Dropout(config.dropout),
        )
        condition_dim = config.item_view_dim + config.gap_embedding_dim + config.response_time_embedding_dim
        self.forget_gate = AdaptiveForgetGate(condition_dim, config.state_dim)
        self.state_cell = nn.GRUCell(config.state_dim, config.state_dim)
        prediction_dim = config.state_dim + config.item_view_dim + config.gap_embedding_dim
        self.prediction_head = nn.Sequential(
            nn.Linear(prediction_dim, config.state_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.state_dim, 1),
        )

    def initial_state(self, batch_size: int, device: torch.device, dtype: torch.dtype) -> SequenceState:
        """创建冷启动学习者状态。"""
        recurrent = torch.zeros((batch_size, self.config.state_dim), device=device, dtype=dtype)
        return SequenceState(recurrent, recurrent.clone())

    def _encode_recurrent(
        self,
        items: Tensor,
        correct: Tensor,
        gaps: Tensor,
        response_times: Tensor,
        initial_state: SequenceState,
    ) -> tuple[Tensor, Tensor]:
        """通过自适应遗忘 GRU 编码一个窗口。"""
        hidden = initial_state.recurrent
        outputs: list[Tensor] = []
        for position in range(items.size(1)):
            valid = items[:, position] >= 0
            item_view = self.item_encoder(items[:, position])
            gap_view = self.gap_encoder(gaps[:, position])
            response_view = self.response_time_encoder(response_times[:, position])
            answer_view = self.answer_embedding(correct[:, position].clamp(0, 1).long())
            conditions = torch.cat([item_view, gap_view, response_view], dim=-1)
            decayed = self.forget_gate(hidden, conditions, gaps[:, position])
            interaction = self.interaction_projection(
                torch.cat([item_view, answer_view, gap_view, response_view], dim=-1)
            )
            candidate_hidden = self.state_cell(interaction, decayed)
            hidden = torch.where(valid.unsqueeze(-1), candidate_hidden, hidden)
            outputs.append(hidden)
        if not outputs:
            return hidden.new_zeros((items.size(0), 0, self.config.state_dim)), hidden
        return torch.stack(outputs, dim=1), hidden

    def _contextualize(
        self,
        recurrent_states: Tensor,
        valid: Tensor,
        initial_state: SequenceState,
    ) -> tuple[Tensor, Tensor | None, Tensor | None]:
        """Lite 默认直接使用 GRU 状态；完整模型覆盖此内部 seam。"""
        return recurrent_states, None, None

    @staticmethod
    def _last_context(contexts: Tensor, valid: Tensor, fallback: Tensor) -> Tensor:
        """提取每个 batch 最后一个有效上下文。"""
        if contexts.size(1) == 0:
            return fallback
        lengths = valid.long().sum(dim=1)
        safe_positions = (lengths - 1).clamp_min(0)
        gathered = contexts[torch.arange(contexts.size(0), device=contexts.device), safe_positions]
        return torch.where((lengths > 0).unsqueeze(-1), gathered, fallback)

    def encode_history(
        self,
        items: Tensor,
        correct: Tensor,
        gaps: Tensor,
        response_times: Tensor,
        initial_state: SequenceState | None = None,
    ) -> tuple[Tensor, SequenceState]:
        """
        编码历史并返回每步上下文和可传给下一窗口的状态。

        :param items: `[batch, length]` 题目索引。
        :param correct: `[batch, length]` 正确性。
        :param gaps: `[batch, length]` 小时间隔。
        :param response_times: `[batch, length]` 答题耗时秒数。
        :param initial_state: 上一窗口返回的状态。
        :returns: 每步上下文和最终窗口状态。
        """
        if initial_state is None:
            initial_state = self.initial_state(items.size(0), items.device, self.item_encoder.item_embedding.weight.dtype)
        valid = items >= 0
        recurrent_states, recurrent = self._encode_recurrent(
            items,
            correct,
            gaps,
            response_times,
            initial_state,
        )
        contexts, memory, memory_mask = self._contextualize(recurrent_states, valid, initial_state)
        final_context = self._last_context(contexts, valid, initial_state.context)
        return contexts, SequenceState(recurrent, final_context, memory, memory_mask)

    def _candidate_logits(self, contexts: Tensor, candidate_items: Tensor, candidate_gaps: Tensor) -> Tensor:
        """根据预测前状态与候选题生成 logits。"""
        item_view = self.item_encoder(candidate_items)
        gap_view = self.gap_encoder(candidate_gaps)
        return self.prediction_head(torch.cat([contexts, item_view, gap_view], dim=-1)).squeeze(-1)

    def forward(
        self,
        sequence_items: Tensor,
        sequence_correct: Tensor,
        sequence_gaps: Tensor,
        sequence_response_times: Tensor,
        initial_state: SequenceState | None = None,
    ) -> tuple[Tensor, Tensor, SequenceState]:
        """
        预测窗口中每次交互在作答前的答对概率 logit。

        :returns: `[batch, length]` logits、有效 mask 和最终窗口状态。
        """
        if initial_state is None:
            initial_state = self.initial_state(
                sequence_items.size(0),
                sequence_items.device,
                self.item_encoder.item_embedding.weight.dtype,
            )
        contexts_after, final_state = self.encode_history(
            sequence_items,
            sequence_correct,
            sequence_gaps,
            sequence_response_times,
            initial_state,
        )
        if sequence_items.size(1) == 0:
            return sequence_gaps.new_zeros(sequence_items.shape), sequence_items >= 0, final_state
        contexts_before = torch.cat([initial_state.context.unsqueeze(1), contexts_after[:, :-1]], dim=1)
        logits = self._candidate_logits(contexts_before, sequence_items, sequence_gaps)
        return logits, sequence_items >= 0, final_state

    def predict_next(
        self,
        history_items: Tensor,
        history_correct: Tensor,
        history_gaps: Tensor,
        history_response_times: Tensor,
        candidate_items: Tensor,
        candidate_gaps: Tensor,
        initial_state: SequenceState | None = None,
    ) -> tuple[Tensor, SequenceState]:
        """
        用共享历史状态独立评估候选题。

        :returns: 每个候选题的答对概率和编码完历史后的状态。
        """
        candidate_items = candidate_items.reshape(-1)
        candidate_gaps = candidate_gaps.reshape(-1)
        if candidate_items.numel() != candidate_gaps.numel():
            raise ValueError("候选题和候选时间间隔长度不一致")
        history_items = history_items.reshape(1, -1)
        history_correct = history_correct.reshape(1, -1)
        history_gaps = history_gaps.reshape(1, -1)
        history_response_times = history_response_times.reshape(1, -1)
        history_lengths = {
            history_items.numel(),
            history_correct.numel(),
            history_gaps.numel(),
            history_response_times.numel(),
        }
        if len(history_lengths) != 1:
            raise ValueError("历史题目、正确性、间隔和答题耗时长度不一致")
        _, state = self.encode_history(
            history_items,
            history_correct,
            history_gaps,
            history_response_times,
            initial_state,
        )
        if candidate_items.numel() == 0:
            return candidate_gaps.new_empty((0,)), state
        contexts = state.context.expand(candidate_items.numel(), -1)
        probabilities = torch.sigmoid(self._candidate_logits(contexts, candidate_items, candidate_gaps))
        return probabilities, state


class MEFKTLite(BaseMEFKT):
    """面向少核 CPU 的自适应遗忘 GRU 知识追踪模型。"""


class MEFKT(BaseMEFKT):
    """面向 GPU 的自适应遗忘 GRU + 因果 Transformer 记忆模型。"""

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
        """初始化完整 MEFKT。"""
        super().__init__(
            item_count,
            item_features,
            item_subjects,
            item_skills,
            subject_count,
            skill_count,
            config,
        )
        layer = nn.TransformerEncoderLayer(
            d_model=config.state_dim,
            nhead=config.transformer_heads,
            dim_feedforward=config.transformer_feedforward_dim,
            dropout=config.dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(
            layer,
            num_layers=config.transformer_layers,
            norm=nn.LayerNorm(config.state_dim),
            enable_nested_tensor=False,
        )

    @staticmethod
    def _sinusoidal_positions(length: int, dimension: int, device: torch.device, dtype: torch.dtype) -> Tensor:
        """生成无需固定最大窗口长度的位置编码。"""
        positions = torch.arange(length, device=device, dtype=torch.float32).unsqueeze(1)
        frequencies = torch.exp(
            torch.arange(0, dimension, 2, device=device, dtype=torch.float32)
            * (-math.log(10_000.0) / dimension)
        )
        encoding = torch.zeros((length, dimension), device=device, dtype=torch.float32)
        encoding[:, 0::2] = torch.sin(positions * frequencies)
        encoding[:, 1::2] = torch.cos(positions * frequencies[: encoding[:, 1::2].size(1)])
        return encoding.to(dtype=dtype)

    def _pack_memory(self, encoded: Tensor, valid: Tensor) -> tuple[Tensor, Tensor]:
        """保留最近的有效上下文作为下一窗口的 Transformer 记忆。"""
        memory_size = self.config.memory_size
        memory = encoded.new_zeros((encoded.size(0), memory_size, encoded.size(-1)))
        memory_mask = torch.zeros((encoded.size(0), memory_size), dtype=torch.bool, device=encoded.device)
        for batch_index in range(encoded.size(0)):
            selected = encoded[batch_index, valid[batch_index]][-memory_size:]
            if selected.numel() == 0:
                continue
            memory[batch_index, -selected.size(0) :] = selected
            memory_mask[batch_index, -selected.size(0) :] = True
        return memory, memory_mask

    def _contextualize(
        self,
        recurrent_states: Tensor,
        valid: Tensor,
        initial_state: SequenceState,
    ) -> tuple[Tensor, Tensor | None, Tensor | None]:
        """用因果 Transformer 融合当前窗口与上一窗口记忆。"""
        batch_size = recurrent_states.size(0)
        if initial_state.memory is None:
            memory = recurrent_states.new_zeros((batch_size, 0, self.config.state_dim))
            memory_mask = torch.zeros((batch_size, 0), dtype=torch.bool, device=recurrent_states.device)
        else:
            memory = initial_state.memory
            memory_mask = initial_state.memory_mask
            if memory_mask is None:
                memory_mask = torch.ones(memory.shape[:2], dtype=torch.bool, device=memory.device)
        combined = torch.cat([memory, recurrent_states], dim=1)
        combined_valid = torch.cat([memory_mask, valid], dim=1)
        if combined.size(1) == 0:
            return recurrent_states, memory, memory_mask
        positions = self._sinusoidal_positions(
            combined.size(1),
            combined.size(2),
            combined.device,
            combined.dtype,
        )
        causal_mask = torch.triu(
            torch.ones((combined.size(1), combined.size(1)), dtype=torch.bool, device=combined.device),
            diagonal=1,
        )
        encoded = self.transformer(
            combined + positions.unsqueeze(0),
            mask=causal_mask,
            src_key_padding_mask=~combined_valid,
        )
        current_contexts = encoded[:, memory.size(1) :]
        next_memory, next_memory_mask = self._pack_memory(encoded, combined_valid)
        return current_contexts, next_memory, next_memory_mask


def build_model(
    profile: str,
    item_count: int,
    item_features: Tensor,
    item_subjects: Tensor,
    item_skills: Tensor,
    subject_count: int,
    skill_count: int,
) -> BaseMEFKT:
    """
    通过统一工厂创建完整模型或 Lite 模型。

    :param profile: `full` 或 `lite`。
    :returns: 共享同一推理 interface 的知识追踪模型。
    """
    if profile == "lite":
        config = lite_config()
        model_type: type[BaseMEFKT] = MEFKTLite
    elif profile == "full":
        config = full_config()
        model_type = MEFKT
    else:
        raise ValueError(f"未知模型 profile: {profile}")
    return model_type(
        item_count,
        item_features,
        item_subjects,
        item_skills,
        subject_count,
        skill_count,
        config,
    )


__all__ = [
    "BaseMEFKT",
    "MEFKT",
    "MEFKTConfig",
    "MEFKTLite",
    "SequenceState",
    "build_model",
    "full_config",
    "lite_config",
]
