#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
为 MEFKT 新课程或 canonical 数据生成冻结题目内容向量。
@Project : adaptive-edu
@File : prepare_mefkt_content_embeddings.py
@Author : Qintsg
@Date : 2026-08-24
'''

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from mefkt_open_world import (
    DEFAULT_CONTENT_MODEL,
    build_item_text,
    encode_item_texts,
    load_item_rows,
    save_content_embeddings,
)


def _parse_args() -> argparse.Namespace:
    """
    解析内容向量生成参数。

    :returns: 命令行参数命名空间。
    """
    parser = argparse.ArgumentParser(description="生成 MEFKT 冻结题目内容向量")
    parser.add_argument("--events-file", required=True, help="canonical CSV")
    parser.add_argument("--output", required=True, help="输出 .npz sidecar")
    parser.add_argument("--model-name", default=DEFAULT_CONTENT_MODEL)
    parser.add_argument("--reuse-sidecar", type=Path, default=None, help="复用相同编码器生成的既有题目向量")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", default=None, help="cpu、cuda 或留空自动选择")
    return parser.parse_args()


def main() -> int:
    """
    读取 canonical CSV，生成并保存内容向量。

    :returns: 进程退出码。
    """
    args = _parse_args()
    item_rows = load_item_rows(Path(args.events_file).resolve())
    item_ids = tuple(sorted(item_rows))
    reused: dict[str, np.ndarray] = {}
    if args.reuse_sidecar:
        with np.load(args.reuse_sidecar.resolve(), allow_pickle=False) as archive:
            existing_model = str(archive["model_name"].item())
            if existing_model != args.model_name:
                raise ValueError("既有 sidecar 编码器与当前编码器不一致")
            existing_ids = [str(value) for value in archive["item_ids"].tolist()]
            existing_vectors = np.asarray(archive["embeddings"], dtype=np.float32)
            if existing_vectors.shape != (len(existing_ids), 384):
                raise ValueError("既有 sidecar 的 ID 与向量形状不一致")
            reused = dict(zip(existing_ids, existing_vectors, strict=True))
    missing = [item_id for item_id in item_ids if item_id not in reused]
    new_vectors = encode_item_texts(
        [build_item_text(item_rows[item_id]) for item_id in missing],
        model_name=args.model_name,
        batch_size=args.batch_size,
        device=args.device,
    ) if missing else np.empty((0, 384), dtype=np.float32)
    additions = dict(zip(missing, new_vectors, strict=True))
    embeddings = np.stack([reused.get(item_id) if item_id in reused else additions[item_id]
                           for item_id in item_ids]).astype(np.float32)
    save_content_embeddings(Path(args.output).resolve(), item_ids, embeddings, args.model_name)
    print({"items": len(item_ids), "reused": len(item_ids) - len(missing),
           "new": len(missing), "dimension": int(embeddings.shape[1]), "model": args.model_name})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
