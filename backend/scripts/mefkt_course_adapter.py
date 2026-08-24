#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT 新课程轻量 logit 校准适配器。
@Project : adaptive-edu
@File : mefkt_course_adapter.py
@Author : Qintsg
@Date : 2026-08-24
'''

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import torch
from torch import Tensor, nn


@dataclass(frozen=True)
class CourseAdapterConfig:
    """可序列化的新课程校准参数。"""

    temperature: float
    bias: float

    def to_dict(self) -> dict[str, float]:
        """
        返回可写入 JSON 的适配器参数。

        :returns: 温度和偏置字典。
        """
        return asdict(self)


class CourseLogitAdapter(nn.Module):
    """只调整预测温度和整体难度偏置的两参数课程适配器。"""

    def __init__(self, temperature: float = 1.0, bias: float = 0.0) -> None:
        """
        初始化课程适配器。

        :param temperature: 初始正温度。
        :param bias: 初始 logit 偏置。
        :returns: None。
        """
        super().__init__()
        if temperature <= 0:
            raise ValueError("temperature 必须大于 0")
        self.log_temperature = nn.Parameter(torch.tensor(math.log(temperature), dtype=torch.float32))
        self.bias = nn.Parameter(torch.tensor(float(bias), dtype=torch.float32))

    def forward(self, logits: Tensor) -> Tensor:
        """
        校准基础模型 logits。

        :param logits: 任意形状的基础模型 logits。
        :returns: 形状不变的课程校准 logits。
        """
        temperature = self.log_temperature.clamp(math.log(0.05), math.log(20.0)).exp()
        return logits / temperature + self.bias

    def config(self) -> CourseAdapterConfig:
        """
        导出当前有效参数。

        :returns: 可序列化适配器配置。
        """
        temperature = float(self.log_temperature.detach().clamp(math.log(0.05), math.log(20.0)).exp())
        return CourseAdapterConfig(temperature=temperature, bias=float(self.bias.detach()))


__all__ = ["CourseAdapterConfig", "CourseLogitAdapter"]
