#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT-NG 在线推理适配器：冻结内容、课程缓存与知识点概率聚合。
@Project : adaptive-edu
@File : ng_runtime.py
@Author : Qintsg
@Date : 2026-09-25
'''

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import torch
from numpy.typing import NDArray
from safetensors.torch import load_file

from ai_services.services.mefkt.ng_catalog import NGCourseCatalog, build_course_catalog
from ai_services.services.mefkt.ng_course_data import NGCourseSpec, load_course_spec
from ai_services.services.mefkt.ng_sequence import predict_candidates, prepare_history
from models.MEFKT_NG.model import ModelConfig


logger = logging.getLogger(__name__)
BUFFER_NAMES = frozenset({"item_content", "item_skills", "item_difficulty", "skill_content", "graph_edges"})
DEFAULT_ENCODER = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MAX_CANDIDATES_PER_PASS = 32
MAX_HISTORY = 200 - MAX_CANDIDATES_PER_PASS
MAX_CACHED_COURSES = 4
BUILD_LOCK_STRIPES = 16


def sha256_file(path: Path) -> str:
    """计算模型包文件 SHA-256。

    :param path: 文件路径。
    :returns: 十六进制摘要。
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class NGPredictor:
    """在课程内复用训练共享参数的 MEFKT-NG 推理器。"""

    def __init__(
        self, bundle_path: Path,
        course_loader: Callable[[int], NGCourseSpec] = load_course_spec,
        encode_texts: Callable[[list[str]], NDArray[np.float32]] | None = None,
    ) -> None:
        """核验模型包并延迟加载冻结句向量模型。

        :param bundle_path: 含 safetensors、目录和元数据的本地目录。
        :param course_loader: 课程数据加载器，测试可注入。
        :param encode_texts: 冻结文本编码函数，测试可注入。
        :returns: None。
        :raises ValueError: 模型文件、源码或摘要错误。
        """
        root = bundle_path.resolve()
        metadata_file = root / "model_metadata.json"
        self.metadata: dict[str, Any] = json.loads(metadata_file.read_text(encoding="utf-8"))
        if self.metadata.get("schema") != "mefkt-ng-inference-bundle-v1":
            raise ValueError("MEFKT-NG 模型包 schema 不兼容")
        weights_file = root / "model.safetensors"
        catalog_file = root / "catalog.json"
        if sha256_file(weights_file) != self.metadata["weights_sha256"]:
            raise ValueError("MEFKT-NG 权重摘要错误")
        if sha256_file(catalog_file) != self.metadata["catalog_sha256"]:
            raise ValueError("MEFKT-NG 训练目录摘要错误")
        architecture_sha = self.metadata.get("architecture_sha256")
        if architecture_sha and sha256_file(Path(__file__).resolve().parents[3] /
                                             "models" / "MEFKT_NG" / "model.py") != architecture_sha:
            raise ValueError("MEFKT-NG 模型结构源码与训练包不一致")
        state = load_file(str(weights_file), device="cpu")
        self._parameters = {name: value for name, value in state.items() if name not in BUFFER_NAMES}
        if not self._parameters or sum(value.numel() for value in self._parameters.values()) != int(
            self.metadata["trainable_parameters"]
        ):
            raise ValueError("MEFKT-NG 可训练参数数目不一致")
        self.config = ModelConfig(**self.metadata["model_config"])
        self._course_loader = course_loader
        self._injected_encoder = encode_texts
        self._encoder_name = os.getenv("KT_MEFKT_NG_ENCODER_PATH") or self.metadata.get(
            "content_encoder_model", DEFAULT_ENCODER,
        )
        self._encoder: Any = None
        self._encoder_lock = threading.RLock()
        self._cache_lock = threading.RLock()
        self._build_locks = tuple(threading.Lock() for _ in range(BUILD_LOCK_STRIPES))
        self._catalogs: OrderedDict[int, NGCourseCatalog] = OrderedDict()
        device_name = os.getenv("KT_MEFKT_NG_DEVICE", "cpu").strip() or "cpu"
        if device_name.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("请求 CUDA 推理，但当前后端没有可用 GPU")
        self.device = torch.device(device_name)
        self.bundle_path = root

    def _encode(self, texts: list[str]) -> NDArray[np.float32]:
        """用训练时相同的冻结多语言编码器生成内容向量。

        :param texts: 静态题目和知识点文本。
        :returns: 384 维归一化向量。
        """
        if self._injected_encoder is not None:
            return np.asarray(self._injected_encoder(texts), dtype=np.float32)
        with self._encoder_lock:
            if self._encoder is None:
                from sentence_transformers import SentenceTransformer

                try:
                    self._encoder = SentenceTransformer(
                        str(self._encoder_name), device="cpu", local_files_only=True,
                    )
                except OSError:
                    if Path(str(self._encoder_name)).exists():
                        raise
                    logger.info("本机未缓存 MEFKT-NG 内容编码器，尝试获取固定模型：%s", self._encoder_name)
                    self._encoder = SentenceTransformer(str(self._encoder_name), device="cpu")
            return np.asarray(self._encoder.encode(
                texts, batch_size=64, convert_to_numpy=True,
                normalize_embeddings=True, show_progress_bar=False,
            ), dtype=np.float32)

    def _course_catalog(self, course_id: int) -> NGCourseCatalog:
        """题库内容不变时复用课程目录，变动时重新编码。

        :param course_id: 业务课程 ID。
        :returns: 当前课程可推理目录。
        """
        course_id = int(course_id)
        spec = self._course_loader(course_id)
        with self._cache_lock:
            cached = self._catalogs.get(course_id)
            if cached is not None and cached.revision == spec.revision:
                self._catalogs.move_to_end(course_id)
                return cached
        build_lock = self._build_locks[course_id % BUILD_LOCK_STRIPES]
        with build_lock:
            # 等待期间题库可能已修订，必须重新读取并检查缓存。
            spec = self._course_loader(course_id)
            with self._cache_lock:
                cached = self._catalogs.get(course_id)
                if cached is not None and cached.revision == spec.revision:
                    self._catalogs.move_to_end(course_id)
                    return cached
            catalog = build_course_catalog(spec, self._encode, self._parameters, self.config, self.device)
            with self._cache_lock:
                self._catalogs[course_id] = catalog
                self._catalogs.move_to_end(course_id)
                while len(self._catalogs) > MAX_CACHED_COURSES:
                    self._catalogs.popitem(last=False)
            return catalog

    @staticmethod
    def _target_points(
        catalog: NGCourseCatalog, answer_history: list[dict[str, Any]],
        knowledge_point_ids: list[int] | None,
    ) -> list[int]:
        """确定可由本课程题目覆盖的目标知识点。

        :param catalog: 课程目录。
        :param answer_history: 历史事件。
        :param knowledge_point_ids: 显式目标。
        :returns: 有代表题的知识点 ID。
        """
        if knowledge_point_ids:
            raw = knowledge_point_ids
        else:
            raw = []
            for record in answer_history:
                values = record.get("knowledge_point_ids")
                if isinstance(values, (list, tuple, set)):
                    raw.extend(values)
                elif record.get("knowledge_point_id") is not None:
                    raw.append(record["knowledge_point_id"])
                if record.get("question_id") is not None:
                    try:
                        raw.extend(catalog.question_to_points.get(int(record["question_id"]), ()))
                    except (TypeError, ValueError):
                        pass
        if not raw:
            return [point_id for point_id in catalog.point_ids if catalog.point_to_questions.get(point_id)]
        target: set[int] = set()
        for value in raw:
            try:
                point_id = int(value)
            except (TypeError, ValueError):
                continue
            if catalog.point_to_questions.get(point_id):
                target.add(point_id)
        return sorted(target)

    def predict(
        self, answer_history: list[dict[str, Any]], knowledge_point_ids: list[int] | None,
        course_id: int,
    ) -> dict[str, object]:
        """以同场候选题概率聚合出当前知识点表现估计。

        :param answer_history: 已评分答题事件。
        :param knowledge_point_ids: 显式目标知识点。
        :param course_id: 业务课程 ID。
        :returns: 兼容 KT 服务的知识点概率响应。
        """
        catalog = self._course_catalog(course_id)
        target_points = self._target_points(catalog, answer_history, knowledge_point_ids)
        candidates = sorted({item for point_id in target_points
                             for item in catalog.point_to_questions[point_id][:3]})
        if not candidates:
            return {"predictions": {}, "confidence": 0.0, "model_type": "mefkt_ng_unavailable",
                    "analysis": "课程中没有可关联目标知识点的题目"}
        history = prepare_history(answer_history, catalog, MAX_HISTORY)
        if not history.items:
            return {"predictions": {}, "confidence": 0.0, "model_type": "mefkt_ng_unavailable",
                    "analysis": "当前课程没有可识别的已评分作答"}
        item_probabilities: dict[int, float] = {}
        for start in range(0, len(candidates), MAX_CANDIDATES_PER_PASS):
            item_probabilities.update(predict_candidates(
                catalog, history, candidates[start:start + MAX_CANDIDATES_PER_PASS],
            ))
        predictions: dict[int, float] = {}
        for point_id in target_points:
            values = [item_probabilities[item] for item in catalog.point_to_questions[point_id][:3]
                      if item in item_probabilities]
            if values:
                predictions[point_id] = round(sum(values) / len(values), 4)
        coverage = history.recognized_count / max(len(answer_history), 1)
        confidence = min(0.90, 0.42 + min(history.recognized_count / 24.0, 1.0) * 0.24
                         + coverage * 0.16 + min(len(predictions) / 16.0, 1.0) * 0.08)
        return {
            "predictions": predictions, "confidence": round(confidence, 3),
            "model_type": "mefkt_ng", "runtime_schema": "mefkt_ng_v1",
            "question_predictions": {catalog.question_ids[index]: round(probability, 4)
                                     for index, probability in item_probabilities.items()},
            "analysis": (f"MEFKT-NG 课程题目推理：识别 {history.recognized_count}/{len(answer_history)} "
                         f"条作答，输出 {len(predictions)} 个知识点"),
        }
