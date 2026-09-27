#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
流式校验 MEFKT-NG 扩充数据的用户、时间、知识点和场次边界。
@Project : adaptive-edu
@File : validate_mefkt_expanded_data.py
@Author : Qintsg
@Date : 2026-09-24
'''

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


def numeric_time(value: str) -> float:
    """将 canonical 数值时间统一为秒。

    :param value: Unix 秒、毫秒或相对秒。
    :returns: 秒数。
    """
    parsed = float(value)
    return parsed / 1000.0 if parsed > 10_000_000_000 else parsed


def audit(path: Path, max_episode: int) -> dict[str, object]:
    """完成单次只读审计。

    :param path: canonical CSV。
    :param max_episode: 模型可容纳的最长场次。
    :returns: 领域、切分和场次统计。
    :raises ValueError: 任一训练不变量不成立。
    """
    domains: Counter[str] = Counter()
    positives: Counter[str] = Counter()
    split_events: Counter[str] = Counter()
    split_users: Counter[str] = Counter()
    items: dict[str, str] = {}
    seen_users: set[str] = set()
    current_user = ""
    current_split = ""
    previous_time = float("-inf")
    previous_episode = ""
    episode_size = 0
    longest = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"user_id", "item_id", "timestamp", "correct", "skill_ids", "subject_id", "episode_id"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"缺少 canonical 字段: {required - set(reader.fieldnames or [])}")
        for line, row in enumerate(reader, start=2):
            user, item = row["user_id"], row["item_id"]
            if not user or not item or row["correct"] not in {"0", "1"}:
                raise ValueError(f"第 {line} 行 ID 或作答标签无效")
            timestamp = numeric_time(row["timestamp"])
            if user != current_user:
                if user in seen_users:
                    raise ValueError(f"第 {line} 行学习者序列不连续: {user}")
                seen_users.add(user)
                current_user = user
                previous_time = float("-inf")
                previous_episode = ""
                episode_size = 0
                bucket = int.from_bytes(hashlib.sha256(user.encode()).digest()[:8], "big") % 10
                current_split = "train" if bucket < 8 else "validation" if bucket == 8 else "test"
                split_users[current_split] += 1
            if timestamp < previous_time:
                raise ValueError(f"第 {line} 行学习者时间倒序: {user}")
            explicit = row["episode_id"]
            episode = explicit if explicit else f"same-time:{timestamp}" if timestamp == previous_time else f"row:{line}"
            episode_size = episode_size + 1 if episode == previous_episode else 1
            longest = max(longest, episode_size)
            if episode_size > max_episode:
                raise ValueError(f"第 {line} 行场次长于模型窗口: {user}, {episode_size}")
            previous_episode = episode
            previous_time = timestamp
            skills = row["skill_ids"]
            if item in items and items[item] != skills:
                raise ValueError(f"第 {line} 行题目知识点映射改变: {item}")
            items[item] = skills
            domains[row["subject_id"]] += 1
            positives[row["subject_id"]] += int(row["correct"])
            split_events[current_split] += 1
    if min(split_events["train"], split_events["validation"], split_events["test"]) == 0:
        raise ValueError("至少一个学习者切分为空")
    return {"rows": sum(domains.values()), "users": len(seen_users), "items": len(items),
            "domains": {name: {"events": count, "positives": positives[name],
                               "positive_rate": positives[name] / count}
                        for name, count in domains.items()}, "split_events": dict(split_events),
            "split_users": dict(split_users), "longest_episode": longest}


def main() -> int:
    """打印审计摘要。

    :returns: 退出码。
    """
    parser = argparse.ArgumentParser(description="审计扩充 canonical CSV")
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--sequence-length", type=int, default=200)
    args = parser.parse_args()
    print(json.dumps(audit(args.events, args.sequence_length), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
