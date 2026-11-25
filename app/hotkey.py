#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— 全局快捷键

为什么不用系统那套：UKUI 的自定义快捷键存在可重定位 schema
（org.ukui.control-center.keybinding）下，具体实例路径由控制中心的
libshortcut.so 自己分配，没有稳定约定，硬写 dconf 很容易留垃圾。

这里直接跟 X11 打交道：XGrabKey 抓一个组合键，用 QSocketNotifier 挂在
Qt 事件循环上（不占线程、不用轮询）。零第三方依赖，纯 ctypes。

限制：只在 X11 会话下有效（麒麟 V10 默认就是 X11）。Wayland 下会返回失败，
此时请在 控制中心 → 快捷键 → 自定义 里绑 `kpg cycle`。
"""

import ctypes
import ctypes.util
import os
import sys
import time

from PyQt5.QtCore import QObject, QSocketNotifier, pyqtSignal

# --------------------------------------------------------------------------- #
# X11 绑定
# --------------------------------------------------------------------------- #
_lib = None


def _x11():
    global _lib
    if _lib is None:
        name = ctypes.util.find_library("X11") or "libX11.so.6"
        _lib = ctypes.CDLL(name)
        _lib.XOpenDisplay.restype = ctypes.c_void_p
        _lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        _lib.XDefaultRootWindow.restype = ctypes.c_ulong
        _lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        _lib.XStringToKeysym.restype = ctypes.c_ulong
        _lib.XStringToKeysym.argtypes = [ctypes.c_char_p]
        _lib.XKeysymToKeycode.restype = ctypes.c_ubyte
        _lib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        _lib.XGrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint,
                                  ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        _lib.XUngrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong]
        _lib.XSelectInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long]
        _lib.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        _lib.XPending.argtypes = [ctypes.c_void_p]
        _lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        _lib.XConnectionNumber.argtypes = [ctypes.c_void_p]
        _lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    return _lib


class _XErrorEvent(ctypes.Structure):
    """XErrorEvent —— error_code 在 type/display/resourceid/serial 之后。"""
    _fields_ = [("type", ctypes.c_int),
                ("display", ctypes.c_void_p),
                ("resourceid", ctypes.c_ulong),
                ("serial", ctypes.c_ulong),
                ("error_code", ctypes.c_ubyte),
                ("request_code", ctypes.c_ubyte),
                ("minor_code", ctypes.c_ubyte)]


class _XEvent(ctypes.Union):
    """XEvent 是 24 个 long 的联合体（64 位下 192 字节）。"""
    _fields_ = [("type", ctypes.c_int),
                ("pad", ctypes.c_long * 24)]


# 修饰键掩码
MODS = {
    "ctrl": 1 << 2,     # ControlMask
    "alt": 1 << 3,      # Mod1Mask
    "shift": 1 << 0,    # ShiftMask
    "super": 1 << 6,    # Mod4Mask
}
MOD_ORDER = ("ctrl", "alt", "shift", "super")

_KEYNAME_RE = __import__("re").compile(r"^[A-Za-z0-9]$|^[A-Za-z][A-Za-z0-9_]{1,20}$")

LOCK_MASKS = [0, 1 << 1, 1 << 4]   # 无 / CapsLock(LockMask) / NumLock(Mod2Mask)

KEYPRESS = 2
GRAB_MODE_ASYNC = 1
BAD_ACCESS = 10


def parse_combo(text):
    """'<Ctrl><Alt>G' -> (修饰键掩码, 'g')，解析失败抛 ValueError。"""
    if not text:
        raise ValueError("组合键为空")
    s = text.strip()
    mods = 0
    while s.startswith("<"):
        end = s.find(">")
        if end < 0:
            raise ValueError("组合键格式不对：%s" % text)
        word = s[1:end].strip().lower()
        alias = {"control": "ctrl", "ctl": "ctrl", "meta": "super",
                 "win": "super", "cmd": "super", "mod1": "alt"}.get(word, word)
        if alias not in MODS:
            raise ValueError("不认识的修饰键：%s" % word)
        mods |= MODS[alias]
        s = s[end + 1:].strip()
    if not s:
        raise ValueError("缺少主键：%s" % text)
    if not _KEYNAME_RE.match(s):
        raise ValueError("不认识的按键：%s" % s)
    try:
        if _x11().XStringToKeysym(s.encode()) == 0:
            raise ValueError("X 无法识别按键：%s（可用 G、F9、space 这类名字）" % s)
    except OSError:
        pass          # 没有 libX11 时只做格式校验
    return mods, s


class _X11Hotkey(QObject):
    """抓一个全局组合键，按下时触发 triggered 信号。"""

    triggered = pyqtSignal()

    def __init__(self, combo, parent=None):
        super(Hotkey, self).__init__(parent)
        self.combo = combo
        self._dpy = None
        self._notifier = None
        self._keycode = 0
        self._mods = 0
        self.error = ""
        self._last = 0.0

    # -- 生命周期 -----------------------------------------------------------
    def start(self):
        if not os.environ.get("DISPLAY"):
            self.error = "当前不是 X11 图形会话"
            return False
        try:
            lib = _x11()
        except OSError as e:
            self.error = "加载 libX11 失败：%s" % e
            return False

        try:
            mods, keyname = parse_combo(self.combo)
        except ValueError as e:
            self.error = str(e)
            return False

        dpy = lib.XOpenDisplay(None)
        if not dpy:
            self.error = "无法连接 X 服务器（DISPLAY=%s）" % os.environ.get("DISPLAY")
            return False
        self._dpy = dpy
        self._mods = mods

        keysym = lib.XStringToKeysym(keyname.encode())
        if keysym == 0:
            self.error = "X 无法识别按键：%s" % keyname
            self._close()
            return False
        keycode = lib.XKeysymToKeycode(dpy, keysym)
        if keycode == 0:
            self.error = "按键没有对应的 keycode：%s" % keyname
            self._close()
            return False
        self._keycode = keycode

        # X 的错误是异步的：装个处理器专门抓 BadAccess（= 被别的程序占了）
        state = {"conflict": False}

        def _handler(d, err):
            try:
                ev = ctypes.cast(err, ctypes.POINTER(_XErrorEvent)).contents
                if ev.error_code == BAD_ACCESS:
                    state["conflict"] = True
            except Exception:
                pass
            return 0

        ERRPROC = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        self._errproc = ERRPROC(_handler)
        lib.XSetErrorHandler.argtypes = [ERRPROC]
        lib.XSetErrorHandler(self._errproc)

        root = lib.XDefaultRootWindow(dpy)
        # owner_events=False：键盘事件只交给抓取方，避免走"正常投递"再投一遍
        # 也不要再 XSelectInput(root, KeyPressMask)，否则同一次按键会被收到两三次
        for lock in LOCK_MASKS:
            lib.XGrabKey(dpy, keycode, mods | lock, root, False,
                         GRAB_MODE_ASYNC, GRAB_MODE_ASYNC)
        lib.XSync(dpy, 0)

        if state["conflict"]:
            lib.XUngrabKey(dpy, keycode, mods, root)
            self._close()
            self.error = ("快捷键 %s 已被其它程序占用，换一个：kpg hotkey \"<Ctrl><Alt>X\""
                          % self.combo)
            return False

        fd = lib.XConnectionNumber(dpy)
        self._notifier = QSocketNotifier(fd, QSocketNotifier.Read, self)
        self._notifier.activated.connect(self._on_ready)
        return True

    def stop(self):
        if self._notifier:
            self._notifier.setEnabled(False)
            self._notifier = None
        if self._dpy:
            lib = _x11()
            lib.XUngrabKey(self._dpy, self._keycode, self._mods,
                           lib.XDefaultRootWindow(self._dpy))
            lib.XSync(self._dpy, 0)
            self._close()

    def _close(self):
        if self._dpy:
            try:
                _x11().XCloseDisplay(self._dpy)
            except Exception:
                pass
            self._dpy = None

    # -- 事件 ---------------------------------------------------------------
    def _on_ready(self):
        lib = _x11()
        dpy = self._dpy
        if not dpy:
            return
        ev = _XEvent()
        while lib.XPending(dpy):
            lib.XNextEvent(dpy, ctypes.byref(ev))
            if ev.type == KEYPRESS:
                now = time.time()
                if now - self._last >= 0.15:
                    self._last = now
                    self.triggered.emit()






class _XKeyEvent(ctypes.Structure):
    """XKeyEvent —— 这里只需要 keycode 和 state。"""
    _fields_ = [("type", ctypes.c_int),
                ("serial", ctypes.c_ulong),
                ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p),
                ("window", ctypes.c_ulong),
                ("root", ctypes.c_ulong),
                ("subwindow", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("x_root", ctypes.c_int), ("y_root", ctypes.c_int),
                ("state", ctypes.c_uint),
                ("keycode", ctypes.c_uint),
                ("same_screen", ctypes.c_int)]


LOCK_BITS = 0
for _m in LOCK_MASKS:
    LOCK_BITS |= _m


class _X11HotkeySet(QObject):
    """一组全局快捷键：一个 X 连接抓多个键，按下时按 label 分发。

    为什么不用多个 Hotkey 实例：每个实例都要自己 XOpenDisplay +
    XSetErrorHandler，而后者是进程级的全局回调，后装的会盖掉先装的，
    冲突检测就哑了。一个连接一张表，干净。
    """

    triggered = pyqtSignal(str)

    def __init__(self, parent=None):
        super(_X11HotkeySet, self).__init__(parent)
        self._binds = {}          # label -> {combo, mods, key, keycode}
        self.errors = {}          # label -> 错误说明
        self._dpy = None
        self._notifier = None
        self._last = {}
        self._errproc = None

    def add(self, label, combo):
        try:
            mods, key = parse_combo(combo)
        except ValueError as e:
            self.errors[label] = str(e)
            return False
        self._binds[label] = {"combo": combo, "mods": mods, "key": key, "keycode": 0}
        return True

    def start(self):
        if not os.environ.get("DISPLAY"):
            self._fail_all("当前不是 X11 图形会话")
            return False
        if not self._binds:
            return False
        try:
            lib = _x11()
        except OSError as e:
            self._fail_all("加载 libX11 失败：%s" % e)
            return False

        dpy = lib.XOpenDisplay(None)
        if not dpy:
            self._fail_all("无法连接 X 服务器（DISPLAY=%s）" % os.environ.get("DISPLAY"))
            return False
        self._dpy = dpy

        for label, b in self._binds.items():
            ks = lib.XStringToKeysym(b["key"].encode())
            if ks == 0:
                self.errors[label] = "X 无法识别按键：%s" % b["key"]
                continue
            b["keycode"] = lib.XKeysymToKeycode(dpy, ks)

        conflict = set()
        cur = {"label": None}

        def _handler(_d, err):
            try:
                ev = ctypes.cast(err, ctypes.POINTER(_XErrorEvent)).contents
                if ev.error_code == BAD_ACCESS and cur["label"]:
                    conflict.add(cur["label"])
            except Exception:
                pass
            return 0

        ERRPROC = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        self._errproc = ERRPROC(_handler)
        lib.XSetErrorHandler.argtypes = [ERRPROC]
        lib.XSetErrorHandler(self._errproc)

        root = lib.XDefaultRootWindow(dpy)
        for label, b in self._binds.items():
            if not b["keycode"]:
                continue
            cur["label"] = label
            for lock in LOCK_MASKS:
                lib.XGrabKey(dpy, b["keycode"], b["mods"] | lock, root, False,
                             GRAB_MODE_ASYNC, GRAB_MODE_ASYNC)
            lib.XSync(dpy, 0)      # 每个键同步一次，才认得出是谁冲突

        for label in conflict:
            b = self._binds[label]
            for lock in LOCK_MASKS:
                lib.XUngrabKey(dpy, b["keycode"], b["mods"] | lock, root)
            b["keycode"] = 0
            self.errors[label] = "%s 已被其它程序占用" % b["combo"]
        lib.XSync(dpy, 0)

        if not any(b["keycode"] for b in self._binds.values()):
            self._close()
            return False

        fd = lib.XConnectionNumber(dpy)
        self._notifier = QSocketNotifier(fd, QSocketNotifier.Read, self)
        self._notifier.activated.connect(self._on_ready)
        return True

    def _fail_all(self, msg):
        for label in self._binds:
            self.errors.setdefault(label, msg)

    def stop(self):
        if self._notifier:
            self._notifier.setEnabled(False)
            self._notifier = None
        if self._dpy:
            lib = _x11()
            root = lib.XDefaultRootWindow(self._dpy)
            for b in self._binds.values():
                if b["keycode"]:
                    for lock in LOCK_MASKS:
                        lib.XUngrabKey(self._dpy, b["keycode"], b["mods"] | lock, root)
            lib.XSync(self._dpy, 0)
            self._close()

    def _close(self):
        if self._dpy:
            try:
                _x11().XCloseDisplay(self._dpy)
            except Exception:
                pass
            self._dpy = None

    def _on_ready(self):
        if not self._dpy:
            return
        lib = _x11()
        ev = _XEvent()
        while lib.XPending(self._dpy):
            lib.XNextEvent(self._dpy, ctypes.byref(ev))
            if ev.type != KEYPRESS:
                continue
            ke = ctypes.cast(ctypes.byref(ev), ctypes.POINTER(_XKeyEvent)).contents
            kc = int(ke.keycode)
            state = int(ke.state) & 0xFF & ~LOCK_BITS
            for label, b in self._binds.items():
                if b["keycode"] == kc and state == b["mods"]:
                    now = time.time()
                    if now - self._last.get(label, 0.0) >= 0.15:
                        self._last[label] = now
                        self.triggered.emit(label)
                    break

# --------------------------------------------------------------------------- #
# Windows：RegisterHotKey + Qt 原生事件过滤
# --------------------------------------------------------------------------- #
if sys.platform.startswith("win"):
    import ctypes
    from ctypes import wintypes
    from PyQt5.QtCore import QAbstractNativeEventFilter

    WM_HOTKEY = 0x0312
    MODS_WIN = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "super": 0x0008}
    MOD_NOREPEAT = 0x4000

    class _POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    class _MSG(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                    ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                    ("time", wintypes.DWORD), ("pt", _POINT)]

    def _vk_of(keyname):
        """把 G / F9 / space 这类名字转成虚拟键码。"""
        k = keyname.strip()
        if len(k) == 1 and k.isalnum():
            return ord(k.upper())
        upper = k.upper()
        if upper.startswith("F") and upper[1:].isdigit():
            n = int(upper[1:])
            if 1 <= n <= 24:
                return 0x70 + n - 1
        named = {"SPACE": 0x20, "TAB": 0x09, "ESC": 0x1B, "ESCAPE": 0x1B,
                 "ENTER": 0x0D, "RETURN": 0x0D, "BACKSPACE": 0x08}
        return named.get(upper, 0)

    def _parse_win(text):
        s = (text or "").strip()
        mods = 0
        while s.startswith("<"):
            end = s.find(">")
            if end < 0:
                raise ValueError("组合键格式不对：%s" % text)
            word = s[1:end].strip().lower()
            alias = {"control": "ctrl", "ctl": "ctrl", "meta": "super",
                     "win": "super", "cmd": "super", "mod1": "alt"}.get(word, word)
            if alias not in MODS_WIN:
                raise ValueError("不认识的修饰键：%s" % word)
            mods |= MODS_WIN[alias]
            s = s[end + 1:].strip()
        if not s:
            raise ValueError("缺少主键：%s" % text)
        vk = _vk_of(s)
        if not vk:
            raise ValueError("不认识的按键：%s" % s)
        return mods, vk

    class _WinHotkeySet(QObject):
        """Windows 版：内部就是若干 _WinHotkey，注册 id 依次往后排。"""

        triggered = pyqtSignal(str)

        def __init__(self, parent=None):
            super(_WinHotkeySet, self).__init__(parent)
            self._parked = []
            self._live = {}
            self.errors = {}

        def add(self, label, combo):
            self._parked.append((label, combo))
            return True

        def start(self):
            base = 0xB100
            for i, (label, combo) in enumerate(self._parked):
                hk = _WinHotkey(combo, self, hid=base + i)
                hk.triggered.connect(lambda _=False, l=label: self.triggered.emit(l))
                if hk.start():
                    self._live[label] = hk
                else:
                    self.errors[label] = hk.error
            return bool(self._live)

        def stop(self):
            for hk in self._live.values():
                hk.stop()
            self._live = {}


    class _WinHotkey(QObject):
        """Windows 全局快捷键。

        用 RegisterHotKey(hwnd=NULL)，WM_HOTKEY 会投到本线程消息队列，
        Qt 的事件分发会把它交给 nativeEventFilter —— 不用自己开消息循环。
        """

        triggered = pyqtSignal()

        def __init__(self, combo, parent=None, hid=0xB001):
            super(_WinHotkey, self).__init__(parent)
            self.combo = combo
            self.error = ""
            self._id = hid
            self._registered = False
            self._filter = None

        def start(self):
            try:
                mods, vk = _parse_win(self.combo)
            except ValueError as e:
                self.error = str(e)
                return False
            try:
                user32 = ctypes.windll.user32
                if not user32.RegisterHotKey(None, self._id, mods | MOD_NOREPEAT, vk):
                    self.error = ("快捷键 %s 已被其它程序占用，换一个：khotkey \"<Ctrl><Alt>X\""
                                  % self.combo)
                    return False
            except Exception as e:
                self.error = "注册快捷键失败：%s" % e
                return False

            self._registered = True
            hk = self

            class _Filter(QAbstractNativeEventFilter):
                def nativeEventFilter(self, evtype, message):
                    try:
                        if evtype in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
                            if msg.message == WM_HOTKEY and int(msg.wParam) == hk._id:
                                hk.triggered.emit()
                    except Exception:
                        pass
                    return False, 0

            from PyQt5.QtCore import QCoreApplication
            self._filter = _Filter()
            QCoreApplication.instance().installNativeEventFilter(self._filter)
            return True

        def stop(self):
            try:
                if self._registered:
                    ctypes.windll.user32.UnregisterHotKey(None, self._id)
            except Exception:
                pass
            self._registered = False
            if self._filter is not None:
                try:
                    from PyQt5.QtCore import QCoreApplication
                    QCoreApplication.instance().removeNativeEventFilter(self._filter)
                except Exception:
                    pass
                self._filter = None


if sys.platform.startswith("win"):
    Hotkey = _WinHotkey
    HotkeySet = _WinHotkeySet
else:
    Hotkey = _X11Hotkey
    HotkeySet = _X11HotkeySet


# --------------------------------------------------------------------------- #
# 自测
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QTimer

    app = QApplication(sys.argv)
    combo = sys.argv[1] if len(sys.argv) > 1 else "<Ctrl><Alt>G"
    hk = Hotkey(combo)
    ok = hk.start()
    print("注册 %s -> %s %s" % (combo, "成功" if ok else "失败", hk.error))
    hk.triggered.connect(lambda: print(">>> 按键触发", flush=True))
    QTimer.singleShot(8000, app.quit)
    app.exec_()
