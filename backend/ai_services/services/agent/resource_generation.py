#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
A3 个性化学习资源生成服务。
@Project : adaptive-edu
@File : resource_generation.py
@Author : Qintsg
@Date : 2026-06-05 00:00
'''

from __future__ import annotations

import json
from typing import Any

from django.db import transaction
from django.utils import timezone

from ai_services.models import AgentRun, GeneratedLearningResource
from ai_services.services.agent.profile_dialog import ProfileDialogService
from ai_services.services.agent.quality_guard import AgentQualityGuard
from ai_services.services.agent.schemas import (
    DEFAULT_RESOURCE_TYPES,
    RESOURCE_TYPE_LABELS,
    RESOURCE_TYPES,
)
from ai_services.services.agent.trace import build_default_agent_trace
from knowledge.models import KnowledgeMastery, KnowledgePoint, Resource


class ResourceGenerationService:
    """个性化学习资源生成服务。"""

    def __init__(self, user: object, course: object):
        """
        初始化服务。

        :param user: 当前学生。
        :param course: 当前课程。
        :return: None。
        """
        self.user = user
        self.course = course

    def generate_resources(
        self,
        *,
        target: str,
        knowledge_point_id: object | None = None,
        profile: dict[str, Any] | None = None,
        resource_types: list[str] | None = None,
        run_type: str = "resource_generation",
    ) -> dict[str, Any]:
        """
        生成并保存个性化学习资源。

        :param target: 学习目标。
        :param knowledge_point_id: 可选知识点 ID。
        :param profile: 调用方提供的画像快照。
        :param resource_types: 期望生成的资源类型列表。
        :param run_type: AgentRun 运行类型。
        :return: 资源生成结果。
        """
        normalized_target = str(target or "").strip()
        selected_types = self._normalize_resource_types(resource_types)
        knowledge_point = self._resolve_knowledge_point(knowledge_point_id)
        profile_snapshot = self._build_profile_snapshot(profile)
        evidence, warnings = self._collect_evidence(knowledge_point, normalized_target)
        normalized_run_type = run_type if run_type in {"resource_generation", "learning_package"} else "resource_generation"

        started_at = timezone.now()
        with transaction.atomic():
            run = AgentRun.objects.create(
                user=self.user,
                course=self.course,
                run_type=normalized_run_type,
                status="running",
                input_text=normalized_target,
                profile_snapshot=profile_snapshot,
                started_at=started_at,
            )
            payloads = [
                self._build_resource_payload(
                    resource_type=resource_type,
                    target=normalized_target,
                    knowledge_point=knowledge_point,
                    profile_snapshot=profile_snapshot,
                    evidence=evidence,
                )
                for resource_type in selected_types
            ]
            resources = [
                GeneratedLearningResource.objects.create(
                    user=self.user,
                    course=self.course,
                    knowledge_point=knowledge_point,
                    agent_run=run,
                    resource_type=payload["resource_type"],
                    title=payload["title"],
                    content=payload["content"],
                    evidence=evidence,
                    profile_snapshot=profile_snapshot,
                    metadata=payload["metadata"],
                    status="completed",
                )
                for payload in payloads
            ]
            serialized_resources = [serialize_generated_resource(resource) for resource in resources]
            quality_report = AgentQualityGuard().validate_resources(resources, required_types=selected_types)
            merged_warnings = list(dict.fromkeys(warnings + quality_report.get("warnings", [])))
            agent_trace = build_default_agent_trace(
                profile_complete=len([value for value in profile_snapshot.values() if value]) >= 6,
                evidence_count=len(evidence),
                resource_count=len(resources),
                warnings=merged_warnings,
            )
            run.status = "completed"
            run.agent_trace = agent_trace
            run.result_payload = {
                "target": normalized_target,
                "profile": profile_snapshot,
                "resources": serialized_resources,
                "resource_types": selected_types,
                "quality_report": quality_report,
                "warnings": merged_warnings,
            }
            run.finished_at = timezone.now()
            run.save(
                update_fields=[
                    "status",
                    "agent_trace",
                    "result_payload",
                    "finished_at",
                    "updated_at",
                ]
            )

        return {
            "run_id": run.id,
            "status": run.status,
            "target": normalized_target,
            "profile": profile_snapshot,
            "agent_trace": agent_trace,
            "resources": serialized_resources,
            "resource_types": selected_types,
            "quality_report": quality_report,
            "warnings": merged_warnings,
        }

    def _normalize_resource_types(self, resource_types: list[str] | None) -> list[str]:
        """
        规整资源类型，默认至少返回 5 类。

        :param resource_types: 调用方资源类型。
        :return: 资源类型列表。
        """
        selected = [
            str(resource_type)
            for resource_type in (resource_types or DEFAULT_RESOURCE_TYPES)
            if str(resource_type) in RESOURCE_TYPES
        ]
        for resource_type in DEFAULT_RESOURCE_TYPES:
            if len(selected) >= 5:
                break
            if resource_type not in selected:
                selected.append(resource_type)
        return selected[:6]

    def _resolve_knowledge_point(self, knowledge_point_id: object | None) -> KnowledgePoint | None:
        """
        解析并校验知识点。

        :param knowledge_point_id: 知识点 ID。
        :return: 知识点或 None。
        """
        if not knowledge_point_id:
            return None
        try:
            parsed_point_id = int(knowledge_point_id)
        except (TypeError, ValueError):
            return None
        return KnowledgePoint.objects.filter(id=parsed_point_id, course=self.course).first()

    def _build_profile_snapshot(self, profile: dict[str, Any] | None) -> dict[str, Any]:
        """
        合并调用方画像和现有画像上下文。

        :param profile: 调用方画像。
        :return: 画像快照。
        """
        existing = ProfileDialogService(self.user, self.course)._build_existing_profile_context()
        snapshot = dict(existing)
        if isinstance(profile, dict):
            snapshot.update({key: value for key, value in profile.items() if value not in (None, "", [])})
        return snapshot

    def _collect_evidence(
        self,
        knowledge_point: KnowledgePoint | None,
        target: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """
        收集课程知识点和已有资源证据。

        :param knowledge_point: 当前知识点。
        :param target: 学习目标。
        :return: evidence 与 warnings。
        """
        evidence: list[dict[str, Any]] = []
        warnings: list[str] = []
        if knowledge_point:
            evidence.append(
                {
                    "source_type": "knowledge_point",
                    "id": knowledge_point.id,
                    "title": knowledge_point.name,
                    "summary": knowledge_point.description or knowledge_point.teaching_goal or knowledge_point.chapter or "",
                }
            )
            related_resources = Resource.objects.filter(
                course=self.course,
                is_visible=True,
                knowledge_points=knowledge_point,
            ).order_by("sort_order", "id")[:5]
        else:
            related_resources = Resource.objects.filter(
                course=self.course,
                is_visible=True,
            ).filter(title__icontains=target[:20] if target else "").order_by("sort_order", "id")[:5]
            if not related_resources:
                related_resources = Resource.objects.filter(course=self.course, is_visible=True).order_by("sort_order", "id")[:5]

        for resource in related_resources:
            evidence.append(
                {
                    "source_type": "course_resource",
                    "id": resource.id,
                    "title": resource.title,
                    "summary": resource.description or resource.chapter_number or resource.resource_type,
                    "resource_type": resource.resource_type,
                }
            )

        if not evidence:
            warnings.append("未检索到课程知识库证据，已使用模板化兜底内容。")
        elif len(evidence) < 2:
            warnings.append("课程证据较少，生成内容需结合教师材料复核。")
        return evidence, warnings

    def _build_resource_payload(
        self,
        *,
        resource_type: str,
        target: str,
        knowledge_point: KnowledgePoint | None,
        profile_snapshot: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        构造单个资源内容。

        :param resource_type: 资源类型。
        :param target: 学习目标。
        :param knowledge_point: 当前知识点。
        :param profile_snapshot: 画像快照。
        :param evidence: 证据列表。
        :return: 资源 payload。
        """
        point_name = knowledge_point.name if knowledge_point else target or self.course.name
        title = f"{point_name}{RESOURCE_TYPE_LABELS[resource_type]}"
        builders = {
            "explanation": self._build_explanation,
            "mindmap": self._build_mindmap,
            "quiz": self._build_quiz,
            "reading": self._build_reading,
            "coding_case": self._build_coding_case,
            "video_script": self._build_video_script,
        }
        content_payload = builders[resource_type](point_name, target, profile_snapshot, evidence)
        content_text = (
            content_payload
            if isinstance(content_payload, str)
            else json.dumps(content_payload, ensure_ascii=False, indent=2)
        )
        return {
            "resource_type": resource_type,
            "title": title,
            "content": content_text,
            "metadata": {
                "payload": content_payload,
                "target": target,
                "recommendation_reason": self._build_recommendation_reason(resource_type, profile_snapshot),
            },
        }

    def _build_explanation(
        self,
        point_name: str,
        target: str,
        profile_snapshot: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> str:
        """
        构造讲解文档。

        :return: Markdown 文档。
        """
        weakness = profile_snapshot.get("weaknesses") or "当前薄弱点"
        evidence_text = "\n".join([f"- {item['title']}: {item.get('summary', '')}" for item in evidence[:3]]) or "- 暂无课程证据"
        return (
            f"## {point_name} 核心讲解\n\n"
            f"学习目标：{target or f'掌握 {point_name} 的基础概念和应用方法'}。\n\n"
            f"针对画像中的薄弱点（{weakness}），建议先理解概念边界，再通过案例和练习巩固。\n\n"
            "### 关键要点\n"
            f"1. 明确 {point_name} 的使用场景。\n"
            "2. 对照课程资料梳理概念之间的前后关系。\n"
            "3. 完成一组基础练习后再进入综合应用。\n\n"
            "### 课程证据\n"
            f"{evidence_text}"
        )

    def _build_mindmap(
        self,
        point_name: str,
        target: str,
        profile_snapshot: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        构造思维导图。

        :return: 思维导图 payload。
        """
        _ = target, profile_snapshot
        evidence_nodes = [item["title"] for item in evidence[:4]] or ["课程资料待补充"]
        mermaid_lines = ["mindmap", f"  root(({point_name}))", "    概念理解", "    操作步骤", "    常见误区", "    练习巩固"]
        for title in evidence_nodes:
            mermaid_lines.append(f"    证据::{title}")
        return {
            "mermaid": "\n".join(mermaid_lines),
            "nodes": [{"label": title, "type": "evidence"} for title in evidence_nodes],
        }

    def _build_quiz(
        self,
        point_name: str,
        target: str,
        profile_snapshot: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        构造练习题。

        :return: 练习题 payload。
        """
        _ = target, profile_snapshot, evidence
        return {
            "questions": [
                {
                    "type": "single_choice",
                    "stem": f"学习 {point_name} 时，第一步最应该关注什么？",
                    "options": ["概念和适用场景", "跳过基础直接做综合题", "只记忆结论", "忽略课程资料"],
                    "answer": "A",
                    "analysis": "先明确概念和适用场景，有助于后续建立稳定的知识结构。",
                    "difficulty": "easy",
                },
                {
                    "type": "short_answer",
                    "stem": f"请用自己的话说明 {point_name} 与当前课程目标的关系。",
                    "answer": f"{point_name} 是完成当前学习目标的重要组成部分，需要结合课程资料和练习理解。",
                    "analysis": "开放题用于检查是否能把知识点放回课程上下文。",
                    "difficulty": "medium",
                },
            ]
        }

    def _build_reading(
        self,
        point_name: str,
        target: str,
        profile_snapshot: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        构造拓展阅读。

        :return: 阅读资源 payload。
        """
        _ = target, profile_snapshot
        items = [
            {
                "title": item["title"],
                "url": "",
                "reason": f"该课程资源可作为 {point_name} 的本地证据材料。",
                "difficulty": "beginner",
                "source_type": item["source_type"],
            }
            for item in evidence[:3]
        ]
        if not items:
            items.append(
                {
                    "title": f"{point_name} 课程资料复习清单",
                    "url": "",
                    "reason": "暂无外部链接，建议优先使用教师提供的课程资料。",
                    "difficulty": "beginner",
                    "source_type": "fallback",
                }
            )
        return {"items": items}

    def _build_coding_case(
        self,
        point_name: str,
        target: str,
        profile_snapshot: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        构造代码实操案例。

        :return: 代码案例 payload。
        """
        _ = target, profile_snapshot, evidence
        return {
            "scenario": f"围绕 {point_name} 完成一个最小可运行练习。",
            "steps": ["阅读课程资料", "写出输入输出假设", "实现核心步骤", "对照结果复盘"],
            "code": "def practice_case():\n    notes = '结合课程资料完成一次最小实操'\n    return notes\n\nprint(practice_case())",
            "expected_output": "结合课程资料完成一次最小实操",
        }

    def _build_video_script(
        self,
        point_name: str,
        target: str,
        profile_snapshot: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        构造视频脚本。

        :return: 视频脚本 payload。
        """
        _ = target, profile_snapshot, evidence
        return {
            "duration_seconds": 90,
            "shots": [
                {"time": "0-20s", "visual": "展示知识点标题和学习目标", "narration": f"今天快速理解 {point_name}。"},
                {"time": "20-60s", "visual": "展示概念关系和示例", "narration": "结合课程证据说明核心概念。"},
                {"time": "60-90s", "visual": "展示练习任务", "narration": "通过一个小练习巩固本节内容。"},
            ],
            "visual_notes": ["使用课程图谱节点作为背景", "关键术语用高亮标注"],
        }

    def _build_recommendation_reason(self, resource_type: str, profile_snapshot: dict[str, Any]) -> str:
        """
        构造推荐理由。

        :param resource_type: 资源类型。
        :param profile_snapshot: 画像快照。
        :return: 推荐理由。
        """
        preferred = profile_snapshot.get("preferred_resource")
        if preferred and resource_type in str(preferred):
            return "该资源类型匹配学生画像中的资源偏好。"
        return "该资源用于补齐当前目标所需的概念理解、练习和应用闭环。"


def serialize_generated_resource(resource: GeneratedLearningResource) -> dict[str, Any]:
    """
    序列化生成资源。

    :param resource: 生成资源模型。
    :return: API payload。
    """
    return {
        "resource_id": resource.id,
        "resource_type": resource.resource_type,
        "title": resource.title,
        "content": resource.content,
        "content_payload": resource.metadata.get("payload", {}),
        "evidence": resource.evidence,
        "profile_snapshot": resource.profile_snapshot,
        "metadata": resource.metadata,
        "knowledge_point_id": resource.knowledge_point_id,
        "knowledge_point_name": resource.knowledge_point.name if resource.knowledge_point_id else "",
        "status": resource.status,
        "created_at": resource.created_at.isoformat() if resource.created_at else None,
    }
