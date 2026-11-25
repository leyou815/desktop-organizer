#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— Windows 自检工具

开发机是麒麟，Windows 分支没法在本地实测。这个脚本用来在真机上逐项验证：
任务栏能不能贴亚克力、注册表读写通不通、托盘能不能起、图标能不能取。

用法（在仓库根目录）：
    python tools\\selftest_win.py

结果会写到 selftest.txt，可以直接贴到 issue 里。
注意：第 7 项会短暂改变任务栏外观，跑完会自动恢复。
"""

import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "app"))

IS_WIN = sys.platform.startswith("win")
RESULT = []


def record(name, ok, detail=""):
    RESULT.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print("[%s] %-26s %s" % (mark, name, detail))


def check(title, fn):
    try:
        ok, detail = fn()
        record(title, ok, detail)
    except Exception:
        record(title, False, traceback.format_exc(limit=1).strip().splitlines()[-1])


# --------------------------------------------------------------------------- #
def t_python():
    from PyQt5.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
    v = sys.version.split()[0]
    return True, "Python %s / PyQt %s / Qt %s" % (v, PYQT_VERSION_STR, QT_VERSION_STR)


def t_desktop():
    import sysenv
    p = sysenv.desktop_dir()
    return os.path.isdir(p), p


def t_config():
    import config
    os.makedirs(config.CONFIG_DIR, exist_ok=True)
    probe = os.path.join(config.CONFIG_DIR, ".write_test")
    with open(probe, "w") as f:
        f.write("ok")
    os.remove(probe)
    return True, config.CONFIG_DIR


def t_registry():
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    name = "DesktopOrganizerSelftest"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, "selftest")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
        val, _ = winreg.QueryValueEx(k, name)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
        winreg.DeleteValue(k, name)
    return val == "selftest", "HKCU\\%s 读写正常" % key


def t_taskbar():
    import panel_win
    hwnds = panel_win._taskbars()
    return bool(hwnds), "找到 %d 个任务栏窗口" % len(hwnds)


def t_api():
    import ctypes
    user32 = ctypes.windll.user32
    ok = hasattr(user32, "SetWindowCompositionAttribute")
    return ok, "SetWindowCompositionAttribute %s" % ("存在" if ok else "不存在（系统太旧？）")


def t_acrylic():
    """真的贴两次不同透明度，看返回值，最后恢复。"""
    import config
    import panel_win
    cfg = config.load()
    panel = panel_win.PanelWin(cfg)

    panel.set_alpha(0.60)
    ok1, err1 = panel.apply_glass()
    time.sleep(0.4)
    panel.set_alpha(0.88)
    ok2, err2 = panel.apply_glass()
    time.sleep(0.4)
    panel.restore()

    ok = bool(ok1 and ok2)
    return ok, "60%%=%s 88%%=%s %s" % (ok1, ok2, (err1 or err2 or ""))


def t_desktop_inventory():
    import sysenv
    import rules
    d = sysenv.desktop_dir()
    files = dirs = lnk = skip = 0
    for name in os.listdir(d):
        p = os.path.join(d, name)
        if os.path.isdir(p) and not os.path.islink(p):
            dirs += 1
            continue
        if rules.should_skip(p)[0]:
            skip += 1
            continue
        files += 1
        if name.lower().endswith((".lnk", ".url")):
            lnk += 1
    return True, "文件 %d（含快捷方式 %d）/ 文件夹 %d / 跳过 %d" % (files, lnk, dirs, skip)


def t_icon():
    """给一个 .lnk 取图标，验证 QFileIconProvider 在中文路径下也正常。"""
    import sysenv
    from PyQt5.QtWidgets import QApplication, QFileIconProvider
    from PyQt5.QtCore import QFileInfo
    app = QApplication.instance() or QApplication([])
    d = sysenv.desktop_dir()
    target = None
    for name in os.listdir(d):
        if name.lower().endswith(".lnk"):
            target = os.path.join(d, name)
            break
    if not target:
        return True, "桌面上没有 .lnk，跳过（可造一个快捷方式再测）"
    icon = QFileIconProvider().icon(QFileInfo(target))
    return (not icon.isNull()), os.path.basename(target)


def t_tray():
    from PyQt5.QtWidgets import QApplication, QSystemTrayIcon
    app = QApplication.instance() or QApplication([])
    return QSystemTrayIcon.isSystemTrayAvailable(), "系统托盘可用" if \
        QSystemTrayIcon.isSystemTrayAvailable() else "托盘不可用"


def t_hotkey():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    hk_id = 0xB0FF
    # Ctrl + Alt + G
    ok = bool(user32.RegisterHotKey(None, hk_id, 0x0002 | 0x0001 | 0x4000, ord("G")))
    user32.UnregisterHotKey(None, hk_id)
    return ok, "Ctrl+Alt+G %s" % ("注册成功" if ok else "被占用或注册失败")


def t_virtual_icons():
    import winreg
    import sysenv
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sysenv.HIDE_ICONS_KEY) as k:
            vals = []
            for clsid in (sysenv.CLSID_COMPUTER, sysenv.CLSID_TRASH, sysenv.CLSID_USER):
                try:
                    v, _ = winreg.QueryValueEx(k, clsid)
                    vals.append(int(v))
                except FileNotFoundError:
                    vals.append(0)
        return True, "键值 %s（当前：%s）" % (vals, "已隐藏" if sysenv.virtual_hidden() else "显示中")
    except FileNotFoundError:
        return True, "尚未创建 HideDesktopIcons 键（首次开关时会创建）"


# --------------------------------------------------------------------------- #
def main():
    print("=" * 62)
    print("  桌面整理 · Windows 自检")
    print("=" * 62)
    if not IS_WIN:
        print("当前不是 Windows（%s）。这个脚本要在 Windows 上跑。" % sys.platform)
        return 1

    check("Python / PyQt5", t_python)
    check("桌面目录", t_desktop)
    check("配置目录可写", t_config)
    check("注册表读写", t_registry)
    check("任务栏窗口", t_taskbar)
    check("亚克力 API", t_api)
    check("贴亚克力（会闪一下）", t_acrylic)
    check("桌面文件盘点", t_desktop_inventory)
    check("快捷方式图标", t_icon)
    check("系统托盘", t_tray)
    check("全局快捷键", t_hotkey)
    check("系统图标开关", t_virtual_icons)

    passed = sum(1 for _, ok, _ in RESULT if ok)
    total = len(RESULT)
    print("-" * 62)
    print("  %d / %d 项通过" % (passed, total))
    if passed < total:
        print("  未通过的项请连同下面的文件一起反馈")
    print("-" * 62)

    out = os.path.join(ROOT, "selftest.txt")
    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write("桌面整理 Windows 自检\n")
            f.write("时间：%s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
            f.write("系统：%s\n\n" % sys.platform)
            for name, ok, detail in RESULT:
                f.write("[%s] %s  %s\n" % ("PASS" if ok else "FAIL", name, detail))
        print("  报告已写入 %s" % out)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
