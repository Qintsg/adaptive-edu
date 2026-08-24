#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
将 SLAM 西班牙语-英语知识追踪 Parquet 转为 MEFKT canonical CSV。
@Project : adaptive-edu
@File : convert_slam_to_canonical.py
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
    解析 Parquet 转换参数。

    :returns: 命令行参数命名空间。
    """
    parser = argparse.ArgumentParser(description="转换 SLAM Parquet 为 MEFKT canonical CSV")
    parser.add_argument("--input-dir", required=True, help="包含 train/validation/test.parquet 的目录")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-users", type=int, default=0)
    parser.add_argument("--max-interactions", type=int, default=0)
    return parser.parse_args()


def _stable_item_id(row: dict[str, object]) -> str:
    """
    根据稳定内容生成题目 ID，避免把每次唯一 exercise_id 当作题目。

    :param row: SLAM 交互记录。
    :returns: 带数据源前缀的稳定题目 ID。
    """
    payload = "|".join(
        [
            str(row.get("prompt") or ""),
            str(row.get("format") or ""),
            " ".join(str(value) for value in (row.get("reference_tokens") or [])),
        ]
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]
    return f"slam:es-en:item:{digest}"


def _text(value: object) -> str:
    """
    将 Parquet 单元格安全转为文本。

    :param value: 原始 Parquet 单元格。
    :returns: 可写入 canonical CSV 的文本。
    """
    if value is None:
        return ""
    if isinstance(value, list):
        return ";".join(str(item) for item in value)
    return str(value)


def _content_difficulty(row: dict[str, object]) -> float:
    """
    根据题目静态文本生成不依赖作答标签的难度代理特征。

    SLAM 的 ``token_accuracy`` 是当前交互的结果统计，不能用于题目内容，
    否则会把当前标签泄漏到内容向量和模型输入中。这里仅使用题干长度，
    让该字段保持为弱先验；真正的题目难度由训练集历史统计学习。

    :param row: SLAM 交互记录。
    :returns: [0.1, 1.0] 范围内的静态难度代理值。
    """
    prompt = _text(row.get("prompt"))
    word_count = len(prompt.split())
    return min(max(word_count / 20.0, 0.1), 1.0)


def _convert_split(input_path: Path, output_path: Path, max_users: int, max_interactions: int) -> dict[str, int]:
    """
    转换一个数据切分并写出 canonical CSV。

    :param input_path: 输入 Parquet。
    :param output_path: 输出 CSV。
    :param max_users: 最大学习者数，0 表示不限制。
    :param max_interactions: 最大交互数，0 表示不限制。
    :returns: 转换统计信息。
    """
    table = parquet.read_table(input_path)
    rows = table.to_pylist()
    rows.sort(key=lambda row: (str(row.get("user_id", "")), float(row.get("days") or 0.0), int(row.get("interaction_index") or 0)))
    selected_users: set[str] = set()
    selected_rows: list[dict[str, str]] = []
    item_texts: dict[str, str] = {}
    for row in rows:
        user_id = str(row.get("user_id") or "").strip()
        if not user_id:
            continue
        if user_id not in selected_users and max_users and len(selected_users) >= max_users:
            continue
        selected_users.add(user_id)
        item_id = _stable_item_id(row)
        prompt = _text(row.get("prompt"))
        skill_names = _text(row.get("skill_names"))
        course_name = "SLAM Spanish-English"
        item_texts[item_id] = " [SEP] ".join(
            value for value in (course_name, "Spanish-English", prompt, skill_names, _text(row.get("format"))) if value
        )
        # SLAM 的 days 是相对天数；写成相对 Unix 秒，避免小于 1e10 的
        # 相对毫秒值被通用 canonical 解析器误认为秒。
        timestamp_seconds = int(float(row.get("days") or 0.0) * 86_400)
        selected_rows.append(
            {
                "user_id": f"slam:{user_id}",
                "item_id": item_id,
                "timestamp": str(timestamp_seconds),
                "correct": str(int(row.get("correct") or 0)),
                "response_time_seconds": str(float(row.get("response_time_seconds") or 10.0)),
                "subject_id": "slam:es-en",
                "skill_ids": _text(row.get("format")) or "unknown",
                "course_name": course_name,
                "item_text": prompt,
                "skill_texts": skill_names,
                "language": "es-en",
                "difficulty": str(_content_difficulty(row)),
                "part": "1",
                "deployed_at": "0",
                "bundle_id": "slam-es-en",
            }
        )
        if max_interactions and len(selected_rows) >= max_interactions:
            break
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(selected_rows)
    return {
        "users": len(selected_users),
        "events": len(selected_rows),
        "items": len(item_texts),
    }


def convert_dataset(input_dir: Path, output_dir: Path, max_users: int, max_interactions: int) -> dict[str, dict[str, int]]:
    """
    转换 train、validation、test 三个切分。

    :param input_dir: Parquet 输入目录。
    :param output_dir: CSV 输出目录。
    :param max_users: 每个切分的学习者上限。
    :param max_interactions: 每个切分的交互上限。
    :returns: 各切分统计信息。
    """
    summary = {}
    for split in ("train", "validation", "test"):
        summary[split] = _convert_split(
            input_dir / f"{split}.parquet",
            output_dir / f"{split}.csv",
            max_users,
            max_interactions,
        )
    item_rows: dict[str, dict[str, str]] = {}
    for split in ("train", "validation", "test"):
        with (output_dir / f"{split}.csv").open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                item_rows.setdefault(row["item_id"], row)
    with (output_dir / "items.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(item_rows.values())
    summary["items"] = {"items": len(item_rows)}
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "source": "bihungba1101/slam-en-es-knowledge-tracing",
                "license_note": "请在发布和混合训练前按数据集仓库说明核对许可证",
                "splits": summary,
                "item_id_policy": "sha1(prompt,format,reference_tokens), not raw exercise_id",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    """
    执行转换并打印统计信息。

    :returns: 进程退出码。
    """
    args = _parse_args()
    print(json.dumps(convert_dataset(Path(args.input_dir), Path(args.output_dir), args.max_users, args.max_interactions), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
