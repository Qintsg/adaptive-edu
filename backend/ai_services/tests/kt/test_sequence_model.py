#!/user/bin/env python
# -*- coding: UTF-8 -*-
"""
MEFKT 序列模型回归测试。
@Project : adaptive-edu
@File : test_sequence_model.py
@Author : Qintsg
@Date : 2026-06-07 20:34
"""

from __future__ import annotations

import torch
from django.test import SimpleTestCase

from models.MEFKT.model import MEFKTSequenceModel


class MEFKTSequenceModelTests(SimpleTestCase):
    """覆盖 MEFKT 序列模型训练路径。"""

    def test_forward_should_match_stepwise_candidate_prediction(self) -> None:
        """
        批量 forward 路径应保持逐步候选预测语义。
        """
        torch.manual_seed(17)
        model = MEFKTSequenceModel(
            item_count=5,
            item_embedding_dim=8,
            num_heads=2,
            head_dim=4,
        )
        model.eval()
        item_tensor = torch.tensor([[0, 1, 2, -1], [3, 4, 1, 2]], dtype=torch.long)
        correct_tensor = torch.tensor([[1, 0, 1, 0], [0, 1, 1, 0]], dtype=torch.long)
        gap_tensor = torch.tensor(
            [[1.0, 2.0, 3.0, 1.0], [1.0, 4.0, 2.0, 1.0]],
            dtype=torch.float32,
        )

        with torch.no_grad():
            forward_prediction, forward_mask = model(item_tensor, correct_tensor, gap_tensor)

            stepwise_prediction = torch.zeros_like(forward_prediction)
            stepwise_mask = torch.zeros_like(forward_mask)
            for batch_index in range(item_tensor.size(0)):
                valid_positions = torch.nonzero(
                    item_tensor[batch_index] >= 0,
                    as_tuple=False,
                ).flatten()
                for target_position in valid_positions[1:].tolist():
                    probability = model.predict_candidate(
                        history_item_indices=item_tensor[batch_index, :target_position],
                        history_correct_flags=correct_tensor[batch_index, :target_position],
                        history_time_gaps=gap_tensor[batch_index, :target_position],
                        candidate_item_indices=item_tensor[
                            batch_index,
                            target_position : target_position + 1,
                        ],
                    )[0]
                    stepwise_prediction[batch_index, target_position - 1] = probability
                    stepwise_mask[batch_index, target_position - 1] = True

        self.assertEqual(forward_mask.tolist(), stepwise_mask.tolist())
        self.assertTrue(
            torch.allclose(
                forward_prediction[forward_mask],
                stepwise_prediction[stepwise_mask],
                atol=1e-5,
            )
        )

