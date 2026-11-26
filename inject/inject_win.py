# -*- coding: utf-8 -*-
"""把 do_inject.dll 送进 explorer，并等它报就绪。

先用 probe 模式跑：DLL 只把任务栏那一层的 XAML 类型名写进 inject.log，
不动任何画刷。确认能拿到 `Windows.UI.Xaml.Shapes.Shape / BackgroundFill`
之后，再切 clear。

    python inject/inject_win.py probe
    python inject/inject_win.py clear
    python inject/inject_win.py restore
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DLL = os.path.join(HERE, "target", "release", "do_inject.dll")

STATE_DIR = os.path.join(os.environ.get("APPDATA", ""), "DesktopOrganizer")
CMD = os.path.join(STATE_DIR, "inject.cmd")
LOG = os.path.join(STATE_DIR, "inject.log")
READY_EVENT = "Local\\DesktopOrganizerTapReady"


def deploy_dll():
    """把 DLL 复制成带时间戳的副本再注入。

    InitializeXamlDiagnosticsEx 会把 DLL 永久钉在 explorer 里（文件被占用，删不掉也覆盖不了），
    直接注入 target/release 里的那份会导致下一次 cargo build 失败。发布时同样走这条：
    安装目录里那份是源，真正注入的是 %APPDATA% 下的部署副本。
    """
    import shutil
    import time as _t
    dst_dir = os.path.join(STATE_DIR, "tap")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, "do_inject_%s.dll" % _t.strftime("%H%M%S"))
    shutil.copy2(SRC_DLL, dst)
    # 只留最近 5 份，别让 explorer 里堆一串旧副本
    olds = sorted(f for f in os.listdir(dst_dir) if f.startswith("do_inject_"))
    for f in olds[:-5]:
        try:
            os.remove(os.path.join(dst_dir, f))
        except OSError:
            pass
    return dst

WH_CALLWNDPROC = 4
WM_NULL = 0

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p,
                                     wintypes.HINSTANCE, wintypes.DWORD]
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.SendNotifyMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
kernel32.LoadLibraryW.restype = wintypes.HMODULE
kernel32.LoadLibraryW.argtypes = [wintypes.LPCWSTR]
kernel32.GetProcAddress.restype = ctypes.c_void_p
kernel32.GetProcAddress.argtypes = [wintypes.HMODULE, ctypes.c_char_p]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                  wintypes.BOOL, wintypes.LPCWSTR]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.ResetEvent.argtypes = [wintypes.HANDLE]


def write_cmd(mode):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(CMD, "w", encoding="utf-8") as f:
        f.write(mode)


def tail_log(n=200):
    if not os.path.isfile(LOG):
        return "(没有日志)"
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return "".join(f.readlines()[-n:])


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "probe").lower()
    if not os.path.isfile(SRC_DLL):
        print("DLL 不存在：%s\n先 cargo build --release" % SRC_DLL)
        return 2

    os.makedirs(STATE_DIR, exist_ok=True)
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("=== 新会话 %s mode=%s ===\n" % (time.strftime("%H:%M:%S"), mode))
    write_cmd(mode)

    ev = kernel32.CreateEventW(None, True, False, READY_EVENT)
    if ev:
        kernel32.ResetEvent(ev)     # 命名事件可能是上一轮留下来、还处于已触发状态的

    hwnd = user32.FindWindowW("Shell_TrayWnd", None)
    if not hwnd:
        print("找不到任务栏窗口")
        return 3
    pid = wintypes.DWORD()
    tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    print("任务栏 hwnd=%s tid=%d pid=%d" % (hwnd, tid, pid.value))

    mod = kernel32.LoadLibraryW(deploy_dll())
    if not mod:
        print("LoadLibrary 失败 err=%d" % ctypes.get_last_error())
        return 4
    proc = kernel32.GetProcAddress(mod, b"HookProc")
    print("HookProc=%#x" % proc)

    hook = user32.SetWindowsHookExW(WH_CALLWNDPROC, proc, mod, tid)
    if not hook:
        print("SetWindowsHookEx 失败 err=%d" % ctypes.get_last_error())
        return 5
    user32.SendNotifyMessageW(hwnd, WM_NULL, 0, 0)
    print("已触发注入，等 DLL 报就绪……")
    rc = kernel32.WaitForSingleObject(ev, 45000)
    user32.UnhookWindowsHookEx(hook)
    print("等待结果 rc=%s" % rc)

    time.sleep(1.5)
    print("---- inject.log ----")
    print(tail_log())
    return 0


if __name__ == "__main__":
    sys.exit(main())
