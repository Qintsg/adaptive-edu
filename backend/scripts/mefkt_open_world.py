#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT 开放世界题目内容表示与新课程接入工具。
@Project : adaptive-edu
@File : mefkt_open_world.py
@Author : Qintsg
@Date : 2026-08-24
'''

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

import numpy as np

BASE_FEATURE_DIM = 7
CONTENT_EMBEDDING_DIM = 384
DEFAULT_CONTENT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def build_item_text(row: dict[str, str]) -> str:
    """
    将课程、题目、学科和知识点元数据组成冻结编码器的输入文本。

    :param row: canonical CSV 的一行或题目元数据行。
    :returns: 稳定、可复现的内容描述文本。
    """
    values = (
        row.get("course_name"),
        row.get("subject_name"),
        row.get("subject_id"),
        row.get("item_text") or row.get("question_text") or row.get("title"),
        row.get("skill_texts") or row.get("skill_ids"),
        row.get("language"),
        row.get("difficulty"),
    )
    return " [SEP] ".join(str(value).strip() for value in values if str(value or "").strip())


def load_item_rows(events_file: Path) -> dict[str, dict[str, str]]:
    """
    从事件 CSV 提取每道题第一次出现的静态元数据。

    :param events_file: canonical CSV 路径。
    :returns: 以 item_id 为键的题目元数据。
    :raises FileNotFoundError: 文件不存在时抛出。
    """
    if not events_file.is_file():
        raise FileNotFoundError(f"找不到 canonical CSV: {events_file}")
    rows: dict[str, dict[str, str]] = {}
    with events_file.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            item_id = str(row.get("item_id", "")).strip()
            if item_id:
                rows.setdefault(item_id, row)
    return rows


def encode_item_texts(
    texts: Iterable[str],
    *,
    model_name: str = DEFAULT_CONTENT_MODEL,
    batch_size: int = 64,
    device: str | None = None,
) -> np.ndarray:
    """
    使用冻结的多语言句向量模型编码课程题目文本。

    该函数只在课程发布或数据预处理阶段运行；MEFKT-Lite 在线推理不加载句向量模型。

    :param texts: 按题目词表顺序排列的文本。
    :param model_name: SentenceTransformers 模型名称或本地目录。
    :param batch_size: 编码 batch 大小。
    :param device: `cpu`、`cuda` 或 None（自动选择）。
    :returns: `[item_count, 384]` 的归一化内容向量。
    :raises RuntimeError: 依赖未安装或输出维度不符合要求时抛出。
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("生成课程内容向量需要安装 sentence-transformers") from exc
    model = SentenceTransformer(model_name, device=device)
    values = list(texts)
    embeddings = model.encode(
        values,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=len(values) > batch_size,
    )
    embeddings = np.asarray(embeddings, dtype=np.float32)
    if embeddings.ndim != 2 or embeddings.shape[1] != CONTENT_EMBEDDING_DIM:
        raise RuntimeError(
            f"内容编码器输出维度必须为 {CONTENT_EMBEDDING_DIM}，实际为 {embeddings.shape}；"
            "请固定同一个冻结编码器，或先增加投影转换。"
        )
    return embeddings


def save_content_embeddings(path: Path, item_ids: Iterable[str], embeddings: np.ndarray, model_name: str) -> None:
    """
    保存题目内容向量 sidecar。

    :param path: `.npz` 输出路径。
    :param item_ids: 题目 ID，顺序必须与向量行一致。
    :param embeddings: `[N, 384]` 内容向量。
    :param model_name: 生成向量所用的冻结编码器名称。
    :returns: None。
    :raises ValueError: ID 数量或向量形状不正确时抛出。
    """
    item_ids = tuple(str(item_id) for item_id in item_ids)
    values = np.asarray(embeddings, dtype=np.float32)
    if values.shape != (len(item_ids), CONTENT_EMBEDDING_DIM):
        raise ValueError(f"内容向量形状错误: ids={len(item_ids)} embeddings={values.shape}")
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, item_ids=np.asarray(item_ids), embeddings=values, model_name=np.asarray(model_name))


def load_content_embeddings(
    path: Path | None,
    item_ids: Iterable[str],
    *,
    dimension: int = CONTENT_EMBEDDING_DIM,
) -> np.ndarray:
    """
    按题目词表加载内容向量，缺失题目使用全零向量。

    :param path: `.npz` 或 JSON sidecar；None 表示全部使用零向量。
    :param item_ids: 目标题目词表。
    :param dimension: 模型要求的固定内容维度。
    :returns: `[N, dimension]` 内容向量。
    """
    target_ids = tuple(str(item_id) for item_id in item_ids)
    result = np.zeros((len(target_ids), dimension), dtype=np.float32)
    if path is None:
        return result
    if not path.is_file():
        raise FileNotFoundError(f"找不到内容向量文件: {path}")
    mapping: dict[str, np.ndarray] = {}
    if path.suffix.lower() == ".npz":
        with np.load(path, allow_pickle=False) as archive:
            source_ids = [str(value) for value in archive["item_ids"].tolist()]
            values = np.asarray(archive["embeddings"], dtype=np.float32)
        if values.ndim != 2 or len(source_ids) != values.shape[0]:
            raise ValueError(f"内容向量 sidecar 格式错误: {path}")
        mapping = dict(zip(source_ids, values, strict=True))
    else:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"JSON 内容向量必须是 item_id 到数组的映射: {path}")
        mapping = {str(key): np.asarray(value, dtype=np.float32) for key, value in raw.items()}
    for index, item_id in enumerate(target_ids):
        value = mapping.get(item_id)
        if value is None or value.ndim != 1:
            continue
        length = min(value.size, dimension)
        result[index, :length] = value[:length]
    result[~np.isfinite(result)] = 0.0
    norms = np.linalg.norm(result, axis=1, keepdims=True)
    return result / np.maximum(norms, 1e-8)


def content_embeddings_metadata(path: Path | None) -> dict[str, object]:
    """
    读取可写入数据 manifest 和 checkpoint 的内容向量 provenance。

    :param path: 内容向量 sidecar；None 表示未启用内容向量。
    :returns: 文件名、大小、SHA-256、编码器、维度和题目数。
    """
    if path is None:
        return {
            "content_embeddings_file": "",
            "content_embeddings_size": 0,
            "content_embeddings_sha256": "",
            "content_embeddings_model": "",
            "content_embeddings_dimension": 0,
            "content_embeddings_items": 0,
        }
    if not path.is_file():
        raise FileNotFoundError(f"找不到内容向量文件: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    model_name = "unknown"
    dimension = 0
    item_count = 0
    if path.suffix.lower() == ".npz":
        with np.load(path, allow_pickle=False) as archive:
            values = np.asarray(archive["embeddings"])
            item_count = int(values.shape[0]) if values.ndim == 2 else 0
            dimension = int(values.shape[1]) if values.ndim == 2 else 0
            if "model_name" in archive.files:
                model_name = str(archive["model_name"].item())
    return {
        "content_embeddings_file": path.name,
        "content_embeddings_size": path.stat().st_size,
        "content_embeddings_sha256": digest.hexdigest(),
        "content_embeddings_model": model_name,
        "content_embeddings_dimension": dimension,
        "content_embeddings_items": item_count,
    }


def append_content_features(base_features: np.ndarray, content_features: np.ndarray) -> np.ndarray:
    """
    将 384 维开放内容向量追加到现有七维数值特征后。

    :param base_features: `[N, 7]` 训练统计特征。
    :param content_features: `[N, 384]` 固定内容向量。
    :returns: `[N, 391]` 供模型静态题目目录使用的矩阵。
    :raises ValueError: 行数或维度不一致时抛出。
    """
    base = np.asarray(base_features, dtype=np.float32)
    content = np.asarray(content_features, dtype=np.float32)
    if base.ndim != 2 or base.shape[1] != BASE_FEATURE_DIM:
        raise ValueError(f"基础题目特征必须为 [N, {BASE_FEATURE_DIM}]，实际为 {base.shape}")
    if content.ndim != 2 or content.shape[0] != base.shape[0]:
        raise ValueError(f"内容特征行数不一致: base={base.shape} content={content.shape}")
    return np.concatenate([base, content], axis=1).astype(np.float32, copy=False)


__all__ = [
    "BASE_FEATURE_DIM",
    "CONTENT_EMBEDDING_DIM",
    "DEFAULT_CONTENT_MODEL",
    "append_content_features",
    "build_item_text",
    "content_embeddings_metadata",
    "encode_item_texts",
    "load_content_embeddings",
    "load_item_rows",
    "save_content_embeddings",
]
