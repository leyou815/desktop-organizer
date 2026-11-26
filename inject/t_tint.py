"""真机测档：把「半透明」的几档逐一贴上去，读像素看背景浓度。

只在开发机跑：需要注入组件、需要真任务栏。测完自动 restore。
用法：python inject/t_tint.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "app"))
sys.path.insert(0, HERE)

import measure  # noqa: E402
import taskbar_tap as tap  # noqa: E402


def shot(tag):
    import ctypes
    user32 = ctypes.WinDLL("user32")
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    px = measure.grab(sw // 2 - 400, sh - 40, 800, 30)
    mean, sd = measure.stats(px)
    # 纵向首三行像素：判断背景有没有"台阶"（真透明时任务栏和壁纸连续）
    top = [px[0], px[1], px[2]]
    print("%-14s 亮度 %6.2f  标准差 %6.2f  首行 %s" % (tag, mean, sd, " ".join(map(str, top))))
    return mean


def main():
    import ctypes
    ctypes.WinDLL("user32").SetProcessDPIAware()
    print("explorer pid =", tap.explorer_pid(), " dll =", tap.dll_source())
    shot("基线（默认）")
    for v in (0.10, 0.20, 0.40, 0.72):
        ok, err = tap.apply_tint(v)
        time.sleep(1.2)
        print("apply_tint(%.2f) -> %s %s" % (v, ok, err))
        shot("半透明 %d%%" % int(v * 100))
    ok, err = tap.apply_clear()
    time.sleep(1.0)
    print("apply_clear ->", ok, err)
    shot("完全透明")
    tap.restore()
    time.sleep(0.8)
    shot("还原")


if __name__ == "__main__":
    main()
