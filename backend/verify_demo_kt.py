#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""只读验证演示容器的 CPU 知识追踪、推荐和故障回退。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "adaptive_edu_api.settings")

import django

django.setup()

from rest_framework.test import APIRequestFactory, force_authenticate

from ai_services.api.kt import kt_predict, kt_recommendations
from platform_ai.kt import knowledge_tracing_facade
from assessments.models import AnswerHistory
from courses.models import Course
from knowledge.models import KnowledgePoint
from users.models import User


def timed(action: Callable[[], Any]) -> tuple[Any, int]:
    """记录一次只读调用的耗时。

    :param action: 待执行函数。
    :returns: 结果与毫秒耗时。
    """
    start = time.perf_counter()
    result = action()
    return result, round((time.perf_counter() - start) * 1000)


def call_kt_api(view: Callable[..., Any], user: User, data: dict[str, object]) -> dict[str, object]:
    """直接调用已认证 KT API，不经过外部网络。

    :param view: KT 视图函数。
    :param user: student1。
    :param data: 请求体。
    :returns: API 状态与数据。
    """
    request = APIRequestFactory().post("/api/ai/kt/check", data, format="json")
    force_authenticate(request, user=user)
    response = view(request)
    body = getattr(response, "data", {})
    return {"http_status": response.status_code, "data": body.get("data") if isinstance(body, dict) else None}


def main() -> None:
    """验证 student1 的既有历史，不写入任何测评或学习状态。

    :returns: None。
    :raises RuntimeError: 运行环境或接口数据不符合预期。
    """
    if os.getenv("DEMO_MODE", "").lower() not in {"1", "true", "yes", "on"}:
        raise RuntimeError("只允许在独立演示容器验证")
    if os.getenv("KT_USE_GPU", "").lower() not in {"0", "false", "no", "off"}:
        raise RuntimeError("当前 KT 配置并非 CPU")
    student = User.objects.get(username="student1")
    course = Course.objects.get(name="大数据技术与应用")
    rows = list(AnswerHistory.objects.filter(user=student, course=course).order_by("answered_at", "id")
                .values("question_id", "knowledge_point_id", "is_correct"))
    history = [
        {
            "question_id": row["question_id"],
            "knowledge_point_id": row["knowledge_point_id"],
            "correct": int(bool(row["is_correct"])),
        }
        for row in rows if row["knowledge_point_id"]
    ]
    point_ids = list(KnowledgePoint.objects.filter(course=course, is_published=True).order_by("order", "id")
                     .values_list("id", flat=True))
    info, info_ms = timed(knowledge_tracing_facade.get_model_info)
    prediction, prediction_ms = timed(lambda: knowledge_tracing_facade.predict_mastery(
        user_id=student.id,
        course_id=course.id,
        answer_history=history,
        knowledge_points=point_ids,
    ))
    raw_predictions = prediction.get("predictions") or {}
    predictions = {int(key): float(value) for key, value in raw_predictions.items()}
    recommendation_api, recommendation_ms = timed(lambda: call_kt_api(
        kt_recommendations,
        student,
        {"course_id": course.id, "predictions": predictions, "threshold": 0.6},
    ))
    with patch("ai_services.api.kt.knowledge_tracing_facade.predict_mastery", side_effect=RuntimeError("模拟模型不可用")):
        forced_api, forced_ms = timed(lambda: call_kt_api(
            kt_predict,
            student,
            {"course_id": course.id, "answer_history": history, "knowledge_points": point_ids},
        ))

    kt_model = (info.get("models") or {}).get("mefkt") or {}
    runtime = kt_model.get("runtime_info") or {}
    rates = list(predictions.values())
    recommendations = (recommendation_api.get("data") or {}).get("recommendations") or []
    forced_data = forced_api.get("data") or {}
    report = {
        "course": course.name,
        "student": student.username,
        "cpu_requested": not bool(info.get("use_gpu")),
        "model_info": {
            "name": kt_model.get("name"),
            "local_bundle_available": kt_model.get("is_local_available"),
            "enabled": kt_model.get("is_enabled"),
            "runtime": runtime,
            "mode": info.get("prediction_mode"),
            "duration_ms": info_ms,
        },
        "prediction": {
            "model_type": prediction.get("model_type"),
            "active_models": prediction.get("active_models"),
            "answer_count": len(history),
            "point_count": len(point_ids),
            "predicted_count": len(predictions),
            "min_rate": min(rates) if rates else None,
            "max_rate": max(rates) if rates else None,
            "average_rate": round(sum(rates) / len(rates), 4) if rates else None,
            "duration_ms": prediction_ms,
        },
        "recommendation_api": {
            "http_status": recommendation_api["http_status"],
            "generation_source": (recommendation_api.get("data") or {}).get("generation_source"),
            "count": len(recommendations),
            "first_three": recommendations[:3],
            "duration_ms": recommendation_ms,
        },
        "forced_failure_api": {
            "http_status": forced_api["http_status"],
            "model_type": forced_data.get("model_type"),
            "generation_source": forced_data.get("generation_source"),
            "demo_fallback": forced_data.get("demo_fallback"),
            "predicted_count": len(forced_data.get("predictions") or {}),
            "duration_ms": forced_ms,
        },
    }
    print(json.dumps(report, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
