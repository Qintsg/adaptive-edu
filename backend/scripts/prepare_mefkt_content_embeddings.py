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
    texts = [build_item_text(item_rows[item_id]) for item_id in item_ids]
    embeddings = encode_item_texts(
        texts,
        model_name=args.model_name,
        batch_size=args.batch_size,
        device=args.device,
    )
    save_content_embeddings(Path(args.output).resolve(), item_ids, embeddings, args.model_name)
    print({"items": len(item_ids), "dimension": int(embeddings.shape[1]), "model": args.model_name})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
