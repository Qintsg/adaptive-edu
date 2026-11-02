# 文件描述：核验教师与学生作业详情的分值一致性。
# 项目名：adaptive-edu；文件名：test_teacher_score_display.py；作者：Qintsg；日期：2026-11-02。
from decimal import Decimal

from rest_framework.test import APITestCase

from assessments.models import Question
from courses.models import Class, ClassCourse, Course, Enrollment
from exams.models import Exam, ExamQuestion
from users.models import User


class TeacherScoreDisplayTests(APITestCase):
    """通过真实登录与接口响应核对百分制分值。"""

    def test_teacher_and_student_see_the_same_normalized_scores(self) -> None:
        """不同题目权重应在两个角色中形成相同的100分分配。

        :returns: 无。
        """
        teacher = User.objects.create_user(
            username="score_display_teacher", password="Test123456", role="teacher"
        )
        student = User.objects.create_user(
            username="score_display_student", password="Test123456", role="student"
        )
        course = Course.objects.create(name="作业分值课程", created_by=teacher)
        teaching_class = Class.objects.create(name="分值班级", teacher=teacher, course=course)
        ClassCourse.objects.create(class_obj=teaching_class, course=course)
        Enrollment.objects.create(user=student, class_obj=teaching_class)
        exam = Exam.objects.create(
            course=course, title="加权作业", created_by=teacher, target_class=teaching_class,
            total_score=100, pass_score=60, status="published",
        )
        for index, weight in enumerate((Decimal("12.5"), Decimal("2"))):
            question = Question.objects.create(
                course=course, content=f"分值题目{index + 1}", question_type="single_choice",
                options=[{"label": "A", "content": "选项A"}, {"label": "B", "content": "选项B"}],
                answer={"answer": "A"}, analysis="根据课程知识判断。", score=1,
            )
            ExamQuestion.objects.create(exam=exam, question=question, score=weight, order=index)

        score_maps = []
        for user, role in ((teacher, "teacher"), (student, "student")):
            self.client.credentials()
            login = self.client.post(
                "/api/auth/login", {"username": user.username, "password": "Test123456"}, format="json"
            )
            self.assertEqual(login.status_code, 200)
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['data']['token']}")
            response = self.client.get(f"/api/{role}/exams/{exam.id}")
            self.assertEqual(response.status_code, 200)
            data = response.data["data"]
            scores = {row["question_id"]: Decimal(str(row["score"])) for row in data["questions"]}
            self.assertEqual(sum(scores.values()), Decimal("100"))
            self.assertEqual(Decimal(str(data["total_score"])), Decimal("100"))
            self.assertEqual(list(scores.values()), [Decimal("86.21"), Decimal("13.79")])
            score_maps.append(scores)
        self.assertEqual(score_maps[0], score_maps[1])
