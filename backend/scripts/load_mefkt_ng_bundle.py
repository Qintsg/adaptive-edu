#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
加载独立的 MEFKT-NG 权重包，并执行离线推理冒烟检查。
@Project : adaptive-edu
@File : load_mefkt_ng_bundle.py
@Author : Qintsg
@Date : 2026-09-24
'''

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import torch
from safetensors.torch import load_file


def sha256_file(path: Path) -> str:
    """计算文件摘要。

    :param path: 文件路径。
    :returns: SHA-256 十六进制值。
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_bundle(root: Path, device: str = "cpu") -> tuple[torch.nn.Module, dict[str, Any], dict[str, Any]]:
    """严格加载 MEFKT-NG 目录和参数。

    :param root: 含权重、元数据和冻结目录的模型包。
    :param device: PyTorch 设备。
    :returns: 推理模型、题目目录、模型元数据。
    :raises ValueError: 文件摘要或模型结构不一致。
    """
    root = root.resolve()
    metadata = json.loads((root / "model_metadata.json").read_text(encoding="utf-8"))
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    weights_path = root / "model.safetensors"
    if metadata.get("schema") != "mefkt-ng-inference-bundle-v1":
        raise ValueError("不是 MEFKT-NG 推理权重包")
    if sha256_file(weights_path) != metadata.get("weights_sha256"):
        raise ValueError("模型权重 SHA-256 与元数据不符")
    if sha256_file(root / "catalog.json") != metadata.get("catalog_sha256"):
        raise ValueError("题目目录 SHA-256 与元数据不符")
    runtime = root / "runtime"
    if str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))
    from mefkt_ng.model import MEFKTNG, ModelConfig

    state = load_file(str(weights_path), device="cpu")
    required = ("item_content", "item_skills", "item_difficulty", "skill_content", "graph_edges")
    if any(name not in state for name in required):
        raise ValueError("权重包缺少冻结课程目录")
    config = ModelConfig(**metadata["model_config"])
    model = MEFKTNG(*(state[name] for name in required), config)
    model.load_state_dict(state, strict=True)
    if len(catalog["item_ids"]) != int(model.item_content.shape[0]):
        raise ValueError("题目 ID 与模型目录长度不一致")
    if len(catalog["skill_ids"]) != int(model.skill_content.shape[0]):
        raise ValueError("知识点 ID 与模型目录长度不一致")
    model = model.to(torch.device(device)).eval()
    return model, catalog, metadata


def smoke_predict(model: torch.nn.Module) -> dict[str, float]:
    """用两条因果作答验证模型可以前向推理。

    :param model: 已加载的 MEFKT-NG 模型。
    :returns: 两个有限作答概率。
    :raises ValueError: 预测异常。
    """
    model_device = next(model.parameters()).device
    batch = {
        "items": torch.tensor([[0, 0]], device=model_device, dtype=torch.long),
        "correct": torch.tensor([[1.0, 0.0]], device=model_device),
        "gaps": torch.tensor([[0.0, 1.0]], device=model_device),
        "time_known": torch.tensor([[False, True]], device=model_device),
        "episodes": torch.tensor([[0, 1]], device=model_device, dtype=torch.long),
        "valid": torch.tensor([[True, True]], device=model_device),
    }
    with torch.inference_mode():
        logits, valid = model(batch)
        probabilities = torch.sigmoid(logits)[valid].cpu().tolist()
    if len(probabilities) != 2 or not all(math.isfinite(value) and 0.0 <= value <= 1.0
                                          for value in probabilities):
        raise ValueError("推理冒烟检查失败")
    return {"first_probability": probabilities[0], "second_probability": probabilities[1]}


def main() -> int:
    """执行命令行加载验证。

    :returns: 进程退出码。
    """
    parser = argparse.ArgumentParser(description="验证独立 MEFKT-NG 权重包")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    model, catalog, metadata = load_bundle(args.bundle, args.device)
    result = {"run_id": metadata["run_id"], "selected_epoch": metadata["selected_epoch"],
              "items": len(catalog["item_ids"]), "skills": len(catalog["skill_ids"]),
              "trainable_parameters": sum(value.numel() for value in model.parameters()),
              "smoke": smoke_predict(model)}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
