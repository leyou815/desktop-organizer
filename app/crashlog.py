#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""崩溃兜底。

PyQt5 有个容易踩的坑：在 paintEvent / 槽函数里抛未捕获异常，不会只打印
traceback，而是直接 abort 整个进程——窗口瞬间消失，命令行里什么都没有。
这次"点抽屉闪退"就是这种：clipPath() 传参被当成 too many arguments。

装好之后，任何未捕获异常和 C 层栈都会落到 crash.log，至少留下线索。
"""

import faulthandler
import os
import sys
import time
import traceback

MAX_BYTES = 512 * 1024


def _rotate(path):
    """超过上限就换一份，只留一代，避免日志无限长。"""
    try:
        if os.path.getsize(path) > MAX_BYTES:
            backup = path + ".1"
            if os.path.exists(backup):
                os.remove(backup)
            os.replace(path, backup)
    except Exception:
        pass


def install(path):
    """装上进程级兜底，返回日志路径。

    任何一步失败都静默跳过：崩溃日志本身不该成为新的崩溃源。
    """
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        _rotate(path)
        fh = open(path, "a", encoding="utf-8", buffering=1)
    except Exception:
        return None

    try:
        fh.write("\n=== 启动 %s  pid %d ===\n"
                 % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid()))
    except Exception:
        pass

    # faulthandler 抓的是 C 层 abort（PyQt5 遇到绘制异常就走这条路），
    # sys.excepthook 抓的是普通未捕获异常，两者互补。
    try:
        faulthandler.enable(file=fh, all_threads=True)
    except Exception:
        pass

    def _hook(etype, value, tb):
        try:
            fh.write("\n=== %s 未捕获异常 ===\n" % time.strftime("%H:%M:%S"))
            traceback.print_exception(etype, value, tb, file=fh)
            fh.flush()
        except Exception:
            pass
        sys.__excepthook__(etype, value, tb)   # 控制台运行时照样能看到

    sys.excepthook = _hook
    return path
