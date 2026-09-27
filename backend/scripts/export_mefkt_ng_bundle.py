#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
从选定 MEFKT-NG checkpoint 提取不含优化器/RNG 的可加载权重包。
@Project : adaptive-edu
@File : export_mefkt_ng_bundle.py
@Author : Qintsg
@Date : 2026-09-24
'''

from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch
from safetensors.torch import save_file

from load_mefkt_ng_bundle import load_bundle, sha256_file, smoke_predict


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """以 UTF-8/LF 写出归档 JSON。

    :param path: 输出路径。
    :param payload: 可序列化对象。
    :returns: None。
    """
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def export_bundle(
    checkpoint_path: Path, prepared_manifest_path: Path, final_summary_path: Path,
    run_config_path: Path, output: Path,
) -> dict[str, Any]:
    """严格核验血缘后导出纯推理模型包。

    :param checkpoint_path: 已验证的选定 epoch checkpoint 临时文件。
    :param prepared_manifest_path: 对应预处理数据 manifest。
    :param final_summary_path: 最终训练摘要。
    :param run_config_path: 原运行的冻结配置与源码摘要。
    :param output: 空的本地模型包目录。
    :returns: 导出校验结果。
    :raises ValueError: checkpoint、摘要或目录不一致。
    """
    checkpoint_path = checkpoint_path.resolve()
    prepared_manifest_path = prepared_manifest_path.resolve()
    final_summary_path = final_summary_path.resolve()
    run_config_path = run_config_path.resolve()
    output = output.resolve()
    if not output.is_dir() or any(output.iterdir()):
        raise ValueError("模型包输出目录必须存在且为空，拒绝覆盖现有模型")
    summary = json.loads(final_summary_path.read_text(encoding="utf-8"))
    run_config = json.loads(run_config_path.read_text(encoding="utf-8"))
    catalog_manifest = json.loads(prepared_manifest_path.read_text(encoding="utf-8"))
    checkpoint_hash = sha256_file(checkpoint_path)
    if checkpoint_hash != summary["best_checkpoint_sha256"]:
        raise ValueError("选定 checkpoint 与最终 summary SHA-256 不一致")
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    if checkpoint.get("schema") != "mefkt-ng-checkpoint-v1":
        raise ValueError("不是 MEFKT-NG checkpoint")
    if checkpoint["run_id"] != summary["run_id"] or checkpoint["data_sha256"] != summary["source_sha256"]:
        raise ValueError("checkpoint 与训练运行或输入数据不一致")
    if checkpoint["model_config"] != run_config["model_config"] or run_config["data_sha256"] != summary["source_sha256"]:
        raise ValueError("checkpoint、运行配置或输入数据不一致")
    if int(checkpoint["epoch"]) != int(summary["best_checkpoint"].split("/")[-1].split("_")[1]):
        raise ValueError("checkpoint epoch 与选定文件名不一致")
    state = checkpoint["model_state"]
    if not isinstance(state, dict) or not state or not all(isinstance(value, torch.Tensor) for value in state.values()):
        raise ValueError("checkpoint 缺少纯张量模型状态")
    tensors = {name: value.detach().cpu().contiguous() for name, value in state.items()}
    if any(not torch.isfinite(value).all() for value in tensors.values() if value.is_floating_point()):
        raise ValueError("checkpoint 存在非有限模型参数或目录")
    item_ids = catalog_manifest["item_ids"]
    skill_ids = catalog_manifest["skill_ids"]
    subject_ids = catalog_manifest["subject_ids"]
    if len(item_ids) != tensors["item_content"].shape[0] or len(skill_ids) != tensors["skill_content"].shape[0]:
        raise ValueError("预处理目录与 checkpoint 张量维度不一致")
    if catalog_manifest["source_sha256"] != summary["source_sha256"]:
        raise ValueError("预处理 manifest 的输入摘要不一致")

    catalog = {"schema": "mefkt-ng-catalog-v1", "item_ids": item_ids,
               "skill_ids": skill_ids, "subject_ids": subject_ids}
    catalog_path = output / "catalog.json"
    write_json(catalog_path, catalog)
    weights_path = output / "model.safetensors"
    save_file(tensors, str(weights_path))
    source_root = Path(__file__).resolve().parent
    for relative in ("mefkt_ng/__init__.py", "mefkt_ng/model.py"):
        if sha256_file(source_root / relative) != run_config["source_snapshot"]["modules"][relative]:
            raise ValueError(f"当前模型源码与训练快照不一致: {relative}")
    runtime_root = output / "runtime" / "mefkt_ng"
    runtime_root.mkdir(parents=True)
    shutil.copyfile(source_root / "mefkt_ng" / "__init__.py", runtime_root / "__init__.py")
    shutil.copyfile(source_root / "mefkt_ng" / "model.py", runtime_root / "model.py")
    shutil.copyfile(source_root / "load_mefkt_ng_bundle.py", output / "load_bundle.py")
    shutil.copyfile(final_summary_path, output / "evaluation_repeated_test.json")
    metadata = {
        "schema": "mefkt-ng-inference-bundle-v1",
        "run_id": summary["run_id"], "selected_epoch": int(checkpoint["epoch"]),
        "source_checkpoint_sha256": checkpoint_hash,
        "source_data_sha256": summary["source_sha256"],
        "source_content_sha256": catalog_manifest["content_sha256"],
        "weights_sha256": sha256_file(weights_path), "catalog_sha256": sha256_file(catalog_path),
        "model_config": checkpoint["model_config"],
        "items": len(item_ids), "skills": len(skill_ids), "subjects": subject_ids,
        "trainable_parameters": sum(value.numel() for name, value in tensors.items()
                                    if name not in {"item_content", "item_skills", "item_difficulty",
                                                    "skill_content", "graph_edges"}),
        "optimizer_and_rng_included": False,
        "compatible_with_legacy_mefkt_loader": False,
        "test_set_status": "already_evaluated_before_continuation",
        "exported_at_utc": datetime.now(UTC).isoformat(),
    }
    write_json(output / "model_metadata.json", metadata)
    model, loaded_catalog, loaded_metadata = load_bundle(output, "cpu")
    smoke = smoke_predict(model)
    result = {"schema": "mefkt-ng-export-validation-v1", "loaded_items": len(loaded_catalog["item_ids"]),
              "loaded_skills": len(loaded_catalog["skill_ids"]), "selected_epoch": loaded_metadata["selected_epoch"],
              "smoke": smoke, "weights_sha256": metadata["weights_sha256"]}
    write_json(output / "export_validation.json", result)
    return result


def main() -> int:
    """执行命令行模型导出。

    :returns: 进程退出码。
    """
    parser = argparse.ArgumentParser(description="导出 MEFKT-NG 纯推理模型权重包")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--prepared-manifest", type=Path, required=True)
    parser.add_argument("--final-summary", type=Path, required=True)
    parser.add_argument("--run-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = export_bundle(args.checkpoint, args.prepared_manifest, args.final_summary,
                           args.run_config, args.output)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
