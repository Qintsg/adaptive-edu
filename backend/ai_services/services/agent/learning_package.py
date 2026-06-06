#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
A3 学习资源包生成与学习路径绑定服务。
@Project : adaptive-edu
@File : learning_package.py
@Author : Qintsg
@Date : 2026-06-07 00:00
'''

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from ai_services.models import AgentRun, GeneratedLearningResource
from ai_services.services.agent.profile_dialog import ProfileDialogService
from ai_services.services.agent.quality_guard import AgentQualityGuard
from ai_services.services.agent.resource_generation import (
    ResourceGenerationService,
    serialize_generated_resource,
)
from ai_services.services.agent.schemas import DEFAULT_RESOURCE_TYPES
from ai_services.services.agent.trace import build_default_agent_trace, build_trace_item
from knowledge.models import KnowledgeMastery, KnowledgePoint
from learning.models import LearningPath, NodeProgress, PathNode


class LearningPackageService:
    """学习资源包生成、查询与路径绑定服务。"""

    def __init__(self, user: object, course: object):
        """
        初始化服务。

        :param user: 当前学生。
        :param course: 当前课程。
        :return: None。
        """
        self.user = user
        self.course = course
        self.quality_guard = AgentQualityGuard()

    def generate_learning_package(
        self,
        *,
        target: str,
        knowledge_point_id: object | None = None,
        profile: dict[str, Any] | None = None,
        resource_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        生成学习资源包并返回路径绑定建议。

        :param target: 学习目标。
        :param knowledge_point_id: 可选知识点 ID。
        :param profile: 画像快照。
        :param resource_types: 期望资源类型。
        :return: 学习包结果。
        """
        normalized_target = str(target or "").strip()
        selected_types = resource_types or DEFAULT_RESOURCE_TYPES
        profile_snapshot = self._build_profile_snapshot(profile)
        progress_events = self._build_progress_events("started")
        generation_result = ResourceGenerationService(self.user, self.course).generate_resources(
            target=normalized_target,
            knowledge_point_id=knowledge_point_id,
            profile=profile_snapshot,
            resource_types=selected_types,
            run_type="learning_package",
        )
        resources = list(
            GeneratedLearningResource.objects.filter(
                agent_run_id=generation_result["run_id"],
                user=self.user,
                course=self.course,
            )
            .select_related("knowledge_point")
            .order_by("id")
        )
        quality_report = self.quality_guard.validate_resources(
            resources,
            required_types=generation_result.get("resource_types", selected_types),
        )
        path_suggestion = self._build_path_suggestion(resources)
        warnings = list(dict.fromkeys(generation_result.get("warnings", []) + quality_report.get("warnings", [])))
        progress_events = self._build_progress_events(
            "completed" if quality_report["status"] != "failed" else "warning",
            warnings=warnings,
        )
        agent_trace = self._build_learning_package_trace(
            base_trace=generation_result.get("agent_trace", []),
            path_suggestion=path_suggestion,
            quality_report=quality_report,
            warnings=warnings,
        )

        run = AgentRun.objects.get(id=generation_result["run_id"])
        run.agent_trace = agent_trace
        run.profile_snapshot = profile_snapshot
        run.result_payload = {
            **generation_result,
            "profile": profile_snapshot,
            "quality_report": quality_report,
            "path_suggestion": path_suggestion,
            "progress_events": progress_events,
            "warnings": warnings,
        }
        run.finished_at = timezone.now()
        run.status = "completed" if quality_report["status"] != "failed" else "failed"
        run.save(update_fields=["agent_trace", "profile_snapshot", "result_payload", "finished_at", "status", "updated_at"])

        serialized_resources = [serialize_generated_resource(resource) for resource in resources]
        return {
            "run_id": run.id,
            "status": run.status,
            "target": normalized_target,
            "profile": profile_snapshot,
            "agent_trace": agent_trace,
            "progress_events": progress_events,
            "resources": serialized_resources,
            "quality_report": quality_report,
            "path_suggestion": path_suggestion,
            "warnings": warnings,
        }

    def apply_resources_to_path(
        self,
        *,
        run_id: object,
        resource_ids: list[object] | None = None,
    ) -> dict[str, Any]:
        """
        将生成资源绑定到当前学生的学习路径节点。

        :param run_id: AgentRun ID。
        :param resource_ids: 可选资源 ID 列表。
        :return: 路径绑定结果。
        """
        run = self._get_owned_run(run_id)
        if run is None:
            return {
                "ok": False,
                "error": "运行记录不存在或无权访问",
                "status_code": 404,
            }

        resources = self._load_resources_for_run(run, resource_ids)
        if not resources:
            return {
                "ok": False,
                "error": "没有可绑定的生成资源",
                "status_code": 400,
            }

        path = self._get_or_create_learning_path()
        bindings: list[dict[str, Any]] = []
        with transaction.atomic():
            for resource in resources:
                node = self._resolve_binding_node(path, resource)
                binding = self._bind_resource_to_node(resource, node)
                bindings.append(binding)

            path.is_dynamic = True
            path.ai_reason = "已将 A3 生成资源包绑定到学习路径，保留已完成节点并补齐当前学习任务。"
            path.save(update_fields=["is_dynamic", "ai_reason", "updated_at"])
            run.result_payload = {
                **(run.result_payload or {}),
                "path_binding": {
                    "path_id": path.id,
                    "bindings": bindings,
                    "applied_at": timezone.now().isoformat(),
                },
            }
            run.save(update_fields=["result_payload", "updated_at"])

        path_nodes = self._serialize_path_nodes(path)
        return {
            "ok": True,
            "path_id": path.id,
            "run_id": run.id,
            "bindings": bindings,
            "nodes": path_nodes,
            "warnings": self._build_binding_warnings(bindings),
        }

    def list_resources(
        self,
        *,
        limit: int = 30,
        resource_type: str = "",
    ) -> dict[str, Any]:
        """
        查询当前学生课程下的生成资源。

        :param limit: 最大返回数量。
        :param resource_type: 可选资源类型。
        :return: 资源列表。
        """
        normalized_limit = max(1, min(int(limit or 30), 100))
        queryset = GeneratedLearningResource.objects.filter(user=self.user, course=self.course).select_related(
            "knowledge_point", "agent_run"
        )
        if resource_type:
            queryset = queryset.filter(resource_type=resource_type)
        resources = list(queryset.order_by("-created_at", "-id")[:normalized_limit])
        return {
            "resources": [serialize_generated_resource(resource) for resource in resources],
            "count": len(resources),
        }

    def get_run_detail(self, run_id: object) -> dict[str, Any] | None:
        """
        查询当前学生课程下的 Agent 运行详情。

        :param run_id: AgentRun ID。
        :return: 运行详情或 None。
        """
        run = self._get_owned_run(run_id)
        if run is None:
            return None
        resources = list(run.generated_resources.select_related("knowledge_point").order_by("id"))
        return {
            "run_id": run.id,
            "run_type": run.run_type,
            "status": run.status,
            "input_text": run.input_text,
            "profile_snapshot": run.profile_snapshot,
            "agent_trace": run.agent_trace,
            "result_payload": run.result_payload,
            "error_message": run.error_message,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "resources": [serialize_generated_resource(resource) for resource in resources],
        }

    def complete_run(self, run_id: object) -> dict[str, Any] | None:
        """
        将 Agent 运行标记为完成，用于前端学习闭环收口。

        :param run_id: AgentRun ID。
        :return: 运行完成摘要或 None。
        """
        run = self._get_owned_run(run_id)
        if run is None:
            return None
        run.status = "completed"
        run.finished_at = run.finished_at or timezone.now()
        run.result_payload = {
            **(run.result_payload or {}),
            "student_completed_at": timezone.now().isoformat(),
        }
        run.save(update_fields=["status", "finished_at", "result_payload", "updated_at"])
        return self.get_run_detail(run.id)

    def _build_profile_snapshot(self, profile: dict[str, Any] | None) -> dict[str, Any]:
        """
        构造学习包画像快照。

        :param profile: 调用方画像。
        :return: 画像快照。
        """
        snapshot = ProfileDialogService(self.user, self.course)._build_existing_profile_context()
        if isinstance(profile, dict):
            snapshot.update({key: value for key, value in profile.items() if value not in (None, "", [])})
        return snapshot

    def _build_progress_events(
        self,
        status: str,
        *,
        warnings: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        构造同步流程进度事件。

        :param status: 当前整体状态。
        :param warnings: 警告列表。
        :return: 进度事件列表。
        """
        stage_status = "completed" if status in ("completed", "warning") else "running"
        return [
            {"stage": "profile", "status": stage_status, "percent": 15, "message": "读取学习画像与课程上下文"},
            {"stage": "knowledge", "status": stage_status, "percent": 35, "message": "检索知识点、课程资源和掌握度证据"},
            {"stage": "generation", "status": stage_status, "percent": 62, "message": "生成多类型个性化资源"},
            {"stage": "quality", "status": "warning" if warnings else stage_status, "percent": 82, "message": "执行证据和结构质量校验"},
            {"stage": "path", "status": stage_status, "percent": 100, "message": "生成学习路径绑定建议"},
        ]

    def _build_learning_package_trace(
        self,
        *,
        base_trace: list[dict[str, Any]],
        path_suggestion: dict[str, Any],
        quality_report: dict[str, Any],
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        """
        构造学习包 Agent trace。

        :param base_trace: 资源生成 trace。
        :param path_suggestion: 路径建议。
        :param quality_report: 质量报告。
        :param warnings: 警告列表。
        :return: trace 项列表。
        """
        if not base_trace:
            base_trace = build_default_agent_trace(
                profile_complete=True,
                evidence_count=0,
                resource_count=quality_report.get("resource_count", 0),
                warnings=warnings,
            )
        trace = list(base_trace)
        trace.append(
            build_trace_item(
                "package_agent",
                "completed",
                "已组装学习资源包与学习顺序",
                detail={"path_node_count": len(path_suggestion.get("candidate_nodes", []))},
            )
        )
        trace.append(
            build_trace_item(
                "quality_guard",
                self._trace_status_from_quality(quality_report["status"]),
                f"质量校验得分 {quality_report['score']}",
                detail=quality_report,
            )
        )
        return trace

    def _trace_status_from_quality(self, quality_status: str) -> str:
        """
        将质量报告状态映射为 Agent trace 标准状态。

        :param quality_status: passed/warning/failed。
        :return: completed/warning/failed。
        """
        if quality_status == "passed":
            return "completed"
        if quality_status in {"warning", "failed"}:
            return quality_status
        return "warning"

    def _build_path_suggestion(self, resources: list[GeneratedLearningResource]) -> dict[str, Any]:
        """
        构造路径绑定建议。

        :param resources: 生成资源列表。
        :return: 路径建议。
        """
        path = self._find_learning_path()
        candidate_nodes = []
        if path:
            candidate_nodes = self._serialize_path_nodes(path)
        suggested_bindings = []
        for resource in resources:
            matched_node = self._match_node_for_resource(path, resource) if path else None
            suggested_bindings.append(
                {
                    "resource_id": resource.id,
                    "resource_type": resource.resource_type,
                    "title": resource.title,
                    "suggested_node_id": matched_node.id if matched_node else None,
                    "suggested_node_title": matched_node.title if matched_node else "",
                    "reason": "按资源关联知识点匹配路径节点" if matched_node else "当前路径无对应节点，应用时会插入补充节点",
                }
            )
        return {
            "path_id": path.id if path else None,
            "candidate_nodes": candidate_nodes,
            "suggested_bindings": suggested_bindings,
            "preserve_completed": True,
        }

    def _get_owned_run(self, run_id: object) -> AgentRun | None:
        """
        获取当前学生拥有的运行记录。

        :param run_id: AgentRun ID。
        :return: 运行记录或 None。
        """
        try:
            parsed_run_id = int(run_id)
        except (TypeError, ValueError):
            return None
        return AgentRun.objects.filter(id=parsed_run_id, user=self.user, course=self.course).first()

    def _load_resources_for_run(
        self,
        run: AgentRun,
        resource_ids: list[object] | None,
    ) -> list[GeneratedLearningResource]:
        """
        读取运行记录下可绑定的生成资源。

        :param run: AgentRun。
        :param resource_ids: 可选资源 ID。
        :return: 资源列表。
        """
        queryset = GeneratedLearningResource.objects.filter(
            agent_run=run,
            user=self.user,
            course=self.course,
            status="completed",
        ).select_related("knowledge_point")
        parsed_ids = self._parse_id_list(resource_ids)
        if parsed_ids:
            queryset = queryset.filter(id__in=parsed_ids)
        return list(queryset.order_by("id"))

    def _parse_id_list(self, raw_values: list[object] | None) -> list[int]:
        """
        解析 ID 列表。

        :param raw_values: 原始 ID 列表。
        :return: 整型 ID 列表。
        """
        parsed: list[int] = []
        for value in raw_values or []:
            try:
                parsed.append(int(value))
            except (TypeError, ValueError):
                continue
        return parsed

    def _find_learning_path(self) -> LearningPath | None:
        """
        查找当前学习路径。

        :return: 学习路径或 None。
        """
        return LearningPath.objects.filter(user=self.user, course=self.course).prefetch_related("nodes").first()

    def _get_or_create_learning_path(self) -> LearningPath:
        """
        获取或创建当前课程学习路径。

        :return: 学习路径。
        """
        path = self._find_learning_path()
        if path:
            return path
        return LearningPath.objects.create(
            user=self.user,
            course=self.course,
            ai_reason="由 A3 Agent 资源包创建的学习路径草稿。",
            is_dynamic=True,
        )

    def _resolve_binding_node(
        self,
        path: LearningPath,
        resource: GeneratedLearningResource,
    ) -> PathNode:
        """
        解析资源应绑定的路径节点，必要时插入补充节点。

        :param path: 学习路径。
        :param resource: 生成资源。
        :return: 路径节点。
        """
        matched = self._match_node_for_resource(path, resource)
        if matched:
            return matched
        order_index = path.nodes.order_by("-order_index").values_list("order_index", flat=True).first()
        next_order = int(order_index) + 1 if order_index is not None else 0
        active_status = "active" if not path.nodes.filter(status="active").exists() else "locked"
        point_name = resource.knowledge_point.name if resource.knowledge_point else resource.title[:40]
        return PathNode.objects.create(
            path=path,
            knowledge_point=resource.knowledge_point,
            title=f"A3 补充：{point_name}",
            goal=f"完成 {resource.title} 并复盘关键概念",
            criterion="完成绑定的生成资源并提交学习反馈",
            suggestion="先读讲解和导图，再完成练习或实操案例。",
            status=active_status,
            order_index=next_order,
            estimated_minutes=35,
            is_inserted=True,
        )

    def _match_node_for_resource(
        self,
        path: LearningPath | None,
        resource: GeneratedLearningResource,
    ) -> PathNode | None:
        """
        按知识点匹配路径节点，优先保留非 completed 节点。

        :param path: 学习路径。
        :param resource: 生成资源。
        :return: 匹配节点或 None。
        """
        if path is None or not resource.knowledge_point_id:
            return None
        queryset = path.nodes.filter(knowledge_point_id=resource.knowledge_point_id).order_by("order_index", "id")
        return queryset.exclude(status="completed").first() or queryset.first()

    def _bind_resource_to_node(
        self,
        resource: GeneratedLearningResource,
        node: PathNode,
    ) -> dict[str, Any]:
        """
        把生成资源绑定到节点 metadata 与 NodeProgress 扩展数据。

        :param resource: 生成资源。
        :param node: 路径节点。
        :return: 绑定记录。
        """
        metadata = dict(resource.metadata or {})
        path_binding = {
            "path_id": node.path_id,
            "node_id": node.id,
            "node_title": node.title,
            "bound_at": timezone.now().isoformat(),
            "binding_strategy": "knowledge_point" if resource.knowledge_point_id else "inserted_node",
        }
        metadata["path_binding"] = path_binding
        resource.metadata = metadata
        resource.save(update_fields=["metadata", "updated_at"])

        progress, _ = NodeProgress.objects.get_or_create(node=node, user=self.user)
        extra_data = dict(progress.extra_data or {})
        generated_resources = extra_data.get("generated_resources", [])
        if not isinstance(generated_resources, list):
            generated_resources = []
        if resource.id not in [item.get("resource_id") for item in generated_resources if isinstance(item, dict)]:
            generated_resources.append(
                {
                    "resource_id": resource.id,
                    "resource_type": resource.resource_type,
                    "title": resource.title,
                    "status": "assigned",
                    "assigned_at": timezone.now().isoformat(),
                }
            )
        extra_data["generated_resources"] = generated_resources
        progress.extra_data = extra_data
        progress.save(update_fields=["extra_data", "updated_at"])
        return {
            "resource_id": resource.id,
            "resource_type": resource.resource_type,
            "title": resource.title,
            "node_id": node.id,
            "node_title": node.title,
            "node_status": node.status,
            "knowledge_point_id": resource.knowledge_point_id,
        }

    def _serialize_path_nodes(self, path: LearningPath) -> list[dict[str, Any]]:
        """
        序列化路径节点和生成资源绑定摘要。

        :param path: 学习路径。
        :return: 节点列表。
        """
        nodes = path.nodes.select_related("knowledge_point").order_by("order_index", "id")
        node_ids = [node.id for node in nodes]
        progress_map = {
            progress.node_id: progress.extra_data
            for progress in NodeProgress.objects.filter(user=self.user, node_id__in=node_ids)
        }
        return [
            {
                "node_id": node.id,
                "title": node.title,
                "goal": node.goal,
                "criterion": node.criterion,
                "status": node.status,
                "suggestion": node.suggestion,
                "node_type": node.node_type,
                "order_index": node.order_index,
                "estimated_minutes": node.estimated_minutes,
                "is_inserted": node.is_inserted,
                "knowledge_point_id": node.knowledge_point_id,
                "knowledge_point_name": node.knowledge_point.name if node.knowledge_point else "",
                "generated_resources": progress_map.get(node.id, {}).get("generated_resources", []),
            }
            for node in nodes
        ]

    def _build_binding_warnings(self, bindings: list[dict[str, Any]]) -> list[str]:
        """
        构造路径绑定提示。

        :param bindings: 绑定记录。
        :return: 警告列表。
        """
        if not bindings:
            return ["没有资源被绑定到学习路径。"]
        inserted_count = len([binding for binding in bindings if binding.get("node_status") == "locked"])
        if inserted_count:
            return ["部分资源已插入到未来节点，需完成当前节点后继续学习。"]
        return []


def build_mastery_update_summary(
    *,
    user: object,
    course: object,
    resources: list[GeneratedLearningResource],
) -> dict[str, Any]:
    """
    根据资源反馈构造画像和路径更新摘要。

    :param user: 当前学生。
    :param course: 当前课程。
    :param resources: 相关生成资源。
    :return: 更新摘要。
    """
    point_ids = sorted({resource.knowledge_point_id for resource in resources if resource.knowledge_point_id})
    mastery_rows = KnowledgeMastery.objects.filter(user=user, course=course, knowledge_point_id__in=point_ids)
    mastery_map = {row.knowledge_point_id: float(row.mastery_rate) for row in mastery_rows}
    point_name_map = {
        point.id: point.name for point in KnowledgePoint.objects.filter(id__in=point_ids)
    }
    return {
        "affected_knowledge_points": [
            {
                "knowledge_point_id": point_id,
                "knowledge_point_name": point_name_map.get(point_id, ""),
                "current_mastery": round(mastery_map.get(point_id, 0.0), 3),
            }
            for point_id in point_ids
        ],
        "profile_update": "已记录资源反馈，后续画像刷新会优先参考学习完成度、评分和难度感受。",
        "path_update": "已将反馈写入资源和节点进度，学习路径刷新时会保留已完成节点。",
    }
