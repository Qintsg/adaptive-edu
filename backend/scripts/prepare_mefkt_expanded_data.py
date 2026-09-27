#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
把 EdNet-KT1 与 Junyi v9 接入现有 MEFKT canonical 训练数据。
@Project : adaptive-edu
@File : prepare_mefkt_expanded_data.py
@Author : Qintsg
@Date : 2026-09-24
'''

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path


def sha256_file(path: Path) -> str:
    """计算文件摘要。

    :param path: 源文件路径。
    :returns: SHA-256 十六进制值。
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sampled(user_id: str, denominator: int) -> bool:
    """按稳定学习者哈希抽样，保留该学习者完整序列。

    :param user_id: 原始学习者标识。
    :param denominator: 抽样分母。
    :returns: 是否入选。
    """
    token = hashlib.sha256(user_id.encode("utf-8")).digest()
    return int.from_bytes(token[:8], "big") % denominator == 0


def token(value: str) -> str:
    """为长且含特殊字符的源 ID 生成稳定短 ID。

    :param value: 源 ID。
    :returns: 20 位十六进制 ID。
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def load_ednet_questions(archive: zipfile.ZipFile) -> dict[str, dict[str, str]]:
    """读取 EdNet 官方题目静态元数据。

    :param archive: 官方 Contents ZIP。
    :returns: 题目 ID 到元数据的映射。
    """
    with archive.open("contents/questions.csv") as handle:
        reader = csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig", newline=""))
        return {row["question_id"]: row for row in reader}


def append_ednet(
    writer: csv.DictWriter, kt1: zipfile.ZipFile, questions: dict[str, dict[str, str]], denominator: int,
) -> dict[str, int]:
    """流式追加按用户抽样的 EdNet KT1 作答。

    :param writer: canonical CSV 写入器。
    :param kt1: 官方 KT1 ZIP。
    :param questions: 官方题目元数据。
    :param denominator: 用户抽样分母。
    :returns: 行数、用户数和跳过计数。
    """
    stats = {"users": 0, "events": 0, "missing_question_or_label": 0}
    members = sorted(name for name in kt1.namelist() if name.startswith("KT1/") and name.endswith(".csv"))
    for member in members:
        user = Path(member).stem
        if not sampled(user, denominator):
            continue
        stats["users"] += 1
        with kt1.open(member) as handle:
            rows = list(csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig", newline="")))
        rows.sort(key=lambda row: (int(row["timestamp"]), int(row["solving_id"])))
        for row in rows:
            question = questions.get(row["question_id"])
            answer = str(row.get("user_answer") or "").strip().lower()
            if not question or answer not in {"a", "b", "c", "d"}:
                stats["missing_question_or_label"] += 1
                continue
            tags = [f"ednet:tag:{part}" for part in question["tags"].split(";") if part]
            if not tags:
                stats["missing_question_or_label"] += 1
                continue
            elapsed = str(row.get("elapsed_time") or "").strip()
            seconds = str(max(0.0, float(elapsed) / 1000.0)) if elapsed else ""
            part = question["part"]
            writer.writerow({
                "user_id": f"ednet:{user}", "item_id": f"ednet:{row['question_id']}",
                "timestamp": row["timestamp"], "correct": int(answer == question["correct_answer"].lower()),
                "response_time_seconds": seconds, "subject_id": "ednet:english",
                "skill_ids": ";".join(tags), "course_name": "EdNet TOEIC",
                "item_text": f"TOEIC part {part}; bundle {question['bundle_id']}",
                "skill_texts": ";".join(f"TOEIC tag {tag}" for tag in question["tags"].split(";") if tag),
                "language": "en", "difficulty": "", "part": part,
                "deployed_at": question["deployed_at"], "bundle_id": question["bundle_id"],
                "episode_id": f"ednet:{user}:{row['solving_id']}",
            })
            stats["events"] += 1
    return stats


def load_junyi_content(archive: zipfile.ZipFile) -> dict[str, dict[str, str]]:
    """读取 Junyi 官方练习内容表。

    :param archive: Kaggle v9 ZIP。
    :returns: 练习 ID 到元数据的映射。
    """
    with archive.open("Info_Content.csv") as handle:
        reader = csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig", newline=""))
        return {row["ucid"]: row for row in reader if row.get("content_kind") == "Exercise"}


def parse_junyi_time(value: str) -> int:
    """将官方分钟级时间解析为 Unix 秒。

    :param value: `YYYY-MM-DD HH:MM:SS UTC`。
    :returns: Unix 秒。
    :raises ValueError: 时间格式无效。
    """
    parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=UTC)
    return int(parsed.timestamp())


def append_junyi(
    writer: csv.DictWriter, archive: zipfile.ZipFile, content: dict[str, dict[str, str]],
    denominator: int, sqlite_path: Path, max_episode: int,
) -> dict[str, int]:
    """以有界内存排序并追加 Junyi 学习者序列。

    :param writer: canonical CSV 写入器。
    :param archive: Kaggle v9 ZIP。
    :param content: 静态练习元数据。
    :param denominator: 用户抽样分母。
    :param sqlite_path: 运行期间排序数据库。
    :param max_episode: 单一粗时间槽允许的最多交互。
    :returns: 行数、用户数与跳过计数。
    """
    stats = {"users": 0, "events": 0, "missing_content_or_label": 0,
             "oversize_slots_dropped": 0, "oversize_events_dropped": 0}
    connection = sqlite3.connect(sqlite_path)
    try:
        connection.execute("CREATE TABLE events (user_id TEXT, time INTEGER, problem_number INTEGER, ordinal INTEGER, ucid TEXT, correct INTEGER, seconds REAL)")
        batch: list[tuple[str, int, int, int, str, int, float]] = []
        with archive.open("Log_Problem.csv") as handle:
            reader = csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig", newline=""))
            for ordinal, row in enumerate(reader):
                user, ucid = str(row.get("uuid") or ""), str(row.get("ucid") or "")
                label = str(row.get("is_correct") or "").strip().lower()
                if not user or not sampled(user, denominator):
                    continue
                if ucid not in content or label not in {"true", "false", "1", "0"}:
                    stats["missing_content_or_label"] += 1
                    continue
                try:
                    timestamp = parse_junyi_time(row["timestamp_TW"])
                    number = int(row.get("problem_number") or 0)
                    seconds = max(0.0, float(row.get("total_sec_taken") or 0))
                except (ValueError, KeyError):
                    stats["missing_content_or_label"] += 1
                    continue
                batch.append((f"junyi:{token(user)}", timestamp, number, ordinal, ucid, int(label in {"true", "1"}), seconds))
                if len(batch) >= 10_000:
                    connection.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?)", batch)
                    connection.commit()
                    batch.clear()
            if batch:
                connection.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?)", batch)
                connection.commit()
        oversize = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(n),0) FROM (SELECT COUNT(*) AS n FROM events "
            "GROUP BY user_id,time HAVING COUNT(*) > ?)", (max_episode,),
        ).fetchone()
        stats["oversize_slots_dropped"], stats["oversize_events_dropped"] = oversize
        if stats["oversize_slots_dropped"]:
            connection.execute(
                "DELETE FROM events WHERE (user_id,time) IN "
                "(SELECT user_id,time FROM events GROUP BY user_id,time HAVING COUNT(*) > ?)",
                (max_episode,),
            )
            connection.commit()
        connection.execute("CREATE INDEX events_order ON events(user_id,time,problem_number,ordinal)")
        previous_user = ""
        for user, timestamp, _number, _ordinal, ucid, correct, seconds in connection.execute(
            "SELECT * FROM events ORDER BY user_id,time,problem_number,ordinal"
        ):
            if user != previous_user:
                stats["users"] += 1
                previous_user = user
            item = content[ucid]
            item_key = token(ucid)
            level4 = item.get("level4_id") or ""
            skills = [f"junyi:exercise:{item_key}"]
            if level4:
                skills.append(f"junyi:level4:{token(level4)}")
            difficulty = {"normal": "medium"}.get(item.get("difficulty", ""), item.get("difficulty", ""))
            writer.writerow({
                "user_id": user, "item_id": f"junyi:exercise:{item_key}",
                "timestamp": timestamp, "correct": correct, "response_time_seconds": seconds,
                "subject_id": "junyi:math", "skill_ids": ";".join(skills),
                "course_name": "Junyi Academy Mathematics", "item_text": item.get("content_pretty_name", ""),
                "skill_texts": item.get("content_pretty_name", ""), "language": "zh-TW",
                "difficulty": difficulty, "part": item.get("learning_stage", ""),
                "deployed_at": "", "bundle_id": "",
                "episode_id": f"junyi:{user}:{timestamp}",
            })
            stats["events"] += 1
    finally:
        connection.close()
    return stats


def main() -> int:
    """生成只追加的新 canonical 数据与来源清单。

    :returns: 退出码。
    :raises FileExistsError: 输出已存在时抛出。
    """
    parser = argparse.ArgumentParser(description="扩充 MEFKT-NG 官方 EdNet/Junyi 数据")
    parser.add_argument("--base-events", type=Path, required=True)
    parser.add_argument("--ednet-kt1", type=Path, required=True)
    parser.add_argument("--ednet-contents", type=Path, required=True)
    parser.add_argument("--junyi-v9", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ednet-denominator", type=int, default=64)
    parser.add_argument("--junyi-denominator", type=int, default=10)
    parser.add_argument("--max-episode", type=int, default=200)
    args = parser.parse_args()
    if args.ednet_denominator < 1 or args.junyi_denominator < 1 or args.max_episode < 2:
        raise ValueError("抽样分母或场次长度非法")
    output = args.output.resolve()
    manifest_path = output.with_suffix(".manifest.json")
    if output.exists() or manifest_path.exists():
        raise FileExistsError("扩充训练输入已存在；请选择新的输出路径，避免覆盖旧数据")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    sqlite_path = output.with_suffix(".sort.sqlite")
    if temporary.exists() or sqlite_path.exists():
        raise FileExistsError("发现上次未完成的中间文件，请先检查后再运行")
    sources = {name: {"path": str(path.resolve()), "sha256": sha256_file(path)} for name, path in (
        ("base", args.base_events), ("ednet_kt1", args.ednet_kt1),
        ("ednet_contents", args.ednet_contents), ("junyi_v9", args.junyi_v9),
    )}
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            with args.base_events.open(encoding="utf-8-sig", newline="") as base:
                reader = csv.DictReader(base)
                fields = [*reader.fieldnames, "episode_id"] if reader.fieldnames else []
                if not fields or "episode_id" in reader.fieldnames:
                    raise ValueError("基线 canonical 表头不符合预期")
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                baseline = 0
                for row in reader:
                    writer.writerow(row)
                    baseline += 1
            with zipfile.ZipFile(args.ednet_kt1) as kt1, zipfile.ZipFile(args.ednet_contents) as contents:
                ednet = append_ednet(writer, kt1, load_ednet_questions(contents), args.ednet_denominator)
            with zipfile.ZipFile(args.junyi_v9) as junyi_zip:
                junyi = append_junyi(writer, junyi_zip, load_junyi_content(junyi_zip),
                                     args.junyi_denominator, sqlite_path, args.max_episode)
        os.replace(temporary, output)
        manifest = {
            "schema": "mefkt-ng-expanded-input-v1", "sources": sources,
            "sampling": {"ednet_user_hash_denominator": args.ednet_denominator,
                         "junyi_user_hash_denominator": args.junyi_denominator,
                         "max_junyi_time_slot_events": args.max_episode},
            "counts": {"base_events": baseline, "ednet": ednet, "junyi": junyi},
            "output": str(output), "output_sha256": sha256_file(output),
            "licenses": {"ednet": "CC BY-NC 4.0", "junyi": "CC BY-NC-SA 4.0"},
            "limitations": ["EdNet 不公开题目原文，内容向量只能使用 part/bundle/tag 静态元数据",
                            "Junyi 时间戳为 15 分钟粒度，同一学习者同一时间槽作为一个不可泄漏场次"],
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps(manifest["counts"], ensure_ascii=False))
    finally:
        if sqlite_path.exists():
            sqlite_path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
