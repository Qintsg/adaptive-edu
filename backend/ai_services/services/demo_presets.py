#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""真实 AI 彩排结果的指纹记录与精确匹配读取。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any

from ai_services.services.demo_fallback import demo_mode_enabled
from ai_services.services.llm.provider_config import DEEPSEEK_FLASH_MODEL


logger = logging.getLogger(__name__)
_WRITE_LOCK = Lock()
_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_LINE_BYTES = 512 * 1024


def prompt_sha256(prompt: str) -> str:
    """计算请求文本的稳定指纹。

    :param prompt: 实际发送给模型的文本。
    :returns: SHA256 十六进制摘要。
    """
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def load_verified_answer(kind: str, call_type: str, prompt: str) -> Any | None:
    """演示模式下读取同模型、同请求的彩排结果。

    :param kind: json、text 或 api_json。
    :param call_type: AI 调用类型。
    :param prompt: 实际请求文本。
    :returns: 精确匹配的预置结果；未命中返回 None。
    """
    if not demo_mode_enabled():
        return None
    filename = os.getenv("DEMO_AI_PRESET_FILE", "").strip()
    if not filename:
        return None
    path = Path(filename)
    try:
        if not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
            return None
        target_hash = prompt_sha256(prompt)
        matched: Any | None = None
        with path.open("rb") as source:
            for line in source:
                if len(line) > _MAX_LINE_BYTES:
                    continue
                try:
                    entry = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(entry, dict):
                    continue
                if (
                    entry.get("schema_version") == 1
                    and entry.get("model") == DEEPSEEK_FLASH_MODEL
                    and entry.get("kind") == kind
                    and entry.get("call_type") == call_type
                    and entry.get("prompt_sha256") == target_hash
                ):
                    response = entry.get("response")
                    if (kind in {"json", "api_json"} and isinstance(response, dict)) or (
                        kind == "text" and isinstance(response, str) and response
                    ):
                        matched = response
        return matched
    except OSError as error:
        logger.warning("读取 AI 彩排结果失败: %s", error)
        return None


def record_verified_answer(kind: str, call_type: str, prompt: str, response: Any) -> None:
    """仅在真实调用成功后记录答案，不保存密钥或原始 prompt。

    :param kind: json、text 或 api_json。
    :param call_type: AI 调用类型。
    :param prompt: 实际请求文本。
    :param response: 真实调用结果。
    :returns: None。
    """
    if not demo_mode_enabled():
        return
    filename = os.getenv("DEMO_AI_CAPTURE_FILE", "").strip()
    if not filename:
        return
    if kind in {"json", "api_json"} and not isinstance(response, dict):
        return
    if kind == "text" and (not isinstance(response, str) or not response):
        return
    entry = {
        "schema_version": 1,
        "model": DEEPSEEK_FLASH_MODEL,
        "kind": kind,
        "call_type": call_type,
        "prompt_sha256": prompt_sha256(prompt),
        "response": response,
    }
    try:
        encoded = (json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError):
        logger.warning("AI 彩排答案包含不可序列化内容，跳过记录: call_type=%s", call_type)
        return
    if len(encoded) > _MAX_LINE_BYTES:
        logger.warning("AI 彩排答案过长，跳过记录: call_type=%s", call_type)
        return
    try:
        path = Path(filename)
        with _WRITE_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("ab") as target:
                target.write(encoded)
    except OSError as error:
        logger.warning("记录 AI 彩排结果失败: %s", error)
