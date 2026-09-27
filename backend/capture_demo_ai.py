#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""在可恢复临时栈采样真实 DeepSeek 回答，并在空密钥栈复核预置命中。"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Iterator
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "adaptive_edu_api.settings")

import django

django.setup()

from django.conf import settings
from rest_framework.test import APIClient

from ai_services.services import llm_service
from ai_services.services.llm.provider_config import DEEPSEEK_FLASH_MODEL
from ai_services.realtime.consumers import _has_verified_chat_for_empty_key
from ai_services.services.student.ai_streaming import (
    build_student_ai_stream_plan,
    iter_student_ai_stream_chunks,
)
from assessments.models import AssessmentResult
from assessments.services.knowledge_generation_support import build_assessment_mistake_payload
from courses.models import Course
from exams.models import FeedbackReport
from exams.reports.service import generate_feedback_report_sync
from knowledge.models import KnowledgePoint, Resource
from users.models import User


COURSE_NAME = "大数据技术与应用"
QUESTION = "Spark SQL 和 DataFrame 有什么关系？"
TARGET = "补齐 Spark SQL 查询、DataFrame 操作和项目实操能力"
FEEDBACK_FIELDS = ("summary", "analysis", "knowledge_gaps", "recommendations", "next_tasks", "encouragement")


class ModelProbe:
    """透传真实 LangChain 调用并记录网关返回的模型标识。"""

    def __init__(self) -> None:
        """初始化本轮调用记录。"""
        self.calls: list[dict[str, str]] = []
        self._original: Callable[..., Any] | None = None
        self._original_stream: Callable[..., Any] | None = None

    def invoke(self, client: Any, *args: Any, **kwargs: Any) -> Any:
        """执行原始请求并读取真实响应元数据。

        :param client: ChatOpenAI 客户端。
        :param args: 原始位置参数。
        :param kwargs: 原始关键字参数。
        :returns: 原始 AI 响应。
        """
        if self._original is None:
            raise RuntimeError("模型探针尚未安装")
        response = self._original(client, *args, **kwargs)
        metadata = getattr(response, "response_metadata", {}) or {}
        response_model = str(metadata.get("model_name") or metadata.get("model") or "")
        request_model = str(getattr(client, "model_name", "") or getattr(client, "model", ""))
        self.calls.append({"request_model": request_model, "response_model": response_model})
        return response

    def stream(self, client: Any, *args: Any, **kwargs: Any) -> Iterator[Any]:
        """透传真实文本流并读取最后一个有效模型标识。

        :param client: ChatOpenAI 客户端。
        :param args: 原始位置参数。
        :param kwargs: 原始关键字参数。
        :yields: 原始流式消息块。
        """
        if self._original_stream is None:
            raise RuntimeError("流式模型探针尚未安装")
        response_model = ""
        for chunk in self._original_stream(client, *args, **kwargs):
            metadata = getattr(chunk, "response_metadata", {}) or {}
            response_model = str(metadata.get("model_name") or metadata.get("model") or response_model)
            yield chunk
        request_model = str(getattr(client, "model_name", "") or getattr(client, "model", ""))
        self.calls.append({"request_model": request_model, "response_model": response_model})


def parse_args() -> argparse.Namespace:
    """解析彩排或复核命令。

    :returns: 已校验的命令行参数。
    """
    parser = argparse.ArgumentParser(description="真实 AI 回答采样与空密钥预置复核")
    parser.add_argument("mode", choices=("capture", "verify"))
    parser.add_argument("--baseline-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected", type=Path)
    args = parser.parse_args()
    if os.getenv("DEMO_CAPTURE_TEMP_STACK") != "1" or not settings.DEMO_MODE:
        parser.error("仅允许在显式标记的可恢复临时演示栈运行")
    if not args.baseline_manifest.is_file():
        parser.error("请先保存并提供未测评基线清单")
    manifest = json.loads(args.baseline_manifest.read_text(encoding="utf-8-sig"))
    if manifest.get("project") != "adaptive-edu-defense-demo" or len(manifest.get("archives", [])) < 2:
        parser.error("基线清单不属于独立演示栈")
    if args.mode == "capture":
        if not llm_service.is_available or not os.getenv("DEMO_AI_CAPTURE_FILE"):
            parser.error("真实采样需要容器内 DeepSeek key 与 DEMO_AI_CAPTURE_FILE")
    elif (
        llm_service.is_available
        or not args.expected
        or not args.expected.is_file()
        or not Path(os.getenv("DEMO_AI_PRESET_FILE", "")).is_file()
    ):
        parser.error("预置复核必须在空 key 栈运行，并提供 --expected 彩排报告")
    return args


def api_result(client: APIClient, route: str, data: dict[str, object]) -> dict[str, object]:
    """通过项目真实 DRF 入口请求学生 AI 功能。

    :param client: 已认证 API 客户端。
    :param route: API 路径。
    :param data: 请求体。
    :returns: 业务响应数据。
    :raises RuntimeError: 接口失败或返回非对象。
    """
    response = client.post(route, data=data, format="json")
    body = getattr(response, "data", None)
    payload = body.get("data") if isinstance(body, dict) else None
    if response.status_code != 200 or not isinstance(payload, dict):
        raise RuntimeError(f"{route} 未返回可用内容，HTTP {response.status_code}")
    return payload


def assert_demo_baseline() -> None:
    """静默确认临时栈仍是 student2 未测评基线。

    :returns: None。
    :raises RuntimeError: 基线不满足。
    """
    from demo_seed import verify_demo

    with contextlib.redirect_stdout(io.StringIO()):
        valid = verify_demo(require_fresh_student=True)
    if not valid:
        raise RuntimeError("student2 不再是未测评基线，请先恢复")


def initial_feedback() -> dict[str, object]:
    """用 student1 的真实初测结果重放报告生成输入。

    :returns: 项目 LLM 服务生成的初测反馈。
    :raises RuntimeError: 缺少初测结果。
    """
    result = AssessmentResult.objects.filter(
        user__username="student1",
        course__name=COURSE_NAME,
        assessment__assessment_type="knowledge",
    ).select_related("assessment").order_by("-completed_at").first()
    if result is None:
        raise RuntimeError("缺少 student1 的大数据初测结果")
    result_data = result.result_data if isinstance(result.result_data, dict) else {}
    details = result_data.get("question_details") or []
    return llm_service.generate_feedback_report(
        exam_info={"title": result.assessment.title, "type": "初始知识评测"},
        score=float(result.score or 0),
        total_score=float(result_data.get("total_score") or 0),
        mistakes=build_assessment_mistake_payload(details),
    )


def completed_exam_feedback() -> dict[str, object]:
    """用预置的真实作业提交触发后台反馈生成。

    :returns: 报告概览。
    :raises RuntimeError: 缺少作业或报告未完成。
    """
    report = FeedbackReport.objects.filter(
        user__username="student1",
        exam__course__name=COURSE_NAME,
        source="exam",
    ).order_by("id").first()
    if report is None:
        raise RuntimeError("缺少 student1 的已完成作业")
    overview = generate_feedback_report_sync(report.id, force=True)
    report.refresh_from_db()
    if report.status != "completed" or not isinstance(overview, dict):
        raise RuntimeError("作业反馈未完成")
    return {
        "overview": overview,
        "analysis": report.analysis,
        "recommendations": report.recommendations,
        "next_tasks": report.next_tasks,
        "conclusion": report.conclusion,
    }


def capture_entries(path: Path, start_offset: int) -> list[dict[str, object]]:
    """读取某一步真实调用新增的 JSONL 条目。

    :param path: 彩排文件。
    :param start_offset: 调用前文件长度。
    :returns: 新增且格式正确的条目。
    """
    if not path.is_file():
        return []
    with path.open("rb") as source:
        source.seek(start_offset)
        lines = source.read().splitlines()
    entries: list[dict[str, object]] = []
    for line in lines:
        try:
            item = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(item, dict):
            entries.append(item)
    return entries


def run_capture_case(
    name: str,
    expected_types: set[str],
    action: Callable[[], dict[str, object]],
    capture_file: Path,
) -> dict[str, object]:
    """验证一次调用确实由指定模型完成并写入彩排文件。

    :param name: 场景名。
    :param expected_types: 至少需要录入的调用类型。
    :param action: 实际业务入口。
    :param capture_file: JSONL 彩排文件。
    :returns: 可供空密钥复核的场景记录。
    :raises RuntimeError: 未调用真实模型或未写入真实结果。
    """
    from langchain_openai import ChatOpenAI

    before = capture_file.stat().st_size if capture_file.is_file() else 0
    probe = ModelProbe()
    probe._original = ChatOpenAI.invoke
    probe._original_stream = ChatOpenAI.stream

    def instrument(client: Any, *args: Any, **kwargs: Any) -> Any:
        """把原始客户端实例交给探针。

        :param client: ChatOpenAI 实例。
        :param args: 原始位置参数。
        :param kwargs: 原始关键字参数。
        :returns: 原始模型响应。
        """
        return probe.invoke(client, *args, **kwargs)

    def instrument_stream(client: Any, *args: Any, **kwargs: Any) -> Iterator[Any]:
        """把流式客户端实例交给探针。

        :param client: ChatOpenAI 实例。
        :param args: 原始位置参数。
        :param kwargs: 原始关键字参数。
        :yields: 原始流式消息块。
        """
        yield from probe.stream(client, *args, **kwargs)

    start = time.perf_counter()
    with patch.object(ChatOpenAI, "invoke", instrument), patch.object(ChatOpenAI, "stream", instrument_stream):
        result = action()
    elapsed_ms = round((time.perf_counter() - start) * 1000)
    if result.get("demo_fallback") or result.get("generation_source") in {"verified_ai_preset", "demo_course_rules"}:
        raise RuntimeError(f"{name} 返回了本地结果，不能当作真实模型答案")
    if not probe.calls or any(
        item["request_model"] != DEEPSEEK_FLASH_MODEL or item["response_model"] != DEEPSEEK_FLASH_MODEL
        for item in probe.calls
    ):
        raise RuntimeError(f"{name} 未能核对 DeepSeek 真实响应模型：{probe.calls}")
    new_entries = capture_entries(capture_file, before)
    actual_types = {str(item.get("call_type")) for item in new_entries if item.get("model") == DEEPSEEK_FLASH_MODEL}
    if not expected_types.intersection(actual_types):
        raise RuntimeError(f"{name} 未写入所需真实答案：预期 {sorted(expected_types)}，实际 {sorted(actual_types)}")
    if name in {"chat", "stream_chat"}:
        comparable: object = str(result.get("reply") or "")
    elif name == "initial_feedback":
        comparable = {field: result.get(field) for field in FEEDBACK_FIELDS}
    else:
        comparable = result
    response_bytes = json.dumps(comparable, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return {
        "name": name,
        "request_type": "service" if name.endswith("feedback") or name == "stream_chat" else "http_api",
        "http_status": None if name.endswith("feedback") or name == "stream_chat" else 200,
        "business_result": "success",
        "duration_ms": elapsed_ms,
        "model_calls": probe.calls,
        "capture_types": sorted(actual_types),
        "response_sha256": hashlib.sha256(response_bytes).hexdigest(),
    }


def run_capture(args: argparse.Namespace) -> dict[str, object]:
    """逐项彩排学生 AI 入口并保存核对记录。

    :param args: 命令行参数。
    :returns: 彩排总报告。
    """
    assert_demo_baseline()
    course = Course.objects.get(name=COURSE_NAME)
    student = User.objects.get(username="student1")
    client = APIClient(HTTP_HOST="localhost")
    client.force_authenticate(user=student)
    point = KnowledgePoint.objects.filter(
        course=course, name="Spark SQL基本操作", is_published=True,
    ).first()
    resource = Resource.objects.filter(
        course=course, is_visible=True, knowledge_points=point,
    ).order_by("sort_order", "id").first()
    if point is None or resource is None:
        raise RuntimeError("课程缺少 Spark SQL 知识点或可见资源")
    capture_file = Path(os.environ["DEMO_AI_CAPTURE_FILE"])

    def stream_chat() -> dict[str, object]:
        """按前端相同参数执行学生 AI 流式问答。

        :returns: 完整回答文本。
        """
        plan = build_student_ai_stream_plan(
            user=student, question=QUESTION, course_id=course.id, point_id=point.id,
        )
        return {"reply": "".join(iter_student_ai_stream_chunks(plan))}

    cases = [
        ("profile", {"profile_analysis"}, lambda: api_result(client, "/api/student/ai/profile-analysis", {"course_id": course.id, "refresh": True})),
        ("path", {"path_planning"}, lambda: api_result(client, "/api/student/ai/path-planning", {"course_id": course.id, "target": TARGET})),
        ("resource_reason", {"resource_reason"}, lambda: api_result(client, "/api/student/ai/resource-reason", {"course_id": course.id, "resource_id": resource.id, "point_id": point.id})),
        ("chat", {"student_chat"}, lambda: api_result(client, "/api/student/ai/chat", {"course_id": course.id, "point_id": point.id, "question": QUESTION})),
        ("stream_chat", {"graph_rag_answer_stream", "graph_rag_course_answer_stream"}, stream_chat),
        ("initial_feedback", {"feedback_report"}, initial_feedback),
        ("exam_feedback", {"feedback_report"}, completed_exam_feedback),
    ]
    results = [run_capture_case(name, expected, action, capture_file) for name, expected, action in cases]
    return {"schema_version": 1, "model": DEEPSEEK_FLASH_MODEL, "course": COURSE_NAME, "question": QUESTION, "cases": results}


def run_verify(expected: dict[str, object]) -> dict[str, object]:
    """空 key 条件下逐字核对固定问答与初测反馈。

    :param expected: 真实 AI 彩排报告。
    :returns: 含缓存命中证据的复核报告。
    :raises RuntimeError: 预置未命中或文字不一致。
    """
    assert_demo_baseline()
    course = Course.objects.get(name=COURSE_NAME)
    student = User.objects.get(username="student1")
    client = APIClient(HTTP_HOST="localhost")
    client.force_authenticate(user=student)
    point = KnowledgePoint.objects.filter(
        course=course, name="Spark SQL基本操作", is_published=True,
    ).first()
    if point is None:
        raise RuntimeError("缺少 Spark SQL 知识点")
    cases = {item["name"]: item for item in expected.get("cases", []) if isinstance(item, dict)}
    chat = api_result(client, "/api/student/ai/chat", {"course_id": course.id, "point_id": point.id, "question": QUESTION})
    feedback = initial_feedback()
    if chat.get("generation_source") != "verified_ai_preset" or feedback.get("generation_source") != "verified_ai_preset":
        raise RuntimeError("固定问答或初测反馈未命中真实彩排答案")
    chat_hash = hashlib.sha256(json.dumps(
        str(chat.get("reply") or ""), ensure_ascii=False, sort_keys=True,
    ).encode("utf-8")).hexdigest()
    if chat_hash != cases["chat"].get("response_sha256"):
        raise RuntimeError("空 key 问答与真实彩排文字不一致")
    if not _has_verified_chat_for_empty_key(course.id, point.id, QUESTION):
        raise RuntimeError("流式问答固定请求未命中真实彩排答案")
    feedback_hash = hashlib.sha256(json.dumps(
        {field: feedback.get(field) for field in FEEDBACK_FIELDS},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")).hexdigest()
    if feedback_hash != cases["initial_feedback"].get("response_sha256"):
        raise RuntimeError("空 key 初测反馈与真实彩排文字不一致")
    return {
        "model": DEEPSEEK_FLASH_MODEL,
        "chat_cache_hit": True,
        "stream_chat_cache_hit": True,
        "initial_feedback_cache_hit": True,
        "exact_text_match": True,
    }


def main() -> None:
    """执行彩排或空密钥复核，并只保存无密钥结果。

    :returns: None。
    """
    args = parse_args()
    if args.mode == "capture":
        capture_target = Path(os.environ["DEMO_AI_CAPTURE_FILE"])
        pending_file = capture_target.with_name(f"{capture_target.name}.pending-{os.getpid()}")
        if pending_file.exists():
            raise RuntimeError("本轮彩排临时文件已存在，请先核对之前的采样")
        os.environ["DEMO_AI_CAPTURE_FILE"] = str(pending_file)
        report = run_capture(args)
        pending_file.replace(capture_target)
        os.environ["DEMO_AI_CAPTURE_FILE"] = str(capture_target)
    else:
        report = run_verify(json.loads(args.expected.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{args.mode} 完成，记录已写入 {args.output}")


if __name__ == "__main__":
    main()
