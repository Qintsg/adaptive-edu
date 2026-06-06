#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
A3 Agent 生成资源质量守卫。
@Project : adaptive-edu
@File : quality_guard.py
@Author : Qintsg
@Date : 2026-06-07 00:00
'''

from __future__ import annotations

from typing import Any

from ai_services.models import GeneratedLearningResource
from ai_services.services.agent.schemas import RESOURCE_TYPES


class AgentQualityGuard:
    """生成资源质量校验与防幻觉提示服务。"""

    def validate_resources(
        self,
        resources: list[GeneratedLearningResource],
        *,
        required_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        校验一组生成资源是否满足 A3 最小可用标准。

        :param resources: 已保存的生成资源列表。
        :param required_types: 本轮期望生成的资源类型。
        :return: 质量报告。
        """
        normalized_required = [
            resource_type for resource_type in (required_types or []) if resource_type in RESOURCE_TYPES
        ]
        resource_reports = [self._validate_single_resource(resource) for resource in resources]
        resource_type_set = {resource.resource_type for resource in resources}
        missing_types = [
            resource_type for resource_type in normalized_required if resource_type not in resource_type_set
        ]
        warnings = self._collect_warnings(resource_reports, missing_types)
        errors = self._collect_errors(resource_reports, missing_types)
        average_score = self._average_score(resource_reports)
        status = "passed"
        if errors:
            status = "failed"
        elif warnings or average_score < 0.82:
            status = "warning"

        return {
            "status": status,
            "score": average_score,
            "resource_count": len(resources),
            "required_types": normalized_required,
            "missing_types": missing_types,
            "warnings": warnings,
            "errors": errors,
            "resources": resource_reports,
        }

    def _validate_single_resource(self, resource: GeneratedLearningResource) -> dict[str, Any]:
        """
        校验单个生成资源。

        :param resource: 生成资源模型。
        :return: 单资源质量报告。
        """
        payload = resource.metadata.get("payload", {}) if isinstance(resource.metadata, dict) else {}
        checks: list[dict[str, Any]] = []
        checks.append(self._check("title", bool(resource.title and len(resource.title) <= 300), "标题需存在且不超过 300 字"))
        checks.append(self._check("content", bool(resource.content and len(resource.content.strip()) >= 20), "正文需包含可学习内容"))
        checks.append(self._check("type", resource.resource_type in RESOURCE_TYPES, "资源类型需在白名单内"))
        checks.append(
            self._check(
                "evidence",
                bool(resource.evidence),
                "未检索到课程证据，前端需展示防幻觉提示",
                warning_only=True,
            )
        )
        checks.extend(self._type_specific_checks(resource.resource_type, payload, resource.content))

        failed_checks = [check for check in checks if not check["passed"] and not check.get("warning_only")]
        warning_checks = [check for check in checks if not check["passed"] and check.get("warning_only")]
        score = max(0.0, round(1 - len(failed_checks) * 0.2 - len(warning_checks) * 0.08, 2))
        status = "passed"
        if failed_checks:
            status = "failed"
        elif warning_checks:
            status = "warning"

        return {
            "resource_id": resource.id,
            "resource_type": resource.resource_type,
            "title": resource.title,
            "status": status,
            "score": score,
            "checks": checks,
            "warnings": [check["message"] for check in warning_checks],
            "errors": [check["message"] for check in failed_checks],
        }

    def _type_specific_checks(
        self,
        resource_type: str,
        payload: Any,
        content: str,
    ) -> list[dict[str, Any]]:
        """
        按资源类型执行结构化校验。

        :param resource_type: 资源类型。
        :param payload: 结构化内容。
        :param content: 文本内容。
        :return: 检查项列表。
        """
        if resource_type == "explanation":
            return [
                self._check("explanation_outline", "##" in content or len(content) >= 120, "讲解文档需包含结构化段落")
            ]
        if resource_type == "mindmap":
            return [
                self._check(
                    "mindmap_structure",
                    isinstance(payload, dict) and (bool(payload.get("mermaid")) or bool(payload.get("nodes"))),
                    "思维导图需包含 mermaid 或 nodes 结构",
                )
            ]
        if resource_type == "quiz":
            questions = payload.get("questions", []) if isinstance(payload, dict) else []
            valid_questions = [
                question
                for question in questions
                if isinstance(question, dict) and question.get("stem") and question.get("answer") and question.get("analysis")
            ]
            return [
                self._check("quiz_questions", len(valid_questions) >= 2, "练习题需至少包含 2 题且带答案解析")
            ]
        if resource_type == "reading":
            items = payload.get("items", []) if isinstance(payload, dict) else []
            return [
                self._check("reading_items", bool(items), "拓展阅读需包含推荐条目")
            ]
        if resource_type == "coding_case":
            steps = payload.get("steps", []) if isinstance(payload, dict) else []
            code = payload.get("code", "") if isinstance(payload, dict) else ""
            return [
                self._check("coding_steps", bool(steps), "代码案例需包含步骤"),
                self._check("coding_code", bool(code), "代码案例需包含示例代码"),
            ]
        if resource_type == "video_script":
            shots = payload.get("shots", []) if isinstance(payload, dict) else []
            return [
                self._check("video_shots", bool(shots), "视频脚本需包含镜头脚本")
            ]
        return []

    def _check(
        self,
        name: str,
        passed: bool,
        message: str,
        *,
        warning_only: bool = False,
    ) -> dict[str, Any]:
        """
        构造单个检查项。

        :param name: 检查项名称。
        :param passed: 是否通过。
        :param message: 失败提示。
        :param warning_only: 是否仅作为警告。
        :return: 检查项字典。
        """
        return {
            "name": name,
            "passed": passed,
            "message": message,
            "warning_only": warning_only,
        }

    def _collect_warnings(
        self,
        resource_reports: list[dict[str, Any]],
        missing_types: list[str],
    ) -> list[str]:
        """
        汇总质量警告。

        :param resource_reports: 单资源报告列表。
        :param missing_types: 缺失资源类型。
        :return: 警告列表。
        """
        warnings: list[str] = []
        if missing_types:
            warnings.append(f"缺少期望资源类型：{', '.join(missing_types)}。")
        for report in resource_reports:
            warnings.extend(report.get("warnings", []))
        return list(dict.fromkeys(warnings))

    def _collect_errors(
        self,
        resource_reports: list[dict[str, Any]],
        missing_types: list[str],
    ) -> list[str]:
        """
        汇总质量错误。

        :param resource_reports: 单资源报告列表。
        :param missing_types: 缺失资源类型。
        :return: 错误列表。
        """
        errors: list[str] = []
        if missing_types:
            errors.append("未生成完整资源类型集合。")
        for report in resource_reports:
            errors.extend(report.get("errors", []))
        return list(dict.fromkeys(errors))

    def _average_score(self, resource_reports: list[dict[str, Any]]) -> float:
        """
        计算平均质量分。

        :param resource_reports: 单资源报告列表。
        :return: 平均分。
        """
        if not resource_reports:
            return 0.0
        return round(
            sum(float(report.get("score", 0.0)) for report in resource_reports) / len(resource_reports),
            2,
        )
