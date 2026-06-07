"""KT prediction result helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


MEFKT_MODEL_TYPES = frozenset({"mefkt_real", "mefkt_question_online"})


def is_mefkt_prediction(result: Mapping[str, object] | None) -> bool:
    """判断 KT 输出是否来自真实 MEFKT 推理。"""
    if not isinstance(result, Mapping):
        return False
    model_type = str(result.get("model_type") or "")
    if model_type in MEFKT_MODEL_TYPES:
        return True
    if model_type not in {"fusion", "ensemble"}:
        return False

    model_results = result.get("model_results")
    if not isinstance(model_results, Mapping):
        return False
    child_results = [
        child_result
        for child_result in model_results.values()
        if isinstance(child_result, Mapping)
    ]
    return bool(child_results) and all(is_mefkt_prediction(child) for child in child_results)


def answered_point_ids(answer_history: Iterable[Mapping[str, object]]) -> set[int]:
    """提取已有答题证据覆盖到的知识点 ID。"""
    point_ids: set[int] = set()
    for record in answer_history:
        point_ids_raw = record.get("knowledge_point_ids")
        if isinstance(point_ids_raw, Iterable) and not isinstance(
            point_ids_raw, (str, bytes, Mapping)
        ):
            before_count = len(point_ids)
            for point_id_raw in point_ids_raw:
                try:
                    point_ids.add(int(point_id_raw))
                except (TypeError, ValueError):
                    continue
            if len(point_ids) > before_count:
                continue

        point_id_raw = record.get("knowledge_point_id")
        if point_id_raw is None:
            continue
        try:
            point_ids.add(int(point_id_raw))
        except (TypeError, ValueError):
            continue
    return point_ids


def normalize_prediction_map(raw_predictions: object) -> dict[int, float]:
    """将 KT 原始 predictions 规整为 int -> float 字典。"""
    if not isinstance(raw_predictions, Mapping):
        return {}
    prediction_map: dict[int, float] = {}
    for point_id_raw, mastery_raw in raw_predictions.items():
        try:
            prediction_map[int(point_id_raw)] = float(mastery_raw)
        except (TypeError, ValueError):
            continue
    return prediction_map


def compact_answer_history(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """将可能按知识点展开的答题历史折叠为每题一次的 KT 输入。"""
    compacted: list[dict[str, object]] = []
    last_key: tuple[object, ...] | None = None
    for row in rows:
        question_id = row.get("question_id")
        correct = 1 if row.get("is_correct", row.get("correct", 0)) else 0
        point_id = _coerce_optional_int(row.get("knowledge_point_id"))
        timestamp_value = row.get("timestamp") or row.get("answered_at")

        if question_id is None:
            compacted.append(
                {
                    "question_id": None,
                    "knowledge_point_id": point_id,
                    "knowledge_point_ids": [point_id] if point_id else [],
                    "correct": correct,
                }
            )
            continue

        timestamp_text = _normalize_timestamp(timestamp_value)
        current_key = (
            _normalize_question_key(question_id),
            correct,
            timestamp_text,
            _normalize_payload_key(row.get("student_answer")),
            _normalize_payload_key(row.get("correct_answer")),
            row.get("source"),
            row.get("exam_id"),
        )
        if compacted and current_key == last_key:
            _append_point_id(compacted[-1], point_id)
            continue

        record = {
            "question_id": _coerce_optional_int(question_id) or question_id,
            "knowledge_point_id": point_id,
            "knowledge_point_ids": [point_id] if point_id else [],
            "correct": correct,
        }
        if timestamp_text is not None:
            record["timestamp"] = timestamp_text
        compacted.append(record)
        last_key = current_key
    return compacted


def _append_point_id(record: dict[str, object], point_id: int | None) -> None:
    """向已折叠记录追加知识点 ID。"""
    if point_id:
        point_ids = record.setdefault("knowledge_point_ids", [])
        if isinstance(point_ids, list) and point_id not in point_ids:
            point_ids.append(point_id)
        if not record.get("knowledge_point_id"):
            record["knowledge_point_id"] = point_id


def _coerce_optional_int(value: object) -> int | None:
    """将标识值转成整数，失败时返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_question_key(question_id: object) -> object:
    """生成答题历史折叠用的题目键。"""
    normalized = _coerce_optional_int(question_id)
    return normalized if normalized is not None else question_id


def _normalize_timestamp(value: object) -> object:
    """生成可比较的时间键。"""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else value


def _normalize_payload_key(value: object) -> object:
    """生成学生答案等 JSON 字段的可比较键。"""
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), str(item)) for key, item in value.items()))
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return value


__all__ = [
    "MEFKT_MODEL_TYPES",
    "answered_point_ids",
    "compact_answer_history",
    "is_mefkt_prediction",
    "normalize_prediction_map",
]
