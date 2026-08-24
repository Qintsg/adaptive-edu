#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
将序列化 ASSISTments 2009 Parquet 转为 MEFKT canonical CSV。
@Project : adaptive-edu
@File : convert_assistments_to_canonical.py
@Author : Qintsg
@Date : 2026-08-24
'''

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from pyarrow import parquet

FIELDNAMES = [
    "user_id",
    "item_id",
    "timestamp",
    "correct",
    "response_time_seconds",
    "subject_id",
    "skill_ids",
    "course_name",
    "item_text",
    "skill_texts",
    "language",
    "difficulty",
    "part",
    "deployed_at",
    "bundle_id",
]


def _parse_args() -> argparse.Namespace:
    """
    解析 ASSISTments 转换参数。

    :returns: 命令行参数命名空间。
    """
    parser = argparse.ArgumentParser(description="转换 ASSISTments 2009 Parquet 为 canonical CSV")
    parser.add_argument("--input", required=True, help="Atomi/ASSISTments2009 Parquet")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-users", type=int, default=0)
    return parser.parse_args()


def _stable_item_id(skill_ids: str, skill_name: str, answer_type: str) -> str:
    """
    根据知识点和题型生成稳定题目族 ID。

    源数据不包含 problem_id，因此模型学习的是知识点/题型组合，而不是伪造
    每次唯一的题目 ID。

    :param skill_ids: 原始知识点 ID 组合。
    :param skill_name: 原始知识点名称。
    :param answer_type: 原始答案类型。
    :returns: 带数据源前缀的稳定题目族 ID。
    """
    digest = hashlib.sha1(f"{skill_ids}|{skill_name}|{answer_type}".encode()).hexdigest()[:20]
    return f"assistments2009:math:item:{digest}"


def convert_dataset(input_path: Path, output_path: Path, max_users: int) -> dict[str, object]:
    """
    展开每名学习者的序列并写出 canonical CSV。

    ASSISTments 派生文件不含时间戳和真实答题耗时。这里使用每次交互递增
    五分钟的相对时间和 10 秒中性默认耗时，保留学习顺序但不声称它们是
    观测时间；跨域训练中的真实时间信号主要由 SLAM 提供。

    :param input_path: 输入 Parquet。
    :param output_path: 输出 canonical CSV。
    :param max_users: 最大学习者数，0 表示不限制。
    :returns: 转换统计与缺失字段策略。
    """
    table = parquet.read_table(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    user_count = 0
    event_count = 0
    item_ids: set[str] = set()
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in table.to_pylist():
            if max_users and user_count >= max_users:
                break
            user_id = str(row.get("user_id") or "").strip()
            if not user_id:
                continue
            skill_ids = list(row.get("skill_ids") or [])
            skill_names = list(row.get("skill_names") or [])
            grades = list(row.get("grades") or [])
            answer_types = list(row.get("answer_types") or [])
            length = min(len(skill_ids), len(skill_names), len(grades), len(answer_types))
            if length == 0:
                continue
            for position in range(length):
                raw_skill_ids = str(skill_ids[position] or "unknown")
                skill_name = str(skill_names[position] or "unknown")
                answer_type = str(answer_types[position] or "unknown")
                prefixed_skills = ";".join(
                    f"assistments2009:math:skill:{token}"
                    for token in raw_skill_ids.split("_")
                    if token
                )
                item_id = _stable_item_id(raw_skill_ids, skill_name, answer_type)
                item_ids.add(item_id)
                writer.writerow(
                    {
                        "user_id": f"assistments2009:{user_id}",
                        "item_id": item_id,
                        "timestamp": str(position * 300),
                        "correct": str(int(str(grades[position]).strip() == "1")),
                        "response_time_seconds": "10.0",
                        "subject_id": "assistments2009:math",
                        "skill_ids": prefixed_skills or "assistments2009:math:skill:unknown",
                        "course_name": "ASSISTments 2009 Mathematics",
                        "item_text": f"Mathematics exercise about {skill_name}; answer type {answer_type}",
                        "skill_texts": skill_name,
                        "language": "en",
                        "difficulty": "0.5",
                        "part": "1",
                        "deployed_at": "0",
                        "bundle_id": f"assistments2009:{answer_type}",
                    }
                )
                event_count += 1
            user_count += 1
    return {
        "source": "Atomi/ASSISTments2009",
        "users": user_count,
        "events": event_count,
        "items": len(item_ids),
        "response_time_policy": "missing_in_source; neutral_default_10_seconds",
        "timestamp_policy": "missing_in_source; preserve_order_with_300_second_steps",
        "license_note": "HF repository has no explicit license tag; verify original ASSISTments terms before distribution",
    }


def main() -> int:
    """
    执行转换并打印 JSON 统计。

    :returns: 进程退出码。
    """
    args = _parse_args()
    summary = convert_dataset(Path(args.input), Path(args.output), args.max_users)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
