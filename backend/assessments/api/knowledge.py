"""
知识测评视图。

保留原有 API 契约，聚焦知识测评题目获取、提交评分和结果轮询。
"""
from __future__ import annotations

import logging
import threading

from django.db import transaction
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from common.http.permissions import IsStudent
from common.http.responses import error_response, success_response
from courses.models import Course, Enrollment
from users.models import User
from assessments.services.assessment_helpers import (
    clean_text,
    get_authenticated_user,
    normalize_options,
    persist_mastery_snapshot,
    upsert_knowledge_assessment_result,
)
from assessments.services.knowledge_generation import async_generate_after_assessment
from assessments.services.knowledge_assessment_logic import (
    blend_mastery_with_kt,
    build_empty_knowledge_result,
    build_feedback_report_payload,
    evaluate_knowledge_answers,
)
from assessments.models import (
    AnswerHistory,
    Assessment,
    AssessmentQuestion,
    AssessmentResult,
    AssessmentStatus,
    Question,
)


logger = logging.getLogger(__name__)


def _assessment_course_for_user(
    user: User, raw_course_id: object,
) -> tuple[Course | None, Response | None]:
    """只允许已选修学生或可管理课程的教师读取测评题库。

    :param user: 已认证用户。
    :param raw_course_id: 请求中的课程 ID。
    :returns: 课程与错误响应，二者至多一个非空。
    """
    try:
        course_id = int(raw_course_id)
    except (TypeError, ValueError):
        return None, error_response(msg='课程ID格式错误')
    course = Course.objects.filter(pk=course_id).first()
    if course is None:
        return None, error_response(msg='课程不存在', code=404)
    if user.role == 'student':
        allowed = Enrollment.objects.filter(user=user).filter(
            Q(class_obj__course=course)
            | Q(class_obj__class_courses__course=course,
                class_obj__class_courses__is_active=True)
        ).exists()
    else:
        allowed = course.can_edit(user)
    if not allowed:
        return None, error_response(msg='无权访问该课程的知识测评', code=403)
    return course, None


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_knowledge_assessment(request: Request) -> Response:
    """
    获取知识点掌握度测评试题。
    GET /api/assessments/initial/knowledge
    """
    course_id = request.query_params.get('course_id')
    if not course_id:
        return error_response(msg='缺少课程ID')
    course, access_error = _assessment_course_for_user(request.user, course_id)
    if access_error is not None:
        return access_error
    course_id = course.id

    assessment = Assessment.objects.filter(
        course_id=course_id,
        assessment_type='knowledge',
        is_active=True,
    ).first()

    if not assessment:
        course_questions_qs = Question.objects.filter(course_id=course_id, is_visible=True)
        preferred_questions = course_questions_qs.filter(for_initial_assessment=True).order_by('id')
        course_questions = preferred_questions if preferred_questions.exists() else course_questions_qs.order_by('id')

        if not course_questions.exists():
            return error_response(
                msg='该课程暂无知识测评题目，请联系教师添加题库',
                code=404,
            )

        assessment = Assessment.objects.create(
            course=course,
            title=f'{course.name} 知识水平测评',
            assessment_type='knowledge',
            description='系统自动生成的知识水平测评',
            is_active=True,
        )
        AssessmentQuestion.objects.bulk_create([
            AssessmentQuestion(assessment=assessment, question=question, order=index)
            for index, question in enumerate(course_questions)
        ])

    questions: list[Question] = list(
        assessment.questions.filter(is_visible=True)
        .prefetch_related('knowledge_points')
        .order_by('assessmentquestion__order', 'id')
    )
    if not questions:
        return error_response(msg='该课程暂无可见知识测评题目', code=404)
    question_payload = []
    for index, question in enumerate(questions, start=1):
        normalized_options = normalize_options(question.options, question.question_type)
        title = clean_text(question.content) or f'题干缺失（题目ID {question.id}），请联系教师补充'
        question_payload.append({
            'question_id': question.id,
            'order': index,
            'content': title,
            'title': title,
            'options': normalized_options,
            'type': question.question_type,
            'question_type': question.question_type,
            'score': float(question.score),
            'difficulty': question.difficulty,
            'points': list(question.knowledge_points.values_list('id', flat=True)),
        })

    return success_response(data={
        'assessment_id': assessment.id,
        'title': assessment.title,
        'questions': question_payload,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsStudent])
def submit_knowledge_assessment(request: Request) -> Response:
    """
    提交知识点掌握度测评答案。
    POST /api/student/assessments/initial/knowledge
    """
    course_id = request.data.get('course_id')
    answers = request.data.get('answers', [])

    if not course_id or not answers:
        return error_response(msg='缺少必要参数')
    course, access_error = _assessment_course_for_user(request.user, course_id)
    if access_error is not None:
        return access_error
    course_id = course.id

    user = get_authenticated_user(request)
    existing_status = AssessmentStatus.objects.filter(user=user, course_id=course_id).first()
    if existing_status and existing_status.knowledge_done:
        existing_result = AssessmentResult.objects.filter(
            user=user,
            course_id=course_id,
            assessment__assessment_type='knowledge',
        ).order_by('-completed_at').first()
        if existing_result:
            return success_response(
                data={
                    'score': float(existing_result.score),
                    'completed': True,
                    'message': '知识测评已提交，请勿重复提交',
                },
                msg='知识测评已完成',
            )

    try:
        assessment = Assessment.objects.get(
            course_id=course_id,
            assessment_type='knowledge',
            is_active=True,
        )
    except Assessment.DoesNotExist:
        return error_response(msg='未找到该课程的知识测评', code=404)

    answer_dict = {str(answer['question_id']): answer['answer'] for answer in answers}
    questions: list[Question] = list(
        assessment.questions.filter(is_visible=True).prefetch_related('knowledge_points')
    )
    if not questions:
        return error_response(msg='该课程暂无可见知识测评题目', code=404)
    evaluation = evaluate_knowledge_answers(
        user=user,
        course_id=course_id,
        questions=questions,
        answer_dict=answer_dict,
    )
    final_mastery_map = blend_mastery_with_kt(
        user_id=user.id,
        course_id=course_id,
        mastery_map=evaluation.mastery_map,
        point_stats=evaluation.point_stats,
        answer_history_records=evaluation.answer_history_records,
    )
    with transaction.atomic():
        from learning.models import LearningPath

        if evaluation.answer_history_models:
            bulk_create_method = AnswerHistory.objects.bulk_create
            bulk_create_method(evaluation.answer_history_models, batch_size=200)
        mastery_list = persist_mastery_snapshot(user, course_id, final_mastery_map, evaluation.point_stats)
        upsert_knowledge_assessment_result(
            user,
            assessment,
            course_id,
            answer_dict,
            evaluation.total_score,
            mastery_list,
            evaluation.question_details,
            questions,
            evaluation.correct_count,
            evaluation.total_question_count,
        )
        status, _ = AssessmentStatus.objects.get_or_create(user=user, course_id=course_id)
        status.knowledge_done = True
        status.generating = True
        status.generation_error = None
        status.save(update_fields=['knowledge_done', 'generating', 'generation_error'])
        LearningPath.objects.filter(user=user, course_id=course_id).delete()

    threading.Thread(
        target=async_generate_after_assessment,
        args=(user.id, course_id, assessment.id, evaluation.question_details),
        daemon=True,
    ).start()

    return success_response(
        data={
            'score': evaluation.total_score,
            'total_score': evaluation.total_possible_score,
            'correct_count': evaluation.correct_count,
            'total_count': evaluation.total_question_count,
            'mastery': mastery_list,
            'question_details': evaluation.question_details,
            'generating': True,
            'completed': True,
        },
        msg='测评提交成功，正在生成学习路径和报告…',
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsStudent])
def get_knowledge_result(request: Request) -> Response:
    """
    轮询获取知识测评结果（含异步生成状态）。
    GET /api/student/assessments/initial/knowledge/result?course_id=xxx
    """
    course_id = request.query_params.get('course_id')
    if not course_id:
        return error_response(msg='缺少course_id参数')

    user = get_authenticated_user(request)
    status = AssessmentStatus.objects.filter(user=user, course_id=course_id).first()
    if not status or not status.knowledge_done:
        return success_response(data=build_empty_knowledge_result(), msg='尚未完成知识测评')

    result = AssessmentResult.objects.filter(
        user=user,
        course_id=course_id,
        assessment__assessment_type='knowledge',
    ).order_by('-completed_at').first()
    if not result:
        return success_response(
            data=build_empty_knowledge_result(
                generating=bool(status and status.generating),
                generation_error=status.generation_error if status else None,
            ),
            msg='未找到评测结果',
        )

    feedback_report_data = None
    if not status.generating:
        try:
            from exams.models import FeedbackReport
            report = FeedbackReport.objects.filter(user=user, source='assessment', assessment_result=result).first()
            feedback_report_data = build_feedback_report_payload(report)
        except Exception as exc:
            logger.warning(f"获取反馈报告失败: {exc}")

    result_data = result.result_data if isinstance(result.result_data, dict) else {}
    mastery_list = result_data.get('mastery', [])
    if not isinstance(mastery_list, list):
        mastery_list = []
    return success_response(data={
        'score': float(result.score),
        'total_score': float(result_data.get('total_score', 0)),
        'correct_count': result_data.get('correct_count', 0),
        'total_count': result_data.get('total_count', 0),
        'mastery': mastery_list,
        'question_details': result_data.get('question_details', []),
        'feedback_report': feedback_report_data,
        'generating': status.generating,
        'generation_error': status.generation_error,
        'completed': True,
    }, msg='获取成功')
