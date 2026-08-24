#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
流式合并多个 MEFKT canonical CSV，并验证学习者序列边界。
@Project : adaptive-edu
@File : merge_mefkt_canonical.py
@Author : Qintsg
@Date : 2026-08-24
'''

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from mefkt_canonical_data import _parse_timestamp


def _parse_args() -> argparse.Namespace:
    """
    解析 canonical 合并参数。

    :returns: 命令行参数命名空间。
    """
    parser = argparse.ArgumentParser(description="合并多个 MEFKT canonical CSV")
    parser.add_argument("--input", action="append", required=True, help="可重复指定的输入 CSV")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def merge_files(input_paths: list[Path], output_path: Path) -> dict[str, object]:
    """
    流式合并输入文件，并检查同一用户连续且时间非递减。

    :param input_paths: canonical CSV 输入列表。
    :param output_path: 合并后的 CSV。
    :returns: 每个来源和合计统计。
    :raises ValueError: 表头不一致、用户重复或时间顺序错误时抛出。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    expected_fields: list[str] | None = None
    seen_users: set[str] = set()
    source_stats: list[dict[str, object]] = []
    total_events = 0
    with output_path.open("w", encoding="utf-8", newline="") as output_handle:
        writer: csv.DictWriter | None = None
        for input_path in input_paths:
            events = 0
            users = 0
            current_user: str | None = None
            previous_timestamp = 0.0
            closed_users: set[str] = set()
            with input_path.open(encoding="utf-8-sig", newline="") as input_handle:
                reader = csv.DictReader(input_handle)
                fields = list(reader.fieldnames or [])
                if expected_fields is None:
                    expected_fields = fields
                    writer = csv.DictWriter(output_handle, fieldnames=expected_fields)
                    writer.writeheader()
                elif fields != expected_fields:
                    raise ValueError(f"canonical 表头不一致: {input_path}")
                assert writer is not None
                for row in reader:
                    user_id = str(row.get("user_id") or "").strip()
                    if not user_id:
                        continue
                    timestamp = _parse_timestamp(row.get("timestamp"))
                    if current_user != user_id:
                        if user_id in closed_users or user_id in seen_users:
                            raise ValueError(f"学习者跨文件重复或序列不连续: {user_id}")
                        if current_user is not None:
                            closed_users.add(current_user)
                        current_user = user_id
                        previous_timestamp = timestamp
                        users += 1
                    elif timestamp < previous_timestamp:
                        raise ValueError(f"学习者时间倒序: user={user_id} file={input_path}")
                    previous_timestamp = timestamp
                    writer.writerow(row)
                    events += 1
            seen_users.update(closed_users)
            if current_user is not None:
                seen_users.add(current_user)
            source_stats.append({"path": str(input_path), "users": users, "events": events})
            total_events += events
    return {"sources": source_stats, "users": len(seen_users), "events": total_events}


def main() -> int:
    """
    执行合并并打印 JSON 统计。

    :returns: 进程退出码。
    """
    args = _parse_args()
    summary = merge_files([Path(value) for value in args.input], Path(args.output))
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
