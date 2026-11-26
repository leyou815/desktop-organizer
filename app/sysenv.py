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
# 系统设置原值台账
# --------------------------------------------------------------------------- #
# 实现在 atomicio（它反过来要 import 本模块，所以这里只能在函数内延迟导入）
def remember_system(kind, values):
    import atomicio
    return atomicio.remember_system(kind, values)


def recall_system(kind):
    import atomicio
    return atomicio.recall_system(kind)


def forget_system(kind):
    import atomicio
    return atomicio.forget_system(kind)


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


def public_desktop_dir():
    """Windows 公共桌面（C:\\Users\\Public\\Desktop）；其它平台返回空串。"""
    if not IS_WINDOWS:
        return ""
    base = os.environ.get("PUBLIC")
    if not base:
        # 未设 PUBLIC 时按 <用户目录的父目录>\\Public 推：C:\\Users\\Admin → C:\\Users\\Public
        base = os.path.join(os.path.dirname(os.path.expanduser("~")), "Public")
    return os.path.join(base, "Desktop")


def desktop_dirs(include_public=False, primary=None):
    """所有要在桌面上整理的位置。

    primary 给了就用它当"用户桌面"（测试/自定义桌面走这条），
    没给就交给 desktop_dir() 现算。

    Windows 把「当前用户桌面」和「公共桌面」合并显示成一个桌面：
    各软件装在公共桌面（C:\\Users\\Public\\Desktop）的快捷方式，用户看得见，
    只扫用户桌面就会漏掉。但公共桌面是**系统级目录**：
      * 搬走会影响本机其它账号（他们桌面上的图标一起消失）
      * 写回权限不一定还在（ACL 允许"删自己可见的条目"未必允许"再写回去"）
      * 软件升级/重装往往会把快捷方式重新生成
    所以默认不纳入，只有用户在设置里显式打开 include_public 才扫。
    麒麟/Linux 只有一个桌面目录，永远返回单元素列表。
    """
    base = primary or desktop_dir()
    out = [base]
    if include_public:
        pub = public_desktop_dir()
        if (pub and os.path.isdir(pub) and
                os.path.normcase(os.path.abspath(pub)) !=
                os.path.normcase(os.path.abspath(base))):
            out.append(pub)
    return out


def dir_writable(path):
    """真的往目录里写一个临时文件试试（os.access 在 Windows 上不可靠）。

    用来在搬文件**之前**确认撤得回来：搬出去只需要读 + 删源目录条目，
    搬回来则需要写权限。公共桌面这类 ACL 特殊的目录正好会卡在后半段，
    所以宁可先探一次，也不要让用户拿到一个"搬得进去、搬不回来"的整理结果。
    """
    if not os.path.isdir(path):
        return False
    probe = None
    try:
        import tempfile
        fd, probe = tempfile.mkstemp(prefix=".do-probe-", dir=path)
        os.close(fd)
        return True
    except OSError:
        return False
    finally:
        if probe:
            try:
                os.remove(probe)
            except OSError:
                pass


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
            text = ("[Desktop Entry]\n"
                    "Type=Application\n"
                    "Name=桌面整理\n"
                    "Comment=启动后驻留托盘：任务栏透明度 + 桌面一键整理\n"
                    "Exec=%s\n"
                    "X-UKUI-Autostart-enabled=true\n"
                    "X-GNOME-Autostart-enabled=true\n"
                    "Hidden=false\n"
                    "NoDisplay=true\n"
                    "StartupNotify=false\n" % exec_cmd)
            # 原子写：先写同目录 .tmp 再 os.replace。
            # 直接 open(path, "w") 会先截断再写，若此时正好登录/崩溃，
            # 桌面会话读到的是一个 0 字节或半截的 .desktop，自启就静默失效了。
            return atomicio.atomic_write_text(path, text)
        if os.path.isfile(path):
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
                                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as k:
                if hide:
                    # 藏之前先把每个图标的原值记下来：用户可能本来就只显示
                    # 其中一两个（比如自己把"网络"关掉过），直接写 1 再写
                    # 回 0 会把他的个人偏好一并抹掉。
                    saved = {}
                    for clsid in _VIRTUAL_KEYS:
                        try:
                            v, _ = winreg.QueryValueEx(k, clsid)
                            saved[clsid] = int(v)
                        except FileNotFoundError:
                            saved[clsid] = None      # 原来没有这个值，还原时删掉
                    remember_system("virtual_icons_win", saved)
                    plan = dict((clsid, 1) for clsid in _VIRTUAL_KEYS)
                else:
                    saved = recall_system("virtual_icons_win")
                    plan = {}
                    for clsid in _VIRTUAL_KEYS:
                        if clsid in saved:
                            # None 表示原来就没这个值 → 还原成"没有"
                            plan[clsid] = saved[clsid]
                        else:
                            plan[clsid] = 0        # 没有台账（旧版本改过）只能退回系统默认
                for clsid, val in plan.items():
                    if val is None:
                        try:
                            winreg.DeleteValue(k, clsid)
                        except FileNotFoundError:
                            pass
                    else:
                        winreg.SetValueEx(k, clsid, 0, winreg.REG_DWORD, int(val))
            if not hide:
                forget_system("virtual_icons_win")
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


def _kylin_raw(key):
    """原始 gsettings 值（'true' / 'false' / 自定义），读不到返回 None。"""
    try:
        out = subprocess.run(["/usr/bin/gsettings", "get", PEONY_SCHEMA, key],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             universal_newlines=True, timeout=5).stdout.strip()
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None


def _kylin_set_virtual_hidden(hide):
    if hide:
        saved = {}
        for k in _VIRTUAL_KEYS:
            raw = _kylin_raw(k)
            if raw is not None:
                saved[k] = raw
        remember_system("virtual_icons_kylin", saved)
        plan = dict((k, "false") for k in _VIRTUAL_KEYS)
    else:
        saved = recall_system("virtual_icons_kylin")
        plan = dict((k, saved.get(k) or "true") for k in _VIRTUAL_KEYS)

    ok = True
    for k, val in plan.items():
        try:
            p = subprocess.run(["/usr/bin/gsettings", "set", PEONY_SCHEMA, k, val],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True, timeout=5)
            ok = (p.returncode == 0 and "failed to commit" not in (p.stderr or "")) and ok
        except (OSError, subprocess.SubprocessError):
            ok = False
    if ok and not hide:
        forget_system("virtual_icons_kylin")
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
