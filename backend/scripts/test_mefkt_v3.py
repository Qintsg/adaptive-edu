#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT v3 显式知识状态与 IRT 架构回归测试。
@Project : adaptive-edu
@File : test_mefkt_v3.py
@Author : Qintsg
@Date : 2026-09-01
'''

from __future__ import annotations

import torch

from mefkt_model_config import lite_config
from mefkt_models import build_model, model_config_from_checkpoint
from mefkt_v3_models import IRTPredictionHead


def _build_lite_model() -> torch.nn.Module:
    """
    构造具有三个知识点的小型 v3 模型。

    :returns: MEFKT-Lite v3 模型。
    """
    item_count = 4
    item_features = torch.zeros((item_count, 391), dtype=torch.float32)
    item_features[:, 0] = torch.tensor([0.1, 0.3, 0.6, 0.9])
    item_subjects = torch.tensor([0, 0, 1, 1], dtype=torch.long)
    item_skills = torch.tensor([[0, -1], [1, -1], [2, -1], [0, 2]], dtype=torch.long)
    return build_model("lite", item_count, item_features, item_subjects, item_skills, 2, 3)


def test_forward_is_causal_and_updates_only_visited_skill_slots() -> None:
    """当前标签不能泄漏，且未访问知识点状态必须保持零值。"""
    torch.manual_seed(19)
    model = _build_lite_model().eval()
    items = torch.tensor([[0, 0]], dtype=torch.long)
    correct = torch.tensor([[1, 0]], dtype=torch.long)
    gaps = torch.tensor([[1.0, 2.0]], dtype=torch.float32)
    response_times = torch.tensor([[10.0, 20.0]], dtype=torch.float32)

    with torch.no_grad():
        logits, _, state = model(items, correct, gaps, response_times)
        changed = correct.clone()
        changed[0, 1] = 1
        changed_logits = model(items, changed, gaps, response_times)[0]

    assert model.config.architecture_version == 3
    assert torch.allclose(logits[0, 1], changed_logits[0, 1], atol=1e-7)
    assert state.skill_memory is not None
    assert state.skill_attempts is not None
    assert state.skill_attempts[0, 0].item() == 2.0
    assert state.skill_attempts[0, 1].item() == 0.0
    assert torch.count_nonzero(state.skill_memory[0, 1]).item() == 0


def test_irt_head_is_monotonic_in_explicit_ability_and_difficulty() -> None:
    """显式能力增大应提高 logit，显式难度增大应降低 logit。"""
    config = lite_config()
    head = IRTPredictionHead(config, config.skill_memory_dim + config.online_feature_dim, 2).eval()
    with torch.no_grad():
        for parameter in head.parameters():
            parameter.zero_()
        head.ability[-1].bias.fill_(1.0)
        head.difficulty[-1].bias.fill_(0.4)
        contexts = torch.zeros((1, config.state_dim))
        items = torch.zeros((1, config.item_view_dim))
        gaps = torch.zeros((1, config.gap_embedding_dim))
        knowledge = torch.zeros((1, config.skill_memory_dim + config.online_feature_dim))
        subjects = torch.zeros(1, dtype=torch.long)
        baseline = head(contexts, items, gaps, knowledge, subjects)
        head.ability[-1].bias.fill_(1.3)
        higher_ability = head(contexts, items, gaps, knowledge, subjects)
        head.difficulty[-1].bias.fill_(0.9)
        harder_item = head(contexts, items, gaps, knowledge, subjects)

    assert higher_ability.logits.item() > baseline.logits.item()
    assert harder_item.logits.item() < higher_ability.logits.item()


def test_unknown_course_can_reuse_stable_external_skill_slots() -> None:
    """开放课程未知题目应使用稳定外部 skill 槽更新并读取状态。"""
    torch.manual_seed(23)
    model = _build_lite_model().eval()
    items = torch.tensor([[-1, -1]], dtype=torch.long)
    correct = torch.tensor([[1, 0]], dtype=torch.long)
    gaps = torch.tensor([[1.0, 1.0]], dtype=torch.float32)
    response_times = torch.tensor([[10.0, 12.0]], dtype=torch.float32)
    features = torch.zeros((1, 2, 7), dtype=torch.float32)
    content = torch.randn((1, 2, 384), dtype=torch.float32)
    valid = torch.ones((1, 2), dtype=torch.bool)
    external_skills = torch.tensor([[[7, -1], [7, -1]]], dtype=torch.long)

    with torch.no_grad():
        _, _, state = model(
            items,
            correct,
            gaps,
            response_times,
            sequence_features=features,
            sequence_content_features=content,
            sequence_valid_mask=valid,
            sequence_skill_indices=external_skills,
        )

    assert state.skill_attempts is not None
    external_slot = model.item_encoder.skill_count + 7
    assert state.skill_attempts[0, external_slot].item() == 2.0


def test_model_factory_preserves_v2_checkpoint_architecture() -> None:
    """旧 checkpoint 配置必须继续构建 v2，而不是错误加载为 v3。"""
    current = lite_config().to_dict()
    current["architecture_version"] = 2
    checkpoint: dict[str, object] = {"metadata": {"model": {"config": current}}}
    config = model_config_from_checkpoint(checkpoint, "lite")
    model = build_model(
        "lite",
        4,
        torch.zeros((4, 391)),
        torch.zeros(4, dtype=torch.long),
        torch.zeros((4, 2), dtype=torch.long),
        2,
        3,
        config,
    )

    assert config.architecture_version == 2
    assert type(model).__name__ == "MEFKTLite"
