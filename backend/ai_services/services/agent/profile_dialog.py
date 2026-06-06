#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
A3 对话式学习画像抽取服务。
@Project : adaptive-edu
@File : profile_dialog.py
@Author : Qintsg
@Date : 2026-06-05 00:00
'''

from __future__ import annotations

import re
from typing import Any

from django.utils import timezone

from ai_services.models import AgentRun, ProfileDialogTurn
from ai_services.services.agent.schemas import PROFILE_FIELDS
from ai_services.services.agent.trace import build_default_agent_trace
from knowledge.models import KnowledgeMastery, ProfileSummary
from users.models import HabitPreference


def _contains_any(text: str, keywords: list[str]) -> bool:
    """
    判断文本是否包含任意关键词。

    :param text: 待检测文本。
    :param keywords: 关键词列表。
    :return: 是否命中。
    """
    return any(keyword in text for keyword in keywords)


class ProfileDialogService:
    """对话式画像抽取服务。"""

    def __init__(self, user: object, course: object):
        """
        初始化服务。

        :param user: 当前学生。
        :param course: 当前课程。
        :return: None。
        """
        self.user = user
        self.course = course

    def extract_profile(self, message: str) -> dict[str, Any]:
        """
        从学生自然语言输入和现有画像数据中抽取画像字段。

        :param message: 学生输入文本。
        :return: 画像抽取结果。
        """
        normalized_message = str(message or "").strip()
        profile = self._extract_from_message(normalized_message)
        profile.update({key: value for key, value in self._build_existing_profile_context().items() if value and not profile.get(key)})

        filled_fields = [field for field in PROFILE_FIELDS if profile.get(field)]
        missing_slots = [field for field in PROFILE_FIELDS if not profile.get(field)]
        next_question = self._build_next_question(missing_slots)
        confidence = min(0.95, max(0.35, round(0.35 + len(filled_fields) * 0.06, 2)))

        run = AgentRun.objects.create(
            user=self.user,
            course=self.course,
            run_type="profile_dialog",
            status="completed",
            input_text=normalized_message,
            profile_snapshot=profile,
            agent_trace=build_default_agent_trace(
                profile_complete=len(filled_fields) >= 6,
                evidence_count=0,
                resource_count=0,
                warnings=[] if len(filled_fields) >= 6 else ["画像字段不足 6 个，建议继续追问。"],
            ),
            result_payload={
                "profile": profile,
                "missing_slots": missing_slots,
                "next_question": next_question,
                "confidence": confidence,
            },
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
        ProfileDialogTurn.objects.create(
            user=self.user,
            course=self.course,
            agent_run=run,
            role="student",
            content=normalized_message,
            extracted_slots=profile,
        )
        if next_question:
            ProfileDialogTurn.objects.create(
                user=self.user,
                course=self.course,
                agent_run=run,
                role="assistant",
                content=next_question,
                extracted_slots={"missing_slots": missing_slots},
            )

        return {
            "run_id": run.id,
            "profile": profile,
            "missing_slots": missing_slots,
            "next_question": next_question,
            "confidence": confidence,
            "agent_trace": run.agent_trace,
        }

    def _extract_from_message(self, message: str) -> dict[str, Any]:
        """
        使用规则兜底抽取画像字段。

        :param message: 学生输入。
        :return: 画像字段。
        """
        profile: dict[str, Any] = {}
        if not message:
            return profile

        goal_match = re.search(r"(?:想|希望|目标是|计划)([^。；;，,]{4,80})", message)
        if goal_match:
            profile["course_goal"] = goal_match.group(1).strip()
        elif _contains_any(message, ["掌握", "学会", "提升", "通过", "完成"]):
            profile["course_goal"] = message[:80]

        weakness_keywords = ["不太好", "薄弱", "不会", "困难", "短板", "基础差", "不熟"]
        if _contains_any(message, weakness_keywords):
            profile["weaknesses"] = self._extract_topic_phrases(message)

        resource_map = {
            "视频": "video",
            "文档": "document",
            "文章": "document",
            "案例": "coding_case",
            "代码": "coding_case",
            "练习": "exercise",
            "题": "exercise",
            "思维导图": "mindmap",
        }
        preferred = [value for keyword, value in resource_map.items() if keyword in message]
        if preferred:
            profile["preferred_resource"] = list(dict.fromkeys(preferred))

        if _contains_any(message, ["案例", "动手", "实操", "代码", "实践"]):
            profile["learning_style"] = "kinesthetic"
            profile["practice_preference"] = "hands_on"
        elif _contains_any(message, ["图", "结构", "导图"]):
            profile["learning_style"] = "visual"
        elif _contains_any(message, ["阅读", "文档", "教材"]):
            profile["learning_style"] = "reading"

        if _contains_any(message, ["两周", "一周", "尽快", "快速", "赶"]):
            profile["pace"] = "fast"
        elif _contains_any(message, ["慢慢", "细致", "打基础"]):
            profile["pace"] = "slow"

        time_match = re.search(r"([每天每周一二三四五六日0-9半个两三四五六七八九十\s]{1,20}(?:小时|分钟|周|天))", message)
        if time_match:
            profile["available_time"] = time_match.group(1).strip()

        if _contains_any(message, ["计算机", "软件", "数据", "大数据", "人工智能", "专业", "背景"]):
            profile["major_or_background"] = self._extract_background(message)
        if _contains_any(message, ["零基础", "基础", "学过", "了解", "入门"]):
            profile["knowledge_foundation"] = self._extract_foundation(message)
        if _contains_any(message, ["考试", "项目", "就业", "比赛", "作业", "提升"]):
            profile["motivation"] = self._extract_motivation(message)

        return profile

    def _build_existing_profile_context(self) -> dict[str, Any]:
        """
        从习惯偏好、掌握度和画像摘要构造补充字段。

        :return: 画像补充字段。
        """
        context: dict[str, Any] = {}
        try:
            habit = self.user.habit_preference
        except HabitPreference.DoesNotExist:
            habit = None
        if habit:
            context.update(
                {
                    "preferred_resource": habit.preferred_resource,
                    "learning_style": habit.learning_style,
                    "pace": habit.study_pace,
                    "available_time": f"每日约 {habit.daily_goal_minutes} 分钟",
                    "practice_preference": "challenge" if habit.accept_challenge else "foundation_first",
                }
            )

        weak_points = list(
            KnowledgeMastery.objects.filter(
                user=self.user,
                course=self.course,
                mastery_rate__lt=0.6,
            )
            .select_related("knowledge_point")
            .order_by("mastery_rate")[:5]
        )
        if weak_points:
            context["weaknesses"] = [record.knowledge_point.name for record in weak_points if record.knowledge_point_id]

        summary = ProfileSummary.objects.filter(user=self.user, course=self.course).first()
        if summary:
            context.setdefault("knowledge_foundation", summary.summary or "")
            context.setdefault("course_goal", summary.suggestion or "")
        return context

    def _extract_topic_phrases(self, message: str) -> list[str]:
        """
        从输入中提取可能的短板主题。

        :param message: 学生输入。
        :return: 主题列表。
        """
        candidates = re.split(r"[，,。；;、和与]", message)
        topics = [
            item.strip()
            for item in candidates
            if item.strip() and _contains_any(item, ["基础", "SQL", "HDFS", "MapReduce", "Spark", "Python", "算法", "图谱", "不会", "不熟"])
        ]
        return topics[:5] or [message[:40]]

    def _extract_background(self, message: str) -> str:
        """
        提取专业或背景短语。

        :param message: 学生输入。
        :return: 背景描述。
        """
        match = re.search(r"我是([^。；;，,]{2,40})", message)
        return match.group(1).strip() if match else "从输入中识别到相关专业或技术背景"

    def _extract_foundation(self, message: str) -> str:
        """
        提取知识基础描述。

        :param message: 学生输入。
        :return: 基础描述。
        """
        if "零基础" in message:
            return "零基础"
        if "基础差" in message or "基础不太好" in message:
            return "基础薄弱"
        if "学过" in message or "了解" in message:
            return "有一定基础"
        return "基础情况待进一步确认"

    def _extract_motivation(self, message: str) -> str:
        """
        提取学习动机。

        :param message: 学生输入。
        :return: 动机描述。
        """
        if "考试" in message:
            return "备考"
        if "项目" in message:
            return "完成项目"
        if "就业" in message:
            return "就业能力提升"
        return "提升课程学习效果"

    def _build_next_question(self, missing_slots: list[str]) -> str:
        """
        根据缺失字段生成下一轮追问。

        :param missing_slots: 缺失字段列表。
        :return: 追问文本。
        """
        question_map = {
            "available_time": "你每天或每周大约可以投入多少学习时间？",
            "knowledge_foundation": "你对这门课的基础大概处于零基础、入门还是已有项目经验？",
            "preferred_resource": "你更喜欢视频、文档、练习题、案例还是思维导图类资源？",
            "weaknesses": "目前最想补齐的 1-3 个薄弱知识点是什么？",
            "course_goal": "你希望这次学习最终达到什么目标？",
        }
        for slot in missing_slots:
            if slot in question_map:
                return question_map[slot]
        return ""
