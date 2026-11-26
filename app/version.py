#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版本号单一来源。

以前 app.py / cli.py / ui_main.py 各写一份 "1.0"，改版本要三处同步，
漏一处就会出现「窗口显示 v1.0、诊断输出 1.0.1」这种自相矛盾。
"""

VERSION = "1.0.1"
