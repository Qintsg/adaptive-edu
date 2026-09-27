#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
答辩演示专用数据初始化与基线核验。
@Project : adaptive-edu
@File : seed_demo.py
@Author : Qintsg
@Date : 2026-09-27
'''

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.utils import timezone

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "adaptive_edu_api.settings")

import django

django.setup()

from django.db import transaction

from assessments.models import (
    AbilityScore,
    AnswerHistory,
    AssessmentResult,
    AssessmentStatus,
    Question,
    SurveyResult,
)
from common.domain.utils import extract_answer_value
from courses.models import Class, Course, Enrollment
from exams.api.student.helpers import FeedbackOverviewInput, build_feedback_overview
from exams.api.student.submission_support import (
    build_answer_history_batch,
    build_exam_submission_context,
    persist_answer_histories,
)
from exams.models import Exam, ExamQuestion, ExamSubmission, FeedbackReport
from knowledge.models import KnowledgeMastery, KnowledgePoint, ProfileSummary, Resource
from learning.models import LearningPath, NodeProgress
from tools.bootstrap import bootstrap_course_assets
from tools.db_seed_support import seed_database_from_testdata
from tools.neo4j_tools import sync_neo4j
from tools.testing import _load_testdata
from users.models import HabitPreference, User, UserCourseContext


DEMO_COURSE = "大数据技术与应用"
DEMO_USERS = {"admin", "teacher1", "student1", "student2"}


def build_demo_seed() -> dict[str, Any]:
    """从通用测试配置提取四账号和唯一演示课程。

    :returns: 演示环境专用的最小种子配置。
    :raises RuntimeError: 源配置缺失必要账号、课程或班级。
    """
    source = _load_testdata()
    if source is None:
        raise RuntimeError("未能读取 tools/testdata.json5")

    admin = source["users"]["admin"]
    teachers = [item for item in source["users"]["teachers"] if item["username"] == "teacher1"]
    students = [
        item
        for item in source["users"]["students"]
        if item["username"] in {"student1", "student2"}
    ]
    courses = [item for item in source["courses"] if item["name"] == DEMO_COURSE]
    classes = [item for item in source["classes"] if item["name"] == "2024春季班"]
    if admin["username"] != "admin" or len(teachers) != 1 or len(students) != 2:
        raise RuntimeError("通用测试配置缺少演示账号")
    if len(courses) != 1 or len(classes) != 1:
        raise RuntimeError("通用测试配置缺少大数据课程或演示班级")

    demo_data = dict(source)
    demo_data["users"] = {"admin": admin, "teachers": teachers, "students": students}
    demo_data["courses"] = courses
    demo_data["classes"] = [{**classes[0], "teacher_index": 0, "course_indices": [0]}]
    demo_data["class_invitations"] = [
        item for item in source.get("class_invitations", []) if item.get("class_index") == 0
    ]
    demo_data["course_seed_content"] = {}
    return demo_data


def seed_demo() -> None:
    """建立四账号数据，并导入大数据课程全部本地资产。

    :returns: None。
    :raises RuntimeError: 非空数据库、灌库失败或验收不通过。
    """
    if User.objects.exists() or Course.objects.exists():
        raise RuntimeError("演示库已有业务数据；请先恢复快照或重置演示专用卷")

    with transaction.atomic():
        seed_database_from_testdata(build_demo_seed())

    bootstrap_course_assets(
        course_name=DEMO_COURSE,
        teacher="teacher1",
        replace=False,
        sync_graph=False,
    )

    course = Course.objects.get(name=DEMO_COURSE)
    student1 = User.objects.get(username="student1")
    align_profile_summary_with_mastery(course=course, student=student1)
    seed_completed_homework(course=course, student=student1)
    try:
        sync_neo4j(int(course.pk))
    except Exception as error:
        print(f"Neo4j 图谱同步失败，页面将使用 PostgreSQL 图谱回退：{error}")

    if not verify_demo(require_fresh_student=True):
        raise RuntimeError("演示基线验收未通过")


def count_visible_weak_points(*, course: Course, student: User) -> int:
    """按学生页面的整数百分比口径统计薄弱知识点。

    :param course: 当前课程。
    :param student: 当前学生。
    :returns: 展示百分比低于 60 的知识点数量。
    """
    rates = KnowledgeMastery.objects.filter(user=student, course=course).values_list(
        "mastery_rate", flat=True
    )
    return sum(
        (rate * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        < Decimal("60")
        for rate in rates
    )


def align_profile_summary_with_mastery(*, course: Course, student: User) -> None:
    """修正预置画像中的薄弱项数量，使其与页面统计一致。

    :param course: 当前课程。
    :param student: 预置学习记录的学生。
    :returns: None。
    :raises RuntimeError: 预置摘要缺少可替换的数量描述。
    """
    profile = ProfileSummary.objects.get(user=student, course=course)
    weak_count = count_visible_weak_points(course=course, student=student)
    summary, replaced = re.subn(
        r"\d+个知识点薄弱",
        f"{weak_count}个知识点薄弱",
        profile.summary or "",
        count=1,
    )
    if replaced != 1:
        raise RuntimeError("预置画像摘要缺少薄弱项数量")
    profile.summary = summary
    profile.save(update_fields=["summary", "generated_at"])


def choose_incorrect_answer(question: Any, correct_answer: Any) -> Any:
    """从真实选项中选一个错误答案，供演示反馈展示。

    :param question: 课程题库中的题目。
    :param correct_answer: 题库内的标准答案值。
    :returns: 能被现有评分规则判为错误的答案。
    """
    if question.question_type == "true_false":
        normalized = str(correct_answer).strip().lower()
        return "false" if normalized in {"true", "1", "yes", "正确", "对"} else "true"
    correct_values = correct_answer if isinstance(correct_answer, list) else [correct_answer]
    normalized_correct = {str(value).strip().upper() for value in correct_values}
    for option in question.options or []:
        if not isinstance(option, dict):
            continue
        option_value = next(
            (option.get(key) for key in ("answer_value", "value", "key", "label") if option.get(key) is not None),
            None,
        )
        if option_value is not None and str(option_value).strip().upper() not in normalized_correct:
            return [option_value] if question.question_type == "multiple_choice" else option_value
    return [] if question.question_type == "multiple_choice" else f"{correct_answer}（待复习）"


def seed_completed_homework(*, course: Course, student: User) -> None:
    """用真实课程套题、评分器写入一份已完成作业和反馈。

    :param course: 已导入作业库的大数据课程。
    :param student: 预置部分学习记录的学生。
    :returns: None。
    :raises RuntimeError: 课程作业库未成功导入。
    """
    exam_candidates = list(Exam.objects.filter(course=course, status="published").order_by("id"))
    eligible = [exam for exam in exam_candidates if ExamQuestion.objects.filter(exam=exam).exists()]
    exam = next((item for item in eligible if item.title.startswith("第2章")), eligible[0] if eligible else None)
    if exam is None:
        raise RuntimeError("课程资产未生成可提交的已发布作业")

    exam_questions = list(ExamQuestion.objects.filter(exam=exam).select_related("question").order_by("order"))
    answers: dict[str, Any] = {}
    for index, exam_question in enumerate(exam_questions):
        question = exam_question.question
        correct = extract_answer_value(question.answer)
        answers[str(question.pk)] = (
            choose_incorrect_answer(question, correct) if index % 5 == 0 else correct
        )

    context = build_exam_submission_context(exam, answers)
    if not context.questions or context.score < 0:
        raise RuntimeError("演示作业评分未生成有效结果")

    wrong_details = [item for item in context.question_details if not item["is_correct"]]
    wrong_question_ids = {item["question_id"] for item in wrong_details}
    gap_names: list[str] = []
    for exam_question in exam_questions:
        if exam_question.question_id not in wrong_question_ids:
            continue
        point_names = list(exam_question.question.knowledge_points.values_list("name", flat=True))
        gap_names.extend(point_names or [exam_question.question.chapter or exam.title])
    gaps = list(dict.fromkeys(gap_names))[:4]
    summary = (
        f"已完成{exam.title}，答对 {context.correct_count}/{len(context.questions)} 题，"
        f"得分 {context.score:.1f}/{float(exam.total_score):.1f}。"
    )
    analysis = "错题已按课程知识点整理，可结合题目解析复习。" if wrong_details else "本次题目均已答对，可继续下一章节。"
    recommendations = (
        [f"先复习{point_name}，再查看本次作业的对应错题解析。" for point_name in gaps]
        if gaps else ["保持当前学习节奏，继续完成下一章节的练习。"]
    )
    next_tasks = ["查看本次作业的逐题解析", "在学习路径中继续完成下一个任务"]

    with transaction.atomic():
        submission = ExamSubmission.objects.create(
            exam=exam,
            user=student,
            answers=answers,
            score=context.score,
            is_passed=context.passed,
            graded_at=timezone.now(),
        )
        history_models, _ = build_answer_history_batch(
            exam=exam,
            user=student,
            answers=answers,
            context=context,
        )
        persist_answer_histories(history_models)
        FeedbackReport.objects.create(
            user=student,
            source="exam",
            exam=exam,
            exam_submission=submission,
            status="completed",
            overview=build_feedback_overview(FeedbackOverviewInput(
                score=context.score,
                total_score=exam.total_score,
                passed=context.passed,
                correct_count=context.correct_count,
                total_count=len(context.questions),
                accuracy=context.accuracy,
                summary=summary,
                knowledge_gaps=gaps,
            )),
            analysis={"analysis": analysis, "knowledge_gaps": gaps},
            recommendations=recommendations,
            next_tasks=next_tasks,
            conclusion="报告依据本次真实作业题目和评分生成。",
        )


def collect_demo_checks(*, require_fresh_student: bool) -> dict[str, dict[str, Any]]:
    """读取数据库并计算可重复的演示基线断言。

    :param require_fresh_student: 是否要求 student2 尚未开始任何测评和学习。
    :returns: 断言名称到结果与实际值的映射。
    """
    checks: dict[str, dict[str, Any]] = {}

    def add(name: str, passed: bool, actual: Any) -> None:
        """将一条断言加入核验报告。

        :param name: 断言名称。
        :param passed: 断言是否成立。
        :param actual: 实际值。
        :returns: None。
        """
        checks[name] = {"ok": passed, "actual": actual}

    usernames = list(User.objects.order_by("username").values_list("username", flat=True))
    add("仅四个演示账号", set(usernames) == DEMO_USERS and len(usernames) == 4, usernames)

    course_names = list(Course.objects.order_by("name").values_list("name", flat=True))
    add("仅大数据课程", course_names == [DEMO_COURSE], course_names)
    course = Course.objects.filter(name=DEMO_COURSE).first()
    student1 = User.objects.filter(username="student1").first()
    student2 = User.objects.filter(username="student2").first()
    if course is None or student1 is None or student2 is None:
        return checks

    class_count = Class.objects.count()
    add("唯一演示班级", class_count == 1, class_count)
    student2_enrollment = Enrollment.objects.filter(
        user=student2,
        class_obj__class_courses__course=course,
        class_obj__class_courses__is_active=True,
    ).count()
    context = UserCourseContext.objects.filter(user=student2, current_course=course).exists()
    add("student2 已加入课程", student2_enrollment > 0 and context, {
        "enrollment": student2_enrollment,
        "current_course": context,
    })

    content_counts = {
        "知识点": KnowledgePoint.objects.filter(course=course).count(),
        "题目": Question.objects.filter(course=course).count(),
        "课程资源": Resource.objects.filter(course=course).count(),
        "本地文件资源": Resource.objects.filter(course=course).exclude(file="").exclude(file__isnull=True).count(),
    }
    add("大数据课程内容非空", all(value > 0 for value in content_counts.values()), content_counts)

    student1_counts = {
        "测评结果": AssessmentResult.objects.filter(user=student1, course=course).count(),
        "学习路径": LearningPath.objects.filter(user=student1, course=course).count(),
        "掌握度": KnowledgeMastery.objects.filter(user=student1, course=course).count(),
        "已完成作业": ExamSubmission.objects.filter(user=student1, exam__course=course, score__gte=0).count(),
        "已完成作业反馈": FeedbackReport.objects.filter(user=student1, exam__course=course, source="exam", status="completed").count(),
    }
    add("student1 已有学习记录", all(value > 0 for value in student1_counts.values()), student1_counts)

    if require_fresh_student:
        expected_weak_count = count_visible_weak_points(course=course, student=student1)
        profile_summary = ProfileSummary.objects.filter(user=student1, course=course).first()
        profile_text = profile_summary.summary if profile_summary else ""
        add("student1 画像薄弱项一致", f"{expected_weak_count}个知识点薄弱" in (profile_text or ""), {
            "页面口径数量": expected_weak_count,
            "摘要": profile_text,
        })

    if require_fresh_student:
        student2_counts = {
            "测评状态": AssessmentStatus.objects.filter(user=student2).count(),
            "测评结果": AssessmentResult.objects.filter(user=student2).count(),
            "问卷结果": SurveyResult.objects.filter(user=student2).count(),
            "能力分数": AbilityScore.objects.filter(user=student2).count(),
            "答题历史": AnswerHistory.objects.filter(user=student2).count(),
            "习惯偏好": HabitPreference.objects.filter(user=student2).count(),
            "知识掌握度": KnowledgeMastery.objects.filter(user=student2).count(),
            "学习路径": LearningPath.objects.filter(user=student2).count(),
            "学习进度": NodeProgress.objects.filter(user=student2).count(),
            "作业提交": ExamSubmission.objects.filter(user=student2).count(),
            "作业反馈": FeedbackReport.objects.filter(user=student2).count(),
        }
        add("student2 尚未测评或学习", all(value == 0 for value in student2_counts.values()), student2_counts)

    return checks


def verify_demo(*, require_fresh_student: bool) -> bool:
    """打印断言结果并返回总体状态。

    :param require_fresh_student: 是否验收 student2 的全新状态。
    :returns: 所有断言均成立时为 True。
    """
    checks = collect_demo_checks(require_fresh_student=require_fresh_student)
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return len(checks) >= (8 if require_fresh_student else 6) and all(
        item["ok"] for item in checks.values()
    )


def main() -> int:
    """处理初始化、运行状态检查和完整基线验收命令。

    :returns: 进程退出码。
    """
    parser = argparse.ArgumentParser(description="答辩演示数据初始化与核验")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--seed", action="store_true", help="在空演示库中初始化")
    group.add_argument("--verify-runtime", action="store_true", help="检查可继续运行的演示库")
    group.add_argument("--verify-baseline", action="store_true", help="检查 student2 未测评的交付基线")
    args = parser.parse_args()

    if args.seed:
        seed_demo()
        return 0
    return 0 if verify_demo(require_fresh_student=args.verify_baseline) else 1


if __name__ == "__main__":
    sys.exit(main())
