#!/user/bin/env python
# -*- coding: UTF-8 -*-
"""MEFKT 训练与状态管理工具。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import cast

from platform_ai.kt.datasets import DEFAULT_PUBLIC_DATASET
from tools.mefkt.course_data import build_course_bundle
from tools.mefkt.paths import MEFKT_META_PATH, MEFKT_MODEL_PATH, MEFKT_PUBLIC_BASELINE_DIR
from tools.mefkt.public_data import MEFKTTrainingBundle, _build_public_bundle
from tools.mefkt.training_support import (
    MEFKTTrainingConfig,
    train_mefkt_bundle,
)


logger = logging.getLogger(__name__)


def _train_mefkt_bundle(
    bundle: MEFKTTrainingBundle,
    output_path: Path,
    metadata_path: Path,
    *,
    epochs: int,
    pretrain_epochs: int,
    batch_size: int,
    lr: float,
    hidden_dim: int,
    align_dim: int,
    similarity_weight: float,
    num_heads: int,
    head_dim: int,
    use_gpu: bool | None = None,
    seed: int = 42,
    early_stopping_patience: int = 12,
    lr_decay: float = 0.96,
    profile: str = "full",
) -> dict[str, object]:
    """兼容旧私有入口，实际训练委托给 support 模块。"""
    return train_mefkt_bundle(
        bundle=bundle,
        output_path=output_path,
        metadata_path=metadata_path,
        config=MEFKTTrainingConfig(
            epochs=epochs,
            pretrain_epochs=pretrain_epochs,
            batch_size=batch_size,
            lr=lr,
            hidden_dim=hidden_dim,
            align_dim=align_dim,
            similarity_weight=similarity_weight,
            num_heads=num_heads,
            head_dim=head_dim,
            use_gpu=use_gpu,
            seed=seed,
            early_stopping_patience=early_stopping_patience,
            lr_decay=lr_decay,
            profile=profile,
        ),
    )


def train_mefkt_v2(
    course_id: int | None = None,
    epochs: int = 16,
    pretrain_epochs: int = 8,
    batch_size: int = 32,
    lr: float = 0.001,
    hidden_dim: int = 128,
    align_dim: int = 128,
    similarity_weight: float = 0.5,
    num_heads: int = 4,
    head_dim: int = 32,
    public_dataset: str | None = None,
    use_synthetic: bool = False,
    synthetic_students: int = 96,
    max_sequences: int | None = None,
    output_path: str | None = None,
    use_gpu: bool | None = None,
    sequence_max_step: int = 64,
    validation_ratio: float = 0.2,
    seed: int = 42,
    early_stopping_patience: int = 12,
    lr_decay: float = 0.96,
    profile: str = "full",
) -> dict[str, object]:
    """训练 MEFKT 模型，保持旧参数签名兼容。"""
    if use_synthetic or synthetic_students != 96:
        logger.info("MEFKT 当前训练优先使用公开数据或课程真实历史，use_synthetic 参数仅保留兼容，不参与监督训练")

    dataset_name = (public_dataset or DEFAULT_PUBLIC_DATASET).strip().lower()
    if course_id is not None or profile == "course-finetune":
        if course_id is None:
            raise ValueError("course-finetune 训练需要传入 course_id")
        bundle = build_course_bundle(
            course_id=int(course_id),
            validation_ratio=validation_ratio,
            seed=seed,
        )
    else:
        bundle = build_training_bundle(
            dataset_name=dataset_name,
            sequence_max_step=sequence_max_step,
            max_sequences=max_sequences,
            validation_ratio=validation_ratio,
            seed=seed,
        )
    output = resolve_mefkt_output_path(bundle.dataset_name, output_path)
    result = _train_mefkt_bundle(
        bundle=bundle,
        output_path=output,
        metadata_path=output.with_suffix(".meta.json"),
        epochs=epochs,
        pretrain_epochs=pretrain_epochs,
        batch_size=batch_size,
        lr=lr,
        hidden_dim=hidden_dim,
        align_dim=align_dim,
        similarity_weight=similarity_weight,
        num_heads=num_heads,
        head_dim=head_dim,
        use_gpu=use_gpu,
        seed=seed,
        early_stopping_patience=early_stopping_patience,
        lr_decay=lr_decay,
        profile=profile,
    )
    print_training_result(result)
    return result


def build_training_bundle(
    dataset_name: str,
    sequence_max_step: int,
    max_sequences: int | None,
    validation_ratio: float = 0.2,
    seed: int = 42,
) -> MEFKTTrainingBundle:
    """构建并按需裁剪公开训练包。"""
    bundle = _build_public_bundle(
        dataset_name,
        sequence_max_step=sequence_max_step,
        validation_ratio=validation_ratio,
        seed=seed,
    )
    if not max_sequences or len(bundle.sequences) <= max_sequences:
        return bundle
    validation_limit = max(1, min(len(bundle.validation_sequences), max_sequences // 5))
    test_limit = max(1, min(len(bundle.test_sequences), max_sequences // 5))
    split_policy = {
        **bundle.split_policy,
        "max_sequences": max_sequences,
        "train_sequences": max_sequences,
        "validation_sequences": validation_limit,
        "test_sequences": test_limit,
    }
    return MEFKTTrainingBundle(
        dataset_name=bundle.dataset_name,
        item_ids=bundle.item_ids,
        item_names=bundle.item_names,
        type_mapping=bundle.type_mapping,
        sequences=bundle.sequences[:max_sequences],
        node_feature_matrix=bundle.node_feature_matrix,
        relation_stats_matrix=bundle.relation_stats_matrix,
        adjacency_matrix=bundle.adjacency_matrix,
        difficulty_vector=bundle.difficulty_vector,
        response_time_vector=bundle.response_time_vector,
        exercise_type_vector=bundle.exercise_type_vector,
        training_mode=bundle.training_mode,
        training_sources=bundle.training_sources + [f"max_sequences={max_sequences}"],
        validation_sequences=bundle.validation_sequences[:validation_limit],
        test_sequences=bundle.test_sequences[:test_limit],
        split_policy=split_policy,
        graph_source=bundle.graph_source,
        feature_coverage=bundle.feature_coverage,
        paper_reproduction_notes=bundle.paper_reproduction_notes + [
            "本次训练使用 max_sequences 裁剪，仅适合作为 smoke/快速验证，不作为论文复现指标。",
        ],
    )


def resolve_mefkt_output_path(dataset_name: str, output_path: str | None) -> Path:
    """解析 MEFKT 模型输出路径。"""
    if output_path:
        return Path(output_path)
    if dataset_name == DEFAULT_PUBLIC_DATASET:
        return MEFKT_MODEL_PATH
    return MEFKT_PUBLIC_BASELINE_DIR / f"mefkt_{dataset_name}.pt"


def print_training_result(result: dict[str, object]) -> None:
    """输出 MEFKT 训练摘要。"""
    metrics_payload = cast(dict[str, float], result["metrics"])
    test_metrics_payload = cast(dict[str, float], result.get("test_metrics") or {})
    print(
        f"[MEFKT] 训练完成: dataset={result['training_dataset']}, "
        f"val_auc={metrics_payload['auc']:.4f}, val_acc={metrics_payload['acc']:.4f}, "
        f"test_auc={test_metrics_payload.get('auc', 0.0):.4f}, "
        f"test_acc={test_metrics_payload.get('acc', 0.0):.4f}, "
        f"path={result['model_path']}, backup={result.get('backup_path')}"
    )


def mefkt_status() -> dict[str, object]:
    """查看当前运行时 MEFKT 模型状态。"""
    if not MEFKT_META_PATH.exists():
        return print_mefkt_status({
            "is_available": False,
            "model_path": str(MEFKT_MODEL_PATH),
            "metadata_path": str(MEFKT_META_PATH),
        })

    metadata = json.loads(MEFKT_META_PATH.read_text(encoding="utf-8"))
    return print_mefkt_status({
        "is_available": MEFKT_MODEL_PATH.exists(),
        "model_path": str(MEFKT_MODEL_PATH),
        "metadata_path": str(MEFKT_META_PATH),
        "training_mode": metadata.get("training_mode"),
        "runtime_schema": metadata.get("runtime_schema"),
        "training_dataset": metadata.get("training_dataset"),
        "question_online_enabled": metadata.get("question_online_enabled", False),
        "best_metrics": metadata.get("best_metrics"),
        "item_count": metadata.get("item_count"),
        "paper_title": metadata.get("paper_title"),
    })


def print_mefkt_status(status: dict[str, object]) -> dict[str, object]:
    """打印并返回 MEFKT 状态。"""
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return status


__all__ = ["MEFKTTrainingBundle", "mefkt_status", "train_mefkt_v2"]
