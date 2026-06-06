"""
AI服务模块 - 数据模型
包含大模型调用日志相关的模型

LLMCallLog: 大模型调用日志，记录每次调用的输入输出
"""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class LLMCallLog(models.Model):
    """
    大模型调用日志模型
    
    记录每次大模型调用的详细信息，用于：
    - 调用追踪和调试
    - 用量统计
    - 性能分析
    """
    CALL_TYPES = [
        ('profile_analysis', '画像诊断'),
        ('path_planning', '路径规划'),
        ('resource_reason', '资源推荐'),
        ('feedback_report', '反馈报告'),
        ('chat', 'AI对话'),
        ('node_intro', '知识点介绍'),
        ('kt_analysis', 'KT分析'),
        ('resource_recommend', '资源推荐(AI)'),
        ('other', '其他'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='llm_calls', 
        verbose_name='用户'
    )
    call_type = models.CharField(
        '调用类型', 
        max_length=30, 
        choices=CALL_TYPES
    )
    input_summary = models.TextField(
        '输入摘要', 
        blank=True, 
        null=True
    )
    output_summary = models.TextField(
        '输出摘要', 
        blank=True, 
        null=True
    )
    model = models.CharField(
        '模型', 
        max_length=50, 
        blank=True, 
        null=True,
        help_text='如: deepseek-v4-flash, deepseek-chat, qwen-plus'
    )
    tokens_used = models.IntegerField(
        'Token用量', 
        null=True, 
        blank=True
    )
    duration_ms = models.IntegerField(
        '耗时(毫秒)', 
        null=True, 
        blank=True
    )
    is_success = models.BooleanField(
        '是否成功', 
        default=True
    )
    error_message = models.TextField(
        '错误信息', 
        blank=True, 
        null=True
    )
    created_at = models.DateTimeField('调用时间', auto_now_add=True)

    class Meta:
        db_table = 'llm_call_logs'
        verbose_name = 'LLM调用日志'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        user_name = self.user.username if self.user else '匿名'
        return f"{user_name} - {self.get_call_type_display()} @ {self.created_at}"


class AgentRun(models.Model):
    """
    A3 多智能体运行记录。

    记录一次画像对话、资源生成或学习包编排的输入、阶段轨迹和输出结果。
    """

    RUN_TYPES = [
        ("profile_dialog", "画像对话"),
        ("resource_generation", "资源生成"),
        ("learning_package", "学习包生成"),
    ]
    STATUS_CHOICES = [
        ("pending", "等待中"),
        ("running", "运行中"),
        ("completed", "已完成"),
        ("failed", "失败"),
        ("cancelled", "已取消"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_runs",
        verbose_name="用户",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.CASCADE,
        related_name="agent_runs",
        verbose_name="课程",
    )
    run_type = models.CharField("运行类型", max_length=40, choices=RUN_TYPES)
    status = models.CharField("状态", max_length=20, choices=STATUS_CHOICES, default="pending")
    input_text = models.TextField("输入内容", blank=True, default="")
    profile_snapshot = models.JSONField("画像快照", default=dict, blank=True)
    agent_trace = models.JSONField("智能体轨迹", default=list, blank=True)
    result_payload = models.JSONField("运行结果", default=dict, blank=True)
    error_message = models.TextField("错误信息", blank=True, default="")
    started_at = models.DateTimeField("开始时间", null=True, blank=True)
    finished_at = models.DateTimeField("结束时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "agent_runs"
        verbose_name = "Agent运行记录"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} - {self.get_run_type_display()} - {self.status}"


class ProfileDialogTurn(models.Model):
    """
    画像对话轮次。

    保存学生自然语言输入、系统追问以及每轮抽取到的画像字段。
    """

    ROLE_CHOICES = [
        ("student", "学生"),
        ("assistant", "助手"),
        ("system", "系统"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile_dialog_turns",
        verbose_name="用户",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.CASCADE,
        related_name="profile_dialog_turns",
        verbose_name="课程",
    )
    agent_run = models.ForeignKey(
        AgentRun,
        on_delete=models.CASCADE,
        related_name="dialog_turns",
        verbose_name="运行记录",
        null=True,
        blank=True,
    )
    role = models.CharField("角色", max_length=20, choices=ROLE_CHOICES)
    content = models.TextField("内容")
    extracted_slots = models.JSONField("抽取字段", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        db_table = "profile_dialog_turns"
        verbose_name = "画像对话轮次"
        verbose_name_plural = verbose_name
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.user.username} - {self.course.name} - {self.role}"


class GeneratedLearningResource(models.Model):
    """
    A3 个性化生成学习资源。

    保存面向学生、课程和知识点生成的讲解、思维导图、练习、阅读和实操内容。
    """

    RESOURCE_TYPES = [
        ("explanation", "讲解文档"),
        ("mindmap", "思维导图"),
        ("quiz", "练习题"),
        ("reading", "拓展阅读"),
        ("coding_case", "代码实操案例"),
        ("video_script", "视频脚本"),
    ]
    STATUS_CHOICES = [
        ("pending", "等待中"),
        ("running", "生成中"),
        ("completed", "已完成"),
        ("failed", "失败"),
        ("cancelled", "已取消"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="generated_learning_resources",
        verbose_name="用户",
    )
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.CASCADE,
        related_name="generated_learning_resources",
        verbose_name="课程",
    )
    knowledge_point = models.ForeignKey(
        "knowledge.KnowledgePoint",
        on_delete=models.SET_NULL,
        related_name="generated_learning_resources",
        verbose_name="知识点",
        null=True,
        blank=True,
    )
    agent_run = models.ForeignKey(
        AgentRun,
        on_delete=models.CASCADE,
        related_name="generated_resources",
        verbose_name="运行记录",
    )
    resource_type = models.CharField("资源类型", max_length=40, choices=RESOURCE_TYPES)
    title = models.CharField("标题", max_length=300)
    content = models.TextField("内容")
    evidence = models.JSONField("证据来源", default=list, blank=True)
    profile_snapshot = models.JSONField("画像快照", default=dict, blank=True)
    metadata = models.JSONField("元数据", default=dict, blank=True)
    status = models.CharField("状态", max_length=20, choices=STATUS_CHOICES, default="completed")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "generated_learning_resources"
        verbose_name = "生成学习资源"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.get_resource_type_display()})"


class GeneratedResourceFeedback(models.Model):
    """
    生成资源学习反馈。

    记录学生对生成资源的完成状态、评分、难度感受和文本反馈。
    """

    USEFULNESS_CHOICES = [
        ("useful", "有帮助"),
        ("neutral", "一般"),
        ("not_useful", "无帮助"),
    ]
    DIFFICULTY_CHOICES = [
        ("easy", "偏简单"),
        ("moderate", "适中"),
        ("hard", "偏困难"),
    ]

    resource = models.ForeignKey(
        GeneratedLearningResource,
        on_delete=models.CASCADE,
        related_name="feedback_records",
        verbose_name="生成资源",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="generated_resource_feedback",
        verbose_name="用户",
    )
    completed = models.BooleanField("是否完成", default=False)
    rating = models.IntegerField(
        "评分",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    usefulness = models.CharField("有用性", max_length=20, choices=USEFULNESS_CHOICES, default="neutral")
    difficulty = models.CharField("难度", max_length=20, choices=DIFFICULTY_CHOICES, default="moderate")
    feedback = models.TextField("文本反馈", blank=True, default="")
    quiz_result = models.JSONField("练习结果", default=dict, blank=True)
    time_spent_seconds = models.IntegerField("学习耗时秒数", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        db_table = "generated_resource_feedback"
        verbose_name = "生成资源反馈"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
        unique_together = ["resource", "user"]

    def __str__(self):
        return f"{self.user.username} - {self.resource.title} - {self.usefulness}"
