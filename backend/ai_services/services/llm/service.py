"""
LLM服务模块 - 使用LangChain框架封装大模型调用

支持的模型：
- DeepSeek V4 (按调用场景选择 deepseek-v4-pro / deepseek-v4-flash)
- 其他 OpenAI 兼容模型可在代码层显式传入 model_name，并复用统一网关。

使用示例:
    from ai_services.services import llm_service

    result = llm_service.analyze_profile(user_data)
"""

from __future__ import annotations

from importlib import import_module
import logging
import json
import os
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from django.conf import settings

from ai_services.services.llm.feedback_kt_mixin import LLMFeedbackKTMixin
from ai_services.services.llm.error_details import summarize_exception_chain
from ai_services.services.llm.profile_path_mixin import LLMProfilePathMixin
from ai_services.services.llm.provider_config import (
    AGENT_ENABLED_CALL_TYPES,
    DEFAULT_MAX_PROMPT_CHARS,
    DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
    DEEPSEEK_FLASH_MODEL,
    DEEPSEEK_PRO_MODEL,
    FAST_FAIL_CALL_TYPES,
    GATEWAY_SAFE_TIMEOUT_SECONDS,
    GRAPH_RAG_MAX_PROMPT_CHARS,
    HIGH_REASONING_CALL_TYPES,
    LATENCY_SAFE_MAX_PROMPT_CHARS,
    LLMCallParameterPlan,
    LLMExecutionPolicy,
    MODEL_CONFIGS as MODEL_PROVIDER_CONFIGS,
    ModelProviderConfig,
    PROMPT_TRUNCATION_NOTICE,
    PRO_MODEL_CALL_TYPES,
    SUPPORTED_API_FORMATS,
)
from ai_services.services.llm.resource_mixin import LLMResourceMixin
from ai_services.services.llm.response_mixin import LLMResponseMixin
from common.core.logging_utils import build_log_message

logger = logging.getLogger(__name__)


def _read_runtime_setting(name: str) -> str:
    """Read a string setting from Django settings first, then environment variables."""
    raw_value = getattr(settings, name, "")
    if isinstance(raw_value, str) and raw_value.strip():
        return raw_value.strip()
    return os.getenv(name, "").strip()


def resolve_llm_proxy_for_base_url(base_url: str) -> str:
    """Resolve the most suitable proxy for the current LLM gateway URL."""
    normalized_base_url = (base_url or "").strip()
    parsed_scheme = urlparse(normalized_base_url).scheme.lower()
    http_proxy = _read_runtime_setting("LLM_HTTP_PROXY") or _read_runtime_setting("HTTP_PROXY")
    https_proxy = _read_runtime_setting("LLM_HTTPS_PROXY") or _read_runtime_setting("HTTPS_PROXY")
    if parsed_scheme == "http":
        return http_proxy or https_proxy
    return https_proxy or http_proxy


class LLMService(LLMProfilePathMixin, LLMResourceMixin, LLMFeedbackKTMixin, LLMResponseMixin):
    """
    大语言模型服务类。

    使用 LangChain 框架进行 LLM 调用，默认按业务场景选择 DeepSeek V4 Pro 或 Flash。
    当未配置统一 API 密钥时，自动使用 Mock 响应。
    """

    MODEL_CONFIGS: dict[str, ModelProviderConfig] = MODEL_PROVIDER_CONFIGS
    SUPPORTED_API_FORMATS = SUPPORTED_API_FORMATS
    AGENT_ENABLED_CALL_TYPES = AGENT_ENABLED_CALL_TYPES
    FAST_FAIL_CALL_TYPES = FAST_FAIL_CALL_TYPES
    GATEWAY_SAFE_TIMEOUT_SECONDS = GATEWAY_SAFE_TIMEOUT_SECONDS
    DEFAULT_MAX_PROMPT_CHARS = DEFAULT_MAX_PROMPT_CHARS
    GRAPH_RAG_MAX_PROMPT_CHARS = GRAPH_RAG_MAX_PROMPT_CHARS
    LATENCY_SAFE_MAX_PROMPT_CHARS = LATENCY_SAFE_MAX_PROMPT_CHARS
    PROMPT_TRUNCATION_NOTICE = PROMPT_TRUNCATION_NOTICE
    def __init__(self, model_name: Optional[str] = None, temperature: float = 0.3):
        """
        初始化LLM服务

        Args:
            model_name: 显式模型名称；为空时由调用策略在 DeepSeek V4 Pro / Flash 中选择
            temperature: 生成温度，0-1之间，越高越随机
        """
        if model_name:
            self.model_name = model_name
            self._explicit_model_name = True
        else:
            self.model_name = "deepseek-v4"
            self._explicit_model_name = False
        self.temperature = temperature
        self._llm = None
        self._api_key = None
        self._base_url = None
        self._provider = ""
        self._api_format = "openai-compatible"
        self._request_timeout = int(getattr(settings, "LLM_REQUEST_TIMEOUT", 120) or 120)
        self._max_retries = int(getattr(settings, "LLM_MAX_RETRIES", 2) or 2)
        self._agent_service = None
        self._proxy_url = ""
        self._low_reasoning_mode = bool(getattr(settings, "LLM_LOW_REASONING_MODE", False))
        self._extra_body: dict[str, Any] = {}

        # 确定模型提供商和API配置
        self._detect_provider()
        self._extra_body = self._resolve_extra_body()

    @property
    def provider_name(self) -> str:
        """返回解析后的提供方标识。"""
        return self._provider or "deepseek"

    @property
    def resolved_api_key(self) -> str:
        """返回当前实例解析后的 API Key。"""
        return self._api_key or ""

    @property
    def resolved_base_url(self) -> str:
        """返回当前实例解析后的 Base URL。"""
        return self._base_url or ""

    @property
    def api_format(self) -> str:
        """返回当前实例使用的接口格式描述。"""
        return self._api_format or "openai-compatible"

    @staticmethod
    def _read_setting(name: str) -> str:
        """优先读取 Django settings，再回退到环境变量。"""
        return _read_runtime_setting(name)

    @property
    def resolved_proxy_url(self) -> str:
        """返回当前网关将使用的代理地址。"""
        return self._proxy_url or ""

    @property
    def resolved_extra_body(self) -> dict[str, Any]:
        """返回默认调用会透传给 OpenAI 兼容网关的额外请求体。"""
        return dict(self._extra_body)

    @property
    def planned_model_family(self) -> str:
        """返回默认模型族描述，实际模型由调用类型决定。"""
        return self.model_name if self._explicit_model_name else "deepseek-v4-pro/flash"

    @property
    def low_reasoning_mode(self) -> bool:
        """返回是否启用了全局低思考/加速模式。"""
        return self._low_reasoning_mode

    @classmethod
    def _normalize_provider_name(cls, provider_name: str) -> str:
        """标准化提供方名称，兼容常见别名。"""
        normalized_name = provider_name.strip().lower()
        alias_map = {"openai-compatible": "custom"}
        return alias_map.get(normalized_name, normalized_name)

    @classmethod
    def _provider_from_model_name(cls, model_name: str) -> str | None:
        """根据模型名前缀反推提供方。"""
        normalized_model = model_name.strip().lower()
        for provider_name, provider_config in cls.MODEL_CONFIGS.items():
            model_prefixes = provider_config.get("model_prefixes", [])
            if any(normalized_model.startswith(prefix) for prefix in model_prefixes):
                return provider_name
        return None

    @classmethod
    def _first_non_empty_setting(cls, keys: list[str]) -> str:
        """从候选设置键中返回第一个非空值。"""
        for key in keys:
            resolved_value = cls._read_setting(key)
            if resolved_value:
                return resolved_value
        return ""

    def _detect_provider(self):
        """
        检测模型提供商并设置API配置

        按模型名前缀识别代码层模型类型，运行时只读取统一 API Key 与统一 base URL。
        所有当前支持的提供方都通过 OpenAI 兼容接口接入。
        """
        detected_provider = self._provider_from_model_name(self.model_name)

        if detected_provider not in self.MODEL_CONFIGS:
            has_custom_gateway = bool(self._read_setting("LLM_API_KEY")) and bool(
                self._read_setting("LLM_BASE_URL")
            )
            detected_provider = "custom" if has_custom_gateway else "deepseek"

        provider_config = self.MODEL_CONFIGS[detected_provider]
        self._provider = detected_provider
        self._api_key = self._first_non_empty_setting(provider_config.get("env_keys", []))

        shared_base_url = self._read_setting("LLM_BASE_URL")
        self._base_url = shared_base_url or DEFAULT_OPENAI_COMPATIBLE_BASE_URL
        self._proxy_url = resolve_llm_proxy_for_base_url(self._base_url)
        self._api_format = provider_config.get("api_format", "openai-compatible")

        logger.debug(
            build_log_message(
                "llm.provider.detected",
                provider=self._provider,
                model=self.planned_model_family,
                api_format=self._api_format,
                base_url=self._base_url,
            )
        )

    def _resolve_extra_body(self) -> dict[str, Any]:
        """构造统一 OpenAI 兼容请求的基础额外参数。"""
        return {}

    @classmethod
    def _call_type_enables_thinking(cls, call_type: str) -> bool:
        """根据业务调用类型判断是否启用 DeepSeek 思考模式。"""
        normalized_call_type = (call_type or "").strip().lower()
        if not normalized_call_type:
            return False
        if normalized_call_type.startswith("graph_rag_"):
            return False
        return (
            normalized_call_type in HIGH_REASONING_CALL_TYPES
            or normalized_call_type in AGENT_ENABLED_CALL_TYPES
            or normalized_call_type.startswith("agent_")
        )

    @classmethod
    def _reasoning_effort_for_call_type(cls, call_type: str) -> str:
        """根据业务调用类型返回 DeepSeek V4 思考深度。"""
        normalized_call_type = (call_type or "").strip().lower()
        if normalized_call_type in AGENT_ENABLED_CALL_TYPES or normalized_call_type.startswith("agent_"):
            return "max"
        if normalized_call_type in HIGH_REASONING_CALL_TYPES:
            return "high"
        return ""

    def _model_for_call_type(self, call_type: str) -> str:
        """根据业务调用类型选择 DeepSeek V4 Pro 或 Flash。"""
        if self._explicit_model_name:
            return self.model_name
        if self.low_reasoning_mode:
            return DEEPSEEK_FLASH_MODEL
        normalized_call_type = (call_type or "").strip().lower()
        if normalized_call_type in PRO_MODEL_CALL_TYPES or normalized_call_type.startswith("agent_"):
            return DEEPSEEK_PRO_MODEL
        return DEEPSEEK_FLASH_MODEL

    def _apply_thinking_flag(
        self,
        *,
        extra_body: dict[str, Any],
        thinking_enabled: bool,
    ) -> dict[str, Any]:
        """按提供方兼容性写入思考开关，低思考模式会覆盖为关闭。"""
        planned_extra_body = dict(extra_body)
        if self.provider_name == "deepseek":
            planned_extra_body["thinking"] = {
                "type": "enabled" if thinking_enabled else "disabled"
            }
            return planned_extra_body

        model_name = self.model_name.strip().lower()
        if (
            self.provider_name in {"qwen", "custom"}
            or "thinking" in model_name
            or "reasoner" in model_name
        ):
            planned_extra_body["enable_thinking"] = thinking_enabled
        return planned_extra_body

    def _resolve_call_parameter_plan(
        self,
        call_type: str = "",
        extra_body_overrides: Optional[Dict[str, Any]] = None,
    ) -> LLMCallParameterPlan:
        """为一次模型调用规划模型、思考模式、思考深度和额外请求体。"""
        thinking_enabled = self._call_type_enables_thinking(call_type)
        reasoning_effort = self._reasoning_effort_for_call_type(call_type)
        if self.low_reasoning_mode:
            thinking_enabled = False
            reasoning_effort = ""

        extra_body = dict(self._extra_body or {})
        if extra_body_overrides:
            extra_body.update(extra_body_overrides)
        extra_body = self._apply_thinking_flag(
            extra_body=extra_body,
            thinking_enabled=thinking_enabled,
        )
        return LLMCallParameterPlan(
            model_name=self._model_for_call_type(call_type),
            thinking_enabled=thinking_enabled,
            reasoning_effort=reasoning_effort if thinking_enabled else "",
            extra_body=extra_body,
        )

    @staticmethod
    def _clamp_positive_int(value: int, minimum: int = 1) -> int:
        """Clamp integer settings to a positive lower bound."""
        return max(minimum, int(value))

    @classmethod
    def _truncate_prompt(cls, prompt: str, max_prompt_chars: int) -> str:
        """Trim oversized prompts while preserving both instructions and output schema."""
        normalized_prompt = str(prompt or "").strip()
        if max_prompt_chars <= 0 or len(normalized_prompt) <= max_prompt_chars:
            return normalized_prompt

        marker = cls.PROMPT_TRUNCATION_NOTICE
        if max_prompt_chars <= len(marker) + 64:
            return normalized_prompt[:max_prompt_chars]

        usable_chars = max_prompt_chars - len(marker)
        head_chars = int(usable_chars * 0.6)
        tail_chars = usable_chars - head_chars
        return (
            f"{normalized_prompt[:head_chars].rstrip()}"
            f"{marker}"
            f"{normalized_prompt[-tail_chars:].lstrip()}"
        )

    def _resolve_execution_policy(self, call_type: str) -> LLMExecutionPolicy:
        """Resolve a call-specific timeout and prompt budget policy."""
        normalized_call_type = (call_type or "").strip().lower()
        default_timeout = self._clamp_positive_int(self._request_timeout, minimum=5)
        default_retries = max(0, int(self._max_retries))

        if normalized_call_type.startswith("graph_rag_"):
            safe_timeout = min(default_timeout, self.GATEWAY_SAFE_TIMEOUT_SECONDS)
            return LLMExecutionPolicy(
                request_timeout_seconds=self._clamp_positive_int(safe_timeout, minimum=5),
                max_retries=0,
                max_attempts=1,
                allow_repair=False,
                max_prompt_chars=self.GRAPH_RAG_MAX_PROMPT_CHARS,
            )

        if normalized_call_type in self.FAST_FAIL_CALL_TYPES:
            safe_timeout = min(default_timeout, self.GATEWAY_SAFE_TIMEOUT_SECONDS)
            return LLMExecutionPolicy(
                request_timeout_seconds=self._clamp_positive_int(safe_timeout, minimum=5),
                max_retries=0,
                max_attempts=1,
                allow_repair=False,
                max_prompt_chars=self.LATENCY_SAFE_MAX_PROMPT_CHARS,
            )

        return LLMExecutionPolicy(
            request_timeout_seconds=default_timeout,
            max_retries=default_retries,
            max_attempts=2,
            allow_repair=True,
            max_prompt_chars=self.DEFAULT_MAX_PROMPT_CHARS,
        )

    @property
    def is_available(self) -> bool:
        """检查LLM服务是否可用"""
        return bool(self._api_key)

    def _create_llm_client(
        self,
        request_timeout: int,
        max_retries: int,
        call_type: str = "",
        extra_body_overrides: Optional[Dict[str, Any]] = None,
    ):
        """Instantiate a ChatOpenAI client with the supplied latency budget."""
        normalized_format = self.api_format.replace("_", "-").lower()
        if normalized_format not in self.SUPPORTED_API_FORMATS:
            logger.warning(
                build_log_message(
                    "llm.client.unsupported_format",
                    api_format=self.api_format,
                    provider=self.provider_name,
                    model=self.planned_model_family,
                )
            )
            return None

        chat_openai_module = import_module("langchain_openai")
        chat_openai_class = getattr(chat_openai_module, "ChatOpenAI")
        parameter_plan = self._resolve_call_parameter_plan(
            call_type=call_type,
            extra_body_overrides=extra_body_overrides,
        )
        client_kwargs = {
            "model": parameter_plan.model_name,
            "api_key": self._api_key,
            "base_url": self._base_url,
            "openai_proxy": self._proxy_url or None,
            "request_timeout": self._clamp_positive_int(request_timeout, minimum=5),
            "max_retries": max(0, int(max_retries)),
        }
        if not parameter_plan.thinking_enabled:
            client_kwargs["temperature"] = self.temperature
        extra_body = dict(parameter_plan.extra_body)
        if extra_body:
            client_kwargs["extra_body"] = extra_body
        if parameter_plan.thinking_enabled and parameter_plan.reasoning_effort:
            client_kwargs["reasoning_effort"] = parameter_plan.reasoning_effort
        return chat_openai_class(**client_kwargs)

    def _get_llm(self):
        """
        延迟初始化LLM实例

        使用 langchain_openai.ChatOpenAI 作为兼容协议客户端，
        仅承载通义千问与 DeepSeek 的聊天调用。
        """
        if self._llm is None and self.is_available:
            try:
                self._llm = self._create_llm_client(
                    request_timeout=self._request_timeout,
                    max_retries=self._max_retries,
                    call_type="",
                )
                # 写入日志记录
                if self._llm is not None:
                    logger.debug(
                        build_log_message(
                            "llm.client.ready",
                            model=self.planned_model_family,
                            base_url=self._base_url,
                        )
                    )
            except ImportError:
                # 写入日志记录
                logger.warning(
                    build_log_message(
                        "llm.client.import_error", detail="langchain_openai 未安装"
                    )
                )
            except Exception as e:
                # 写入日志记录
                logger.error(
                    build_log_message(
                        "llm.client.init_fail",
                        model=self.planned_model_family,
                        provider=self.provider_name,
                        base_url=self._base_url,
                        proxy_enabled=bool(self._proxy_url),
                        error=e,
                        error_detail=summarize_exception_chain(e),
                    )
                )

        return self._llm

    def _get_llm_for_policy(
        self,
        policy: LLMExecutionPolicy,
        call_type: str = "",
        extra_body_overrides: Optional[Dict[str, Any]] = None,
    ):
        """Return a cached or one-off chat client that matches the execution policy."""
        if not self.is_available:
            return None

        parameter_plan = self._resolve_call_parameter_plan(
            call_type=call_type,
            extra_body_overrides=extra_body_overrides,
        )

        uses_default_budget = (
            policy.request_timeout_seconds == self._clamp_positive_int(self._request_timeout, minimum=5)
            and policy.max_retries == max(0, int(self._max_retries))
        )
        if uses_default_budget and not parameter_plan.thinking_enabled and not extra_body_overrides:
            return self._get_llm()

        try:
            return self._create_llm_client(
                request_timeout=policy.request_timeout_seconds,
                max_retries=policy.max_retries,
                call_type=call_type,
                extra_body_overrides=extra_body_overrides,
            )
        except ImportError:
            logger.warning(
                build_log_message(
                    "llm.client.import_error",
                    detail="langchain_openai 未安装",
                )
            )
            return None
        except Exception as error:
            logger.error(
                build_log_message(
                    "llm.client.init_fail",
                    model=self.planned_model_family,
                    provider=self.provider_name,
                    base_url=self._base_url,
                    proxy_enabled=bool(self._proxy_url),
                    error=error,
                    error_detail=summarize_exception_chain(error),
                    timeout_seconds=policy.request_timeout_seconds,
                    max_retries=policy.max_retries,
                )
            )
            return None

    def _get_agent_service(self):
        """Lazily build the LangChain agent orchestration layer."""
        if self._agent_service is None and self.is_available:
            from platform_ai.llm.agent import get_agent_service

            parameter_plan = self._resolve_call_parameter_plan("agent_orchestration")
            self._agent_service = get_agent_service(
                model_name=parameter_plan.model_name,
                api_key=self._api_key,
                base_url=self._base_url,
                api_format=self.api_format,
                temperature=self.temperature,
                request_timeout=self._request_timeout,
                max_retries=self._max_retries,
                proxy_url=self._proxy_url,
                reasoning_enabled=parameter_plan.thinking_enabled,
                reasoning_effort=parameter_plan.reasoning_effort,
                extra_body_json=json.dumps(
                    parameter_plan.extra_body,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        return self._agent_service

    @classmethod
    def _should_use_agent_service(cls, call_type: str) -> bool:
        """仅对显式 agent 任务启用编排层，避免常规调用产生递归开销。"""
        normalized_call_type = (call_type or "").strip().lower()
        if not normalized_call_type:
            return False
        if normalized_call_type.startswith("graph_rag_"):
            return False
        return (
            normalized_call_type in cls.AGENT_ENABLED_CALL_TYPES
            or normalized_call_type.startswith("agent_")
        )


# 创建默认实例
llm_service = LLMService()
