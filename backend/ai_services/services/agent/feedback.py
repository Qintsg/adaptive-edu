#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
A3 生成资源反馈与效果汇总服务。
@Project : adaptive-edu
@File : feedback.py
@Author : Qintsg
@Date : 2026-06-07 00:00
'''

from __future__ import annotations

from typing import Any

from django.db.models import Avg, Count
from django.utils import timezone

from ai_services.models import GeneratedLearningResource, GeneratedResourceFeedback
from ai_services.services.agent.learning_package import build_mastery_update_summary
from learning.models import NodeProgress


class GeneratedResourceFeedbackService:
    """生成资源反馈与画像/路径更新闭环服务。"""

    def __init__(self, user: object, course: object):
        """
        初始化服务。

        :param user: 当前学生。
        :param course: 当前课程。
        :return: None。
        """
        self.user = user
        self.course = course

    def submit_feedback(
        self,
        *,
        resource_id: object,
        completed: bool,
        rating: object | None = None,
        usefulness: str = "neutral",
        difficulty: str = "moderate",
        feedback: str = "",
        quiz_result: dict[str, Any] | None = None,
        time_spent_seconds: object | None = None,
    ) -> dict[str, Any] | None:
        """
        提交或更新生成资源反馈。

        :param resource_id: 生成资源 ID。
        :param completed: 是否完成。
        :param rating: 评分。
        :param usefulness: 有用性。
        :param difficulty: 难度感受。
        :param feedback: 文本反馈。
        :param quiz_result: 练习结果。
        :param time_spent_seconds: 学习耗时。
        :return: 反馈结果或 None。
        """
        resource = self._get_owned_resource(resource_id)
        if resource is None:
            return None

        parsed_rating = self._normalize_rating(rating)
        parsed_seconds = self._normalize_seconds(time_spent_seconds)
        normalized_usefulness = usefulness if usefulness in {"useful", "neutral", "not_useful"} else "neutral"
        normalized_difficulty = difficulty if difficulty in {"easy", "moderate", "hard"} else "moderate"
        feedback_record, created = GeneratedResourceFeedback.objects.update_or_create(
            resource=resource,
            user=self.user,
            defaults={
                "completed": bool(completed),
                "rating": parsed_rating,
                "usefulness": normalized_usefulness,
                "difficulty": normalized_difficulty,
                "feedback": str(feedback or "")[:2000],
                "quiz_result": quiz_result if isinstance(quiz_result, dict) else {},
                "time_spent_seconds": parsed_seconds,
            },
        )
        node_update = self._mark_bound_resource_progress(resource, completed=bool(completed))
        related_resources = list(
            GeneratedLearningResource.objects.filter(
                agent_run=resource.agent_run,
                user=self.user,
                course=self.course,
            )
        )
        update_summary = build_mastery_update_summary(
            user=self.user,
            course=self.course,
            resources=related_resources,
        )
        return {
            "feedback": self._serialize_feedback(feedback_record),
            "created": created,
            "resource": {
                "resource_id": resource.id,
                "title": resource.title,
                "resource_type": resource.resource_type,
            },
            "node_update": node_update,
            "update_summary": update_summary,
        }

    def get_effect_summary(self) -> dict[str, Any]:
        """
        汇总当前课程生成资源学习效果。

        :return: 效果摘要。
        """
        resources = GeneratedLearningResource.objects.filter(user=self.user, course=self.course)
        feedback_records = GeneratedResourceFeedback.objects.filter(
            user=self.user,
            resource__course=self.course,
        )
        aggregate = feedback_records.aggregate(
            feedback_count=Count("id"),
            average_rating=Avg("rating"),
        )
        completed_count = feedback_records.filter(completed=True).count()
        useful_count = feedback_records.filter(usefulness="useful").count()
        total_resources = resources.count()
        recent_feedback = [
            self._serialize_feedback(record)
            for record in feedback_records.select_related("resource").order_by("-created_at")[:8]
        ]
        update_summary = build_mastery_update_summary(
            user=self.user,
            course=self.course,
            resources=list(resources.select_related("knowledge_point")[:50]),
        )
        return {
            "resource_count": total_resources,
            "feedback_count": aggregate["feedback_count"] or 0,
            "completed_count": completed_count,
            "completion_rate": round(completed_count / total_resources, 3) if total_resources else 0,
            "average_rating": round(float(aggregate["average_rating"] or 0), 2),
            "useful_count": useful_count,
            "recent_feedback": recent_feedback,
            "update_summary": update_summary,
        }

    def _get_owned_resource(self, resource_id: object) -> GeneratedLearningResource | None:
        """
        获取当前学生拥有的生成资源。

        :param resource_id: 生成资源 ID。
        :return: 资源或 None。
        """
        try:
            parsed_resource_id = int(resource_id)
        except (TypeError, ValueError):
            return None
        return GeneratedLearningResource.objects.filter(
            id=parsed_resource_id,
            user=self.user,
            course=self.course,
        ).select_related("agent_run", "knowledge_point").first()

    def _normalize_rating(self, rating: object | None) -> int | None:
        """
        规整评分。

        :param rating: 原始评分。
        :return: 1-5 评分或 None。
        """
        if rating in (None, ""):
            return None
        try:
            parsed_rating = int(rating)
        except (TypeError, ValueError):
            return None
        return max(1, min(parsed_rating, 5))

    def _normalize_seconds(self, seconds: object | None) -> int | None:
        """
        规整学习耗时。

        :param seconds: 原始秒数。
        :return: 非负秒数或 None。
        """
        if seconds in (None, ""):
            return None
        try:
            parsed_seconds = int(seconds)
        except (TypeError, ValueError):
            return None
        return max(0, parsed_seconds)

    def _mark_bound_resource_progress(
        self,
        resource: GeneratedLearningResource,
        *,
        completed: bool,
    ) -> dict[str, Any]:
        """
        将反馈同步到绑定节点的 NodeProgress.extra_data。

        :param resource: 生成资源。
        :param completed: 是否完成。
        :return: 节点更新摘要。
        """
        binding = (resource.metadata or {}).get("path_binding", {})
        node_id = binding.get("node_id") if isinstance(binding, dict) else None
        if not node_id:
            return {"updated": False, "reason": "资源尚未绑定到学习路径节点"}

        progress = NodeProgress.objects.filter(node_id=node_id, user=self.user).first()
        if progress is None:
            progress = NodeProgress.objects.create(node_id=node_id, user=self.user)
        extra_data = dict(progress.extra_data or {})
        generated_resources = extra_data.get("generated_resources", [])
        if not isinstance(generated_resources, list):
            generated_resources = []

        updated_items: list[dict[str, Any]] = []
        resource_seen = False
        for item in generated_resources:
            if not isinstance(item, dict):
                continue
            if item.get("resource_id") == resource.id:
                resource_seen = True
                item = {
                    **item,
                    "status": "completed" if completed else "in_progress",
                    "completed_at": timezone.now().isoformat() if completed else "",
                }
            updated_items.append(item)
        if not resource_seen:
            updated_items.append(
                {
                    "resource_id": resource.id,
                    "resource_type": resource.resource_type,
                    "title": resource.title,
                    "status": "completed" if completed else "in_progress",
                    "completed_at": timezone.now().isoformat() if completed else "",
                }
            )
        extra_data["generated_resources"] = updated_items
        progress.extra_data = extra_data
        if completed:
            completed_generated_ids = {
                item.get("resource_id")
                for item in updated_items
                if isinstance(item, dict) and item.get("status") == "completed"
            }
            progress.completed_resources = list(
                dict.fromkeys([*progress.completed_resources, *[f"generated:{resource_id}" for resource_id in completed_generated_ids]])
            )
        progress.save(update_fields=["extra_data", "completed_resources", "updated_at"])
        return {
            "updated": True,
            "node_id": node_id,
            "resource_status": "completed" if completed else "in_progress",
        }

    def _serialize_feedback(self, feedback_record: GeneratedResourceFeedback) -> dict[str, Any]:
        """
        序列化反馈记录。

        :param feedback_record: 反馈模型。
        :return: API payload。
        """
        return {
            "feedback_id": feedback_record.id,
            "resource_id": feedback_record.resource_id,
            "resource_title": feedback_record.resource.title if feedback_record.resource_id else "",
            "completed": feedback_record.completed,
            "rating": feedback_record.rating,
            "usefulness": feedback_record.usefulness,
            "difficulty": feedback_record.difficulty,
            "feedback": feedback_record.feedback,
            "quiz_result": feedback_record.quiz_result,
            "time_spent_seconds": feedback_record.time_spent_seconds,
            "created_at": feedback_record.created_at.isoformat() if feedback_record.created_at else None,
        }
