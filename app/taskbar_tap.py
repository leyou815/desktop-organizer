#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— 任务栏「真·全透明」（注入 explorer）

为什么必须注入
--------------
Win11 的任务栏背景不是窗口颜色，而是 explorer 进程里一块 XAML `Rectangle`
（元素名 `BackgroundFill`），和图标画在同一棵视觉树里。进程外改它：

  * SetWindowCompositionAttribute（AccentState 0~5）→ 实测拉不动，或只拉动 4 级灰度
  * DWM backdrop / TaskbarAcrylicOpacity 注册表 → 无效
  * 隐藏 DesktopWindowContentBridge 子窗口 → 背景没了，图标也没了（同一棵树）
  * 色键透明 LWA_COLORKEY → DComp 内容不走重定向表面，无效

TranslucentTB 也是注入，走的是 XAML Diagnostics。本模块配 `do_inject.dll` 复刻这条
路（自己实现，不抄代码）：

  1. SetWindowsHookEx(WH_CALLWNDPROC) 把 DLL 送进 explorer
  2. DLL 里调 Windows.UI.Xaml.dll!InitializeXamlDiagnosticsEx，XAML 回调我们的
     DllGetClassObject 拿到一个 IObjectWithSite
  3. 从 IXamlDiagnostics 拿 IVisualTreeService，开始收视觉树通知
  4. 挑出名字是 BackgroundFill / BackgroundStroke 的 Rectangle，把 Fill 画刷换成空
  5. 原画刷带引用存着，收到 restore 就原样放回去

进程间只用两个文件通信（都在 %APPDATA%\\DesktopOrganizer）：
  inject.cmd  宿主写 probe / clear / restore，DLL 每 700ms 读一次
  inject.log  DLL 写，一行一件事；宿主靠它确认"到底成没成"

⚠️ InitializeXamlDiagnosticsEx 会把 DLL 永久钉在 explorer 里：文件被占用，删不掉也
覆盖不了。所以每次都部署一份带时间戳的副本再注入，绝不动源文件。
"""

import ctypes
import os
import shutil
import sys
import time
from ctypes import wintypes

IS_WINDOWS = sys.platform.startswith("win")

STATE_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                         "DesktopOrganizer")
CMD = os.path.join(STATE_DIR, "inject.cmd")
LOG = os.path.join(STATE_DIR, "inject.log")
TAP_DIR = os.path.join(STATE_DIR, "tap")
READY_EVENT = "Local\\DesktopOrganizerTapReady"

WH_CALLWNDPROC = 4
WM_NULL = 0

MODE_PROBE = "probe"
MODE_CLEAR = "clear"
MODE_RESTORE = "restore"


class TapError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# DLL 从哪来
# --------------------------------------------------------------------------- #
def _candidates():
    """按优先级列出 do_inject.dll 的可能位置，兼容「源码目录」「安装目录」「打包 exe」。"""
    here = os.path.dirname(os.path.abspath(__file__))        # …/app
    root = os.path.dirname(here)                             # …/DesktopOrganizer
    out = []
    env = os.environ.get("DESKTOP_ORGANIZER_TAP_DLL")
    if env:
        out.append(env)
    if getattr(sys, "frozen", False):
        # PyInstaller：DLL 跟着 exe 走，放 exe 同级的 tap\ 下
        out.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                                "tap", "do_inject.dll"))
    out.append(os.path.join(root, "tap", "do_inject.dll"))
    out.append(os.path.join(root, "inject", "target", "release", "do_inject.dll"))
    out.append(os.path.join(os.path.dirname(root), "inject", "target", "release",
                            "do_inject.dll"))
    return out


def dll_source():
    """找到可用的 do_inject.dll；找不到返回 None（界面上显示为"本机没有注入组件"）。"""
    for p in _candidates():
        if os.path.isfile(p):
            return p
    return None


# --------------------------------------------------------------------------- #
# Win32
# --------------------------------------------------------------------------- #
if IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _user32.FindWindowW.restype = wintypes.HWND
    _user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                 ctypes.POINTER(wintypes.DWORD)]
    _user32.SetWindowsHookExW.restype = wintypes.HHOOK
    _user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p,
                                          wintypes.HINSTANCE, wintypes.DWORD]
    _user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    _user32.SendNotifyMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM]
    _kernel32.LoadLibraryW.restype = wintypes.HMODULE
    _kernel32.LoadLibraryW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetProcAddress.restype = ctypes.c_void_p
    _kernel32.GetProcAddress.argtypes = [wintypes.HMODULE, ctypes.c_char_p]
    _kernel32.CreateEventW.restype = wintypes.HANDLE
    _kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                       wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.ResetEvent.argtypes = [wintypes.HANDLE]


def taskbar_info():
    """(hwnd, tid, pid)。找不到任务栏就返回 (0, 0, 0)。"""
    if not IS_WINDOWS:
        return 0, 0, 0
    hwnd = _user32.FindWindowW("Shell_TrayWnd", None)
    if not hwnd:
        return 0, 0, 0
    pid = wintypes.DWORD()
    tid = _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(hwnd), int(tid), int(pid.value)


def explorer_pid():
    return taskbar_info()[2]


# --------------------------------------------------------------------------- #
# 日志 / 命令
# --------------------------------------------------------------------------- #
def write_cmd(mode):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(CMD, "w", encoding="utf-8") as f:
        f.write(mode)


def read_log():
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def log_tail(n=40):
    lines = read_log().splitlines()
    return "\n".join(lines[-n:])


def tap_pid():
    """日志里最后一次「注入成功」的 explorer pid；没有就是 0。

    用日志而不是内存标记：程序重启后也要能判断"上一次注入的那个 explorer 还在不在"。
    """
    pid = 0
    for line in read_log().splitlines():
        marker = "== 注入成功 pid="
        i = line.find(marker)
        if i >= 0:
            digits = ""
            for ch in line[i + len(marker):]:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            if digits:
                pid = int(digits)
    return pid


def is_active():
    """注入的 DLL 是否还活着（explorer 一重启它就没了）。"""
    p = tap_pid()
    return bool(p) and p == explorer_pid()


# --------------------------------------------------------------------------- #
# 注入
# --------------------------------------------------------------------------- #
def _deploy():
    src = dll_source()
    if not src:
        raise TapError("没有找到 do_inject.dll（安装包里缺少注入组件）")
    os.makedirs(TAP_DIR, exist_ok=True)
    dst = os.path.join(TAP_DIR, "do_inject_%s.dll" % time.strftime("%H%M%S"))
    shutil.copy2(src, dst)
    olds = sorted(f for f in os.listdir(TAP_DIR) if f.startswith("do_inject_"))
    for f in olds[:-5]:
        try:
            os.remove(os.path.join(TAP_DIR, f))
        except OSError:
            pass
    return dst


def inject(timeout=20.0):
    """把 DLL 送进 explorer 并等它报就绪。

    返回 (成功?, 说明)。不抛异常——调用方是界面线程，宁可显示一句人话也别炸。
    """
    if not IS_WINDOWS:
        return False, "只有 Windows 需要注入"
    hwnd, tid, _pid = taskbar_info()
    if not hwnd:
        return False, "找不到任务栏窗口（Shell_TrayWnd），稍后再试"

    try:
        dll = _deploy()
    except TapError as e:
        return False, str(e)
    except OSError as e:
        return False, "部署注入组件失败：%s" % e

    ev = _kernel32.CreateEventW(None, True, False, READY_EVENT)
    if ev:
        _kernel32.ResetEvent(ev)     # 命名事件可能还停在上次"已触发"的状态

    mod = _kernel32.LoadLibraryW(dll)
    if not mod:
        return False, "加载注入组件失败（错误码 %d）" % ctypes.get_last_error()
    proc = _kernel32.GetProcAddress(mod, b"HookProc")
    if not proc:
        return False, "注入组件里找不到 HookProc"

    hook = _user32.SetWindowsHookExW(WH_CALLWNDPROC, proc, mod, tid)
    if not hook:
        return False, ("挂钩被拒绝（错误码 %d）。杀毒软件可能会拦这类操作，"
                       "把本程序加入信任名单后再试" % ctypes.get_last_error())
    try:
        _user32.SendNotifyMessageW(hwnd, WM_NULL, 0, 0)
        rc = _kernel32.WaitForSingleObject(ev, int(timeout * 1000)) if ev else 1
    finally:
        _user32.UnhookWindowsHookEx(hook)

    if rc == 0 and tap_pid() == _pid:
        return True, ""
    return False, "注入超时，explorer 没有回应。日志末行：%s" % (
        (read_log().splitlines() or [""])[-1][:120])


def ensure_active():
    """确保 DLL 正在管着当前这个 explorer。已经在跑就什么都不做。

    这层判断很关键：DLL 一旦被钉在 explorer 里就常驻，重复注入等于往同一个进程里
    塞第二份监控，两份会互相覆盖。所以只认「没有活着的那一份」。
    """
    if is_active():
        return True, ""
    return inject()


def _wait_for(text, timeout=3.0):
    """等日志里出现某行（从调用时刻算起，只看新写入的部分）。"""
    start = len(read_log())
    end = time.time() + timeout
    while time.time() < end:
        body = read_log()
        if text in body[start:]:
            return True
        time.sleep(0.15)
    return False


def apply_clear():
    """让任务栏背景透明。返回 (成功?, 错误信息)。"""
    os.makedirs(STATE_DIR, exist_ok=True)
    write_cmd(MODE_CLEAR)
    if not is_active():
        ok, err = inject()
        if not ok:
            return False, err
        # 注入时 DLL 会读一次 inject.cmd，正常已经在透明了；再等一拍确认
        _wait_for("已清空", 3.0)
    else:
        _wait_for("已清空", 2.0)
    if tap_pid() != explorer_pid():
        return False, "注入组件没能连上任务栏"
    return True, ""


def restore(timeout=3.0):
    """把原画刷放回去。DLL 不在（explorer 重启过）就没什么要还原的。"""
    os.makedirs(STATE_DIR, exist_ok=True)
    write_cmd(MODE_RESTORE)
    if not is_active():
        return True
    return _wait_for("已还原", timeout)


def probe():
    """只读：把任务栏那层的 XAML 类型名写进日志，不动画刷。排查用。"""
    os.makedirs(STATE_DIR, exist_ok=True)
    write_cmd(MODE_PROBE)
    ok, err = ensure_active()
    return ok, err
