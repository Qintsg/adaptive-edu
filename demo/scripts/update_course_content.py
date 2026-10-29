# 文件描述：同步课程解析、作业百分制和已保存的学习反馈。
# 项目名：adaptive-edu；文件名：update_course_content.py；作者：Qintsg；日期：2026-10-29。

from __future__ import annotations

import json
import os
from decimal import Decimal

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "adaptive_edu_api.settings")
django.setup()

from django.db import transaction
from django.db.models import Q

from assessments.models import AnswerHistory, AssessmentResult, Question
from assessments.services.question_explanations import apply_curated_question_data, refresh_question_details
from courses.models import Course
from demo_seed import align_profile_summary_with_mastery
from exams.api.student.helpers import build_submission_feedback_snapshot
from exams.api.student.submission_support import sync_result_submission_snapshot
from exams.models import ExamSubmission, FeedbackReport
from exams.services.score_policy import sync_course_exam_totals
from learning.models import NodeProgress
from tools.demo_student1_snapshot_types import DEMO_COURSE_NAME
from users.models import User


def main() -> None:
    """更新课程内容，保留学生的实际作答和学习进度。"""
    course = Course.objects.get(name=DEMO_COURSE_NAME)
    with transaction.atomic():
        question_rows = list(Question.objects.filter(course=course))
        updated_questions = apply_curated_question_data(question_rows)
        question_map = {question.id: question for question in question_rows}
        exam_count = sync_course_exam_totals(course.pk)
        for result in AssessmentResult.objects.filter(course=course):
            revised = refresh_question_details(result.result_data, question_map)
            if revised != result.result_data:
                result.result_data = revised
                result.save(update_fields=["result_data"])
        for progress in NodeProgress.objects.filter(node__path__course=course):
            revised = refresh_question_details(progress.extra_data, question_map)
            if revised != progress.extra_data:
                progress.extra_data = revised
                progress.save(update_fields=["extra_data"])
        scores = []
        for submission in ExamSubmission.objects.filter(exam__course=course, score__gte=0).select_related("exam"):
            snapshot = build_submission_feedback_snapshot(submission)
            score, passed = sync_result_submission_snapshot(submission, snapshot)
            scores.append({"exam_id": submission.exam_id, "score": score, "total_score": 100})
            grading = {str(item["question_id"]): item for item in snapshot["grading"]["question_results"]}
            for history in AnswerHistory.objects.filter(user=submission.user, exam_id=submission.exam_id, source="exam"):
                item = grading.get(str(history.question_id))
                if item:
                    history.score = Decimal(str(item["earned_score"]))
                    history.is_correct = item["is_correct"]
                    history.save(update_fields=["score", "is_correct"])
            for report in FeedbackReport.objects.filter(exam_submission=submission):
                report.overview = {
                    **report.overview,
                    "score": score,
                    "total_score": 100,
                    "passed": passed,
                    "correct_count": snapshot["correct_count"],
                    "total_count": snapshot["total_count"],
                    "accuracy": snapshot["accuracy"],
                    "summary": f"本次作业答对{snapshot['correct_count']}/{snapshot['total_count']}题，得分{score:.2f}/100。",
                }
                report.save(update_fields=["overview"])
        for report in FeedbackReport.objects.filter(Q(exam__course=course) | Q(assessment_result__course=course)):
            changed = []
            for field in ("overview", "analysis"):
                current = getattr(report, field)
                revised = refresh_question_details(current, question_map)
                if revised != current:
                    setattr(report, field, revised)
                    changed.append(field)
            if changed:
                report.save(update_fields=changed)
        student = User.objects.get(username="student1")
        align_profile_summary_with_mastery(course=course, student=student)
        if Question.objects.filter(course=course, analysis="").exists():
            raise ValueError("课程仍有题目缺少解析。")
    print(json.dumps({"updated_questions": updated_questions, "exams": exam_count, "scores": scores}, ensure_ascii=False))
    from platform_ai.rag import student_learning_rag

    index = student_learning_rag.build_index(course.pk, persist=True, force_rebuild=True)
    print(json.dumps({"indexed_documents": len(index.get("documents", []))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
