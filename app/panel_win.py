#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— Windows 任务栏毛玻璃后端

Windows 没有"任务栏透明度"这个官方设置项。真正能让任务栏变成亚克力（Acrylic）
的是未公开 API `user32!SetWindowCompositionAttribute`，配合
`ACCENT_ENABLE_ACRYLICBLURBEHIND` 把一层带 alpha 的模糊贴到任务栏窗口上。
TranslucentTB 这类工具走的就是这条路，不是改注册表。

流程：
  1. 确保「设置 → 个性化 → 颜色 → 透明效果」是开的（注册表 EnableTransparency=1），
     关掉的话任务栏是纯色，贴什么模糊都看不出来
  2. FindWindow("Shell_TrayWnd") 拿到主任务栏，再枚举 Shell_SecondaryTrayWnd 拿副屏
  3. 给每个任务栏窗口下发 ACCENT_POLICY：State=4(亚克力)、GradientColor=0xAABBGGRR
  4. 资源管理器重启后窗口句柄会变，所以要定期复查句柄，变了就重新贴

⚠️ 本文件在麒麟上无法实测，所有调用都有异常兜底；失败会返回明确错误而不是崩溃。
"""

import ctypes
import sys
from ctypes import wintypes

IS_WINDOWS = sys.platform.startswith("win")

# ---- AccentState ---------------------------------------------------------- #
ACCENT_DISABLED = 0
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
ACCENT_ENABLE_HOSTBACKDROP = 5

WCA_ACCENT_POLICY = 19

# 与麒麟版共用同一份常量/异常，避免两套定义各自漂移
from panel_core import PanelError, PRESETS, BLUR_NAMES, GLASS_MAX_ALPHA  # noqa: E402


if IS_WINDOWS:
    class ACCENT_POLICY(ctypes.Structure):
        _fields_ = [("AccentState", ctypes.c_int),
                    ("AccentFlags", ctypes.c_int),
                    ("GradientColor", ctypes.c_uint),
                    ("AnimationId", ctypes.c_int)]

    class WCADATA(ctypes.Structure):
        _fields_ = [("Attribute", ctypes.c_int),
                    ("Data", ctypes.c_void_p),
                    ("SizeOfData", ctypes.c_size_t)]

    _user32 = ctypes.windll.user32
    _user32.FindWindowW.restype = wintypes.HWND
    _user32.FindWindowExW.restype = wintypes.HWND
    _user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                                       wintypes.LPARAM),
                                    wintypes.LPARAM]
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


def _taskbars():
    """主任务栏 + 所有副屏任务栏的窗口句柄。"""
    if not IS_WINDOWS:
        return []
    out = []
    hwnd = _user32.FindWindowW("Shell_TrayWnd", None)
    if hwnd:
        out.append(hwnd)

    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(h, _l):
        buf = ctypes.create_unicode_buffer(64)
        _user32.GetClassNameW(h, buf, 64)
        if buf.value == "Shell_SecondaryTrayWnd":
            found.append(h)
        return True

    try:
        _user32.EnumWindows(_cb, 0)
    except Exception:
        pass
    return out + found


def _set_accent(hwnd, state, color_argb):
    """给一个窗口贴 accent。返回是否成功。"""
    policy = ACCENT_POLICY()
    policy.AccentState = state
    policy.AccentFlags = 2 if state == ACCENT_ENABLE_ACRYLICBLURBEHIND else 0
    policy.GradientColor = color_argb
    policy.AnimationId = 0

    data = WCADATA()
    data.Attribute = WCA_ACCENT_POLICY
    data.Data = ctypes.cast(ctypes.pointer(policy), ctypes.c_void_p)
    data.SizeOfData = ctypes.sizeof(policy)

    fn = getattr(_user32, "SetWindowCompositionAttribute", None)
    if fn is None:
        raise PanelError("当前系统没有 SetWindowCompositionAttribute（需要 Win10 1803 以上）")
    fn.argtypes = [wintypes.HWND, ctypes.POINTER(WCADATA)]
    fn.restype = wintypes.BOOL
    return bool(fn(hwnd, ctypes.byref(data)))


def _enable_transparency(on=True):
    """确保系统「透明效果」是开的，否则任务栏是纯色。"""
    try:
        import winreg
        path = (r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "EnableTransparency", 0, winreg.REG_DWORD, 1 if on else 0)
        return True
    except Exception:
        return False


def _transparency_enabled():
    try:
        import winreg
        path = (r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            v, _ = winreg.QueryValueEx(k, "EnableTransparency")
        return int(v) == 1
    except Exception:
        return None


class PanelWin(object):
    """接口与 panel_core.PanelCore 保持一致，UI 层无感知换后端。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self._last_hwnds = ()
        self._applied = False

    # -- 能力 ---------------------------------------------------------------
    def supports_blur_level(self):
        return False          # Windows 只有系统 Acrylic 一档，没有三级磨砂

    def available(self):
        return IS_WINDOWS

    def info(self):
        hwnds = _taskbars()
        return {
            "平台": "Windows",
            "任务栏窗口": "%d 个" % len(hwnds) if hwnds else "未找到",
            "透明度": "%d%%" % int(self.get_alpha() * 100),
            "系统透明效果": {True: "开", False: "关", None: "读不到"}[_transparency_enabled()],
            "已应用": "是" if self._applied else "否",
        }

    # -- 透明度 -------------------------------------------------------------
    def glass_on(self):
        return self.cfg["general"].get("glass", "1") == "1"

    def max_alpha(self):
        return GLASS_MAX_ALPHA if self.glass_on() else 1.0

    def blur_level(self):
        try:
            return int(self.cfg["general"].get("blur_level", "3"))
        except ValueError:
            return 3

    def set_blur_level(self, level):
        # Windows 无分级磨砂，记下来但不改系统
        self.cfg["general"]["blur_level"] = str(level)

    def get_alpha(self):
        try:
            return max(0.0, min(1.0, float(self.cfg["general"].get("alpha", "0.6"))))
        except (TypeError, ValueError):
            return 0.6

    def set_alpha(self, value, smooth=False):
        value = max(0.0, min(self.max_alpha(), float(value)))
        self.cfg["general"]["alpha"] = "%.3f" % value
        self.apply_glass()
        return value

    # -- 应用 ---------------------------------------------------------------
    def apply_glass(self):
        """把当前透明度 + 玻璃状态贴到任务栏窗口上。

        返回值：(成功?, 错误信息)。失败不抛，让 UI 能提示。
        """
        if not IS_WINDOWS:
            return False, "不是 Windows 平台"

        hwnds = _taskbars()
        if not hwnds:
            return False, "找不到任务栏窗口（Shell_TrayWnd）"

        if self.glass_on():
            _enable_transparency(True)

        alpha = self.get_alpha()
        if self.glass_on():
            state = ACCENT_ENABLE_ACRYLICBLURBEHIND
            a = int(round(max(0.02, min(1.0, alpha)) * 255))
        else:
            # 关掉玻璃质感：只留模糊（仍半透明，但没有亚克力颗粒感）
            state = ACCENT_ENABLE_BLURBEHIND
            a = int(round(max(0.02, min(1.0, alpha)) * 255))

        # 色调：深色 #1A1A1A + alpha
        tint = (a << 24) | 0x001A1A1A
        ok_any = False
        err = ""
        for h in hwnds:
            try:
                if _set_accent(h, state, tint):
                    ok_any = True
            except PanelError as e:
                err = str(e)
            except Exception as e:
                err = "%s" % e

        self._last_hwnds = tuple(hwnds)
        self._applied = ok_any
        if ok_any:
            return True, ""
        return False, err or "SetWindowCompositionAttribute 调用失败"

    def keep_alive(self):
        """资源管理器重启会让句柄失效，句柄变了就重新贴一次。"""
        if not IS_WINDOWS or not self.glass_on():
            return
        if tuple(_taskbars()) != self._last_hwnds:
            self.apply_glass()

    def set_glass(self, on):
        self.cfg["general"]["glass"] = "1" if on else "0"
        if on:
            self.apply_glass()

    # -- 兼容接口 -----------------------------------------------------------
    def pin_popups(self):
        """Windows 上没有对应概念（开始菜单/右键菜单透明度由系统统一控制）。"""
        return

    def probe_write(self):
        ok, err = self.apply_glass()
        if not ok:
            raise PanelError(err)
        return True

    def restore(self):
        """恢复系统默认外观。"""
        for h in _taskbars():
            try:
                _set_accent(h, ACCENT_DISABLED, 0)
            except Exception:
                pass
        self._applied = False


def preset_value(key):
    for k, _, v in PRESETS:
        if k == key:
            return v
    return None
