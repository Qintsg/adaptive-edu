#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
管理员激活码状态筛选接口回归测试。
@Project : adaptive-edu
@File : test_activation_code_filters.py
@Author : Qintsg
@Date : 2026-09-24 21:00
'''

from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from users.models import ActivationCode, User


class ActivationCodeFilterTests(APITestCase):
    """验证未使用与已过期筛选互不混淆。"""

    def setUp(self) -> None:
        """
        创建三种状态的激活码。

        :returns: 无。
        """
        self.admin = User.objects.create_user(
            username="activation_filter_admin",
            password="Test123456",
            role="admin",
        )
        now = timezone.now()
        self.active = ActivationCode.objects.create(
            code="QA_ACTIVE_CODE",
            code_type="teacher",
            created_by=self.admin,
            expires_at=now + timedelta(days=2),
        )
        self.expired = ActivationCode.objects.create(
            code="QA_EXPIRED_CODE",
            code_type="teacher",
            created_by=self.admin,
            expires_at=now - timedelta(days=1),
        )
        self.used = ActivationCode.objects.create(
            code="QA_USED_CODE",
            code_type="teacher",
            created_by=self.admin,
            is_used=True,
            used_at=now,
        )
        self.client.force_authenticate(user=self.admin)

    def test_expired_filter_returns_only_expired_unused_codes(self) -> None:
        """
        已过期筛选只返回未使用且过期的激活码。

        :returns: 无。
        """
        response = self.client.get("/api/admin/activation-codes", {"expired": "true"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["total"], 1)
        self.assertEqual(response.data["data"]["codes"][0]["id"], self.expired.id)

    def test_unused_filter_excludes_expired_codes(self) -> None:
        """
        未使用筛选排除已过期的激活码。

        :returns: 无。
        """
        response = self.client.get(
            "/api/admin/activation-codes",
            {"is_used": "false", "expired": "false"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["total"], 1)
        self.assertEqual(response.data["data"]["codes"][0]["id"], self.active.id)
