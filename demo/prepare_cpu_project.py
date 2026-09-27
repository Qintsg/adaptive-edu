#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
将镜像内的 PyTorch 源切换到 CPU，保留仓库原始 pyproject 与 uv.lock。
@Project : adaptive-edu
@File : prepare_cpu_project.py
@Author : Qintsg
@Date : 2026-09-27
'''

from __future__ import annotations

import sys
from pathlib import Path


def prepare_cpu_project(project_file: Path) -> None:
    """只修改镜像构建上下文中的项目配置副本。

    :param project_file: Docker 层内 pyproject.toml 的绝对路径。
    :returns: None。
    :raises RuntimeError: 项目配置不符合预期，无法安全替换。
    """
    source = project_file.read_text(encoding="utf-8")
    replacements = {
        'name = "pytorch-cu130"': 'name = "pytorch-cpu"',
        'url = "https://download.pytorch.org/whl/cu130"': 'url = "https://download.pytorch.org/whl/cpu"',
        'torch = { index = "pytorch-cu130" }': 'torch = { index = "pytorch-cpu" }',
        'package = false': 'package = false\nenvironments = ["sys_platform == \'linux\'"]',
    }
    for original, replacement in replacements.items():
        if source.count(original) != 1:
            raise RuntimeError(f"pyproject 中预期配置出现次数错误：{original}")
        source = source.replace(original, replacement, 1)
    project_file.write_text(source, encoding="utf-8", newline="\n")


def main() -> int:
    """从命令行读取镜像内配置路径并执行替换。

    :returns: 成功时返回 0。
    :raises ValueError: 命令行参数数量错误。
    """
    if len(sys.argv) != 2:
        raise ValueError("需要提供镜像内 pyproject.toml 路径")
    prepare_cpu_project(Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
