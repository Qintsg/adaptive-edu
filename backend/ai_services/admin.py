"""
AI服务模块 - Admin配置
"""
from django.contrib import admin
from .models import (
    AgentRun,
    GeneratedLearningResource,
    GeneratedResourceFeedback,
    LLMCallLog,
    ProfileDialogTurn,
)


@admin.register(LLMCallLog)
class LLMCallLogAdmin(admin.ModelAdmin):
    """LLM调用日志管理"""
    list_display = ['call_type', 'user', 'model', 'is_success', 'tokens_used', 'duration_ms', 'created_at']
    list_filter = ['call_type', 'is_success', 'model']
    search_fields = ['user__username']
    readonly_fields = ['call_type', 'user', 'input_summary', 'output_summary', 'model', 
                       'tokens_used', 'duration_ms', 'is_success', 'error_message', 'created_at']


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    """A3 Agent 运行记录管理。"""

    list_display = ["id", "run_type", "user", "course", "status", "started_at", "finished_at", "created_at"]
    list_filter = ["run_type", "status", "course"]
    search_fields = ["user__username", "course__name", "input_text"]
    readonly_fields = [
        "user",
        "course",
        "run_type",
        "status",
        "input_text",
        "profile_snapshot",
        "agent_trace",
        "result_payload",
        "error_message",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    ]


@admin.register(ProfileDialogTurn)
class ProfileDialogTurnAdmin(admin.ModelAdmin):
    """画像对话轮次管理。"""

    list_display = ["id", "user", "course", "role", "created_at"]
    list_filter = ["role", "course"]
    search_fields = ["user__username", "course__name", "content"]
    readonly_fields = ["user", "course", "agent_run", "role", "content", "extracted_slots", "created_at"]


@admin.register(GeneratedLearningResource)
class GeneratedLearningResourceAdmin(admin.ModelAdmin):
    """生成学习资源管理。"""

    list_display = ["id", "title", "resource_type", "user", "course", "knowledge_point", "status", "created_at"]
    list_filter = ["resource_type", "status", "course"]
    search_fields = ["title", "user__username", "course__name", "knowledge_point__name"]
    readonly_fields = [
        "user",
        "course",
        "knowledge_point",
        "agent_run",
        "resource_type",
        "title",
        "content",
        "evidence",
        "profile_snapshot",
        "metadata",
        "status",
        "created_at",
        "updated_at",
    ]


@admin.register(GeneratedResourceFeedback)
class GeneratedResourceFeedbackAdmin(admin.ModelAdmin):
    """生成资源反馈管理。"""

    list_display = ["id", "resource", "user", "completed", "rating", "usefulness", "difficulty", "created_at"]
    list_filter = ["completed", "rating", "usefulness", "difficulty"]
    search_fields = ["resource__title", "user__username", "feedback"]
    readonly_fields = [
        "resource",
        "user",
        "completed",
        "rating",
        "usefulness",
        "difficulty",
        "feedback",
        "quiz_result",
        "time_spent_seconds",
        "created_at",
    ]
