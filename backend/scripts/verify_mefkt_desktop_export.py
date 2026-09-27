#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
删除远端 MEFKT PVC 前核验桌面过程数据、输入和纯模型权重。
@Project : adaptive-edu
@File : verify_mefkt_desktop_export.py
@Author : Qintsg
@Date : 2026-09-24
'''

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from load_mefkt_ng_bundle import load_bundle, smoke_predict


EXPECTED_ARCHIVES = {
    "two_source_process.tar": "194bf947e445a7af75b66f571e0482150da3e148fc8d7d5d81dbdbf45b2302ac",
    "four_source_process.tar": "46271eca7a1eb07a7da9987424aa186302ee01522e54c44be981c28d4a7b3b33",
    "prepared.tar": "efdc8a703f3c32c923adf863fe7cf242209b3e029e4132d78bb19340d850a8e4",
    "inputs.tar": "1e8fa8ae57cb355a13a58aa25a9202a136d8310bf72c7b14f00e281616b1a39f",
    "code.tar": "930ec4116619c1f0fdd9c8da8c564f2cb368263b7cf64646d9b9e5a869e4e91f",
}


def sha256_file(path: Path) -> str:
    """流式计算文件摘要。

    :param path: 待核验文件。
    :returns: SHA-256 十六进制值。
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_process_files(root: Path) -> dict[str, Any]:
    """核验五份归档和全部展开文件。

    :param root: 桌面归档根目录。
    :returns: 文件数和字节数。
    :raises ValueError: 任一摘要、大小或 checkpoint 排除条件不符。
    """
    process = root / "process_data"
    manifest = json.loads((process / "file_manifest.json").read_text(encoding="utf-8"))
    if set(manifest["archives"]) != set(EXPECTED_ARCHIVES):
        raise ValueError("过程归档集合不完整")
    total_files = total_bytes = 0
    for name, expected in EXPECTED_ARCHIVES.items():
        archive = root / "transfer" / name
        record = manifest["archives"][name]
        if sha256_file(archive) != expected or record["sha256"] != expected:
            raise ValueError(f"归档摘要不一致：{name}")
        target = process / record["target"]
        if len(record["file_hashes"]) != record["files"]:
            raise ValueError(f"归档文件计数不一致：{name}")
        for file_record in record["file_hashes"]:
            file_path = target / file_record["path"]
            if not file_path.is_file() or file_path.stat().st_size != file_record["bytes"]:
                raise ValueError(f"展开文件缺失或大小不符：{file_path}")
            if sha256_file(file_path) != file_record["sha256"]:
                raise ValueError(f"展开文件 SHA-256 不符：{file_path}")
        total_files += record["files"]
        total_bytes += record["bytes"]
    if any(path.suffix == ".pt" or any(part in {"checkpoints", "rng", "torch_cache"}
                                        for part in path.parts)
           for path in (process / "runs").rglob("*")):
        raise ValueError("过程数据意外包含逐轮 checkpoint、RNG 或缓存")
    return {"archives": len(EXPECTED_ARCHIVES), "files": total_files, "bytes": total_bytes}


def verify_runs(root: Path) -> dict[str, Any]:
    """核验两次运行的指标、预测及冻结输入。

    :param root: 桌面归档根目录。
    :returns: 两个运行的产物计数。
    :raises ValueError: 轮次或输入摘要不匹配。
    """
    process = root / "process_data"
    checks: dict[str, Any] = {}
    for run_id, epochs, expected_predictions in (
        ("mefkt-ng-20260924-g4", 153, 1),
        ("mefkt-ng-20260924-4src-g4", 156, 2),
    ):
        run = process / "runs" / run_id
        config = json.loads((run / "run_config.json").read_text(encoding="utf-8"))
        rows = [json.loads(line) for line in (run / "epoch_metrics.jsonl").read_text(encoding="utf-8").splitlines()]
        if len(rows) != epochs or [row["epoch"] for row in rows] != list(range(1, epochs + 1)):
            raise ValueError(f"逐轮指标不连续：{run_id}")
        predictions = run / "predictions"
        validation_count = len(list(predictions.glob("validation_epoch_*.csv.gz")))
        test_count = len(list(predictions.glob("test_final_epoch_*.csv.gz")))
        if validation_count != epochs or test_count != expected_predictions:
            raise ValueError(f"预测文件不完整：{run_id}")
        inputs = process / "inputs" / "mefkt-ng-inputs" / run_id
        if sha256_file(inputs / "train.csv") != config["data_sha256"]:
            raise ValueError(f"训练 CSV 与运行配置不符：{run_id}")
        if sha256_file(inputs / "item_content_embeddings.npz") != config["content_sha256"]:
            raise ValueError(f"内容向量与运行配置不符：{run_id}")
        checks[run_id] = {"epochs": epochs, "validation_predictions": validation_count,
                          "test_predictions": test_count,
                          "step_logs": {path.name: sum(1 for _ in path.open(encoding="utf-8"))
                                        for path in sorted((run / "steps").glob("*.jsonl"))}}
    current = process / "runs" / "mefkt-ng-20260924-4src-g4"
    if not (current / "final_summary_epoch_0120.json").is_file() or not (current / "final_summary_epoch_0156.json").is_file():
        raise ValueError("四来源运行首段或续训摘要缺失")
    if not (process / "analysis" / "overfitting_report.md").is_file():
        raise ValueError("过拟合诊断报告缺失")
    with (process / "analysis" / "epoch_generalization.csv").open(encoding="utf-8", newline="") as handle:
        if len(list(csv.DictReader(handle))) != 156:
            raise ValueError("泛化曲线 CSV 不完整")
    return checks


def verify_model(root: Path) -> dict[str, Any]:
    """再次独立加载纯权重包并检查血缘。

    :param root: 桌面归档根目录。
    :returns: 权重和推理检查摘要。
    :raises ValueError: 模型或选定 checkpoint 血缘错误。
    """
    bundle = root / "model_bundle"
    model, catalog, metadata = load_bundle(bundle, "cpu")
    summary = json.loads((root / "process_data" / "runs" / "mefkt-ng-20260924-4src-g4" /
                          "final_summary_epoch_0156.json").read_text(encoding="utf-8"))
    if metadata["source_checkpoint_sha256"] != summary["best_checkpoint_sha256"]:
        raise ValueError("模型权重与最终选定 checkpoint 不对应")
    if metadata["selected_epoch"] != 136 or len(catalog["item_ids"]) != 28248:
        raise ValueError("选定模型或题目目录不符合预期")
    return {"selected_epoch": metadata["selected_epoch"], "weights_sha256": metadata["weights_sha256"],
            "trainable_parameters": sum(value.numel() for value in model.parameters()),
            "smoke": smoke_predict(model)}


def main() -> int:
    """生成 PVC 清理前的本地完整性证明。

    :returns: 进程退出码。
    """
    parser = argparse.ArgumentParser(description="验证 MEFKT 桌面归档是否可安全清理远端 PVC")
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    desktop = Path.home().joinpath("Desktop").resolve()
    if desktop not in root.parents:
        raise ValueError("归档必须位于桌面")
    result = {"schema": "mefkt-desktop-export-verification-v1",
              "verified_at_utc": datetime.now(UTC).isoformat(),
              "process": verify_process_files(root), "runs": verify_runs(root),
              "model": verify_model(root), "all_checks_passed": True}
    report = root / "verification_report.json"
    if report.exists():
        raise ValueError("已存在完整性报告，拒绝覆盖")
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")
    print(json.dumps({"all_checks_passed": True, "files": result["process"]["files"],
                      "model_sha256": result["model"]["weights_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
