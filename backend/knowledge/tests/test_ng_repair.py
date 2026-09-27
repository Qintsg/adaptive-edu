#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
验证初始掌握度修复命令识别新的 MEFKT-NG 结果类型。
@Project : adaptive-edu
@File : test_ng_repair.py
@Author : Qintsg
@Date : 2026-09-25
'''

from __future__ import annotations

from django.test import SimpleTestCase

from knowledge.management.commands.repair_initial_mastery import Command


class NGRepairTests(SimpleTestCase):
    """检查管理命令复用统一的真实模型类型集合。"""

    def test_ng_prediction_may_fill_measured_course_point(self) -> None:
        """NG 结果应与旧 MEFKT 一样参与初测掌握度合并。

        :returns: None。
        """
        result = Command()._merge_mastery(
            direct_mastery={101: 0.30}, prediction_map={101: 0.70, 102: 0.65},
            prediction_source="mefkt_ng",
        )
        self.assertIn(102, result)
        self.assertGreater(result[101], 0.30)
