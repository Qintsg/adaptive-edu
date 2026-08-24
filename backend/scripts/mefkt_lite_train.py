#!/user/bin/env python
# -*- coding: UTF-8 -*-
'''
MEFKT-Lite 训练兼容入口。
@Project : adaptive-edu
@File : mefkt_lite_train.py
@Author : Qintsg
@Date : 2026-08-24
'''

from __future__ import annotations

import sys

from mefkt_train import main


if __name__ == "__main__":
    if "--profile" not in sys.argv:
        sys.argv.extend(["--profile", "lite"])
    raise SystemExit(main())
