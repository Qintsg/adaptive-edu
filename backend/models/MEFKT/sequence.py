"""MEFKT 融合遗忘机制的序列预测模型。"""

from __future__ import annotations

import math

import torch
import torch.nn.functional as functional
from torch import Tensor, nn


class MEFKTSequenceModel(nn.Module):
    """融合遗忘机制的行为序列预测模型。"""

    def __init__(
        self,
        item_count: int,
        item_embedding_dim: int,
        num_heads: int = 4,
        head_dim: int = 32,
        pretrained_item_embedding: Tensor | None = None,
    ) -> None:
        """
        初始化 MEFKT 行为预测模型。

        :param item_count: 节点数量。
        :param item_embedding_dim: 节点嵌入维度。
        :param num_heads: 注意力头数。
        :param head_dim: 单头维度。
        :param pretrained_item_embedding: 预训练节点嵌入。
        """
        super().__init__()
        self.item_embedding = nn.Embedding(item_count, item_embedding_dim)
        if pretrained_item_embedding is not None:
            self.item_embedding.weight.data.copy_(pretrained_item_embedding)
        self.answer_embedding = nn.Embedding(2, item_embedding_dim)
        self.query_projection = nn.Linear(item_embedding_dim, num_heads * head_dim)
        self.key_projection = nn.Linear(item_embedding_dim, num_heads * head_dim)
        self.value_projection = nn.Linear(item_embedding_dim, num_heads * head_dim)
        self.history_projection = nn.Linear(item_embedding_dim * 2, item_embedding_dim)
        self.output_layer = nn.Sequential(
            nn.Linear(num_heads * head_dim + item_embedding_dim, item_embedding_dim),
            nn.ReLU(),
            nn.Dropout(p=0.1),
            nn.Linear(item_embedding_dim, 1),
        )
        self.num_heads = num_heads
        self.head_dim = head_dim
        self.theta_raw = nn.Parameter(torch.zeros(num_heads))

    def _perceived_distance(
        self,
        history_time_gap: Tensor,
        relevance_score: Tensor,
    ) -> Tensor:
        """
        估计从历史位置到当前预测位置的可感知距离。

        :return: 每个位置的感知距离。
        """
        step_distance = torch.arange(
            history_time_gap.size(0),
            0,
            -1,
            device=history_time_gap.device,
            dtype=history_time_gap.dtype,
        )
        normalized_gap = history_time_gap.clamp_min(1.0)
        reverse_gap = torch.flip(normalized_gap, dims=[0])
        cumulative_gap = torch.flip(torch.cumsum(reverse_gap, dim=0), dims=[0])

        reverse_relevance = torch.flip(relevance_score, dims=[0])
        cumulative_relevance = torch.flip(torch.cumsum(reverse_relevance, dim=0), dims=[0])
        return (
            step_distance.unsqueeze(1)
            * cumulative_gap.unsqueeze(1)
            * cumulative_relevance
        )

    def predict_candidate(
        self,
        history_item_indices: Tensor,
        history_correct_flags: Tensor,
        history_time_gaps: Tensor,
        candidate_item_indices: Tensor,
    ) -> Tensor:
        """
        基于历史序列为候选节点计算正确概率。

        :return: 候选概率张量。
        """
        if history_item_indices.numel() <= 0:
            candidate_embedding = self.item_embedding(candidate_item_indices.long())
            base_logit = self.output_layer(
                torch.cat(
                    [
                        torch.zeros(
                            candidate_embedding.size(0),
                            self.num_heads * self.head_dim,
                            device=candidate_embedding.device,
                        ),
                        candidate_embedding,
                    ],
                    dim=1,
                )
            )
            return torch.sigmoid(base_logit.squeeze(1))

        history_embedding = self.item_embedding(history_item_indices.long())
        answer_embedding = self.answer_embedding(history_correct_flags.long())
        interaction_embedding = self.history_projection(
            torch.cat([history_embedding, answer_embedding], dim=1)
        )

        history_query = self.query_projection(history_embedding).view(
            -1,
            self.num_heads,
            self.head_dim,
        )
        history_key = self.key_projection(history_embedding).view(
            -1,
            self.num_heads,
            self.head_dim,
        )
        self_relevance = torch.sum(history_query * history_key, dim=2) / math.sqrt(self.head_dim)
        relevance_score = torch.softmax(self_relevance, dim=0)
        perceived_distance = self._perceived_distance(history_time_gaps.float(), relevance_score)

        theta = functional.softplus(self.theta_raw).view(1, self.num_heads) + 1e-4
        key_tensor = self.key_projection(history_embedding).view(-1, self.num_heads, self.head_dim)
        value_tensor = self.value_projection(interaction_embedding).view(-1, self.num_heads, self.head_dim)

        predicted_probabilities: list[Tensor] = []
        for candidate_index in candidate_item_indices.long():
            candidate_embedding = self.item_embedding(candidate_index)
            query_tensor = self.query_projection(candidate_embedding).view(self.num_heads, self.head_dim)
            raw_score = torch.sum(key_tensor * query_tensor.unsqueeze(0), dim=2) / math.sqrt(self.head_dim)
            decay_score = torch.exp(-theta * perceived_distance)
            attention_weight = torch.softmax(raw_score * decay_score, dim=0)
            context_vector = torch.sum(attention_weight.unsqueeze(2) * value_tensor, dim=0).reshape(-1)
            logit = self.output_layer(
                torch.cat([context_vector, candidate_embedding], dim=0)
            ).squeeze(0)
            predicted_probabilities.append(torch.sigmoid(logit))
        return torch.stack(predicted_probabilities, dim=0)

    def forward(
        self,
        sequence_item_indices: Tensor,
        sequence_correct_flags: Tensor,
        sequence_time_gaps: Tensor,
    ) -> tuple[Tensor, Tensor]:
        """
        对一批序列执行下一题预测。

        :return: `(预测概率, 有效位置掩码)`。
        """
        batch_size, sequence_length = sequence_item_indices.shape
        if sequence_length <= 1:
            empty_prediction = torch.zeros(batch_size, 0, device=sequence_item_indices.device)
            empty_mask = torch.zeros(batch_size, 0, dtype=torch.bool, device=sequence_item_indices.device)
            return empty_prediction, empty_mask

        safe_item_indices = sequence_item_indices.clamp_min(0).long()
        valid_positions = sequence_item_indices >= 0
        item_embedding = self.item_embedding(safe_item_indices)
        answer_embedding = self.answer_embedding(sequence_correct_flags.long().clamp(0, 1))
        interaction_embedding = self.history_projection(
            torch.cat([item_embedding, answer_embedding], dim=2)
        )
        query_tensor = self.query_projection(item_embedding).view(
            batch_size,
            sequence_length,
            self.num_heads,
            self.head_dim,
        )
        key_tensor = self.key_projection(item_embedding).view(
            batch_size,
            sequence_length,
            self.num_heads,
            self.head_dim,
        )
        value_tensor = self.value_projection(interaction_embedding).view(
            batch_size,
            sequence_length,
            self.num_heads,
            self.head_dim,
        )

        target_count = sequence_length - 1
        history_query = query_tensor[:, :-1]
        history_key = key_tensor[:, :-1]
        history_value = value_tensor[:, :-1]
        candidate_query = query_tensor[:, 1:]
        candidate_embedding = item_embedding[:, 1:]
        history_valid = valid_positions[:, :-1]
        target_valid = valid_positions[:, 1:]

        target_positions = torch.arange(target_count, device=sequence_item_indices.device)
        history_positions = torch.arange(target_count, device=sequence_item_indices.device)
        causal_mask = history_positions.unsqueeze(0) <= target_positions.unsqueeze(1)
        valid_history_mask = (
            history_valid.unsqueeze(1)
            & target_valid.unsqueeze(2)
            & causal_mask.unsqueeze(0)
        )
        valid_mask = target_valid & valid_history_mask.any(dim=2)
        valid_history_float = valid_history_mask.float()

        self_relevance = torch.sum(history_query * history_key, dim=3) / math.sqrt(self.head_dim)
        masked_self_relevance = self_relevance.unsqueeze(1).masked_fill(
            ~valid_history_mask.unsqueeze(3),
            -1.0e9,
        )
        relevance_score = torch.softmax(masked_self_relevance, dim=2) * valid_history_float.unsqueeze(3)
        cumulative_relevance = torch.flip(
            torch.cumsum(torch.flip(relevance_score, dims=[2]), dim=2),
            dims=[2],
        )

        history_gap = sequence_time_gaps[:, :-1].float().clamp_min(1.0)
        masked_gap = history_gap.unsqueeze(1) * valid_history_float
        cumulative_gap = torch.flip(
            torch.cumsum(torch.flip(masked_gap, dims=[2]), dim=2),
            dims=[2],
        )
        step_distance = (
            target_positions.unsqueeze(1) - history_positions.unsqueeze(0) + 1
        ).clamp_min(1).float()
        perceived_distance = (
            step_distance.unsqueeze(0).unsqueeze(3)
            * cumulative_gap.unsqueeze(3)
            * cumulative_relevance
        )

        raw_score = torch.einsum("bshd,bthd->btsh", history_key, candidate_query) / math.sqrt(self.head_dim)
        theta = functional.softplus(self.theta_raw).view(1, 1, 1, self.num_heads) + 1e-4
        decay_score = torch.exp(-theta * perceived_distance)
        attention_logits = (raw_score * decay_score).masked_fill(
            ~valid_history_mask.unsqueeze(3),
            -1.0e9,
        )
        attention_weight = torch.softmax(attention_logits, dim=2) * valid_history_float.unsqueeze(3)
        context_tensor = torch.sum(
            attention_weight.unsqueeze(4) * history_value.unsqueeze(1),
            dim=2,
        ).reshape(batch_size, target_count, self.num_heads * self.head_dim)
        output_input = torch.cat([context_tensor, candidate_embedding], dim=2)
        prediction = torch.sigmoid(
            self.output_layer(output_input.reshape(batch_size * target_count, -1)).view(
                batch_size,
                target_count,
            )
        )
        return prediction * valid_mask.float(), valid_mask


__all__ = ["MEFKTSequenceModel"]
