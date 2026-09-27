#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""答辩演示模式的课程数据回退；所有结果都标注来源。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from django.conf import settings
from django.db.models import Q

from knowledge.models import KnowledgeMastery, KnowledgePoint, ProfileSummary, Resource


DEMO_SOURCE = "demo_course_rules"


def demo_mode_enabled() -> bool:
    """读取显式演示开关。

    :returns: 是否启用演示模式。
    """
    return bool(getattr(settings, "DEMO_MODE", False))


def mark_demo_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """给本地规则结果加来源标记。

    :param payload: 已生成的结果。
    :returns: 带来源标记的副本。
    """
    return {**payload, "demo_fallback": True, "generation_source": DEMO_SOURCE}


def course_mastery_data(user: object, course_id: int) -> list[dict[str, object]]:
    """读取课程知识点及学生实际掌握度。

    :param user: 当前学生。
    :param course_id: 课程 ID。
    :returns: 有序知识点数据。
    """
    rates = dict(
        KnowledgeMastery.objects.filter(user=user, course_id=course_id)
        .values_list("knowledge_point_id", "mastery_rate")
    )
    points = KnowledgePoint.objects.filter(course_id=course_id, is_published=True).order_by("order", "id")
    return [
        {
            "point_id": point.id,
            "knowledge_point_id": point.id,
            "point_name": point.name,
            "mastery_rate": float(rates.get(point.id, 0.5)),
        }
        for point in points
    ]


def build_demo_profile(user: object, course_id: int) -> dict[str, object]:
    """根据课程掌握度保存一份可继续学习的画像。

    :param user: 当前学生。
    :param course_id: 课程 ID。
    :returns: 与画像接口兼容的结果。
    """
    mastery = course_mastery_data(user, course_id)
    average = sum(float(item["mastery_rate"]) for item in mastery) / len(mastery) if mastery else 0
    weak = [str(item["point_name"]) for item in mastery if float(item["mastery_rate"]) < 0.6]
    strong = [str(item["point_name"]) for item in mastery if float(item["mastery_rate"]) >= 0.8]
    summary = f"已记录 {len(mastery)} 个课程知识点，当前平均掌握度为 {average:.0%}。"
    weakness = "、".join(weak[:3]) if weak else "暂无明显薄弱知识点"
    suggestion = f"先复习{weakness}，再完成相应的课程练习。" if weak else "继续学习课程资源，并通过练习检查掌握情况。"
    ProfileSummary.objects.update_or_create(
        user=user,
        course_id=course_id,
        defaults={"summary": summary, "weakness": weakness, "suggestion": suggestion},
    )
    return mark_demo_payload({
        "success": True,
        "course_id": course_id,
        "summary": summary,
        "weakness": weakness,
        "strength": strong[:3],
        "suggestion": suggestion,
        "kt_enhanced": False,
        "cached": False,
    })


def apply_verified_profile(user: object, course_id: int, payload: Mapping[str, object]) -> dict[str, object]:
    """保存彩排画像，供后续学习画像页面读取。

    :param user: 当前学生。
    :param course_id: 课程 ID。
    :param payload: 同一学生和课程的真实彩排结果。
    :returns: 可供接口返回的画像。
    """
    summary = str(payload.get("summary") or "")
    raw_weakness = payload.get("weakness") or ""
    weakness = "、".join(str(item) for item in raw_weakness) if isinstance(raw_weakness, list) else str(raw_weakness)
    suggestion = str(payload.get("suggestion") or "")
    ProfileSummary.objects.update_or_create(
        user=user,
        course_id=course_id,
        defaults={"summary": summary, "weakness": weakness, "suggestion": suggestion},
    )
    return {**payload, "success": True, "demo_fallback": True, "generation_source": "verified_ai_preset"}


def build_demo_path_plan(user: object, course_id: int) -> dict[str, object]:
    """用真实课程掌握度构造路径规划建议。

    :param user: 当前学生。
    :param course_id: 课程 ID。
    :returns: 与路径规划接口兼容的结果。
    """
    from ai_services.services.llm.profile_path_support import build_path_fallback

    result = build_path_fallback(course_mastery_data(user, course_id))
    return mark_demo_payload({
        "reason": result.get("reason", ""),
        "suggested_nodes": result.get("nodes", []),
    })


def build_demo_learning_path(user: object, course: object) -> object:
    """跳过 KT 服务，按已有掌握度生成持久化路径。

    :param user: 当前学生。
    :param course: 当前课程。
    :returns: 学习路径模型。
    """
    from ai_services.services.path.service import PathService

    return PathService().generate_path(
        user,
        course,
        mastery_data=course_mastery_data(user, int(course.id)),
    )


def build_demo_chat(course_id: int, question: str, point_id: int | None = None) -> dict[str, object]:
    """从当前课程知识点与资源构造本地问答。

    :param course_id: 当前课程 ID。
    :param question: 学生问题。
    :param point_id: 可选的知识点 ID。
    :returns: 已标明本地规则来源的答复。
    """
    points = list(KnowledgePoint.objects.filter(course_id=course_id, is_published=True).order_by("order", "id")[:150])
    point = next((item for item in points if item.id == point_id), None)
    if point is None:
        point = next((item for item in sorted(points, key=lambda item: len(item.name), reverse=True) if item.name in question), None)
    if point is None:
        point = points[0] if points else None
    if point is None:
        reply = "当前课程还没有可用的知识点资料，请先查看课程资源或联系教师。"
        return mark_demo_payload({"reply": reply, "sources": [], "mode": "demo_fallback", "matched_point": None})

    description = (point.description or point.introduction or point.teaching_goal or "").strip()
    resource = Resource.objects.filter(course_id=course_id, is_visible=True, knowledge_points=point).order_by("sort_order", "id").first()
    reply = f"根据课程已有内容，{point.name}：{description or '建议先理解基本概念和适用场景。'}"
    if resource:
        reply += f"可以接着学习《{resource.title}》，再用配套练习检查理解。"
    else:
        reply += "建议结合课程题目练习，再查看知识图谱中的关联知识点。"
    return mark_demo_payload({
        "reply": reply,
        "sources": [{"title": resource.title, "resource_id": resource.id}] if resource else [],
        "mode": "demo_fallback",
        "matched_point": {"point_id": point.id, "point_name": point.name},
        "related_points": {"prerequisites": [], "postrequisites": []},
    })


def build_demo_search(user: object, course_id: int, query: str, limit: int) -> dict[str, object]:
    """用课程数据库中的知识点回答图谱检索。

    :param user: 当前学生。
    :param course_id: 课程 ID。
    :param query: 搜索词。
    :param limit: 返回上限。
    :returns: 搜索结果。
    """
    points = KnowledgePoint.objects.filter(course_id=course_id, is_published=True).filter(
        Q(name__icontains=query) | Q(description__icontains=query)
    ).order_by("order", "id")[:limit]
    rates = dict(KnowledgeMastery.objects.filter(user=user, course_id=course_id).values_list("knowledge_point_id", "mastery_rate"))
    return mark_demo_payload({
        "query": query,
        "retrieval_mode": "demo_course_index",
        "matched_points": [
            {
                "point_id": point.id,
                "point_name": point.name,
                "chapter": point.chapter,
                "description": point.description,
                "mastery_rate": float(rates.get(point.id, 0)),
                "prerequisites": [],
                "postrequisites": [],
            }
            for point in points
        ],
    })


def build_demo_feedback(
    title: str,
    score: float,
    total_score: float,
    mistakes: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """从真实评分和错题生成规则反馈。

    :param title: 测评或作业标题。
    :param score: 实际得分。
    :param total_score: 满分。
    :param mistakes: 实际错题。
    :returns: 带来源标记的反馈。
    """
    from ai_services.services.llm.feedback_kt_support import FeedbackReportInput, build_feedback_report_fallback

    payload = build_feedback_report_fallback(FeedbackReportInput(
        exam_info={"title": title, "type": "课程测评"},
        score=score,
        total_score=total_score,
        mistakes=mistakes,
        kt_predictions=None,
    ))
    return mark_demo_payload(payload)


def build_demo_kt_prediction(
    user_id: int,
    course_id: int,
    answer_history: Sequence[Mapping[str, object]],
    knowledge_points: Sequence[object] | None = None,
) -> dict[str, object]:
    """用真实答题和课程掌握度生成 KT 演示预测。

    :param user_id: 学生 ID。
    :param course_id: 课程 ID。
    :param answer_history: 当前请求的答题历史。
    :param knowledge_points: 指定知识点 ID。
    :returns: KT 接口兼容的规则预测。
    """
    existing_rates = dict(KnowledgeMastery.objects.filter(
        user_id=user_id, course_id=course_id,
    ).values_list("knowledge_point_id", "mastery_rate"))
    point_ids = [int(point_id) for point_id in (knowledge_points or []) if str(point_id).isdigit()]
    if not point_ids:
        point_ids = list(KnowledgePoint.objects.filter(
            course_id=course_id, is_published=True,
        ).values_list("id", flat=True))
    counts: dict[int, list[int]] = {point_id: [0, 0] for point_id in point_ids}
    for answer in answer_history:
        raw_point_id = answer.get("knowledge_point_id")
        if not str(raw_point_id).isdigit():
            continue
        point_id = int(str(raw_point_id))
        if point_id not in counts:
            continue
        counts[point_id][0] += 1
        counts[point_id][1] += int(bool(answer.get("correct", answer.get("is_correct", False))))
    predictions = {
        point_id: round(
            (correct + 1) / (total + 2) if total else float(existing_rates.get(point_id, 0.5)),
            4,
        )
        for point_id, (total, correct) in counts.items()
    }
    return mark_demo_payload({
        "predictions": predictions,
        "confidence": 0.5,
        "model_type": "demo_course_rules",
        "analysis": "依据当前答题和课程记录计算掌握度。",
        "answer_count": len(answer_history),
    })


def build_demo_kt_recommendations(
    predictions: Mapping[object, object], threshold: float,
) -> list[dict[str, object]]:
    """按掌握度阈值生成确定性复习建议。

    :param predictions: 知识点掌握度预测。
    :param threshold: 需要复习的阈值。
    :returns: 学习建议列表。
    """
    recommendations: list[dict[str, object]] = []
    for raw_point_id, raw_rate in predictions.items():
        try:
            point_id = int(raw_point_id)
            rate = float(raw_rate)
        except (TypeError, ValueError):
            continue
        if rate >= threshold:
            continue
        recommendations.append({
            "knowledge_point_id": point_id,
            "current_mastery": rate,
            "target_mastery": threshold,
            "priority": "high" if rate < 0.4 else "medium",
            "suggestion": f"建议复习该知识点并完成配套练习，当前掌握度为 {rate:.0%}。",
            "generation_source": DEMO_SOURCE,
        })
    return sorted(recommendations, key=lambda item: float(item["current_mastery"]))
