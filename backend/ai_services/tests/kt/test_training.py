#!/user/bin/env python
# -*- coding: UTF-8 -*-
"""
MEFKT 训练链路回归测试。
@Project : adaptive-edu
@File : test_training.py
@Author : Qintsg
@Date : 2026-06-07 19:45
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

import torch
from django.test import SimpleTestCase

from ai_services.services.mefkt.runtime import CourseQuestionRuntimeBundle
from models.MEFKT.model import NODE_FEATURE_SCHEMA, RELATION_STAT_SCHEMA
from tools.mefkt.public_data import MEFKTTrainingBundle, SequenceRecord
from tools.mefkt.training_support import MEFKTTrainingConfig


def _sequence(index: int) -> SequenceRecord:
    """
    构造短序列样本。

    :param index: 样本序号。
    :return: MEFKT 训练序列。
    """
    first_item = index % 3
    second_item = (index + 1) % 3
    return ([first_item, second_item], [index % 2, (index + 1) % 2], [1.0, 2.0])


def _training_bundle(
    *,
    sequences: list[SequenceRecord] | None = None,
    validation_sequences: list[SequenceRecord] | None = None,
    test_sequences: list[SequenceRecord] | None = None,
    dataset_name: str = "assist2017",
) -> MEFKTTrainingBundle:
    """
    构造最小 MEFKT 训练包。

    :param sequences: 训练序列。
    :param validation_sequences: 验证序列。
    :param test_sequences: 测试序列。
    :param dataset_name: 数据集名称。
    :return: 可用于训练辅助函数的 bundle。
    """
    item_count = 3
    return MEFKTTrainingBundle(
        dataset_name=dataset_name,
        item_ids=[101, 102, 103],
        item_names=["题目A", "题目B", "题目C"],
        type_mapping={"single_choice": 0},
        sequences=sequences if sequences is not None else [_sequence(index) for index in range(6)],
        validation_sequences=validation_sequences
        if validation_sequences is not None
        else [_sequence(index) for index in range(6, 8)],
        test_sequences=test_sequences if test_sequences is not None else [_sequence(8)],
        node_feature_matrix=torch.zeros((item_count, len(NODE_FEATURE_SCHEMA)), dtype=torch.float32),
        relation_stats_matrix=torch.zeros((item_count, len(RELATION_STAT_SCHEMA)), dtype=torch.float32),
        adjacency_matrix=torch.eye(item_count, dtype=torch.float32),
        difficulty_vector=torch.zeros(item_count, dtype=torch.float32),
        response_time_vector=torch.ones(item_count, dtype=torch.float32),
        exercise_type_vector=torch.zeros(item_count, dtype=torch.long),
        training_mode="public_pretrain_question_online",
        training_sources=["unit-test"],
        split_policy={"strategy": "unit"},
        graph_source="unit_graph",
        feature_coverage={"real_response_time_ratio": 0.0},
        paper_reproduction_notes=["unit"],
    )


def _training_config(**overrides: Any) -> MEFKTTrainingConfig:
    """
    构造小规模 MEFKT 训练配置。

    :param overrides: 需要覆盖的配置字段。
    :return: 训练配置。
    """
    payload = {
        "epochs": 4,
        "pretrain_epochs": 1,
        "batch_size": 2,
        "lr": 0.01,
        "hidden_dim": 4,
        "align_dim": 4,
        "similarity_weight": 0.5,
        "num_heads": 1,
        "head_dim": 2,
        "use_gpu": False,
        "seed": 7,
        "early_stopping_patience": 1,
        "lr_decay": 0.5,
        "profile": "smoke",
    }
    payload.update(overrides)
    return MEFKTTrainingConfig(**payload)


class MEFKTTrainingSupportTests(SimpleTestCase):
    """覆盖 MEFKT 训练支撑函数。"""

    def test_sequence_predictor_should_record_history_early_stop_and_test_metrics(self) -> None:
        """
        序列训练应记录验证历史、学习率衰减、早停并输出测试集指标。
        """
        from tools.mefkt.training_support import train_sequence_predictor

        bundle = _training_bundle()
        ready_embedding = torch.full((3, 4), 0.25, dtype=torch.float32)

        def fake_sequence_epoch(
            *,
            sequence_model: torch.nn.Module,
            sequence_optimizer: torch.optim.Optimizer,
            train_sequences: list[SequenceRecord],
            batch_size: int,
            device: torch.device,
        ) -> float:
            """
            模拟一次序列训练，保留 optimizer step 以匹配真实调度器调用顺序。

            :param sequence_model: 序列模型。
            :param sequence_optimizer: 序列模型优化器。
            :param train_sequences: 训练序列。
            :param batch_size: 批大小。
            :param device: 训练设备。
            :return: 固定 loss。
            """
            _ = (sequence_model, train_sequences, batch_size, device)
            sequence_optimizer.zero_grad()
            sequence_optimizer.step()
            return 0.123

        with (
            patch("tools.mefkt.training_support.run_sequence_epoch", side_effect=fake_sequence_epoch) as epoch_runner,
            patch(
                "tools.mefkt.training_support._evaluate_sequence_model",
                side_effect=[
                    {"auc": 0.8, "acc": 0.7, "samples": 4.0},
                    {"auc": 0.6, "acc": 0.5, "samples": 4.0},
                    {"auc": 0.55, "acc": 0.5, "samples": 1.0},
                ],
            ) as evaluator,
        ):
            result = train_sequence_predictor(
                bundle=bundle,
                ready_embedding=ready_embedding,
                device=torch.device("cpu"),
                config=_training_config(),
            )

        self.assertEqual(epoch_runner.call_count, 2)
        self.assertEqual(evaluator.call_count, 3)
        self.assertEqual(result.best_metrics["auc"], 0.8)
        self.assertEqual(result.test_metrics["auc"], 0.55)
        self.assertEqual(len(result.training_history), 2)
        self.assertEqual(result.training_history[0]["epoch"], 1.0)
        self.assertAlmostEqual(result.training_history[0]["lr"], 0.01)
        self.assertAlmostEqual(result.training_history[1]["lr"], 0.005)
        self.assertEqual(result.training_history[1]["val_auc"], 0.6)

    def test_metadata_should_include_training_quality_and_output_backup_fields(self) -> None:
        """
        训练元数据应携带新增训练质量、切分策略、测试指标和备份路径字段。
        """
        from tools.mefkt.training_support import (
            MEFKTModelComponents,
            MEFKTSequenceTrainingResult,
            build_mefkt_metadata,
        )

        class RuntimeDevice:
            """提供训练设备标签的轻量对象。"""

            label = "cpu"
            reason = "unit"

        graph_encoder = torch.nn.Linear(2, 2)
        attribute_encoder = torch.nn.Linear(2, 2)
        fusion_layer = torch.nn.Linear(2, 2)
        components = MEFKTModelComponents(
            runtime_device=RuntimeDevice(),
            device=torch.device("cpu"),
            graph_encoder=graph_encoder,
            attribute_encoder=attribute_encoder,
            fusion_layer=fusion_layer,
            feature_dim=len(NODE_FEATURE_SCHEMA),
            relation_dim=len(RELATION_STAT_SCHEMA),
        )
        sequence_result = MEFKTSequenceTrainingResult(
            best_metrics={"auc": 0.8, "acc": 0.7, "samples": 4.0},
            best_sequence_state={},
            test_metrics={"auc": 0.6, "acc": 0.5, "samples": 2.0},
            training_history=[{"epoch": 1.0, "loss": 0.1, "val_auc": 0.8, "lr": 0.01}],
        )

        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "mefkt_unit.pt"
            metadata = build_mefkt_metadata(
                bundle=_training_bundle(dataset_name="course_1"),
                output_path=output_path,
                components=components,
                fused_embedding=torch.zeros((3, 8), dtype=torch.float32),
                sequence_result=sequence_result,
                config=_training_config(profile="course-finetune"),
            )

        self.assertEqual(metadata["seed"], 7)
        self.assertEqual(metadata["early_stopping_patience"], 1)
        self.assertEqual(metadata["lr_decay"], 0.5)
        self.assertEqual(metadata["training_profile"], "course-finetune")
        self.assertEqual(metadata["split_policy"], {"strategy": "unit"})
        self.assertEqual(metadata["graph_source"], "unit_graph")
        self.assertEqual(metadata["test_metrics"], {"auc": 0.6, "acc": 0.5, "samples": 2.0})
        self.assertEqual(metadata["training_history"], sequence_result.training_history)
        self.assertTrue(str(metadata["backup_path"]).endswith("mefkt_unit.pt.bak"))

    def test_checkpoint_save_should_create_identical_backup(self) -> None:
        """
        保存 MEFKT checkpoint 时应同步生成内容完全一致的 .pt.bak。
        """
        import json

        from models.MEFKT.model import (
            GraphContrastiveEncoder,
            LinearAlignmentFusion,
            MultiAttributeEncoder,
        )
        from tools.mefkt.training_support import save_mefkt_checkpoint

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            model_path = temp_path / "model.pt"
            meta_path = temp_path / "model.meta.json"
            graph_encoder = GraphContrastiveEncoder(4, 4, 4)
            attribute_encoder = MultiAttributeEncoder(4, 1, 4, relation_dim=4)
            fusion_layer = LinearAlignmentFusion(4, 4, 4)
            metadata = {"model_name": "MEFKT", "runtime_schema": "question_online_v1"}

            save_mefkt_checkpoint(
                output_path=model_path,
                metadata_path=meta_path,
                metadata_payload=metadata,
                sequence_state={},
                components=type(
                    "Components",
                    (),
                    {
                        "graph_encoder": graph_encoder,
                        "attribute_encoder": attribute_encoder,
                        "fusion_layer": fusion_layer,
                    },
                )(),
            )

            self.assertTrue(model_path.exists())
            self.assertTrue(model_path.with_suffix(".pt.bak").exists())
            self.assertEqual(
                model_path.read_bytes(),
                model_path.with_suffix(".pt.bak").read_bytes(),
            )
            self.assertEqual(json.loads(meta_path.read_text(encoding="utf-8")), metadata)


class MEFKTTrainingBundleTests(SimpleTestCase):
    """覆盖公开训练包裁剪和课程微调训练包。"""

    def test_public_loader_should_accept_three_line_csv_suffix(self) -> None:
        """
        公开数据文件即使带 csv 后缀，也应兼容三行序列格式。
        """
        from tools.mefkt.public_data import load_public_sequences

        with TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "builder_train.csv"
            data_path.write_text("3\n1,2,3\n1,0,1\n", encoding="utf-8")

            self.assertEqual(load_public_sequences(data_path), [([1, 2, 3], [1, 0, 1])])

    def test_public_bundle_should_carry_validation_test_and_quality_metadata(self) -> None:
        """
        公开训练包应携带验证/测试切分和特征质量说明。
        """
        from tools.mefkt.public_data import build_public_bundle

        bundle = build_public_bundle(
            "assist2017",
            sequence_max_step=64,
            validation_ratio=0.2,
            seed=42,
        )

        self.assertTrue(bundle.sequences)
        self.assertTrue(bundle.validation_sequences)
        self.assertTrue(bundle.test_sequences)
        self.assertIn("graph_source", bundle.__dataclass_fields__)
        self.assertEqual(bundle.feature_coverage["response_time_source"], "revisit_distance_proxy")
        self.assertIn("test_sequences", bundle.split_policy)

    def test_public_training_bundle_trim_should_preserve_validation_test_metadata(self) -> None:
        """
        max_sequences 裁剪公开数据时应同步裁剪验证/测试集并记录质量说明。
        """
        from tools.mefkt_training import build_training_bundle

        source_bundle = _training_bundle(
            sequences=[_sequence(index) for index in range(10)],
            validation_sequences=[_sequence(index) for index in range(10, 14)],
            test_sequences=[_sequence(index) for index in range(14, 17)],
        )

        with patch("tools.mefkt_training._build_public_bundle", return_value=source_bundle):
            bundle = build_training_bundle(
                dataset_name="assist2017",
                sequence_max_step=64,
                max_sequences=5,
                validation_ratio=0.3,
                seed=9,
            )

        self.assertEqual(len(bundle.sequences), 5)
        self.assertEqual(len(bundle.validation_sequences), 1)
        self.assertEqual(len(bundle.test_sequences), 1)
        self.assertEqual(bundle.split_policy["max_sequences"], 5)
        self.assertEqual(bundle.split_policy["validation_sequences"], 1)
        self.assertIn("max_sequences=5", bundle.training_sources)
        self.assertIn("smoke/快速验证", bundle.paper_reproduction_notes[-1])

    def test_course_bundle_should_use_runtime_graph_and_real_history_features(self) -> None:
        """
        课程微调训练包应使用课程题图、答题历史切分和真实特征覆盖说明。
        """
        from tools.mefkt.course_data import build_course_bundle

        item_count = 3
        runtime_bundle = CourseQuestionRuntimeBundle(
            question_ids=[201, 202, 203],
            question_id_to_index={201: 0, 202: 1, 203: 2},
            question_to_points={201: [301], 202: [302], 203: [303]},
            point_to_question_indices={301: [0], 302: [1], 303: [2]},
            representative_question_index={301: 0, 302: 1, 303: 2},
            node_feature_matrix=torch.ones((item_count, len(NODE_FEATURE_SCHEMA)), dtype=torch.float32),
            relation_stats_matrix=torch.ones((item_count, len(RELATION_STAT_SCHEMA)), dtype=torch.float32),
            adjacency_matrix=torch.eye(item_count, dtype=torch.float32),
            difficulty_vector=torch.tensor([0.2, 0.4, 0.6], dtype=torch.float32),
            response_time_vector=torch.tensor([0.1, 0.2, 0.3], dtype=torch.float32),
            exercise_type_vector=torch.tensor([0, 1, 1], dtype=torch.long),
        )
        course_sequences = [_sequence(index) for index in range(5)]

        with (
            patch("tools.mefkt.course_data.build_course_runtime_bundle", return_value=runtime_bundle),
            patch("tools.mefkt.course_data.load_course_sequences", return_value=course_sequences),
        ):
            bundle = build_course_bundle(course_id=88, validation_ratio=0.4, seed=3)

        self.assertEqual(bundle.dataset_name, "course_88")
        self.assertEqual(bundle.item_ids, [201, 202, 203])
        self.assertEqual(bundle.training_mode, "course_question_finetune")
        self.assertEqual(len(bundle.sequences), 3)
        self.assertEqual(len(bundle.validation_sequences), 2)
        self.assertEqual(bundle.test_sequences, bundle.validation_sequences)
        self.assertEqual(bundle.graph_source, "course_question_knowledge_resource_graph")
        self.assertEqual(bundle.feature_coverage["real_response_time_ratio"], 1.0)
        self.assertEqual(bundle.feature_coverage["sequence_count"], 5)
        self.assertEqual(bundle.split_policy["strategy"], "course_user_sequence_train_validation")

    def test_course_finetune_profile_should_require_course_id(self) -> None:
        """
        course-finetune 训练画像缺少 course_id 时应直接报错，避免误跑公开数据。
        """
        from tools.mefkt_training import train_mefkt_v2

        with self.assertRaisesMessage(ValueError, "course-finetune 训练需要传入 course_id"):
            train_mefkt_v2(profile="course-finetune", epochs=1, pretrain_epochs=1)
