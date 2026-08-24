#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
生成可复现的多学科 MEFKT canonical CSV smoke 数据。
@Project : adaptive-edu
@File : generate_mefkt_multidomain_smoke.py
@Author : Qintsg
@Date : 2026-08-24
'''

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DomainSpec:
    """一个模拟学科及其知识点配置。"""

    name: str
    skills: tuple[str, ...]
    time_bias: float


DOMAINS = (
    DomainSpec("math", ("algebra", "geometry", "calculus", "probability"), 0.0),
    DomainSpec("physics", ("mechanics", "electricity", "waves", "thermodynamics"), 4.0),
    DomainSpec("chemistry", ("atom", "reaction", "organic", "solution"), 7.0),
    DomainSpec("english", ("grammar", "reading", "vocabulary", "writing"), -2.0),
)


def _parse_args() -> argparse.Namespace:
    """
    解析 smoke 数据生成参数。

    :returns: 命令行参数命名空间。
    """
    parser = argparse.ArgumentParser(description="生成 MEFKT 多学科 canonical CSV smoke 数据")
    parser.add_argument("--output", default="runtime_logs/mefkt_multidomain_smoke.csv")
    parser.add_argument("--users", type=int, default=80)
    parser.add_argument("--interactions-per-user", type=int, default=48)
    parser.add_argument("--items-per-domain", type=int, default=24)
    parser.add_argument("--seed", type=int, default=20260824)
    return parser.parse_args()


def _build_item_rows(items_per_domain: int) -> dict[str, dict[str, str]]:
    """
    构造全局唯一的多学科题目元数据。

    :param items_per_domain: 每个学科生成的题目数量。
    :returns: 以全局题目 ID 为键的题目元数据。
    :raises ValueError: 题目数量小于 4 时抛出。
    """
    if items_per_domain < 4:
        raise ValueError("每个学科至少需要 4 道题，才能覆盖全部知识点")
    rows: dict[str, dict[str, str]] = {}
    for domain_index, domain in enumerate(DOMAINS):
        for item_index in range(items_per_domain):
            item_id = f"smoke:{domain.name}:q{item_index:03d}"
            skill = domain.skills[item_index % len(domain.skills)]
            secondary = domain.skills[(item_index + 1) % len(domain.skills)]
            rows[item_id] = {
                "item_id": item_id,
                "subject_id": domain.name,
                "skill_ids": f"{domain.name}:{skill};{domain.name}:{secondary}",
                "part": str(domain_index + 1),
                "deployed_at": str(1_650_000_000 + domain_index * 86_400),
                "bundle_id": f"smoke-{domain.name}",
                "difficulty": f"{0.25 + (item_index % 8) * 0.07:.4f}",
                "course_name": f"开放世界 {domain.name} 课程",
                "item_text": f"{domain.name} 课程第 {item_index + 1} 题，考查 {skill} 与 {secondary} 的综合应用",
                "skill_texts": f"{skill};{secondary}",
                "language": "zh",
            }
    return rows


def _make_event_rows(users: int, interactions_per_user: int, item_rows: dict[str, dict[str, str]], seed: int) -> list[dict[str, str]]:
    """
    生成带答题耗时、时间间隔和跨学科行为的事件序列。

    :param users: 学习者数量。
    :param interactions_per_user: 每个学习者的交互数量。
    :param item_rows: 题目元数据。
    :param seed: 随机种子。
    :returns: 按学习者和时间排序的 canonical 行。
    :raises ValueError: 用户数或交互数不足时抛出。
    """
    if users < 20 or interactions_per_user < 12:
        raise ValueError("至少需要 20 个学习者和 12 次交互，才能覆盖 train/validation/test")
    rng = random.Random(seed)
    domain_items = {
        domain.name: [item_id for item_id, row in item_rows.items() if row["subject_id"] == domain.name]
        for domain in DOMAINS
    }
    rows: list[dict[str, str]] = []
    base_timestamp = 1_700_000_000_000
    for user_index in range(users):
        user_id = f"smoke_user_{user_index:04d}"
        ability = {domain.name: rng.uniform(-0.9, 0.9) for domain in DOMAINS}
        skill_ability = {
            f"{domain.name}:{skill}": rng.uniform(-0.45, 0.45)
            for domain in DOMAINS
            for skill in domain.skills
        }
        timestamp = base_timestamp + user_index * 86_400_000
        for position in range(interactions_per_user):
            domain = DOMAINS[(position + user_index) % len(DOMAINS)]
            items = domain_items[domain.name]
            item_index = (position * 5 + user_index * 3 + (position // len(DOMAINS)) * 7) % len(items)
            item_id = items[item_index]
            item = item_rows[item_id]
            skill_tokens = item["skill_ids"].split(";")
            difficulty = float(item["difficulty"])
            signal = ability[domain.name] + sum(skill_ability[token] for token in skill_tokens) / len(skill_tokens)
            probability = max(0.05, min(0.95, 0.58 + 0.22 * signal - 0.25 * (difficulty - 0.5)))
            correct = int(rng.random() < probability)
            gap_hours = 0.5 + (position % 6) * 1.5 + rng.random() * 2.0
            response_time = max(
                2.0,
                22.0 + domain.time_bias + difficulty * 24.0 - ability[domain.name] * 5.0 + rng.uniform(-3.0, 3.0),
            )
            if correct:
                response_time *= 0.82 + rng.random() * 0.12
            timestamp += int(gap_hours * 3_600_000)
            rows.append(
                {
                    "user_id": user_id,
                    "item_id": item_id,
                    "timestamp": str(timestamp),
                    "correct": str(correct),
                    "response_time_seconds": f"{response_time:.3f}",
                    "subject_id": item["subject_id"],
                    "skill_ids": item["skill_ids"],
                    "part": item["part"],
                    "deployed_at": item["deployed_at"],
                    "bundle_id": item["bundle_id"],
                    "course_name": item["course_name"],
                    "item_text": item["item_text"],
                    "skill_texts": item["skill_texts"],
                    "language": item["language"],
                    "difficulty": item["difficulty"],
                }
            )
    return rows


def generate_dataset(output: Path, users: int, interactions_per_user: int, items_per_domain: int, seed: int) -> dict[str, int]:
    """
    生成并写出 canonical CSV。

    :param output: 输出 CSV 路径。
    :param users: 学习者数量。
    :param interactions_per_user: 每个学习者的交互数量。
    :param items_per_domain: 每个学科的题目数量。
    :param seed: 随机种子。
    :returns: 输出统计信息。
    """
    item_rows = _build_item_rows(items_per_domain)
    events = _make_event_rows(users, interactions_per_user, item_rows, seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "user_id",
        "item_id",
        "timestamp",
        "correct",
        "response_time_seconds",
        "subject_id",
        "skill_ids",
        "part",
        "deployed_at",
        "bundle_id",
        "course_name",
        "item_text",
        "skill_texts",
        "language",
        "difficulty",
    ]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(events)
    return {
        "users": users,
        "events": len(events),
        "items": len(item_rows),
        "subjects": len(DOMAINS),
        "skills": sum(len(domain.skills) for domain in DOMAINS),
    }


def main() -> int:
    """
    生成 smoke 数据并打印统计信息。

    :returns: 进程退出码。
    """
    args = _parse_args()
    summary = generate_dataset(
        Path(args.output),
        args.users,
        args.interactions_per_user,
        args.items_per_domain,
        args.seed,
    )
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
