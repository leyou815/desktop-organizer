#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— Windows 安装脚本

做四件事：
  1. 检查 Python / PyQt5
  2. 把程序复制到 %LOCALAPPDATA%\\DesktopOrganizer
  3. 在开始菜单建快捷方式（指向 pythonw，避免弹黑框）
  4. 询问是否开机自启（写 HKCU\\...\\Run）

只写当前用户目录和 HKCU 注册表，不需要管理员权限。
"""

import os
import shutil
import subprocess
import sys

APP_NAME = "桌面整理"
FOLDER = "DesktopOrganizer"


def local_appdata():
    return os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local")


def start_menu():
    return os.path.join(os.environ.get("APPDATA") or
                        os.path.join(os.path.expanduser("~"), "AppData", "Roaming"),
                        "Microsoft", "Windows", "Start Menu", "Programs")


def pythonw():
    exe = sys.executable or "python"
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return cand if os.path.isfile(cand) else exe


def check_env():
    print("==> 检查环境")
    if sys.version_info < (3, 8):
        print("    Python 版本过低：%s（需要 3.8+）" % sys.version.split()[0])
        return False
    print("    Python %s  %s" % (sys.version.split()[0], sys.executable))
    try:
        import PyQt5.QtCore as c
        print("    PyQt5 %s" % c.PYQT_VERSION_STR)
    except Exception:
        print("    缺少 PyQt5，请先执行： pip install PyQt5")
        return False
    return True


def copy_files(src, dst):
    print("==> 安装到 %s" % dst)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(dst)
    for name in ("app", "assets"):
        s = os.path.join(src, name)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(dst, name))
    print("    完成")


def make_shortcut(dst):
    lnk = os.path.join(start_menu(), APP_NAME + ".lnk")
    entry = os.path.join(dst, "app", "cli.py")
    icon = os.path.join(dst, "assets", "icon.ico")
    ps = (
        "$ws = New-Object -ComObject WScript.Shell;"
        "$s = $ws.CreateShortcut('%s');"
        "$s.TargetPath = '%s';"
        "$s.Arguments = '\"%s\" run';"
        "$s.WorkingDirectory = '%s';"
        "%s"
        "$s.WindowStyle = 7;"
        "$s.Description = '%s';"
        "$s.Save()"
    ) % (lnk, pythonw(), entry, dst,
         ("$s.IconLocation = '%s';" % icon) if os.path.isfile(icon) else "",
         APP_NAME)
    print("==> 创建开始菜单快捷方式")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        print("    %s" % lnk)
        return True
    except Exception as e:
        print("    失败（可忽略，直接用 run_windows.bat）：%s" % e)
        return False


def set_autostart(dst, on):
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            cmd = '"%s" "%s" run' % (pythonw(), os.path.join(dst, "app", "cli.py"))
            winreg.SetValueEx(k, FOLDER, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, FOLDER)
            except FileNotFoundError:
                pass


def main():
    src = os.path.dirname(os.path.abspath(__file__))
    print("=" * 52)
    print("  %s  Windows 安装" % APP_NAME)
    print("=" * 52)

    if not sys.platform.startswith("win"):
        print("这个脚本只用于 Windows。麒麟/Linux 请用： bash install.sh")
        return 1
    if not check_env():
        return 1

    dst = os.path.join(local_appdata(), FOLDER)
    copy_files(src, dst)
    make_shortcut(dst)

    print("==> 开机自启")
    ans = input("    登录后自动常驻托盘？[Y/n] ").strip().lower()
    on = ans in ("", "y", "yes")
    try:
        set_autostart(dst, on)
        print("    已%s" % ("开启" if on else "关闭"))
    except Exception as e:
        print("    写入注册表失败：%s" % e)

    print()
    print("安装完成。")
    print("  开始菜单搜索「%s」即可打开" % APP_NAME)
    print("  或双击：%s" % os.path.join(dst, "app", "cli.py"))
    print("  卸载：python uninstall_windows.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
