"""AI、图谱与外部资源相关 Django settings 装载。"""

from __future__ import annotations

from collections.abc import Callable
import logging
import os


ConfigValue = Callable[[str, str, str], str]
ConfigInt = Callable[[str, str, int], int]
EnvConfigBool = Callable[[str, str, str, bool], bool]
ConfigJsonDict = Callable[[str, str, str], dict[str, object]]


def _int_setting(
    env_name: str,
    section: str,
    key: str,
    default: int,
    config_int: ConfigInt,
) -> int:
    """读取环境变量优先的整数配置。"""
    value = config_int(section, key, default)
    raw_env_value = os.getenv(env_name, "").strip()
    if raw_env_value.isdigit():
        return int(raw_env_value)
    return value


def load_ai_settings(
    config_value: ConfigValue,
    config_int: ConfigInt,
    env_config_bool: EnvConfigBool,
    config_json_dict: ConfigJsonDict,
    debug: bool,
) -> dict[str, object]:
    """
    加载 AI、Neo4j、GraphRAG 与资源 MCP settings。

    :return: 可合并进 Django settings 模块 globals 的变量字典。
    """
    settings_values = _load_graph_and_resource_settings(
        config_value,
        config_int,
        env_config_bool,
    )
    settings_values.update(
        _load_llm_settings(
            config_value,
            config_int,
            env_config_bool,
            config_json_dict,
            debug,
        )
    )
    return settings_values


def _load_graph_and_resource_settings(
    config_value: ConfigValue,
    config_int: ConfigInt,
    env_config_bool: EnvConfigBool,
) -> dict[str, object]:
    """加载 Neo4j、GraphRAG 和资源 MCP settings。"""
    return {
        "NEO4J_BOLT_URL": os.getenv("NEO4J_BOLT_URL", "bolt://localhost:7687"),
        "NEO4J_USERNAME": os.getenv("NEO4J_USERNAME", "neo4j"),
        "NEO4J_PASSWORD": os.getenv("NEO4J_PASSWORD", "password"),
        "GRAPHRAG_EMBEDDER_PROVIDER": os.getenv(
            "GRAPHRAG_EMBEDDER_PROVIDER",
            config_value("graphrag", "embedder_provider", "hash"),
        ).strip() or "hash",
        "GRAPHRAG_SENTENCE_MODEL": os.getenv(
            "GRAPHRAG_SENTENCE_MODEL",
            config_value(
                "graphrag",
                "sentence_model",
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            ),
        ).strip() or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "GRAPHRAG_VECTOR_DIMENSION": _int_setting(
            "GRAPHRAG_VECTOR_DIMENSION",
            "graphrag",
            "vector_dimension",
            256,
            config_int,
        ),
        "GRAPHRAG_QDRANT_PATH": os.getenv(
            "GRAPHRAG_QDRANT_PATH",
            config_value("graphrag", "qdrant_path", "runtime_logs/rag/qdrant"),
        ).strip() or "runtime_logs/rag/qdrant",
        "RESOURCE_MCP_ENABLED": env_config_bool(
            "RESOURCE_MCP_ENABLED", "resource_mcp", "enabled", True
        ),
        "RESOURCE_MCP_TIMEOUT_SECONDS": _int_setting(
            "RESOURCE_MCP_TIMEOUT_SECONDS", "resource_mcp", "timeout_seconds", 12, config_int
        ),
        "TAVILY_API_KEY": os.getenv("TAVILY_API_KEY", ""),
        "TAVILY_SEARCH_DEPTH": os.getenv(
            "TAVILY_SEARCH_DEPTH", config_value("resource_mcp", "tavily_search_depth", "basic")
        ),
        "TAVILY_MAX_RESULTS": _int_setting(
            "TAVILY_MAX_RESULTS", "resource_mcp", "tavily_max_results", 8, config_int
        ),
    }


def _load_llm_settings(
    config_value: ConfigValue,
    config_int: ConfigInt,
    env_config_bool: EnvConfigBool,
    config_json_dict: ConfigJsonDict,
    debug: bool,
) -> dict[str, object]:
    """加载 DeepSeek V4、统一网关、代理、重试和密钥 settings。"""
    values: dict[str, object] = {
        "LLM_REQUEST_TIMEOUT": _int_setting(
            "LLM_REQUEST_TIMEOUT",
            "llm",
            "request_timeout_seconds",
            config_int("ai_services", "api_timeout", 120),
            config_int,
        ),
        "LLM_MAX_RETRIES": _int_setting(
            "LLM_MAX_RETRIES", "llm", "max_retries", 2, config_int
        ),
        "LLM_BASE_URL": os.getenv(
            "LLM_BASE_URL", config_value("llm", "base_url", "https://api.deepseek.com")
        ).strip()
        or "https://api.deepseek.com",
        "LLM_LOW_REASONING_MODE": env_config_bool(
            "LLM_LOW_REASONING_MODE", "llm", "low_reasoning_mode", False
        ),
        "LLM_HTTP_PROXY": os.getenv("LLM_HTTP_PROXY", os.getenv("HTTP_PROXY", "")).strip(),
        "LLM_HTTPS_PROXY": os.getenv("LLM_HTTPS_PROXY", os.getenv("HTTPS_PROXY", "")).strip(),
        "LLM_API_KEY": os.getenv("LLM_API_KEY", ""),
    }

    _ = config_json_dict
    if not debug and not values["LLM_API_KEY"]:
        logging.warning("未配置LLM API密钥，AI功能将使用Mock响应。")
        logging.warning("请在 backend/.env 中设置统一 OpenAI 兼容网关密钥 LLM_API_KEY。")

    return values
