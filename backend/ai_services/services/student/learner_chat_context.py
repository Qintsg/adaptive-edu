# 文件描述：为课程问答提供精简的学习信息与回答要求。
# 项目名：adaptive-edu；文件名：learner_chat_context.py；作者：Qintsg；日期：2026-10-29。

from __future__ import annotations

import json
import re
from typing import Any

from assessments.models import AbilityScore
from knowledge.models import KnowledgeMastery
from learning.models import PathNode
from users.models import HabitPreference, User


def is_learning_advice_question(question: str) -> bool:
    """识别需要结合学习信息回答的问题。

    :param question: 学生最新问题。
    :returns: 是否涉及个人学习建议。
    """
    return bool(re.search(r"学习建议|适合我|我的学习|复习计划|学习计划|学习安排|薄弱|我该.*学|我应该.*学", question))


def learner_chat_context(user: User, course_id: int) -> dict[str, Any]:
    """读取当前学生在当前课程的学习信息。

    :param user: 当前登录用户。
    :param course_id: 当前课程ID。
    :returns: 用于问答的精简学习信息。
    """
    rows = list(KnowledgeMastery.objects.filter(user=user, course_id=course_id)
                .select_related("knowledge_point").order_by("mastery_rate", "knowledge_point_id"))
    weak = [row for row in rows if float(row.mastery_rate) < 0.6]
    strong = [row for row in reversed(rows) if float(row.mastery_rate) >= 0.8]
    context: dict[str, Any] = {
        "薄弱知识点": [{"名称": row.knowledge_point.name, "掌握度百分比": round(float(row.mastery_rate) * 100)} for row in weak[:6]],
        "较熟悉知识点": [{"名称": row.knowledge_point.name, "掌握度百分比": round(float(row.mastery_rate) * 100)} for row in strong[:3]],
        "当前任务": list(PathNode.objects.filter(path__user=user, path__course_id=course_id, status__in=["active", "failed"]).order_by("order_index").values_list("title", flat=True)[:2]),
    }
    habit = HabitPreference.objects.filter(user=user).first()
    if habit:
        context["学习偏好"] = {
            "资源形式": habit.get_preferred_resource_display(),
            "学习时段": habit.get_preferred_study_time_display(),
            "学习节奏": habit.get_study_pace_display(),
            "单次时长": habit.get_study_duration_display(),
            "复习频率": habit.get_review_frequency_display(),
            "学习方式": habit.get_learning_style_display(),
            "每日目标分钟": habit.daily_goal_minutes,
        }
    ability = AbilityScore.objects.filter(user=user, course_id=course_id).first()
    if ability:
        context["能力测评"] = ability.scores
    return context


def personalized_prompt_suffix(user: User, course_id: int) -> str:
    """构造与当前问题互补的学习背景说明。

    :param user: 当前登录用户。
    :param course_id: 当前课程ID。
    :returns: 精简的学习背景与使用规则。
    """
    context = learner_chat_context(user, course_id)
    return (
        "\n\n# 当前学生的课程学习情况\n"
        + json.dumps(context, ensure_ascii=False)
        + "\n\n# 回答方式\n"
        "1. 直接解决最新问题，并结合最近对话理解指代与追问。\n"
        "2. 概念、原理、代码问题以知识本身为主，用掌握情况调整解释深度；默认不附带画像评价、学习计划或用时安排。\n"
        "3. 学习建议只选2至3个近期重点，每项不超过90字，结合资源偏好写出具体行动、用时和检验方法；按用户追问再展开。\n"
        "4. 选中的知识点只是背景；问题涉及整体学习或切换主题时，按问题范围作答。\n"
        "5. 学习偏好用于选择讲解形式，不据此推断固定能力。课程资料用于核对课程事实，不编造课程资源。\n"
        "6. 引用时使用知识点或课程资料名称，不显示题库内部编号、检索编号和内部报告编号。"
        "\n7. 解释训练与评估时，准确区分训练集拟合、验证集调参与独立测试集评价。"
    )
