#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
校验并安全展开 MEFKT 桌面训练归档，不接收 checkpoint 或 RNG。
@Project : adaptive-edu
@File : extract_mefkt_desktop_archive.py
@Author : Qintsg
@Date : 2026-09-24
'''

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


ARCHIVES = (
    ("two_source_process.tar", "194bf947e445a7af75b66f571e0482150da3e148fc8d7d5d81dbdbf45b2302ac",
     "runs/mefkt-ng-20260924-g4"),
    ("four_source_process.tar", "46271eca7a1eb07a7da9987424aa186302ee01522e54c44be981c28d4a7b3b33",
     "runs/mefkt-ng-20260924-4src-g4"),
    ("prepared.tar", "efdc8a703f3c32c923adf863fe7cf242209b3e029e4132d78bb19340d850a8e4", "prepared"),
    ("inputs.tar", "1e8fa8ae57cb355a13a58aa25a9202a136d8310bf72c7b14f00e281616b1a39f", "inputs"),
    ("code.tar", "930ec4116619c1f0fdd9c8da8c564f2cb368263b7cf64646d9b9e5a869e4e91f", "code"),
)


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


def extract_one(archive: Path, destination: Path) -> dict[str, Any]:
    """逐文件安全展开一个已验证归档。

    :param archive: tar 文件。
    :param destination: 当前归档独立且为空的目标目录。
    :returns: 文件数、总字节和每个文件的摘要。
    :raises ValueError: 成员路径不安全或含不需要的 checkpoint。
    """
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"目标目录非空，拒绝覆盖：{destination}")
    destination.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    with tarfile.open(archive, "r:") as bundle:
        for member in bundle:
            member_path = PurePosixPath(member.name)
            parts = member_path.parts
            if member_path.is_absolute() or not parts or any(part in {"", ".", ".."} for part in parts):
                raise ValueError(f"归档成员路径不安全：{member.name}")
            if any(part in {"checkpoints", "rng", "torch_cache"} for part in parts):
                raise ValueError(f"归档意外包含逐轮 checkpoint/RNG：{member.name}")
            target = destination.joinpath(*parts)
            target.relative_to(destination)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile() or target.exists():
                raise ValueError(f"归档成员非普通文件或重复：{member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise ValueError(f"无法读取归档成员：{member.name}")
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
            if target.stat().st_size != member.size:
                raise ValueError(f"归档成员字节数不一致：{member.name}")
            files.append({"path": member_path.as_posix(), "bytes": member.size,
                          "sha256": sha256_file(target)})
    return {"files": len(files), "bytes": sum(row["bytes"] for row in files), "file_hashes": files}


def main() -> int:
    """展开五个已冻结归档并写入审计清单。

    :returns: 进程退出码。
    """
    parser = argparse.ArgumentParser(description="安全展开 MEFKT 桌面过程数据")
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    desktop = Path.home().joinpath("Desktop").resolve()
    if desktop not in root.parents:
        raise ValueError("MEFKT 归档目录必须位于当前用户桌面")
    process_root = root / "process_data"
    if not process_root.is_dir() or any(process_root.iterdir()):
        raise ValueError("过程数据目录必须存在且为空")
    audit: dict[str, Any] = {"schema": "mefkt-desktop-process-archive-v1", "archives": {}}
    for name, expected, relative in ARCHIVES:
        archive = root / "transfer" / name
        actual = sha256_file(archive)
        if actual != expected:
            raise ValueError(f"归档 SHA-256 不一致：{name}")
        extracted = extract_one(archive, process_root / relative)
        audit["archives"][name] = {"sha256": actual, "target": relative, **extracted}
        print(json.dumps({"archive": name, "files": extracted["files"],
                          "bytes": extracted["bytes"]}, ensure_ascii=False), flush=True)
    (process_root / "file_manifest.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
