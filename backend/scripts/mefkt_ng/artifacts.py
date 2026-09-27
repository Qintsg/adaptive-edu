#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT-NG 训练全程指标和 checkpoint 的只追加持久化。
@Project : adaptive-edu
@File : artifacts.py
@Author : Qintsg
@Date : 2026-09-24
'''

from __future__ import annotations

import csv
import json
import os
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch

from mefkt_ng.data import sha256_file


def utc_now() -> str:
    """返回可审计的 UTC 时间。

    :returns: ISO-8601 时间。
    """
    return datetime.now(UTC).isoformat()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """原子替换小型状态索引或运行配置。

    :param path: 输出文件。
    :param payload: JSON 内容。
    :returns: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class DurableJsonl:
    """每次追加后刷新磁盘的训练轨迹写入器。"""

    def __init__(self, path: Path) -> None:
        """打开只追加 JSONL 文件。

        :param path: 记录路径。
        :returns: None。
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("a", encoding="utf-8", newline="\n")

    def append(self, payload: dict[str, Any]) -> None:
        """写入并同步一条完整记录。

        :param payload: 可 JSON 序列化记录。
        :returns: None。
        """
        self._handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def close(self) -> None:
        """关闭记录文件。

        :returns: None。
        """
        self._handle.close()

    def __enter__(self) -> DurableJsonl:
        """进入上下文。

        :returns: 写入器自身。
        """
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        """离开上下文并关闭文件。

        :param _type: 异常类型。
        :param _value: 异常对象。
        :param _traceback: 异常栈。
        :returns: None。
        """
        self.close()


def save_checkpoint(path: Path, payload: dict[str, Any]) -> str:
    """永久保留一个 epoch 的完整可恢复 checkpoint。

    :param path: 唯一 epoch 文件名。
    :param payload: 权重、优化器、调度器、随机数状态和指标。
    :returns: checkpoint SHA-256。
    :raises FileExistsError: 已存在同名产物。
    """
    if path.exists():
        raise FileExistsError(f"不能覆盖已有 checkpoint: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        torch.save(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return sha256_file(path)


def snapshot_source(output_dir: Path, script_dir: Path) -> dict[str, object]:
    """保存本次训练使用的脚本副本和逐文件摘要。

    :param output_dir: 运行输出目录。
    :param script_dir: backend/scripts 目录。
    :returns: ZIP 文件及其 SHA-256。
    """
    archive_path = output_dir / "training_source.zip"
    if archive_path.exists():
        raise FileExistsError(f"代码快照已存在: {archive_path}")
    paths = [script_dir / "mefkt_ng_train.py", *sorted((script_dir / "mefkt_ng").glob("*.py"))]
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, arcname=path.relative_to(script_dir).as_posix())
    return {"file": archive_path.name, "sha256": sha256_file(archive_path),
            "modules": {path.relative_to(script_dir).as_posix(): sha256_file(path) for path in paths}}


def write_epoch_csv(epoch_file: Path, csv_file: Path) -> None:
    """从权威 JSONL 重建便于表格处理的逐轮 CSV。

    :param epoch_file: 只追加逐轮指标。
    :param csv_file: 目标 CSV。
    :returns: None。
    """
    rows: list[dict[str, Any]] = []
    with epoch_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                entry = json.loads(line)
                row: dict[str, Any] = {key: entry.get(key) for key in
                                       ("epoch", "segment_id", "recorded_at_utc", "learning_rate", "next_learning_rate",
                                        "optimizer_steps", "train_stream_loss", "elapsed_seconds", "checkpoint_sha256")}
                for split in ("train", "validation"):
                    for name, value in entry.get(split, {}).get("overall", {}).items():
                        row[f"{split}_{name}"] = value
                rows.append(row)
    if not rows:
        return
    temporary = csv_file.with_name(csv_file.name + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, csv_file)


def check_disk_budget(output_dir: Path, estimated_checkpoint_bytes: int, epochs: int) -> dict[str, int]:
    """检查每轮留存是否有基本磁盘空间。

    :param output_dir: 运行目录。
    :param estimated_checkpoint_bytes: 首个 checkpoint 近似大小。
    :param epochs: 计划轮数。
    :returns: 估计与可用磁盘字节数。
    :raises RuntimeError: 当前空闲空间明显不足。
    """
    usage = shutil.disk_usage(output_dir)
    estimate = int(estimated_checkpoint_bytes * epochs * 1.25)
    if usage.free < estimate:
        raise RuntimeError(f"全部 epoch checkpoint 预计至少需要 {estimate} 字节，当前空闲 {usage.free} 字节")
    return {"estimated_all_checkpoints_bytes": estimate, "free_bytes_at_start": usage.free}
