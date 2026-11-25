#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桌面整理 —— Windows 卸载脚本

只删程序、开始菜单快捷方式和自启项。
已经归好类的文件一个都不动。
"""

import os
import shutil
import sys

APP_NAME = "桌面整理"
FOLDER = "DesktopOrganizer"


def main():
    if not sys.platform.startswith("win"):
        print("这个脚本只用于 Windows。麒麟/Linux 请用： bash uninstall.sh")
        return 1

    dst = os.path.join(os.environ.get("LOCALAPPDATA") or
                       os.path.join(os.path.expanduser("~"), "AppData", "Local"), FOLDER)
    lnk = os.path.join(os.environ.get("APPDATA") or
                       os.path.join(os.path.expanduser("~"), "AppData", "Roaming"),
                       "Microsoft", "Windows", "Start Menu", "Programs",
                       APP_NAME + ".lnk")

    print("==> 停止正在运行的实例")
    os.system('taskkill /IM pythonw.exe /F >nul 2>nul')

    print("==> 删除程序文件")
    if os.path.isdir(dst):
        shutil.rmtree(dst)
        print("    %s" % dst)
    for p in (lnk,):
        if os.path.isfile(p):
            os.remove(p)
            print("    %s" % p)

    print("==> 移除自启")
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, FOLDER)
        print("    已移除")
    except FileNotFoundError:
        print("    没有自启项")
    except Exception as e:
        print("    失败：%s" % e)

    shelf = os.path.join(os.path.expanduser("~"), "Desktop", ".桌面抽屉")
    print()
    print("卸载完成。")
    if os.path.isdir(shelf):
        print("已归档的文件没有动，还在：")
        print("  %s" % shelf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
