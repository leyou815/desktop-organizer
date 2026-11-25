#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— 平台层

同一套逻辑在两个系统上跑，差异全部收在这里：
  桌面目录    麒麟 xdg-user-dir      Windows User Shell Folders（会跟着 OneDrive 重定向走）
  配置目录     ~/.config/...         %APPDATA%\\DesktopOrganizer
  自启         autostart/*.desktop   HKCU\\...\\Run 注册表项
  隐藏判定     . 开头                FILE_ATTRIBUTE_HIDDEN / SYSTEM 属性
  启动文件     xdg-open / Gio        os.startfile
  系统图标     此电脑/回收站/主目录   同左，但藏着的方式是 HideDesktopIcons 注册表

注意：Windows 分支的代码在麒麟上无法实测，所有调用都做了异常兜底，
失败时返回"不支持"而不是崩溃。详见 README 的验证情况。
"""

import os
import subprocess
import sys

IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")

APP_ID = "DesktopOrganizer"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
HIDE_ICONS_KEY = (r"Software\Microsoft\Windows\CurrentVersion\Explorer"
                  r"\HideDesktopIcons\NewStartPanel")

# Windows 桌面系统图标的 CLSID
CLSID_COMPUTER = "{20D04FE0-3AEA-1069-A2D8-08002B30309D}"
CLSID_TRASH = "{645FF040-5081-101B-9F08-00AA002F954E}"
CLSID_USER = "{59031A47-3F72-44A7-89C5-5595FE6B30EE}"

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4


# --------------------------------------------------------------------------- #
# 目录
# --------------------------------------------------------------------------- #
def desktop_dir():
    """系统认定的桌面目录。环境变量 ORGANIZER_DESKTOP 可覆盖（测试用）。"""
    override = os.environ.get("ORGANIZER_DESKTOP") or os.environ.get("DESK_SHELF_DESKTOP")
    if override:
        return override

    if IS_WINDOWS:
        p = _win_desktop_from_registry()
        if p and os.path.isdir(p):
            return p
        for cand in (os.path.join(os.path.expanduser("~"), "Desktop"),
                     os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop"),
                     os.path.join(os.path.expanduser("~"), "桌面")):
            if os.path.isdir(cand):
                return cand
        return os.path.join(os.path.expanduser("~"), "Desktop")

    # 麒麟 / 其他 Linux
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, universal_newlines=True,
                             timeout=5).stdout.strip()
        if out and os.path.isdir(out):
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    for name in ("桌面", "Desktop"):
        p = os.path.join(os.path.expanduser("~"), name)
        if os.path.isdir(p):
            return p
    return os.path.join(os.path.expanduser("~"), "桌面")


def _win_desktop_from_registry():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer"
                            r"\User Shell Folders") as k:
            val, _ = winreg.QueryValueEx(k, "Desktop")
        return os.path.expandvars(val)
    except Exception:
        return ""


def config_dir():
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData",
                                                         "Roaming")
        return os.path.join(base, "DesktopOrganizer")
    return os.path.join(os.path.expanduser("~"), ".config", "desktop-organizer")


def shelf_dirname():
    """归档目录名。Windows 上不用点开头（隐藏靠属性），但保持一致更好认。"""
    return ".桌面抽屉"


# --------------------------------------------------------------------------- #
# 隐藏判定
# --------------------------------------------------------------------------- #
def is_hidden(path):
    """点开头 / Windows 隐藏或系统属性。"""
    name = os.path.basename(path)
    if name.startswith("."):
        return True
    if IS_WINDOWS:
        return _win_attrs_hidden(path)
    return False


def _win_attrs_hidden(path):
    try:
        import ctypes
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == -1:
            return False
        return bool(attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM))
    except Exception:
        return False


def set_hidden(path, hidden=True):
    """把归档根目录设成隐藏，免得在资源管理器里碍眼。"""
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        cur = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if cur == -1:
            return False
        new = (cur | FILE_ATTRIBUTE_HIDDEN) if hidden else (cur & ~FILE_ATTRIBUTE_HIDDEN)
        return bool(ctypes.windll.kernel32.SetFileAttributesW(str(path), new))
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# 自启
# --------------------------------------------------------------------------- #
def autostart_path():
    if IS_WINDOWS:
        return "HKCU\\%s\\%s" % (RUN_KEY, APP_ID)
    return os.path.join(os.path.expanduser("~"), ".config", "autostart",
                        "desktop-organizer.desktop")


def autostart_on():
    if IS_WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, APP_ID)
            return True
        except Exception:
            return False
    return os.path.isfile(autostart_path())


def set_autostart(on, exec_cmd):
    """exec_cmd：要写进自启的完整命令。"""
    if IS_WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
                if on:
                    winreg.SetValueEx(k, APP_ID, 0, winreg.REG_SZ, exec_cmd)
                else:
                    try:
                        winreg.DeleteValue(k, APP_ID)
                    except FileNotFoundError:
                        pass
            return True
        except Exception:
            return False

    path = autostart_path()
    try:
        if on:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("[Desktop Entry]\n"
                        "Type=Application\n"
                        "Name=桌面整理\n"
                        "Comment=启动后驻留托盘：任务栏透明度 + 桌面一键整理\n"
                        "Exec=%s\n"
                        "X-UKUI-Autostart-enabled=true\n"
                        "X-GNOME-Autostart-enabled=true\n"
                        "Hidden=false\n"
                        "NoDisplay=true\n"
                        "StartupNotify=false\n" % exec_cmd)
        elif os.path.isfile(path):
            os.remove(path)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# 打开 / 启动
# --------------------------------------------------------------------------- #
def open_path(path):
    """用系统默认程序打开文件或文件夹。"""
    if IS_WINDOWS:
        try:
            os.startfile(path)          # noqa: S606  仅 Windows 存在
            return True
        except Exception:
            return False
    try:
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
    except Exception:
        try:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return True
        except OSError:
            return False


# --------------------------------------------------------------------------- #
# 桌面系统图标（此电脑 / 回收站 / 主目录）
# --------------------------------------------------------------------------- #
if IS_WINDOWS:
    VIRTUAL = [
        ("此电脑", "shell:MyComputerFolder", None),
        ("回收站", "shell:RecycleBinFolder", None),
        ("用户文件夹", "shell:Profile", None),
    ]
    _VIRTUAL_KEYS = [CLSID_COMPUTER, CLSID_TRASH, CLSID_USER]
else:
    VIRTUAL = [
        ("计算机", "computer:///", "computer"),
        ("回收站", "trash:///", "user-trash"),
        ("主目录", os.path.expanduser("~"), "user-home"),
    ]
    _VIRTUAL_KEYS = ["computer-icon-visible", "trash-icon-visible", "home-icon-visible"]


def open_virtual(target):
    """打开虚拟位置：shell:xxx / computer:/// / 绝对路径。"""
    if IS_WINDOWS:
        try:
            os.startfile(target)
            return True
        except Exception:
            try:
                subprocess.Popen(["explorer.exe", target], close_fds=True)
                return True
            except OSError:
                return False
    if target.startswith("computer://") or target.startswith("trash://"):
        for cmd in (["peony", target], ["gio", "open", target]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                return True
            except OSError:
                continue
        return False
    return open_path(target)


def virtual_hidden():
    """三个系统图标是不是都藏起来了。"""
    if IS_WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, HIDE_ICONS_KEY) as k:
                vals = []
                for clsid in _VIRTUAL_KEYS:
                    try:
                        v, _ = winreg.QueryValueEx(k, clsid)
                        vals.append(int(v) == 1)
                    except FileNotFoundError:
                        vals.append(False)
            return bool(vals) and all(vals)
        except Exception:
            return False
    return _kylin_virtual_hidden()


def set_virtual_hidden(hide):
    if IS_WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, HIDE_ICONS_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
                for clsid in _VIRTUAL_KEYS:
                    winreg.SetValueEx(k, clsid, 0, winreg.REG_DWORD, 1 if hide else 0)
            _refresh_desktop()
            return True
        except Exception:
            return False
    return _kylin_set_virtual_hidden(hide)


def _refresh_desktop():
    """让资源管理器立刻刷新桌面。"""
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    except Exception:
        pass


# -- 麒麟：peony 的三个 gsettings -------------------------------------------- #
PEONY_SCHEMA = "org.ukui.peony.settings"


def _kylin_get(key):
    try:
        out = subprocess.run(["/usr/bin/gsettings", "get", PEONY_SCHEMA, key],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             universal_newlines=True, timeout=5).stdout.strip()
        return out == "true"
    except (OSError, subprocess.SubprocessError):
        return None


def _kylin_virtual_hidden():
    states = [_kylin_get(k) for k in _VIRTUAL_KEYS]
    return all(v is False for v in states)


def _kylin_set_virtual_hidden(hide):
    ok = True
    for k in _VIRTUAL_KEYS:
        try:
            p = subprocess.run(["/usr/bin/gsettings", "set", PEONY_SCHEMA, k,
                                "true" if not hide else "false"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True, timeout=5)
            ok = (p.returncode == 0 and "failed to commit" not in (p.stderr or "")) and ok
        except (OSError, subprocess.SubprocessError):
            ok = False
    return ok


# --------------------------------------------------------------------------- #
# 杂项
# --------------------------------------------------------------------------- #
def pythonw():
    """Windows 上自启不该弹黑框，优先用 pythonw.exe。"""
    exe = sys.executable or "python"
    if IS_WINDOWS:
        cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(cand):
            return cand
    return exe


def startup_command(entry_py):
    """拼自启命令：Windows 用 pythonw 直跑入口；Linux 用 bin 启动器。"""
    if IS_WINDOWS:
        if getattr(sys, "frozen", False):      # PyInstaller 打的 exe
            return '"%s" run' % sys.executable
        return '"%s" "%s" run' % (pythonw(), entry_py)
    root = os.path.dirname(os.path.dirname(os.path.abspath(entry_py)))
    return os.path.join(root, "bin", "zhengli") + " run"
