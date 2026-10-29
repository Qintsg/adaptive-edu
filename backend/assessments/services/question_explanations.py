# 文件描述：补充题目解析并同步已经保存的答题详情。
# 项目名：adaptive-edu；文件名：question_explanations.py；作者：Qintsg；日期：2026-10-29。

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from django.utils import timezone

from assessments.models import Question
from common.domain.utils import decorate_question_options, extract_answer_value


@lru_cache(maxsize=1)
def curated_explanations() -> dict[str, dict[str, Any]]:
    """读取已经核对的课程题目解析。

    :returns: 按题干索引的解析记录。
    """
    source = Path(__file__).resolve().parents[2] / "tools/data/big_data_question_explanations.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    return {item["content"]: item for item in payload["items"]}


def ensure_question_explanations(questions: Sequence[Question]) -> int:
    """补齐题目解析，保存模型生成的新增内容。

    :param questions: 需要展示答题详情的真实题目。
    :returns: 更新的题目数量。
    """
    missing = [question for question in questions if not (question.analysis or "").strip()]
    if not missing:
        return 0
    known = curated_explanations()
    unknown = []
    for question in missing:
        if question.content in known:
            question.analysis = known[question.content]["analysis"]
        else:
            unknown.append(question)
    if unknown:
        from ai_services.services import llm_service

        client = llm_service._get_llm()
        if client is None:
            raise RuntimeError("题目解析生成服务不可用。")
        prompt = (
            "为以下题目补充中文解析。每题用40至100字解释正确答案的依据，说明具体知识，"
            "不要重复题干，不要输出学生评价。返回JSON对象："
            '{"items":[{"id":题目ID,"analysis":"解析"}]}。题目：\n'
            + json.dumps([{"id": question.id, "content": question.content, "options": question.options, "answer": question.answer} for question in unknown], ensure_ascii=False)
        )
        response = client.bind(response_format={"type": "json_object"}).invoke([
            SystemMessage(content="你是课程教师，准确解释解题原理。仅输出有效JSON。"),
            HumanMessage(content=prompt),
        ])
        generated = {int(item["id"]): str(item["analysis"]).strip() for item in json.loads(response.content)["items"]}
        if set(generated) != {question.id for question in unknown} or any(not value for value in generated.values()):
            raise ValueError("生成的题目解析不完整。")
        for question in unknown:
            question.analysis = generated[question.id]
    for question in missing:
        question.updated_at = timezone.now()
    Question.objects.bulk_update(missing, ["analysis", "updated_at"])
    return len(missing)


def apply_curated_question_data(questions: Sequence[Question]) -> int:
    """应用已核对的题目答案、选项和解析。

    :param questions: 当前课程的题目。
    :returns: 更新的题目数量。
    """
    known = curated_explanations()
    changed = []
    for question in questions:
        item = known.get(question.content)
        if item is None:
            continue
        original = (question.analysis, question.answer, question.options)
        if not (question.analysis or "").strip():
            question.analysis = item["analysis"]
        question.answer = item["answer"]
        question.options = item.get("options", question.options)
        if original != (question.analysis, question.answer, question.options):
            question.updated_at = timezone.now()
            changed.append(question)
    Question.objects.bulk_update(changed, ["analysis", "answer", "options", "updated_at"])
    return len(changed)


def refresh_question_details(value: Any, questions: dict[int, Question]) -> Any:
    """同步报告与学习进度内的逐题解析。

    :param value: 已保存的JSON内容。
    :param questions: 当前课程题目的ID映射。
    :returns: 更新后的JSON内容。
    """
    if isinstance(value, list):
        return [refresh_question_details(item, questions) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: refresh_question_details(item, questions) for key, item in value.items()}
    question_id = result.get("question_id")
    question = questions.get(int(question_id)) if str(question_id).isdigit() else None
    if question is None:
        content = result.get("question_text") or result.get("content")
        question = next((item for item in questions.values() if item.content == content), None)
    if question is not None and ("correct_answer" in result or "is_correct" in result):
        result["analysis"] = question.analysis or ""
        if "options" in result:
            result["options"] = decorate_question_options(question.options, question.question_type, result.get("student_answer"), extract_answer_value(question.answer))
    return result
