# 文件描述：更新已有初始评测报告的学习建议。
# 项目名：adaptive-edu
# 文件名：refresh_initial_report_text.py
# 作者：Qintsg
# 日期：2026-10-29

from __future__ import annotations

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "adaptive_edu_api.settings")
django.setup()

from django.db import transaction

from assessments.models import AssessmentResult
from exams.models import FeedbackReport
from tools.demo_student1_snapshot_parse import load_inline_snapshot
from tools.demo_student1_snapshot_types import DEMO_COURSE_NAME, DEMO_STUDENT_USERNAME


def main() -> None:
    """同步内置学习记录对应的两份报告文字。

    :returns: 无。
    """
    snapshot = load_inline_snapshot()
    with transaction.atomic():
        result = AssessmentResult.objects.select_for_update().get(
            user__username=DEMO_STUDENT_USERNAME,
            course__name=DEMO_COURSE_NAME,
            assessment__assessment_type="knowledge",
        )
        data = dict(result.result_data)
        if (
            float(result.score) != snapshot.score
            or data["correct_count"] != snapshot.correct_count
            or data["total_count"] != snapshot.total_count
            or [item["content"] for item in data["question_details"]]
            != [item.content for item in snapshot.question_details]
        ):
            raise ValueError("测评记录已变化，请核对目标报告。")
        feedback = snapshot.feedback_report
        revised = {
            "summary": feedback.summary,
            "analysis": feedback.summary,
            "knowledge_gaps": feedback.knowledge_gaps,
            "recommendations": feedback.recommendations,
            "next_tasks": feedback.next_tasks,
            "encouragement": feedback.encouragement,
            "conclusion": feedback.conclusion,
        }
        data["feedback_report"] = {**data["feedback_report"], **revised}
        result.result_data = data
        result.save(update_fields=["result_data"])
        report = FeedbackReport.objects.select_for_update().get(
            source="assessment", assessment_result=result
        )
        report.overview = {
            **report.overview,
            "summary": feedback.summary,
            "knowledge_gaps": feedback.knowledge_gaps,
        }
        report.analysis = feedback.summary
        report.recommendations = feedback.recommendations
        report.next_tasks = feedback.next_tasks
        report.conclusion = feedback.conclusion
        report.save(update_fields=["overview", "analysis", "recommendations", "next_tasks", "conclusion"])
    print(f"assessment_result={result.pk} feedback_report={report.pk} updated")


if __name__ == "__main__":
    main()
