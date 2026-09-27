#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT-NG 因果、数据边界和完整留存的无训练回归检查。
@Project : adaptive-edu
@File : test_mefkt_ng.py
@Author : Qintsg
@Date : 2026-09-24
'''

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch

from mefkt_ng.artifacts import DurableJsonl, save_checkpoint
from mefkt_ng.data import PreparedData, WindowDataset, _split_user, collate_windows, prepare_data
from mefkt_ng.metrics import summarize_predictions
from mefkt_ng.model import MEFKTNG, ModelConfig
from mefkt_ng.training_loop import _resume, _rng_path
from mefkt_ng.training_runtime import Context, capture_rng, configure_torch_cache, load_initial_checkpoint, prepare_run_directory


class MEFKTNGModelTests(unittest.TestCase):
    """在 CPU 只执行前向，不进行参数优化。"""

    def setUp(self) -> None:
        """建立两道题、两个知识点的确定性模型。

        :returns: None。
        """
        torch.manual_seed(31)
        content = torch.zeros((2, 384))
        content[0, 0] = 1.0
        content[1, 1] = 1.0
        self.model = MEFKTNG(
            content, torch.tensor([[0], [1]]), torch.zeros((2, 2)), content,
            torch.empty((0, 3), dtype=torch.long),
            ModelConfig(hidden_dim=32, graph_layers=0, dropout=0.0),
        ).eval()

    @staticmethod
    def _batch(items: list[int], correct: list[int], episodes: list[int], gaps: list[float] | None = None) -> dict[str, torch.Tensor]:
        """生成有效作答 batch。

        :param items: 题目序列。
        :param correct: 二元结果序列。
        :param episodes: 测验场次。
        :param gaps: 小时间隔。
        :returns: 模型输入字典。
        """
        length = len(items)
        return {"items": torch.tensor([items]), "correct": torch.tensor([correct], dtype=torch.float32),
                "episodes": torch.tensor([episodes]), "gaps": torch.tensor([gaps or [0.0] * length]),
                "time_known": torch.ones((1, length), dtype=torch.bool),
                "valid": torch.ones((1, length), dtype=torch.bool)}

    def test_current_answer_never_changes_its_own_prediction(self) -> None:
        """当前位置答案只能影响后续不同场次。

        :returns: None。
        """
        first = self._batch([0, 0], [1, 0], [1, 2])
        changed = self._batch([0, 0], [0, 0], [1, 2])
        with torch.no_grad():
            original, _ = self.model(first)
            modified, _ = self.model(changed)
        self.assertEqual(float(original[0, 0]), float(modified[0, 0]))
        self.assertNotEqual(float(original[0, 1]), float(modified[0, 1]))

    def test_same_episode_cannot_see_other_answers(self) -> None:
        """同场题目共享考前状态。

        :returns: None。
        """
        with torch.no_grad():
            original, _ = self.model(self._batch([0, 0, 0], [1, 0, 0], [1, 1, 2]))
            modified, _ = self.model(self._batch([0, 0, 0], [0, 0, 0], [1, 1, 2]))
        self.assertEqual(float(original[0, 1]), float(modified[0, 1]))
        self.assertNotEqual(float(original[0, 2]), float(modified[0, 2]))

    def test_same_episode_uses_one_pre_exam_time(self) -> None:
        """一场试卷跨越时间时，所有题仍读取考前状态。

        :returns: None。
        """
        with torch.no_grad():
            immediate, _ = self.model(self._batch([0, 0], [0, 0], [1, 1], [0.0, 0.0]))
            separated, _ = self.model(self._batch([0, 0], [0, 0], [1, 1], [0.0, 24.0]))
        self.assertEqual(float(immediate[0, 1]), float(separated[0, 1]))

    def test_other_skill_does_not_receive_direct_update(self) -> None:
        """题目 A 的标签不改变独立知识点 B 的下一题预测。

        :returns: None。
        """
        with torch.no_grad():
            original, _ = self.model(self._batch([0, 1], [1, 0], [1, 2]))
            modified, _ = self.model(self._batch([0, 1], [0, 0], [1, 2]))
        self.assertEqual(float(original[0, 1]), float(modified[0, 1]))

    def test_time_without_new_learning_cannot_improve_recall(self) -> None:
        """只增加等待时间不能提高同题预测。

        :returns: None。
        """
        with torch.no_grad():
            immediate, _ = self.model(self._batch([0, 0], [1, 0], [1, 2], [0.0, 0.0]))
            delayed, _ = self.model(self._batch([0, 0], [1, 0], [1, 2], [0.0, 72.0]))
        self.assertLessEqual(float(delayed[0, 1]), float(immediate[0, 1]))

    def test_synthetic_loss_has_finite_gradients_without_optimizer_step(self) -> None:
        """合成数据上仅检查反向图连通性，不更新模型参数。

        :returns: None。
        """
        self.model.train()
        batch = self._batch([0, 1, 0], [1, 0, 1], [1, 2, 3], [0.0, 24.0, 24.0])
        logits, mask = self.model(batch)
        loss = torch.nn.functional.binary_cross_entropy_with_logits(logits[mask], batch["correct"][mask])
        loss.backward()
        gradients = [parameter.grad for parameter in self.model.parameters() if parameter.grad is not None]
        self.assertTrue(gradients)
        self.assertTrue(all(bool(torch.isfinite(value).all()) for value in gradients))

    def test_typed_graph_encoder_runs_without_future_events(self) -> None:
        """带方向的先修边可进入内容编码与当前题预测。

        :returns: None。
        """
        content = torch.zeros((2, 384))
        content[0, 0], content[1, 1] = 1.0, 1.0
        model = MEFKTNG(content, torch.tensor([[0], [1]]), torch.zeros((2, 2)), content,
                        torch.tensor([[0, 1, 0]]), ModelConfig(hidden_dim=32, graph_layers=2, dropout=0.0)).eval()
        with torch.no_grad():
            logits, mask = model(self._batch([0, 1], [1, 0], [1, 2]))
        self.assertEqual(int(mask.sum()), 2)
        self.assertTrue(bool(torch.isfinite(logits[mask]).all()))


class MEFKTNGDataTests(unittest.TestCase):
    """检查真实事件窗口与评分边界。"""

    def test_context_targets_once_and_episode_not_split(self) -> None:
        """上下文不重复计分，同一测验不跨窗口。

        :returns: None。
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path, content_path, data_root = root / "events.csv", root / "content.npz", root / "prepared"
            users = {split: [] for split in ("train", "validation", "test")}
            for index in range(80):
                users[_split_user(f"student-{index}")].append(f"student-{index}")
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("user_id", "item_id", "timestamp", "correct", "skill_ids", "submission_id"))
                writer.writeheader()
                for selected in (users["train"][0], users["validation"][0], users["test"][0]):
                    for item in range(7):
                        writer.writerow({"user_id": selected, "item_id": f"item-{item % 2}",
                                         "timestamp": f"2026-01-01T00:{item:02d}:00+00:00", "correct": item % 2,
                                         "skill_ids": f"skill-{item % 2}", "submission_id": "exam" if item in (2, 3) else f"single-{item}"})
            vectors = np.zeros((2, 384), dtype=np.float32)
            vectors[0, 0], vectors[1, 1] = 1.0, 1.0
            np.savez_compressed(content_path, item_ids=np.asarray(("item-0", "item-1")),
                                embeddings=vectors, model_name=np.asarray("test-encoder"))
            graph_path = root / "relations.json"
            graph_path.write_text(json.dumps([{"from": "skill-0", "to": "skill-1", "type": "prerequisite"}]),
                                  encoding="utf-8")
            prepared = prepare_data(csv_path, content_path, data_root, length=4, context=1,
                                    graph_file=graph_path)
            self.assertEqual(prepared.manifest["graph_edges"], 1)
            self.assertEqual(prepared.manifest["splits"]["train"]["target_events"], 7)
            self.assertEqual(prepared.manifest["splits"]["validation"]["target_events"], 7)
            self.assertEqual(prepared.manifest["splits"]["test"]["target_events"], 7)
            for split in ("train", "validation", "test"):
                with WindowDataset(prepared.root, split) as dataset:
                    counted: list[int] = []
                    for index in range(len(dataset)):
                        batch = collate_windows([index], dataset)
                        counted.extend(batch["source_rows"][batch["target"]].tolist())
                    self.assertEqual(len(counted), len(set(counted)))

    def test_ungraded_is_not_treated_as_incorrect(self) -> None:
        """缺失标签不得变成 0。

        :returns: None。
        """
        from mefkt_ng.data import _parse_correct

        self.assertIsNone(_parse_correct({"correct": "", "user_answer": ""}))
        self.assertEqual(_parse_correct({"correct": "0"}), 0)


class MEFKTNGArtifactTests(unittest.TestCase):
    """检查下游可重分析的指标和只追加产物。"""

    def test_initial_checkpoint_transfers_parameters_only(self) -> None:
        """扩充课程目录后保留新缓冲区，迁移旧 run 的共享参数。

        :returns: None。
        """
        old_content = torch.zeros((1, 384))
        old_content[0, 0] = 1.0
        new_content = torch.zeros((2, 384))
        new_content[:, 1] = 1.0
        config = ModelConfig(hidden_dim=32, graph_layers=0)
        old = MEFKTNG(old_content, torch.tensor([[0]]), torch.zeros((1, 2)), old_content,
                      torch.empty((0, 3), dtype=torch.long), config)
        new = MEFKTNG(new_content, torch.tensor([[0], [1]]), torch.zeros((2, 2)), new_content,
                      torch.empty((0, 3), dtype=torch.long), config)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "old.pt"
            save_checkpoint(source, {"schema": "mefkt-ng-checkpoint-v1", "run_id": "old",
                                     "epoch": 9, "data_sha256": "old-data", "model_state": old.state_dict()})
            lineage = load_initial_checkpoint(new, source)
            self.assertEqual(lineage["run_id"], "old")
            self.assertEqual(lineage["epoch"], 9)
            self.assertTrue(torch.equal(new.item_content, new_content))
            for name, value in new.named_parameters():
                self.assertTrue(torch.equal(value, dict(old.named_parameters())[name]))

    def test_metrics_and_append_only_checkpoint(self) -> None:
        """AUC 单类明确为空，checkpoint 不覆盖旧轮次。

        :returns: None。
        """
        perfect = summarize_predictions(np.asarray((-2.0, 2.0)), np.asarray((0, 1)))
        self.assertEqual(perfect["auc"], 1.0)
        self.assertIsNone(summarize_predictions(np.asarray((1.0, 2.0)), np.asarray((1, 1)))["auc"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with DurableJsonl(root / "steps.jsonl") as writer:
                writer.append({"step": 1, "loss": 0.7})
                writer.append({"step": 2, "loss": 0.6})
            records = [json.loads(line) for line in (root / "steps.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["step"] for row in records], [1, 2])
            checkpoint = root / "checkpoints" / "epoch_0001.pt"
            save_checkpoint(checkpoint, {"weight": torch.ones(1)})
            with self.assertRaises(FileExistsError):
                save_checkpoint(checkpoint, {"weight": torch.zeros(1)})

    def test_prelaunch_manifest_and_log_do_not_block_first_run(self) -> None:
        """Pod 预先归档 Job 清单与打开日志后仍能建立新运行。

        :returns: None。
        """
        content = torch.zeros((1, 384))
        content[0, 0] = 1.0
        model = MEFKTNG(content, torch.tensor([[0]]), torch.zeros((1, 2)), content,
                        torch.empty((0, 3), dtype=torch.long), ModelConfig(hidden_dim=32, graph_layers=0))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            (output / "logs").mkdir(parents=True)
            (output / "logs" / "rank-0.log").write_text("Pod 已启动\n", encoding="utf-8")
            (output / "job_manifest_preview.yaml").write_text("kind: Job\n", encoding="utf-8")
            args = argparse.Namespace(output_dir=str(output), resume=False, epochs=1)
            data = PreparedData(Path(directory), {"source_sha256": "test-source", "content_sha256": "test-content",
                                                   "graph_sha256": ""})
            result = prepare_run_directory(args, Context(0, 0, 1, torch.device("cpu")), data, model)
            self.assertEqual(result["data_sha256"], "test-source")
            self.assertTrue((output / "run_config.json").is_file())

    def test_resume_repairs_missing_epoch_metric_without_retraining(self) -> None:
        """完整 checkpoint 存在但末轮 JSONL 缺失时能恢复记录。

        :returns: None。
        """
        content = torch.zeros((1, 384))
        content[0, 0] = 1.0
        model = MEFKTNG(content, torch.tensor([[0]]), torch.zeros((1, 2)), content,
                        torch.empty((0, 3), dtype=torch.long), ModelConfig(hidden_dim=32, graph_layers=0))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ):
                configure_torch_cache(root, 0)
                optimizer = torch.optim.AdamW(model.parameters(), lr=0.0001)
                scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer)
                segment = "synthetic-segment"
                save_checkpoint(_rng_path(root, 1, 0, segment), {"rng": capture_rng()})
                checkpoint = root / "checkpoints" / f"epoch_0001_{segment}.pt"
                save_checkpoint(checkpoint, {
                    "run_id": "synthetic", "data_sha256": "synthetic-data", "epoch": 1,
                    "segment_id": segment, "global_step": 0, "model_state": model.state_dict(),
                    "optimizer_state": optimizer.state_dict(), "scheduler_state": scheduler.state_dict(),
                    "best_nll": 0.6, "best_auc": None, "stale": 0,
                    "epoch_metrics": {"epoch": 1, "train": {"overall": {"nll": 0.7}},
                                      "validation": {"overall": {"nll": 0.6}}},
                })
                result = _resume(root, model, optimizer, scheduler,
                                 Context(0, 0, 1, torch.device("cpu")),
                                 {"run_id": "synthetic", "data_sha256": "synthetic-data"},
                                 root / "epoch_metrics.jsonl")
                self.assertEqual(result[:2], (1, 0))
                self.assertIsNone(result[3])
                self.assertEqual(len((root / "epoch_metrics.jsonl").read_text(encoding="utf-8").splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
