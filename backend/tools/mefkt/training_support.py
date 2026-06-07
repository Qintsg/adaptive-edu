"""MEFKT 训练流程支持函数。"""

from __future__ import annotations

import json
import random
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import torch
from torch import Tensor

from models.MEFKT.model import (
    GraphContrastiveEncoder,
    LinearAlignmentFusion,
    MEFKTSequenceModel,
    MultiAttributeEncoder,
    NODE_FEATURE_SCHEMA,
    QUESTION_TYPE_VOCAB,
    RELATION_STAT_SCHEMA,
)
from platform_ai.kt.torch_device import resolve_torch_device
from tools.mefkt.paths import PAPER_DOI, PAPER_TITLE, RUNTIME_SCHEMA
from tools.mefkt.public_data import (
    MEFKTTrainingBundle,
    _collate_batch,
    _evaluate_sequence_model,
    _relative_to_project,
)


@dataclass(frozen=True)
class MEFKTTrainingConfig:
    """MEFKT 训练参数。"""

    epochs: int
    pretrain_epochs: int
    batch_size: int
    lr: float
    hidden_dim: int
    align_dim: int
    similarity_weight: float
    num_heads: int
    head_dim: int
    use_gpu: bool | None
    seed: int = 42
    early_stopping_patience: int = 12
    lr_decay: float = 0.96
    profile: str = "full"


@dataclass(frozen=True)
class MEFKTModelComponents:
    """MEFKT 图编码、属性编码与融合组件。"""

    runtime_device: object
    device: torch.device
    graph_encoder: GraphContrastiveEncoder
    attribute_encoder: MultiAttributeEncoder
    fusion_layer: LinearAlignmentFusion
    feature_dim: int
    relation_dim: int


@dataclass(frozen=True)
class MEFKTSequenceTrainingResult:
    """MEFKT 序列模型训练结果。"""

    best_metrics: dict[str, float]
    best_sequence_state: dict[str, Tensor]
    test_metrics: dict[str, float]
    training_history: list[dict[str, float]]


def write_mefkt_metadata(metadata_path: Path, payload: dict[str, object]) -> None:
    """持久化模型元数据。"""
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def train_mefkt_bundle(
    *,
    bundle: MEFKTTrainingBundle,
    output_path: Path,
    metadata_path: Path,
    config: MEFKTTrainingConfig,
) -> dict[str, object]:
    """针对公开训练包训练可在线重建的 MEFKT 模型。"""
    set_training_seed(config.seed)
    components = build_mefkt_components(bundle, config)
    print(f"[MEFKT] 训练设备={components.runtime_device.label}, reason={components.runtime_device.reason}")
    fused_embedding = pretrain_mefkt_embedding(bundle, components, config)
    sequence_result = train_sequence_predictor(bundle, fused_embedding, components.device, config)
    metadata_payload = build_mefkt_metadata(
        bundle=bundle,
        output_path=output_path,
        components=components,
        fused_embedding=fused_embedding,
        sequence_result=sequence_result,
        config=config,
    )
    save_mefkt_checkpoint(
        output_path=output_path,
        metadata_path=metadata_path,
        metadata_payload=metadata_payload,
        sequence_state=sequence_result.best_sequence_state,
        components=components,
    )
    return {
        "model_path": str(output_path),
        "metadata_path": str(metadata_path),
        "backup_path": str(output_path.with_suffix(output_path.suffix + ".bak")),
        "metrics": sequence_result.best_metrics,
        "test_metrics": sequence_result.test_metrics,
        "training_mode": bundle.training_mode,
        "item_count": len(bundle.item_ids),
        "training_dataset": bundle.dataset_name,
        "training_device": components.runtime_device.label,
    }


def set_training_seed(seed: int) -> None:
    """固定 Python 与 PyTorch 随机种子，提升训练可复现性。"""
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def build_mefkt_components(
    bundle: MEFKTTrainingBundle,
    config: MEFKTTrainingConfig,
) -> MEFKTModelComponents:
    """构建 MEFKT 编码器和融合层。"""
    runtime_device = resolve_torch_device(config.use_gpu)
    device = runtime_device.device
    feature_dim = int(bundle.node_feature_matrix.size(1))
    relation_dim = int(bundle.relation_stats_matrix.size(1))
    type_count = max(bundle.type_mapping.values(), default=0) + 1
    graph_encoder = GraphContrastiveEncoder(feature_dim, config.hidden_dim, config.align_dim).to(device)
    attribute_encoder = MultiAttributeEncoder(
        feature_dim,
        type_count,
        config.align_dim,
        relation_dim=relation_dim,
    ).to(device)
    fusion_layer = LinearAlignmentFusion(config.align_dim, config.align_dim, config.align_dim).to(device)
    return MEFKTModelComponents(
        runtime_device=runtime_device,
        device=device,
        graph_encoder=graph_encoder,
        attribute_encoder=attribute_encoder,
        fusion_layer=fusion_layer,
        feature_dim=feature_dim,
        relation_dim=relation_dim,
    )


def pretrain_mefkt_embedding(
    bundle: MEFKTTrainingBundle,
    components: MEFKTModelComponents,
    config: MEFKTTrainingConfig,
) -> Tensor:
    """预训练图结构、属性编码和融合层，返回题目 embedding。"""
    feature_matrix = bundle.node_feature_matrix.to(components.device)
    relation_stats = bundle.relation_stats_matrix.to(components.device)
    adjacency = bundle.adjacency_matrix.to(components.device)
    difficulty_vector = bundle.difficulty_vector.to(components.device)
    response_time_vector = bundle.response_time_vector.to(components.device)
    type_vector = bundle.exercise_type_vector.to(components.device)
    optimizer = torch.optim.Adam(
        list(components.graph_encoder.parameters())
        + list(components.attribute_encoder.parameters())
        + list(components.fusion_layer.parameters()),
        lr=config.lr,
    )
    fused_embedding = None
    for _ in range(max(config.pretrain_epochs, 1)):
        fused_embedding = run_pretrain_epoch(
            components=components,
            optimizer=optimizer,
            feature_matrix=feature_matrix,
            relation_stats=relation_stats,
            adjacency=adjacency,
            difficulty_vector=difficulty_vector,
            response_time_vector=response_time_vector,
            type_vector=type_vector,
            similarity_weight=config.similarity_weight,
        )
    if fused_embedding is None:
        raise RuntimeError("MEFKT 预训练未产生融合嵌入")
    return fused_embedding


def run_pretrain_epoch(
    *,
    components: MEFKTModelComponents,
    optimizer: torch.optim.Optimizer,
    feature_matrix: Tensor,
    relation_stats: Tensor,
    adjacency: Tensor,
    difficulty_vector: Tensor,
    response_time_vector: Tensor,
    type_vector: Tensor,
    similarity_weight: float,
) -> Tensor:
    """执行单轮 MEFKT 表征预训练。"""
    components.graph_encoder.train()
    components.attribute_encoder.train()
    components.fusion_layer.train()
    struct_embedding, contrastive_loss = components.graph_encoder.contrastive_loss(feature_matrix, adjacency)
    attribute_result = components.attribute_encoder(
        node_feature_matrix=feature_matrix,
        difficulty_vector=difficulty_vector,
        response_time_vector=response_time_vector,
        exercise_type_vector=type_vector,
        exercise_adjacency=adjacency,
        relation_stats_matrix=relation_stats,
    )
    fused_embedding = components.fusion_layer(struct_embedding, attribute_result.embedding)
    total_loss = (
        contrastive_loss
        + attribute_result.difficulty_loss
        + similarity_weight * attribute_result.similarity_loss
        + 1e-4 * fused_embedding.pow(2).mean()
    )
    optimizer.zero_grad()
    total_loss.backward()
    torch.nn.utils.clip_grad_norm_(
        list(components.graph_encoder.parameters())
        + list(components.attribute_encoder.parameters())
        + list(components.fusion_layer.parameters()),
        max_norm=5.0,
    )
    optimizer.step()
    return fused_embedding


def train_sequence_predictor(
    bundle: MEFKTTrainingBundle,
    ready_embedding: Tensor,
    device: torch.device,
    config: MEFKTTrainingConfig,
) -> MEFKTSequenceTrainingResult:
    """训练 MEFKT 序列预测模型。"""
    train_sequences = list(bundle.sequences)
    validation_sequences = list(bundle.validation_sequences or bundle.sequences)
    test_sequences = list(bundle.test_sequences or validation_sequences)
    sequence_model = MEFKTSequenceModel(
        item_count=len(bundle.item_ids),
        item_embedding_dim=int(ready_embedding.size(1)),
        num_heads=config.num_heads,
        head_dim=config.head_dim,
        pretrained_item_embedding=ready_embedding.detach().cpu(),
    ).to(device)
    sequence_optimizer = torch.optim.Adam(sequence_model.parameters(), lr=config.lr)
    scheduler = torch.optim.lr_scheduler.ExponentialLR(
        sequence_optimizer,
        gamma=config.lr_decay,
    )
    best_metrics = {"auc": 0.0, "acc": 0.0, "samples": 0.0}
    best_sequence_state: dict[str, Tensor] | None = None
    training_history: list[dict[str, float]] = []
    stale_epoch_count = 0
    for epoch_index in range(max(config.epochs, 1)):
        average_loss = run_sequence_epoch(
            sequence_model=sequence_model,
            sequence_optimizer=sequence_optimizer,
            train_sequences=train_sequences,
            batch_size=config.batch_size,
            device=device,
        )
        metrics = _evaluate_sequence_model(sequence_model, validation_sequences, config.batch_size, device)
        learning_rate = float(sequence_optimizer.param_groups[0]["lr"])
        training_history.append({
            "epoch": float(epoch_index + 1),
            "loss": float(average_loss),
            "val_auc": float(metrics["auc"]),
            "val_acc": float(metrics["acc"]),
            "val_samples": float(metrics["samples"]),
            "lr": learning_rate,
        })
        if metrics["auc"] >= best_metrics["auc"]:
            best_metrics = metrics
            best_sequence_state = cpu_state_dict(sequence_model)
            stale_epoch_count = 0
        else:
            stale_epoch_count += 1
        print(
            f"[MEFKT] epoch={epoch_index + 1}/{max(config.epochs, 1)} "
            f"loss={average_loss:.4f} auc={metrics['auc']:.4f} "
            f"acc={metrics['acc']:.4f} samples={int(metrics['samples'])} "
            f"lr={learning_rate:.6f}"
        )
        scheduler.step()
        if 0 < config.early_stopping_patience <= stale_epoch_count:
            print(f"[MEFKT] early-stop epoch={epoch_index + 1} patience={config.early_stopping_patience}")
            break
    if best_sequence_state is not None:
        sequence_model.load_state_dict(best_sequence_state)
    test_metrics = _evaluate_sequence_model(sequence_model, test_sequences, config.batch_size, device)
    return MEFKTSequenceTrainingResult(
        best_metrics=best_metrics,
        best_sequence_state=best_sequence_state or cpu_state_dict(sequence_model),
        test_metrics=test_metrics,
        training_history=training_history,
    )


def run_sequence_epoch(
    *,
    sequence_model: MEFKTSequenceModel,
    sequence_optimizer: torch.optim.Optimizer,
    train_sequences: list[object],
    batch_size: int,
    device: torch.device,
) -> float:
    """执行单轮序列模型训练并返回平均 loss。"""
    random.shuffle(train_sequences)
    sequence_model.train()
    total_loss_value = 0.0
    valid_batch_count = 0
    for start_index in range(0, len(train_sequences), batch_size):
        batch_sequences = train_sequences[start_index : start_index + batch_size]
        item_tensor, correct_tensor, time_gap_tensor = _collate_batch(batch_sequences)
        probability_tensor, valid_mask = sequence_model(
            item_tensor.to(device),
            correct_tensor.to(device),
            time_gap_tensor.to(device),
        )
        target_tensor = correct_tensor[:, 1:].float().to(device)
        if not bool(valid_mask.any()):
            continue
        loss = torch.nn.functional.binary_cross_entropy(
            probability_tensor[valid_mask],
            target_tensor[valid_mask],
        )
        sequence_optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(sequence_model.parameters(), max_norm=5.0)
        sequence_optimizer.step()
        total_loss_value += float(loss.item())
        valid_batch_count += 1
    return total_loss_value / max(valid_batch_count, 1)


def cpu_state_dict(model: torch.nn.Module) -> dict[str, Tensor]:
    """将模型 state_dict 移动到 CPU。"""
    return {key: value.detach().cpu() for key, value in model.state_dict().items()}


def build_reproduction_summary(
    bundle: MEFKTTrainingBundle,
    config: MEFKTTrainingConfig,
) -> dict[str, object]:
    """生成论文复现程度说明，避免把工程适配训练误标为严格复现。"""
    candidate_datasets = {"assist2009", "ednet"}
    has_proxy_features = not bool(bundle.feature_coverage.get("real_response_time_ratio"))
    is_candidate = (
        config.profile == "paper"
        and bundle.dataset_name in candidate_datasets
        and not has_proxy_features
    )
    if is_candidate:
        level = "paper_candidate"
        summary = "数据集和特征条件满足论文复现候选要求，可用于复现型指标对比。"
    elif bundle.training_mode == "course_question_finetune":
        level = "course_adaptation"
        summary = "课程域微调用于本系统在线预测效果，不作为公开论文指标复现。"
    else:
        level = "engineering_adaptation"
        summary = "公开数据训练使用题目关系和属性代理特征，属于工程化适配而非严格论文复现。"
    return {
        "is_paper_reproduction_candidate": is_candidate,
        "paper_reproduction_level": level,
        "paper_reproduction_summary": summary,
    }


def build_torch_runtime_metadata(components: MEFKTModelComponents) -> dict[str, object]:
    """提取训练运行时的 PyTorch 与设备信息。"""
    gpu_name = None
    if torch.cuda.is_available():
        try:
            gpu_name = torch.cuda.get_device_name(torch.cuda.current_device())
        except (AssertionError, RuntimeError):
            gpu_name = None
    return {
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "requested_gpu": bool(getattr(components.runtime_device, "requested_gpu", False)),
        "using_gpu": bool(getattr(components.runtime_device, "using_gpu", False)),
        "training_device": components.runtime_device.label,
        "training_device_reason": components.runtime_device.reason,
        "gpu_name": gpu_name,
    }


def build_mefkt_metadata(
    *,
    bundle: MEFKTTrainingBundle,
    output_path: Path,
    components: MEFKTModelComponents,
    fused_embedding: Tensor,
    sequence_result: MEFKTSequenceTrainingResult,
    config: MEFKTTrainingConfig,
) -> dict[str, object]:
    """构造 MEFKT 运行时元数据。"""
    reproduction_summary = build_reproduction_summary(bundle, config)
    torch_runtime_metadata = build_torch_runtime_metadata(components)
    return {
        "model_name": "MEFKT",
        "paper_title": PAPER_TITLE,
        "paper_doi": PAPER_DOI,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "runtime_schema": RUNTIME_SCHEMA,
        "training_mode": bundle.training_mode,
        "training_dataset": bundle.dataset_name,
        "public_training_only": bundle.training_mode != "course_question_finetune",
        "question_online_enabled": True,
        **reproduction_summary,
        "item_count": len(bundle.item_ids),
        "item_ids": bundle.item_ids,
        "item_names": bundle.item_names,
        "feature_dim": components.feature_dim,
        "relation_dim": components.relation_dim,
        "embedding_dim": int(fused_embedding.size(1)),
        "num_heads": config.num_heads,
        "head_dim": config.head_dim,
        "hidden_dim": config.hidden_dim,
        "align_dim": config.align_dim,
        "epochs": config.epochs,
        "pretrain_epochs": config.pretrain_epochs,
        "learning_rate": config.lr,
        "batch_size": config.batch_size,
        "similarity_weight": config.similarity_weight,
        "seed": config.seed,
        "early_stopping_patience": config.early_stopping_patience,
        "lr_decay": config.lr_decay,
        "training_profile": config.profile,
        **torch_runtime_metadata,
        "training_sources": bundle.training_sources,
        "split_policy": bundle.split_policy,
        "graph_source": bundle.graph_source,
        "feature_coverage": bundle.feature_coverage,
        "paper_reproduction_notes": bundle.paper_reproduction_notes,
        "type_mapping": bundle.type_mapping,
        "question_type_vocab": QUESTION_TYPE_VOCAB,
        "node_feature_schema": list(NODE_FEATURE_SCHEMA),
        "relation_stat_schema": list(RELATION_STAT_SCHEMA),
        "best_metrics": sequence_result.best_metrics,
        "test_metrics": sequence_result.test_metrics,
        "training_history": sequence_result.training_history,
        "model_path": _relative_to_project(output_path),
        "backup_path": _relative_to_project(output_path.with_suffix(output_path.suffix + ".bak")),
        "response_time_proxy": "公开数据使用重访距离代理，在线课程题图使用题目难度、长度、历史正确率与图结构统计综合近似",
        "difficulty_proxy": "公开数据使用错误率，在线课程题图使用题目难度与历史表现联合编码",
    }


def save_mefkt_checkpoint(
    *,
    output_path: Path,
    metadata_path: Path,
    metadata_payload: dict[str, object],
    sequence_state: dict[str, Tensor],
    components: MEFKTModelComponents,
) -> None:
    """保存 MEFKT 训练检查点和元数据。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = {
        "state_dict": sequence_state,
        "sequence_state_dict": sequence_state,
        "graph_state_dict": cpu_state_dict(components.graph_encoder),
        "attribute_state_dict": cpu_state_dict(components.attribute_encoder),
        "fusion_state_dict": cpu_state_dict(components.fusion_layer),
        "metadata": metadata_payload,
    }
    torch.save(checkpoint, output_path)
    shutil.copyfile(output_path, output_path.with_suffix(output_path.suffix + ".bak"))
    write_mefkt_metadata(metadata_path, metadata_payload)
