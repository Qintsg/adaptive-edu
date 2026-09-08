#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT v3：显式 IRT、skill memory、在线历史特征和领域校准模型。
@Project : adaptive-edu
@File : mefkt_v3_models.py
@Author : Qintsg
@Date : 2026-09-01
'''

from __future__ import annotations

from dataclasses import dataclass

import torch
from mefkt_model_config import MEFKTConfig
from mefkt_models import MEFKT, MEFKTLite, SequenceState
from torch import Tensor, nn
from torch.nn import functional


@dataclass(frozen=True)
class SkillStateTrace:
    """一个窗口内作答前知识特征和作答后最终状态。"""

    knowledge_before: Tensor
    skill_memory: Tensor
    skill_attempts: Tensor
    skill_successes: Tensor
    skill_last_seen: Tensor
    elapsed_hours: Tensor
    positive_streak: Tensor
    negative_streak: Tensor
    session_steps: Tensor
    last_items: Tensor


@dataclass(frozen=True)
class IRTOutput:
    """显式 IRT 分解结果。"""

    logits: Tensor
    ability: Tensor
    difficulty: Tensor
    residual: Tensor


@dataclass(frozen=True)
class V3Window:
    """v3 窗口编码的内部结果。"""

    contexts_after: Tensor
    item_views: Tensor
    gap_views: Tensor
    knowledge_before: Tensor
    subjects: Tensor
    valid: Tensor
    state: SequenceState


class SkillAwareStateTracker(nn.Module):
    """在固定槽中维护按知识点寻址的 mastery 和在线统计。"""

    def __init__(self, config: MEFKTConfig, skill_slots: int) -> None:
        """
        初始化 skill memory 更新器。

        :param config: v3 模型配置。
        :param skill_slots: 已知和开放课程 skill 槽总数。
        :returns: None。
        """
        super().__init__()
        self.config = config
        self.skill_slots = skill_slots
        self.update_projection = nn.Sequential(
            nn.Linear(config.state_dim, config.skill_memory_dim),
            nn.GELU(),
            nn.LayerNorm(config.skill_memory_dim),
        )
        self.memory_cell = nn.GRUCell(config.skill_memory_dim, config.skill_memory_dim)

    @property
    def feature_dim(self) -> int:
        """
        返回供 IRT 预测头使用的知识特征维度。

        :returns: skill memory 与在线统计拼接维度。
        """
        return self.config.skill_memory_dim + self.config.online_feature_dim

    def _gather_mean(self, values: Tensor, skills: Tensor) -> Tensor:
        """
        按题目关联 skill 聚合状态，padding 槽不参与平均。

        :param values: `[batch, slots, dim]` 状态。
        :param skills: `[batch, max_skills]` 状态槽。
        :returns: `[batch, dim]` 平均状态。
        """
        padding = values.new_zeros((values.size(0), 1, values.size(-1)))
        extended = torch.cat([values, padding], dim=1)
        batch_indices = torch.arange(values.size(0), device=values.device).unsqueeze(1)
        gathered = extended[batch_indices, skills]
        mask = skills < self.skill_slots
        return (gathered * mask.unsqueeze(-1)).sum(dim=1) / mask.sum(dim=1, keepdim=True).clamp_min(1)

    def _gather_scalar_mean(self, values: Tensor, skills: Tensor) -> tuple[Tensor, Tensor]:
        """
        聚合每个题目相关 skill 的标量统计。

        :param values: `[batch, slots]` 标量状态。
        :param skills: `[batch, max_skills]` 状态槽。
        :returns: 聚合均值和有效 skill 数。
        """
        extended = torch.cat([values, values.new_zeros((values.size(0), 1))], dim=1)
        batch_indices = torch.arange(values.size(0), device=values.device).unsqueeze(1)
        gathered = extended[batch_indices, skills]
        mask = skills < self.skill_slots
        count = mask.sum(dim=1).clamp_min(1)
        return (gathered * mask).sum(dim=1) / count, count

    def _knowledge_features(
        self,
        memory: Tensor,
        attempts: Tensor,
        successes: Tensor,
        last_seen: Tensor,
        current_elapsed: Tensor,
        positive_streak: Tensor,
        negative_streak: Tensor,
        session_steps: Tensor,
        last_items: Tensor,
        items: Tensor,
        skills: Tensor,
    ) -> Tensor:
        """
        构造作答前 mastery、正确率、间隔和 session 行为特征。

        :returns: `[batch, skill_memory_dim + 7]` 知识特征。
        """
        memory_view = self._gather_mean(memory, skills)
        attempt_view, _ = self._gather_scalar_mean(attempts, skills)
        success_view, _ = self._gather_scalar_mean(successes, skills)
        last_seen_view, _ = self._gather_scalar_mean(last_seen, skills)
        success_rate = torch.where(attempt_view > 0, success_view / attempt_view.clamp_min(1), 0.5)
        recency = torch.where(
            attempt_view > 0,
            torch.log1p((current_elapsed - last_seen_view).clamp_min(0.0)) / 10.0,
            torch.zeros_like(current_elapsed),
        )
        numeric = torch.stack(
            [
                success_rate,
                torch.log1p(attempt_view) / 5.0,
                recency,
                torch.log1p(positive_streak) / 3.0,
                torch.log1p(negative_streak) / 3.0,
                torch.log1p(session_steps) / 5.0,
                (last_items == items).float(),
            ],
            dim=-1,
        )
        return torch.cat([memory_view, numeric], dim=-1)

    def encode(
        self,
        interactions: Tensor,
        items: Tensor,
        correct: Tensor,
        gaps: Tensor,
        skills: Tensor,
        valid: Tensor,
        initial_state: SequenceState,
    ) -> SkillStateTrace:
        """
        编码一个窗口并返回每步作答前知识特征。

        :returns: 知识特征轨迹和最终可传递状态。
        :raises RuntimeError: 初始状态缺少 v3 字段时抛出。
        """
        fields = (
            initial_state.skill_memory,
            initial_state.skill_attempts,
            initial_state.skill_successes,
            initial_state.skill_last_seen,
            initial_state.elapsed_hours,
            initial_state.positive_streak,
            initial_state.negative_streak,
            initial_state.session_steps,
            initial_state.last_items,
        )
        if any(value is None for value in fields):
            raise RuntimeError("MEFKT v3 初始状态缺少 skill memory 或在线统计")
        memory, attempts, successes, last_seen, elapsed, positive, negative, steps, last_items = (
            value.clone() for value in fields if value is not None
        )
        traces: list[Tensor] = []
        for position in range(items.size(1)):
            position_valid = valid[:, position]
            current_elapsed = torch.where(
                position_valid,
                elapsed + gaps[:, position].float().clamp_min(0.0),
                elapsed,
            )
            current_skills = skills[:, position]
            traces.append(
                self._knowledge_features(
                    memory,
                    attempts,
                    successes,
                    last_seen,
                    current_elapsed,
                    positive,
                    negative,
                    steps,
                    last_items,
                    items[:, position],
                    current_skills,
                )
            )
            skill_mask = (current_skills < self.skill_slots) & position_valid.unsqueeze(-1)
            safe_skills = current_skills.clamp_max(self.skill_slots - 1)
            one_hot = functional.one_hot(safe_skills, self.skill_slots).to(memory.dtype)
            one_hot = one_hot * skill_mask.unsqueeze(-1)
            batch_indices = torch.arange(items.size(0), device=items.device).unsqueeze(1)
            old_memory = memory[batch_indices, safe_skills]
            update_input = self.update_projection(interactions[:, position]).unsqueeze(1).expand_as(old_memory)
            candidate = self.memory_cell(
                update_input.reshape(-1, self.config.skill_memory_dim),
                old_memory.reshape(-1, self.config.skill_memory_dim),
            ).reshape_as(old_memory)
            slot_counts = one_hot.sum(dim=1)
            aggregated = torch.einsum("bks,bkd->bsd", one_hot, candidate)
            aggregated = aggregated / slot_counts.unsqueeze(-1).clamp_min(1)
            memory = torch.where(slot_counts.unsqueeze(-1) > 0, aggregated, memory)
            attempts = attempts + slot_counts
            successes = successes + slot_counts * correct[:, position].float().unsqueeze(-1)
            last_seen = torch.where(slot_counts > 0, current_elapsed.unsqueeze(-1), last_seen)
            answer = correct[:, position].float()
            positive = torch.where(position_valid & (answer > 0.5), positive + 1, torch.where(position_valid, 0, positive))
            negative = torch.where(position_valid & (answer < 0.5), negative + 1, torch.where(position_valid, 0, negative))
            steps = torch.where(position_valid, steps + 1, steps)
            last_items = torch.where(position_valid, items[:, position], last_items)
            elapsed = current_elapsed
        knowledge = torch.stack(traces, dim=1) if traces else interactions.new_zeros(
            (items.size(0), 0, self.feature_dim)
        )
        return SkillStateTrace(
            knowledge,
            memory,
            attempts,
            successes,
            last_seen,
            elapsed,
            positive,
            negative,
            steps,
            last_items,
        )

    def read_candidates(self, state: SequenceState, items: Tensor, skills: Tensor, gaps: Tensor) -> Tensor:
        """
        从共享历史状态读取多个候选题的作答前知识特征。

        :returns: `[candidates, feature_dim]` 候选知识特征。
        """
        count = items.numel()
        values = (
            state.skill_memory,
            state.skill_attempts,
            state.skill_successes,
            state.skill_last_seen,
            state.elapsed_hours,
            state.positive_streak,
            state.negative_streak,
            state.session_steps,
            state.last_items,
        )
        if any(value is None for value in values):
            raise RuntimeError("MEFKT v3 候选预测状态不完整")
        expanded = [value.expand(count, *value.shape[1:]) for value in values if value is not None]
        memory, attempts, successes, last_seen, elapsed, positive, negative, steps, last_items = expanded
        return self._knowledge_features(
            memory,
            attempts,
            successes,
            last_seen,
            elapsed + gaps.float().clamp_min(0.0),
            positive,
            negative,
            steps,
            last_items,
            items,
            skills,
        )


class IRTPredictionHead(nn.Module):
    """显式分解学生能力、题目难度、领域校准与低幅残差。"""

    def __init__(self, config: MEFKTConfig, knowledge_dim: int, subject_count: int) -> None:
        """
        初始化 IRT 预测头。

        :param config: v3 模型配置。
        :param knowledge_dim: skill memory 与在线特征维度。
        :param subject_count: 已知学科数量。
        :returns: None。
        """
        super().__init__()
        self.config = config
        self.ability = nn.Sequential(
            nn.Linear(config.state_dim + knowledge_dim, config.state_dim // 2),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.state_dim // 2, 1),
        )
        self.difficulty = nn.Sequential(
            nn.Linear(config.item_view_dim, config.state_dim // 2),
            nn.GELU(),
            nn.Linear(config.state_dim // 2, 1),
        )
        residual_dim = config.state_dim + config.item_view_dim + config.gap_embedding_dim + knowledge_dim
        self.residual = nn.Sequential(
            nn.Linear(residual_dim, config.state_dim // 2),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.state_dim // 2, 1),
            nn.Tanh(),
        )
        self.domain_calibration = nn.Embedding(subject_count + 1, 2)
        nn.init.zeros_(self.domain_calibration.weight)

    def forward(
        self,
        contexts: Tensor,
        item_views: Tensor,
        gap_views: Tensor,
        knowledge: Tensor,
        subjects: Tensor,
    ) -> IRTOutput:
        """
        计算 `ability - difficulty + calibrated residual`。

        :returns: logits 及可解释分量。
        """
        ability = self.ability(torch.cat([contexts, knowledge], dim=-1)).squeeze(-1)
        difficulty = self.difficulty(item_views).squeeze(-1)
        residual = self.residual(torch.cat([contexts, item_views, gap_views, knowledge], dim=-1)).squeeze(-1)
        calibration = self.domain_calibration(subjects)
        scale = torch.exp(0.25 * torch.tanh(calibration[..., 0]))
        bias = calibration[..., 1]
        logits = scale * (ability - difficulty) + bias + self.config.irt_residual_scale * residual
        return IRTOutput(logits, ability, difficulty, residual)


class _MEFKTV3Mixin:
    """为 Full 和 Lite 复用 v3 状态与 IRT 行为。"""

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
        """初始化共享 v3 模块。"""
        super().__init__(
            item_count,
            item_features,
            item_subjects,
            item_skills,
            subject_count,
            skill_count,
            config,
        )
        skill_slots = skill_count + config.external_skill_slots
        self.skill_tracker = SkillAwareStateTracker(config, skill_slots)
        self.irt_head = IRTPredictionHead(config, self.skill_tracker.feature_dim, subject_count)

    def initial_state(self, batch_size: int, device: torch.device, dtype: torch.dtype) -> SequenceState:
        """创建包含全局状态、skill memory 和在线统计的冷启动状态。"""
        base = super().initial_state(batch_size, device, dtype)
        slots = self.skill_tracker.skill_slots
        return SequenceState(
            base.recurrent,
            base.context,
            base.memory,
            base.memory_mask,
            torch.zeros((batch_size, slots, self.config.skill_memory_dim), device=device, dtype=dtype),
            torch.zeros((batch_size, slots), device=device, dtype=dtype),
            torch.zeros((batch_size, slots), device=device, dtype=dtype),
            torch.zeros((batch_size, slots), device=device, dtype=dtype),
            torch.zeros(batch_size, device=device, dtype=dtype),
            torch.zeros(batch_size, device=device, dtype=dtype),
            torch.zeros(batch_size, device=device, dtype=dtype),
            torch.zeros(batch_size, device=device, dtype=dtype),
            torch.full((batch_size,), -2, device=device, dtype=torch.long),
        )

    def _encode_window(
        self,
        items: Tensor,
        correct: Tensor,
        gaps: Tensor,
        response_times: Tensor,
        initial_state: SequenceState | None,
        features: Tensor | None,
        content_features: Tensor | None,
        valid_mask: Tensor | None,
        external_skills: Tensor | None,
    ) -> V3Window:
        """通过单一内部 seam 编码完整 v3 窗口。"""
        if initial_state is None:
            initial_state = self.initial_state(
                items.size(0), items.device, self.item_encoder.item_embedding.weight.dtype
            )
        valid = valid_mask.bool() if valid_mask is not None else items >= 0
        item_views = self.item_encoder(
            items,
            features,
            content_features,
            apply_item_id_dropout=True,
        )
        gap_views = self.gap_encoder(gaps)
        response_views = self.response_time_encoder(response_times)
        answer_views = self.answer_embedding(correct.clamp(0, 1).long())
        interactions = self.interaction_projection(
            torch.cat([item_views, answer_views, gap_views, response_views], dim=-1)
        )
        skills = self.item_encoder.resolve_skill_indices(items, external_skills)
        skill_trace = self.skill_tracker.encode(
            interactions,
            items,
            correct,
            gaps,
            skills,
            valid,
            initial_state,
        )
        hidden = initial_state.recurrent
        recurrent_states: list[Tensor] = []
        for position in range(items.size(1)):
            conditions = torch.cat(
                [item_views[:, position], gap_views[:, position], response_views[:, position]], dim=-1
            )
            decayed = self.forget_gate(hidden, conditions, gaps[:, position])
            candidate = self.state_cell(interactions[:, position], decayed)
            hidden = torch.where(valid[:, position].unsqueeze(-1), candidate, hidden)
            recurrent_states.append(hidden)
        recurrent = (
            torch.stack(recurrent_states, dim=1)
            if recurrent_states
            else hidden.new_zeros((items.size(0), 0, self.config.state_dim))
        )
        contexts, memory, memory_mask = self._contextualize(recurrent, valid, initial_state)
        final_context = self._last_context(contexts, valid, initial_state.context)
        state = SequenceState(
            hidden,
            final_context,
            memory,
            memory_mask,
            skill_trace.skill_memory,
            skill_trace.skill_attempts,
            skill_trace.skill_successes,
            skill_trace.skill_last_seen,
            skill_trace.elapsed_hours,
            skill_trace.positive_streak,
            skill_trace.negative_streak,
            skill_trace.session_steps,
            skill_trace.last_items,
        )
        subjects = self.item_encoder.resolve_subject_indices(items)
        return V3Window(contexts, item_views, gap_views, skill_trace.knowledge_before, subjects, valid, state)

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
        sequence_skill_indices: Tensor | None = None,
    ) -> tuple[Tensor, SequenceState]:
        """编码历史并保留原有 public interface。"""
        window = self._encode_window(
            items,
            correct,
            gaps,
            response_times,
            initial_state,
            sequence_features,
            sequence_content_features,
            sequence_valid_mask,
            sequence_skill_indices,
        )
        return window.contexts_after, window.state

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
        sequence_skill_indices: Tensor | None = None,
    ) -> tuple[Tensor, Tensor, SequenceState]:
        """预测窗口中每次交互在作答前的答对 logit。"""
        if initial_state is None:
            initial_state = self.initial_state(
                sequence_items.size(0),
                sequence_items.device,
                self.item_encoder.item_embedding.weight.dtype,
            )
        window = self._encode_window(
            sequence_items,
            sequence_correct,
            sequence_gaps,
            sequence_response_times,
            initial_state,
            sequence_features,
            sequence_content_features,
            sequence_valid_mask,
            sequence_skill_indices,
        )
        if sequence_items.size(1) == 0:
            return sequence_gaps.new_zeros(sequence_items.shape), window.valid, window.state
        contexts_before = torch.cat([initial_state.context.unsqueeze(1), window.contexts_after[:, :-1]], dim=1)
        output = self.irt_head(
            contexts_before,
            window.item_views,
            window.gap_views,
            window.knowledge_before,
            window.subjects,
        )
        return output.logits, window.valid, window.state

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
        history_skill_indices: Tensor | None = None,
        candidate_skill_indices: Tensor | None = None,
    ) -> tuple[Tensor, SequenceState]:
        """用共享历史状态独立评估已知或开放课程候选题。"""
        history_items = history_items.reshape(1, -1)
        history_correct = history_correct.reshape(1, -1)
        history_gaps = history_gaps.reshape(1, -1)
        history_response_times = history_response_times.reshape(1, -1)
        if history_features is not None:
            history_features = history_features.reshape(1, history_items.size(1), 7)
        if history_content_features is not None:
            history_content_features = history_content_features.reshape(
                1, history_items.size(1), self.config.content_embedding_dim
            )
        if history_valid_mask is not None:
            history_valid_mask = history_valid_mask.reshape(1, -1).bool()
        if history_skill_indices is not None:
            history_skill_indices = history_skill_indices.reshape(1, history_items.size(1), -1)
        window = self._encode_window(
            history_items,
            history_correct,
            history_gaps,
            history_response_times,
            initial_state,
            history_features,
            history_content_features,
            history_valid_mask,
            history_skill_indices,
        )
        candidate_items = candidate_items.reshape(-1)
        candidate_gaps = candidate_gaps.reshape(-1)
        if candidate_items.numel() == 0:
            return candidate_gaps.new_empty((0,)), window.state
        if candidate_features is not None:
            candidate_features = candidate_features.reshape(-1, 7)
        if candidate_content_features is not None:
            candidate_content_features = candidate_content_features.reshape(-1, self.config.content_embedding_dim)
        if candidate_skill_indices is not None:
            candidate_skill_indices = candidate_skill_indices.reshape(candidate_items.numel(), -1)
        item_views = self.item_encoder(candidate_items, candidate_features, candidate_content_features)
        gap_views = self.gap_encoder(candidate_gaps)
        skills = self.item_encoder.resolve_skill_indices(candidate_items, candidate_skill_indices)
        knowledge = self.skill_tracker.read_candidates(window.state, candidate_items, skills, candidate_gaps)
        contexts = window.state.context.expand(candidate_items.numel(), -1)
        subjects = self.item_encoder.resolve_subject_indices(candidate_items)
        logits = self.irt_head(contexts, item_views, gap_views, knowledge, subjects).logits
        return torch.sigmoid(logits), window.state


class MEFKTLiteV3(_MEFKTV3Mixin, MEFKTLite):
    """面向少核 CPU 的显式 IRT + skill memory 模型。"""


class MEFKTV3(_MEFKTV3Mixin, MEFKT):
    """面向 GPU 的显式 IRT + skill memory + Transformer 模型。"""


__all__ = [
    "IRTPredictionHead",
    "IRTOutput",
    "MEFKTLiteV3",
    "MEFKTV3",
    "SkillAwareStateTracker",
]
