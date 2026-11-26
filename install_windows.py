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

import base64
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
    """先整份拷到临时目录，成功后再替换旧安装。

    老版本是 rmtree(dst) 之后才 copytree：一旦拷贝中途失败（杀软占用、磁盘满），
    用户就会连旧的可用版本都没了。这里改成 staged copy + 目录替换，
    任何一步失败都不动原安装。
    """
    print("==> 安装到 %s" % dst)
    names = [n for n in ("app", "assets", "tap") if os.path.isdir(os.path.join(src, n))]
    if "app" not in names:
        raise RuntimeError("源码目录里找不到 app/，可能是在错误的目录下运行")

    tmp = dst + ".new"
    old = dst + ".old"
    for p in (tmp, old):
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
    os.makedirs(tmp)

    try:
        for name in names:
            shutil.copytree(os.path.join(src, name), os.path.join(tmp, name))
        # 关键文件校验：拷完发现还是空的就别替换（例如权限不足只建了空目录）
        for must in ("app/cli.py", "app/app.py"):
            if not os.path.isfile(os.path.join(tmp, *must.split("/"))):
                raise RuntimeError("拷贝不完整，缺少 %s" % must)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        print("    失败：已回滚，未改动现有安装")
        raise

    had_old = os.path.isdir(dst)
    if had_old:
        os.replace(dst, old)      # 同一分区上的目录改名是原子的
    os.replace(tmp, dst)
    if had_old:
        shutil.rmtree(old, ignore_errors=True)
    print("    完成")


def _ps_quote(s):
    """PowerShell 单引号字面量转义：内部单引号写两遍。

    用户名里带 ' 时（如 C:\\Users\\O'Brien），原实现直接把路径拼进 '...' 里，
    PowerShell 会解析报错 → 快捷方式静默创建失败。
    """
    return "'" + str(s).replace("'", "''") + "'"


def make_shortcut(dst):
    lnk = os.path.join(start_menu(), APP_NAME + ".lnk")
    entry = os.path.join(dst, "app", "cli.py")
    icon = os.path.join(dst, "assets", "icon.ico")
    ps = (
        "$ws = New-Object -ComObject WScript.Shell;"
        "$s = $ws.CreateShortcut(%s);"
        "$s.TargetPath = %s;"
        "$s.Arguments = %s;"
        "$s.WorkingDirectory = %s;"
        "%s"
        "$s.WindowStyle = 7;"
        "$s.Description = %s;"
        "$s.Save()"
    ) % (_ps_quote(lnk), _ps_quote(pythonw()),
         _ps_quote('"%s" run' % entry), _ps_quote(dst),
         ("$s.IconLocation = %s;" % _ps_quote(icon)) if os.path.isfile(icon) else "",
         _ps_quote(APP_NAME))
    print("==> 创建开始菜单快捷方式")
    try:
        # 走 -EncodedCommand：脚本里再有特殊字符也不会被外层 shell 吃掉
        enc = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-EncodedCommand", enc],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if not os.path.isfile(lnk):
            raise RuntimeError("快捷方式未生成")
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
    try:
        copy_files(src, dst)
    except Exception as e:
        print("        安装中止：%s" % e)
        return 1
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
