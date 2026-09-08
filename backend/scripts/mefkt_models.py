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
from dataclasses import dataclass

import torch
from mefkt_encoders import AdaptiveForgetGate, LogTimeEncoder, MultiViewItemEncoder
from mefkt_model_config import MEFKTConfig, full_config, legacy_config, lite_config
from torch import Tensor, nn


@dataclass
class SequenceState:
    """可在相邻窗口之间传递的学习者状态。"""

    recurrent: Tensor
    context: Tensor
    memory: Tensor | None = None
    memory_mask: Tensor | None = None
    skill_memory: Tensor | None = None
    skill_attempts: Tensor | None = None
    skill_successes: Tensor | None = None
    skill_last_seen: Tensor | None = None
    elapsed_hours: Tensor | None = None
    positive_streak: Tensor | None = None
    negative_streak: Tensor | None = None
    session_steps: Tensor | None = None
    last_items: Tensor | None = None

    def detach(self) -> SequenceState:
        """
        截断反向传播图并保留状态值。

        :returns: 与当前值相同但已 detach 的状态。
        """
        return SequenceState(
            self.recurrent.detach(),
            self.context.detach(),
            self.memory.detach() if self.memory is not None else None,
            self.memory_mask.detach() if self.memory_mask is not None else None,
            self.skill_memory.detach() if self.skill_memory is not None else None,
            self.skill_attempts.detach() if self.skill_attempts is not None else None,
            self.skill_successes.detach() if self.skill_successes is not None else None,
            self.skill_last_seen.detach() if self.skill_last_seen is not None else None,
            self.elapsed_hours.detach() if self.elapsed_hours is not None else None,
            self.positive_streak.detach() if self.positive_streak is not None else None,
            self.negative_streak.detach() if self.negative_streak is not None else None,
            self.session_steps.detach() if self.session_steps is not None else None,
            self.last_items.detach() if self.last_items is not None else None,
        )


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
        """
        初始化共享的题目、时间、遗忘和预测模块。

        :param item_count: 已知题目数量。
        :param item_features: 题目数值和内容特征。
        :param item_subjects: 题目学科索引。
        :param item_skills: 题目知识点索引。
        :param subject_count: 学科词表大小。
        :param skill_count: 知识点词表大小。
        :param config: 模型结构配置。
        :returns: None。
        """
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
        """
        创建冷启动学习者状态。

        :param batch_size: 学习者批量大小。
        :param device: 状态所在设备。
        :param dtype: 状态浮点类型。
        :returns: 全零冷启动状态。
        """
        recurrent = torch.zeros((batch_size, self.config.state_dim), device=device, dtype=dtype)
        return SequenceState(recurrent, recurrent.clone())

    def _encode_recurrent(
        self,
        items: Tensor,
        correct: Tensor,
        gaps: Tensor,
        response_times: Tensor,
        initial_state: SequenceState,
        sequence_features: Tensor | None = None,
        sequence_content_features: Tensor | None = None,
        valid_mask: Tensor | None = None,
    ) -> tuple[Tensor, Tensor, Tensor]:
        """
        通过自适应遗忘 GRU 编码一个窗口。

        :param items: 题目索引。
        :param correct: 正确性标签。
        :param gaps: 交互前时间间隔。
        :param response_times: 历史真实答题耗时。
        :param initial_state: 上一窗口状态。
        :param sequence_features: 未知题目七维数值特征。
        :param sequence_content_features: 未知题目内容向量。
        :param valid_mask: 有效交互 mask。
        :returns: 每步 GRU 状态、最终 recurrent state 和有效 mask。
        """
        hidden = initial_state.recurrent
        valid = valid_mask.bool() if valid_mask is not None else items >= 0
        if valid.shape != items.shape:
            raise ValueError("sequence_valid_mask 必须与 items 形状一致")
        outputs: list[Tensor] = []
        for position in range(items.size(1)):
            item_view = self.item_encoder(
                items[:, position],
                sequence_features[:, position] if sequence_features is not None else None,
                sequence_content_features[:, position] if sequence_content_features is not None else None,
            )
            gap_view = self.gap_encoder(gaps[:, position])
            response_view = self.response_time_encoder(response_times[:, position])
            answer_view = self.answer_embedding(correct[:, position].clamp(0, 1).long())
            conditions = torch.cat([item_view, gap_view, response_view], dim=-1)
            decayed = self.forget_gate(hidden, conditions, gaps[:, position])
            interaction = self.interaction_projection(
                torch.cat([item_view, answer_view, gap_view, response_view], dim=-1)
            )
            candidate_hidden = self.state_cell(interaction, decayed)
            hidden = torch.where(valid[:, position].unsqueeze(-1), candidate_hidden, hidden)
            outputs.append(hidden)
        if not outputs:
            return hidden.new_zeros((items.size(0), 0, self.config.state_dim)), hidden, valid
        return torch.stack(outputs, dim=1), hidden, valid

    def _contextualize(
        self,
        recurrent_states: Tensor,
        valid: Tensor,
        initial_state: SequenceState,
    ) -> tuple[Tensor, Tensor | None, Tensor | None]:
        """
        Lite 默认直接使用 GRU 状态；完整模型覆盖此内部 seam。

        :param recurrent_states: 当前窗口的 GRU 状态序列。
        :param valid: 有效交互 mask。
        :param initial_state: 上一窗口状态。
        :returns: 上下文序列、memory 和 memory mask。
        """
        return recurrent_states, None, None

    @staticmethod
    def _last_context(contexts: Tensor, valid: Tensor, fallback: Tensor) -> Tensor:
        """
        提取每个 batch 最后一个有效上下文。

        :param contexts: 上下文序列。
        :param valid: 有效位置 mask。
        :param fallback: 没有有效位置时的回退状态。
        :returns: 每个 batch 的最后有效上下文。
        """
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
        sequence_features: Tensor | None = None,
        sequence_content_features: Tensor | None = None,
        sequence_valid_mask: Tensor | None = None,
    ) -> tuple[Tensor, SequenceState]:
        """
        编码历史并返回每步上下文和可传给下一窗口的状态。

        :param items: `[batch, length]` 题目索引。
        :param correct: `[batch, length]` 正确性。
        :param gaps: `[batch, length]` 小时间隔。
        :param response_times: `[batch, length]` 答题耗时秒数。
        :param initial_state: 上一窗口返回的状态。
        :param sequence_features: 未知题目的 `[batch, length, 7]` 数值特征。
        :param sequence_content_features: 未知题目的 `[batch, length, content_dim]` 内容向量。
        :param sequence_valid_mask: `[batch, length]` 有效交互 mask；未知题目必须显式标记为 True。
        :returns: 每步上下文和最终窗口状态。
        """
        if initial_state is None:
            initial_state = self.initial_state(items.size(0), items.device, self.item_encoder.item_embedding.weight.dtype)
        recurrent_states, recurrent, valid = self._encode_recurrent(
            items,
            correct,
            gaps,
            response_times,
            initial_state,
            sequence_features,
            sequence_content_features,
            sequence_valid_mask,
        )
        contexts, memory, memory_mask = self._contextualize(recurrent_states, valid, initial_state)
        final_context = self._last_context(contexts, valid, initial_state.context)
        return contexts, SequenceState(recurrent, final_context, memory, memory_mask)

    def _candidate_logits(
        self,
        contexts: Tensor,
        candidate_items: Tensor,
        candidate_gaps: Tensor,
        candidate_features: Tensor | None = None,
        candidate_content_features: Tensor | None = None,
    ) -> Tensor:
        """
        根据预测前状态与候选题生成 logits。

        :param contexts: 作答前学习者状态。
        :param candidate_items: 候选题索引。
        :param candidate_gaps: 候选题前时间间隔。
        :param candidate_features: 未知候选题数值特征。
        :param candidate_content_features: 未知候选题内容向量。
        :returns: 候选题答对 logits。
        """
        item_view = self.item_encoder(candidate_items, candidate_features, candidate_content_features)
        gap_view = self.gap_encoder(candidate_gaps)
        return self.prediction_head(torch.cat([contexts, item_view, gap_view], dim=-1)).squeeze(-1)

    def forward(
        self,
        sequence_items: Tensor,
        sequence_correct: Tensor,
        sequence_gaps: Tensor,
        sequence_response_times: Tensor,
        initial_state: SequenceState | None = None,
        sequence_features: Tensor | None = None,
        sequence_content_features: Tensor | None = None,
        sequence_valid_mask: Tensor | None = None,
    ) -> tuple[Tensor, Tensor, SequenceState]:
        """
        预测窗口中每次交互在作答前的答对概率 logit。

        :param sequence_items: 题目索引序列。
        :param sequence_correct: 正确性序列。
        :param sequence_gaps: 交互前时间间隔序列。
        :param sequence_response_times: 真实答题耗时序列。
        :param initial_state: 上一窗口状态。
        :param sequence_features: 未知题目七维数值特征。
        :param sequence_content_features: 未知题目内容向量。
        :param sequence_valid_mask: 有效交互 mask。
        :returns: `[batch, length]` logits、有效 mask 和最终窗口状态。
        """
        if initial_state is None:
            initial_state = self.initial_state(
                sequence_items.size(0),
                sequence_items.device,
                self.item_encoder.item_embedding.weight.dtype,
            )
        valid_mask = sequence_valid_mask.bool() if sequence_valid_mask is not None else sequence_items >= 0
        if valid_mask.shape != sequence_items.shape:
            raise ValueError("sequence_valid_mask 必须与 sequence_items 形状一致")
        contexts_after, final_state = self.encode_history(
            sequence_items,
            sequence_correct,
            sequence_gaps,
            sequence_response_times,
            initial_state,
            sequence_features,
            sequence_content_features,
            sequence_valid_mask,
        )
        if sequence_items.size(1) == 0:
            return sequence_gaps.new_zeros(sequence_items.shape), valid_mask, final_state
        contexts_before = torch.cat([initial_state.context.unsqueeze(1), contexts_after[:, :-1]], dim=1)
        logits = self._candidate_logits(
            contexts_before,
            sequence_items,
            sequence_gaps,
            sequence_features,
            sequence_content_features,
        )
        return logits, valid_mask, final_state

    def predict_next(
        self,
        history_items: Tensor,
        history_correct: Tensor,
        history_gaps: Tensor,
        history_response_times: Tensor,
        candidate_items: Tensor,
        candidate_gaps: Tensor,
        initial_state: SequenceState | None = None,
        history_features: Tensor | None = None,
        history_content_features: Tensor | None = None,
        candidate_features: Tensor | None = None,
        candidate_content_features: Tensor | None = None,
        history_valid_mask: Tensor | None = None,
    ) -> tuple[Tensor, SequenceState]:
        """
        用共享历史状态独立评估候选题。

        :param history_items: 历史题目索引。
        :param history_correct: 历史正确性。
        :param history_gaps: 历史交互前时间间隔。
        :param history_response_times: 历史真实答题耗时。
        :param candidate_items: 候选题索引。
        :param candidate_gaps: 候选题前时间间隔。
        :param initial_state: 上一窗口状态。
        :param history_features: 未知历史题数值特征。
        :param history_content_features: 未知历史题内容向量。
        :param candidate_features: 未知候选题数值特征。
        :param candidate_content_features: 未知候选题内容向量。
        :param history_valid_mask: 有效历史交互 mask。
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
        if history_features is not None:
            history_features = history_features.reshape(1, history_items.size(1), -1)
        if history_content_features is not None:
            history_content_features = history_content_features.reshape(1, history_items.size(1), -1)
        if history_valid_mask is not None:
            history_valid_mask = history_valid_mask.reshape(1, history_items.size(1)).bool()
        candidate_features = candidate_features.reshape(-1, 7) if candidate_features is not None else None
        candidate_content_features = (
            candidate_content_features.reshape(-1, self.config.content_embedding_dim)
            if candidate_content_features is not None
            else None
        )
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
            history_features,
            history_content_features,
            history_valid_mask,
        )
        if candidate_items.numel() == 0:
            return candidate_gaps.new_empty((0,)), state
        contexts = state.context.expand(candidate_items.numel(), -1)
        probabilities = torch.sigmoid(
            self._candidate_logits(
                contexts,
                candidate_items,
                candidate_gaps,
                candidate_features,
                candidate_content_features,
            )
        )
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
        """
        初始化完整 MEFKT。

        :param item_count: 已知题目数量。
        :param item_features: 题目数值和内容特征。
        :param item_subjects: 题目学科索引。
        :param item_skills: 题目知识点索引。
        :param subject_count: 学科词表大小。
        :param skill_count: 知识点词表大小。
        :param config: Full 模型结构配置。
        :returns: None。
        """
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
        """
        生成无需固定最大窗口长度的位置编码。

        :param length: 序列长度。
        :param dimension: 状态维度。
        :param device: 输出设备。
        :param dtype: 输出浮点类型。
        :returns: 正弦位置编码。
        """
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
        """保留最近的有效上下文作为下一窗口的 Transformer 记忆。

        有效 memory 前置、padding 后置，避免因果 mask 让无效 query 没有
        可见 key，进而在部分 Transformer 后端中产生 NaN。

        :param encoded: Transformer 编码后的上下文。
        :param valid: 有效上下文 mask。
        :returns: 固定长度 memory 和对应 mask。
        """
        memory_size = self.config.memory_size
        memory = encoded.new_zeros((encoded.size(0), memory_size, encoded.size(-1)))
        memory_mask = torch.zeros((encoded.size(0), memory_size), dtype=torch.bool, device=encoded.device)
        for batch_index in range(encoded.size(0)):
            selected = encoded[batch_index, valid[batch_index]][-memory_size:]
            if selected.numel() == 0:
                continue
            memory[batch_index, : selected.size(0)] = selected
            memory_mask[batch_index, : selected.size(0)] = True
        return memory, memory_mask

    def _contextualize(
        self,
        recurrent_states: Tensor,
        valid: Tensor,
        initial_state: SequenceState,
    ) -> tuple[Tensor, Tensor | None, Tensor | None]:
        """
        用因果 Transformer 融合当前窗口与上一窗口记忆。

        :param recurrent_states: 当前窗口 GRU 状态。
        :param valid: 当前窗口有效 mask。
        :param initial_state: 上一窗口状态与 memory。
        :returns: 当前上下文、下一窗口 memory 和 memory mask。
        """
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
    config: MEFKTConfig | None = None,
) -> BaseMEFKT:
    """
    通过统一工厂创建完整模型或 Lite 模型。

    :param profile: `full` 或 `lite`。
    :param item_count: 已知题目数量。
    :param item_features: 题目数值和内容特征。
    :param item_subjects: 题目学科索引。
    :param item_skills: 题目知识点索引。
    :param subject_count: 学科词表大小。
    :param skill_count: 知识点词表大小。
    :param config: 可选的 checkpoint 结构配置；为空时使用当前最新版。
    :returns: 共享同一推理 interface 的知识追踪模型。
    """
    if profile == "lite":
        effective_config = config or lite_config()
        if effective_config.architecture_version >= 3:
            from mefkt_v3_models import MEFKTLiteV3

            model_type: type[BaseMEFKT] = MEFKTLiteV3
        else:
            model_type = MEFKTLite
    elif profile == "full":
        effective_config = config or full_config()
        if effective_config.architecture_version >= 3:
            from mefkt_v3_models import MEFKTV3

            model_type = MEFKTV3
        else:
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
        effective_config,
    )


def model_config_from_checkpoint(checkpoint: dict[str, object], profile: str) -> MEFKTConfig:
    """
    从 checkpoint metadata 恢复结构版本，缺失时回退到 v2。

    :param checkpoint: 已加载的 checkpoint 字典。
    :param profile: full 或 lite。
    :returns: 可传给模型工厂的结构配置。
    """
    metadata = checkpoint.get("metadata", {})
    if isinstance(metadata, dict):
        model_metadata = metadata.get("model", {})
        if isinstance(model_metadata, dict):
            config = model_metadata.get("config")
            if isinstance(config, dict):
                return MEFKTConfig.from_dict(config)
    return legacy_config(profile)


__all__ = [
    "MEFKT",
    "BaseMEFKT",
    "MEFKTConfig",
    "MEFKTLite",
    "SequenceState",
    "build_model",
    "full_config",
    "lite_config",
    "model_config_from_checkpoint",
]
