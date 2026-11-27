#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— Windows 任务栏后端

⚠️ 实测结论（Windows 11 10.0.26200 / 25H2，2026-11-26 复核）
任务栏背景由 explorer 的 XAML 层自己绘制，外部进程改不动。以下全部实测无效
（取样任务栏 2560x60 物理像素，均亮度/标准差/图标对比度三指标都不动）：
  - SetWindowCompositionAttribute：AccentState 0~5 × alpha 0/128/255
    （注意：官方未公开常量表里 1=GRADIENT、2=TRANSPARENTGRADIENT、
      3=BLURBEHIND、4=ACRYLICBLURBEHIND，2 才是「整条透明」那一档）
    贴上去只有 2 号状态能拉动 4 级（37.32 → 41.57），其余纹丝不动
  - DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE = 2/3/4)：HRESULT=0 但无变化
  - 注册表 TaskbarAcrylicOpacity：重启 explorer 后依然无变化
  - 隐藏 XAML 子窗口 DesktopWindowContentBridge：整条任务栏变成纯色 103，
    标准差 0.00、图标对比度 0.0 —— 图标和背景是同一个视觉树，拆不开
  - 色键透明（WS_EX_LAYERED + LWA_COLORKEY）：无变化，DComp 内容不走重定向表面

市面上的第三方任务栏美化工具能做到「背景透明 + 图标清晰」，它的思路（ExplorerTAP）
是注入 explorer 后拿到任务栏背景那个 XAML Shape，直接换掉 Fill 画刷 —— 全部
发生在 explorer 进程内部。这类工具签过名，所以杀软不拦。

本程序也走这条路：`inject/` 下是一个零依赖的 Rust DLL（走 XAML
Diagnostics，同一机制但代码是重写的），由 taskbar_tap.py 送进 explorer。
实测 Win11 26200 上背景真正消失、图标不受影响，且能原样还原。

注入还多了一种用法：不摘画刷，只把背景矩形的 Opacity 压低，
于是「半透明」也能做到背景变淡、图标不变——整窗 alpha 做不到这一点。

三条路（互斥，按用户选择走一条）：
  A. 注入：透明档真透、半透明档只压背景，图标零损失；代价是要往
     explorer 塞一个 DLL（杀软可能拦），且卸载得等 explorer 重启
  B. 自动隐藏：系统原生，整条让位给壁纸，图标零损失，可逆
  C. WS_EX_LAYERED 整窗不透明度：能透出桌面，但图标与文字等比变淡（兜底方案）

Win10（build < 22000）上 AccentPolicy 的 alpha 仍然有效，走 accent 分支，
可以做到「背景透、图标清晰」；Win11 才需要上面三条。

流程：
  1. 确保「设置 → 个性化 → 颜色 → 透明效果」是开的（EnableTransparency=1）
  2. FindWindow("Shell_TrayWnd") 拿主任务栏，再枚举 Shell_SecondaryTrayWnd 拿副屏
  3. 按 taskbar_mode 分流：autohide 走 SHAppBarMessage；fade 走 layered / accent
  4. 资源管理器重启后窗口句柄会变，定期复查句柄，变了就重新贴
"""

import ctypes
import os
import sys
import time
from ctypes import wintypes

import sysenv

IS_WINDOWS = sys.platform.startswith("win")
# Win11 从 build 22000 起任务栏换成 XAML 实现，外部 AccentPolicy 就失效了；
# Win10 上它仍然有效，而且不会牵动图标，所以两代要分开走。
WIN11 = IS_WINDOWS and sys.getwindowsversion().build >= 22000

# ---- AccentState ---------------------------------------------------------- #
ACCENT_DISABLED = 0
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
ACCENT_ENABLE_HOSTBACKDROP = 5

WCA_ACCENT_POLICY = 19

# 与麒麟版共用同一份常量/异常，避免两套定义各自漂移
from panel_core import PanelError, PRESETS, BLUR_NAMES  # noqa: E402
import taskbar_tap as tap  # noqa: E402


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


# ---- 整窗不透明度（分层窗口）---------------------------------------------- #
# Win11 26200 实测：SetWindowCompositionAttribute 的 GradientColor 贴到任务栏上，
# 只能拉动约 23 级灰度（255 里的 9%）——纯黑和纯白分别是 217 和 240，肉眼几乎
# 分不出。所以「把 alpha 映射成 RGB 明度」这条路在本机是死的，滑块拖到底也看不出
# 变化。
#
# 真正能连续控制的是把任务栏窗口设成 layered，再用 SetLayeredWindowAttributes
# 给整窗一个 0-255 的不透明度：实测线性、可逆、跨度 168 级。代价是图标和文字也
# 一起变淡（这是整窗混合的必然结果），所以留一个下限，别让人彻底找不到任务栏。
WS_EX_LAYERED = 0x00080000
GWL_EXSTYLE = -20
LWA_ALPHA = 0x00000002

MIN_ALPHA_WIN11 = 0.55  # Win11 整窗混合的下限：再低图标与文字就看不清了。
# 实测 10% 时任务栏只剩一层淡影，图标对比度从 61 掉到 7（等于消失）。
MIN_ALPHA = 0.0         # Win10 走 accent 的 alpha，0 = 背景全透、图标依然清晰


# -- 自动隐藏 -------------------------------------------------------------
# Win11 的任务栏是一整块 XAML 表面（背景与图标在同一个视觉树里，外部拆不开），
# 所以"背景透、图标清晰"从进程外做不到。真正零损耗的替代是系统自带的自动隐藏：
# 整条让位给壁纸，鼠标碰到底边才滑出来。实测同一条命令即时生效、可逆。
ABM_GETSTATE = 4
ABM_SETSTATE = 10
ABS_AUTOHIDE = 0x1
ABS_ALWAYSONTOP = 0x2


class APPBARDATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uCallbackMessage", wintypes.UINT), ("uEdge", wintypes.UINT),
                ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM)]


def _appbar(state=None):
    """state 为 None 时只读取当前状态，否则下发 ABM_SETSTATE。"""
    bar = _taskbars()
    if not bar:
        return None
    abd = APPBARDATA()
    abd.cbSize = ctypes.sizeof(APPBARDATA)
    abd.hWnd = bar[0]
    shell32 = ctypes.windll.shell32
    shell32.SHAppBarMessage.restype = ctypes.c_size_t
    shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(APPBARDATA)]
    if state is None:
        return int(shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(abd)))
    abd.lParam = state
    shell32.SHAppBarMessage(ABM_SETSTATE, ctypes.byref(abd))
    return int(abd.lParam)


# 第三方任务栏美化工具和本程序改的是同一块任务栏，后写的会覆盖先写的。
# 检测到就提示用户二选一，而不是让两个程序互相打架。
# 这里是**进程名**（用来识别那个工具在不在跑），界面永远只显示"第三方任务栏美化工具"，
# 不会把这些名字摆给用户看。
_TASKBAR_TOOLS = ("TranslucentTaskbar", "TranslucentTB", "RoundedTB",
                  "ExplorerPatcher", "TaskbarX", "StartAllBack")


def _running_taskbar_tools():
    """返回正在运行的第三方任务栏工具名（用进程快照，不额外起子进程）。"""
    found = []
    try:
        TH32CS_SNAPPROCESS = 0x2

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_char * 260)]

        k32 = ctypes.windll.kernel32
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == -1:
            return found
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        ok = k32.Process32First(snap, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile.decode("mbcs", "ignore")
            stem = os.path.splitext(name)[0]
            for t in _TASKBAR_TOOLS:
                if stem.lower() == t.lower() and t not in found:
                    found.append(t)
            ok = k32.Process32Next(snap, ctypes.byref(entry))
        k32.CloseHandle(snap)
    except Exception:
        pass
    return found


def _get_exstyle(hwnd):
    _user32.GetWindowLongW.restype = ctypes.c_long
    return _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)


def _set_exstyle(hwnd, value):
    _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    _user32.SetWindowLongW.restype = ctypes.c_long
    return _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, value)


def _set_opacity(hwnd, level):
    """把整个任务栏窗口按 level(0~1) 半透明。成功返回 True。"""
    try:
        ex = _get_exstyle(hwnd)
        if not (ex & WS_EX_LAYERED):
            _set_exstyle(hwnd, ex | WS_EX_LAYERED)
        _user32.SetLayeredWindowAttributes.argtypes = [
            wintypes.HWND, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD]
        _user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
        a = int(round(255 * max(0.0, min(1.0, level))))
        return bool(_user32.SetLayeredWindowAttributes(hwnd, 0, a, LWA_ALPHA))
    except Exception:
        return False


def _get_opacity(hwnd):
    """读回 layered 的实际 alpha（0~255）。不是 layered 或读不到返回 None。

    实测：explorer 会自己把 WS_EX_LAYERED 加回去（任务栏本来就用它做合成），
    但 alpha 会被重置成 255。所以「有 layered 标志」不等于「我们的透明度还在」，
    巡检必须比 alpha，否则淡出会静默失效、用户只看到任务栏莫名其妙变实。
    """
    try:
        _user32.GetLayeredWindowAttributes.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(wintypes.DWORD)]
        _user32.GetLayeredWindowAttributes.restype = wintypes.BOOL
        key = wintypes.DWORD()
        alpha = ctypes.c_ubyte()
        flags = wintypes.DWORD()
        if not _user32.GetLayeredWindowAttributes(hwnd, ctypes.byref(key),
                                                  ctypes.byref(alpha), ctypes.byref(flags)):
            return None
        return int(alpha.value)
    except Exception:
        return None


def _clear_opacity(hwnd, orig_ex):
    """还原：先回满不透明，再把 layered 标志摘掉。"""
    try:
        _user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
    except Exception:
        pass
    try:
        if orig_ex is not None:
            _set_exstyle(hwnd, orig_ex)
    except Exception:
        pass


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


def _system_light():
    """系统当前是不是亮色主题（SystemUsesLightTheme=1）。读不到时默认亮色。

    保留给外部排查用（cli diagnose / 手工实验）；贴透明度的主流程已经不再依赖
    它——整窗 alpha 与深浅主题无关。
    """
    try:
        import winreg
        path = (r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            v, _ = winreg.QueryValueEx(k, "SystemUsesLightTheme")
        return int(v) == 1
    except Exception:
        return True


class PanelWin(object):
    """接口与 panel_core.PanelCore 保持一致，UI 层无感知换后端。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self._last_hwnds = ()
        self._applied = False
        self._backed_up = False     # 原值只记一次，别每次贴 accent 都覆盖成"已改过"的值
        self._transparency_ok = False   # "透明效果"已经确保开启过，不必每次拖滑块都写注册表
        self._ex_style = {}             # hwnd -> 动它之前的扩展样式，退出时按原样还回去
        self._tap_try = 0.0             # 上次尝试重新注入的时刻（限速用）
        # 上次可能是崩溃/被强杀，透明画刷还留在 explorer 里：启动时先无条件还原一次。
        # 否则用户会看到一条透空的任务栏，却完全不知道是谁改的、怎么改回去。
        # 组件不在（explorer 重启过）时这是空操作，代价只有一次文件写入。
        try:
            if self.taskbar_mode() != self.MODE_INJECT:
                tap.restore(timeout=1.5)
        except Exception:
            pass

    # -- 能力 ---------------------------------------------------------------
    def supports_blur_level(self):
        return False          # Windows 只有系统 Acrylic 一档，没有三级磨砂

    def available(self):
        return IS_WINDOWS

    def info(self):
        hwnds = _taskbars()
        mode = self.taskbar_mode()
        names = {self.MODE_AUTOHIDE: "自动隐藏", self.MODE_INJECT: "注入全透明"}
        info = {
            "平台": "Windows",
            "任务栏窗口": "%d 个" % len(hwnds) if hwnds else "未找到",
            "形态": names.get(mode, "整窗淡出"),
        }
        if mode == self.MODE_AUTOHIDE:
            info["自动隐藏"] = "已开启" if self.get_autohide() else "未生效"
        elif mode == self.MODE_INJECT:
            a = self.inject_tint()
            info["形态"] = ("完全透明（注入）" if a <= 0.001
                           else "半透明（注入 %d%%）" % int(round(a * 100)))
            info["注入组件"] = "已连上" if tap.is_active() else "未连上"
            info["组件来源"] = tap.dll_source() or "缺失"
        else:
            info["透明度"] = "%d%%" % int(self.get_alpha() * 100)
        info["系统透明效果"] = {True: "开", False: "关", None: "读不到"}[_transparency_enabled()]
        info["已应用"] = "是" if self._applied else (
            "否（这一形态不需要）" if mode in (self.MODE_AUTOHIDE, self.MODE_INJECT) else "否")
        tools = _running_taskbar_tools()
        if tools:
            info["第三方工具"] = "、".join(tools) + "（会互相覆盖，建议只留一个）"
        return info

    # -- 透明度 -------------------------------------------------------------
    def glass_on(self):
        return self.cfg["general"].get("glass", "1") == "1"

    def max_alpha(self):
        # 分层窗口能一路做到 100%（完全不透明），不再需要为了"别成实心色块"
        # 把上限压到 92%。
        return 1.0

    def min_alpha(self):
        # Win11 走整窗混合，前景跟着等比变淡，下限必须抬到图标还看得清的档位；
        # Win10 走 accent，只改背景不动图标，可以一路到 0（全透）。
        return MIN_ALPHA_WIN11 if WIN11 else MIN_ALPHA

    def blur_level(self):
        try:
            return int(self.cfg["general"].get("blur_level", "3"))
        except ValueError:
            return 3

    def set_blur_level(self, level):
        # Windows 无分级磨砂，记下来但不改系统
        self.cfg["general"]["blur_level"] = str(level)

    def get_alpha(self):
        # 读数就夹在有效区间里：老配置里可能留着 0（当时以为能全透），
        # 直接回显 0% 会跟界面上的 10% 对不上，diagnose 也会自相矛盾。
        try:
            v = float(self.cfg["general"].get("alpha", "0.6"))
        except (TypeError, ValueError):
            v = 0.6
        return max(self.min_alpha(), min(self.max_alpha(), v))

    def set_alpha(self, value, smooth=False, sync_glass=True):
        # Windows 侧 apply_glass() 就是"把 accent 贴到任务栏"，不调用等于没设置，
        # 所以这里的 sync_glass 默认 True（与 panel_core 的语义差异是平台差异，不是遗漏）。
        value = max(self.min_alpha(), min(self.max_alpha(), float(value)))
        self.cfg["general"]["alpha"] = "%.3f" % value
        self.apply_glass()      # 透明度必须落到窗口上，因此不看 sync_glass
        return value

    # -- 任务栏形态（Windows 特有的两条路）--------------------------------
    MODE_FADE = "fade"
    MODE_AUTOHIDE = "autohide"
    MODE_INJECT = "inject"

    def supports_inject(self):
        """能不能做「真·全透明」：得有注入组件，而且得是 Windows。

        组件缺失（老版本安装包、杀软删了文件）时界面直接不显示这一项，
        而不是让用户打开开关之后看到一句报错。
        """
        return bool(IS_WINDOWS and tap.dll_source())

    def taskbar_mode(self):
        v = str(self.cfg["general"].get("taskbar_mode") or self.MODE_FADE).strip().lower()
        if v == self.MODE_AUTOHIDE:
            return self.MODE_AUTOHIDE
        if v == self.MODE_INJECT:
            return self.MODE_INJECT
        return self.MODE_FADE

    def supports_autohide(self):
        return bool(IS_WINDOWS and _taskbars())

    def get_autohide(self):
        state = _appbar(None)
        return bool(state is not None and (state & ABS_AUTOHIDE))

    def set_autohide(self, on):
        """开关任务栏自动隐藏。即时生效，写回系统设置本身（重启后保留）。"""
        if not IS_WINDOWS:
            return False
        cur = _appbar(None)
        base = cur if cur is not None else (ABS_AUTOHIDE | ABS_ALWAYSONTOP)
        if on:
            state = base | ABS_AUTOHIDE
        else:
            # 关掉时连同 always-on-top 一起复位，回到系统默认的常驻顶栏
            state = (base & ~ABS_AUTOHIDE) | ABS_ALWAYSONTOP
        _appbar(state)
        return self.get_autohide() == bool(on)

    def set_taskbar_mode(self, mode, tint=None):
        """三种形态互斥：同一时刻只能有一种在管任务栏。

        自动隐藏 / 整窗淡出 / 注入（全透明或背景着色）都会改动同一块表面，叠在一起
        必然互相覆盖（例如注入了还开着 layered，透明就变成"壁纸 × 半透明"的浑浊色）。
        所以切到哪个，先把另外两个摘干净。

        tint：注入形态下的背景浓度。0 = 整块去掉，0~1 = 只把背景压淡、图标不动。
        """
        if mode not in (self.MODE_AUTOHIDE, self.MODE_INJECT):
            mode = self.MODE_FADE
        prev = self.taskbar_mode()
        self.cfg["general"]["taskbar_mode"] = mode
        if tint is not None:
            self.cfg["general"]["inject_tint"] = "%.3f" % max(0.0, min(1.0, tint))

        if prev == self.MODE_INJECT and mode != self.MODE_INJECT:
            # 离开注入模式：先把画刷/透明度还回去，再卸别的
            try:
                tap.restore()
            except Exception:
                pass
        elif mode != self.MODE_INJECT:
            # 即便配置里没记着注入，explorer 里也可能还留着透明画刷（上次崩溃）：
            # 切到别的形态时顺手清一次，成本只是一次文件写 + 一次日志比对。
            try:
                tap.restore(timeout=1.0)
            except Exception:
                pass

        if mode == self.MODE_INJECT:
            self._drop_opacity()
            self.set_autohide(False)
            want = self.inject_tint()
            ok, err = tap.apply_tint(want) if want > 0.001 else tap.apply_clear()
            if not ok:
                # 注入失败就把配置退回去，别留下"开关是开的、任务栏没变"的脏状态
                self.cfg["general"]["taskbar_mode"] = prev
                raise PanelError(err)
        elif mode == self.MODE_AUTOHIDE:
            self._drop_opacity()
            self.set_autohide(True)
        else:
            self.set_autohide(False)
            self.apply_glass()
        return mode

    def running_taskbar_tools(self):
        """正在运行的第三方任务栏外观工具。和它们抢同一块任务栏，只能二选一。"""
        return _running_taskbar_tools() if IS_WINDOWS else []

    # -- 外观档位（给界面用的固定值）----------------------------------------
    # 横排单选按钮用的六档，两端是「无痕」（整块消失）和「凝实」（系统原样），
    # 中间四档取 0.15 / 0.35 / 0.60 / 0.80 的等视感梯度（按实测亮度曲线挑的，
    # 档与档之间肉眼能分清，又不至于密到点错）。
    #   半透明档 = 注入后把背景那块矩形的 Opacity 压低，图标不在里面，
    #   所以「背景变淡、图标照旧清晰」——整窗 alpha 做不到这一点（55% 以下图标就糊了）。
    STYLES = (
        ("clear", "无痕", 0.00),
        ("gauze", "轻纱", 0.15),
        ("mist",  "薄雾", 0.35),
        ("frost", "磨砂", 0.60),
        ("haze",  "浓雾", 0.80),
        ("solid", "凝实", 1.00),
    )

    def current_style(self):
        """当前实际生效的档位 key。

        不另存一个 style 字段：形态和浓度本来就已经落在配置里，
        多存一份等于给"配置和现实不一致"留了个后门。
        """
        mode = self.taskbar_mode()
        if mode == self.MODE_INJECT:
            a = self.inject_tint()
        elif mode == self.MODE_FADE:
            a = self.get_alpha()
        else:
            # 自动隐藏等非档位形态：界面上按最实的一档显示
            a = 1.0
        for key, _label, val in self.STYLES:
            if abs(val - a) < 0.08:
                return key
        # 老配置里可能是任意值（比如 0.55、0.72），挑最接近的档位显示，不假装精确
        best = min(self.STYLES, key=lambda s: abs(s[2] - a))
        return best[0]

    def inject_tint(self):
        """注入档位的背景浓度：0 = 整块去掉，0~1 = 只压背景的透明度。"""
        try:
            return float(self.cfg["general"].get("inject_tint") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def set_style(self, key):
        """按档位切换。切哪个都先把另外两种形态摘干净，避免叠在一起互相糊。"""
        if not any(k == key for k, _l, _v in self.STYLES):
            key = "solid"

        tint = dict((k, v) for k, _l, v in self.STYLES)[key]
        if tint >= 0.999:
            # 「不透明」既不留在注入形态（那会让组件一直被钉在 explorer 里），
            # 也不留一个 255 的 layered 标志（视觉一样，但 restore 时多一层要还）。
            if self.taskbar_mode() != self.MODE_FADE:
                self.set_taskbar_mode(self.MODE_FADE)
            self.set_alpha(1.0)
            self._drop_opacity()
            return key

        if self.supports_inject():
            # 注入能给"背景淡、图标清晰"，优先走它
            return self.set_taskbar_mode(self.MODE_INJECT, tint)

        # 没有注入组件（安装包缺文件 / 杀软删了）时的兜底：整窗淡出。
        # 最低只能到 0.55——再低图标和文字一起糊成一片，还不如不给这档。
        alpha = max(0.55, tint)
        if self.taskbar_mode() != self.MODE_FADE:
            self.set_taskbar_mode(self.MODE_FADE)
        self.set_alpha(alpha)
        return key

    def _drop_opacity(self):
        """摘掉我们自己贴的 layered，不动用户的其他设置。"""
        for h, ex in list(self._ex_style.items()):
            _clear_opacity(h, ex)
        self._ex_style.clear()
        for h in _taskbars():
            try:
                ex = _get_exstyle(h)
                if ex & WS_EX_LAYERED:
                    _clear_opacity(h, ex & ~WS_EX_LAYERED)
            except Exception:
                pass
        self._applied = False

    # -- 应用 ---------------------------------------------------------------
    BACKUP_KEY = "panel_win"

    def _backup_once(self):
        """动系统「透明效果」之前，把原值记一次，退出时才能写回去。

        读不到（None）就不记：还原时宁可不碰，也不能把用户的设置改成猜的值。
        """
        if self._backed_up:
            return
        if not sysenv.recall_system(self.BACKUP_KEY):
            cur = _transparency_enabled()
            if cur is not None:
                try:
                    sysenv.remember_system(self.BACKUP_KEY,
                                           {"EnableTransparency": 1 if cur else 0})
                except OSError:
                    pass        # 台账写不进去不能挡住贴 accent
        self._backed_up = True

    def apply_glass(self):
        """把当前透明度 + 玻璃状态贴到任务栏窗口上。

        返回值：(成功?, 错误信息)。失败不抛，让 UI 能提示。
        """
        if not IS_WINDOWS:
            return False, "不是 Windows 平台"

        hwnds = _taskbars()
        if not hwnds:
            return False, "找不到任务栏窗口（Shell_TrayWnd）"

        if self.taskbar_mode() == self.MODE_INJECT:
            # 注入模式下画刷由 explorer 里的组件管，这里什么都不该碰：
            # 一贴 layered 就把"真透明"糊成半透明，前面注入的功夫全废。
            want = self.inject_tint()
            return tap.apply_tint(want) if want > 0.001 else tap.apply_clear()

        if self.taskbar_mode() == self.MODE_AUTOHIDE:
            # 自动隐藏模式下不再叠加整窗透明：两者一起用会既看不见任务栏、
            # 又让悬停出来的那一条发灰。
            self._drop_opacity()
            return True, ""

        if self.glass_on():
            self._backup_once()
            # 拖滑块时 apply_glass 会被反复调用，写注册表只做一次：
            # 系统设置项没变，重复写只是白白触发 explorer 的变更通知。
            if not self._transparency_ok:
                self._transparency_ok = bool(_enable_transparency(True))

        alpha = self.get_alpha()
        alpha = max(self.min_alpha(), min(1.0, alpha))
        if self.cfg["general"].get("alpha") != "%.3f" % alpha:
            # 老配置里可能有 0 或者超过 100% 的值，落盘前先修正，免得每次启动都重算
            self.cfg["general"]["alpha"] = "%.3f" % alpha

        ok_any = False
        err = ""
        alive = set(hwnds)
        # 资源管理器重启后旧句柄作废，顺手清掉，免得 restore 时对野句柄操作
        self._ex_style = {h: v for h, v in self._ex_style.items() if h in alive}
        for h in hwnds:
            try:
                if h not in self._ex_style:
                    # 存"没被我们碰过"的样子：把 layered 位摘掉再记。
                    # 否则上一次异常退出留下的 layered 会被当成原值记住，
                    # restore 之后永远摘不掉（虽然视觉上不透明，但状态是脏的）。
                    self._ex_style[h] = _get_exstyle(h) & ~WS_EX_LAYERED
                if WIN11:
                    # Win11：accent 打不穿 XAML 层（实测 1 级都拉不动），
                    # 只做整窗不透明度，代价是图标跟着变淡。
                    if _set_opacity(h, alpha):
                        ok_any = True
                    elif not err:
                        err = "SetLayeredWindowAttributes 调用失败"
                else:
                    # Win10：accent 的 alpha 真有效，只压背景，图标清晰。
                    state = (ACCENT_ENABLE_ACRYLICBLURBEHIND if self.glass_on()
                             else ACCENT_DISABLED)
                    tint = int(round(alpha * 255)) << 24     # AABBGGRR：纯黑，alpha 可调
                    if _set_accent(h, state, tint):
                        ok_any = True
                    elif not err:
                        err = "SetWindowCompositionAttribute 调用失败"
            except PanelError as e:
                err = str(e)
            except Exception as e:
                err = "%s" % e

        self._last_hwnds = tuple(hwnds)
        self._applied = ok_any
        if ok_any:
            return True, ""
        return False, err or "设置任务栏透明度失败"

    def keep_alive(self):
        """资源管理器重启会换句柄，另外它自己也可能把 layered 标志冲掉。

        注入模式还有第三种失效：explorer 重启 = 我们送进去的 DLL 跟着一起没了。
        这时要重新注入，但必须限速——杀软如果一直拦，每 4 秒硬试一次会让界面卡成幻灯片。
        """
        if not IS_WINDOWS:
            return
        hwnds = tuple(_taskbars())
        if self.taskbar_mode() == self.MODE_INJECT:
            try:
                if not tap.is_active() and time.time() - self._tap_try > 20.0:
                    self._tap_try = time.time()
                    want = self.inject_tint()
                    (tap.apply_tint(want) if want > 0.001 else tap.apply_clear())
            except Exception:
                pass
            self._last_hwnds = hwnds
            return
        if self.taskbar_mode() == self.MODE_AUTOHIDE:
            # 自动隐藏不靠 layered；只在被系统改动过时补一次（explorer 重启、
            # 用户在设置里手动关掉），不必每 4 秒重写一次 AppBar 状态。
            try:
                if not self.get_autohide():
                    self.set_autohide(True)
            except Exception:
                pass
            self._last_hwnds = hwnds
            return
        if hwnds != self._last_hwnds:
            self.apply_glass()
            return
        # 句柄没变，但我们的透明度可能被冲掉了：explorer 重绘/主题切换会把
        # layered 标志加回来而 alpha 归 255。比起只查标志位，直接比 alpha 才靠谱。
        want = int(round(self.get_alpha() * 255))
        for h in hwnds:
            try:
                got = _get_opacity(h)
                if got is None or abs(got - want) > 6:
                    self.apply_glass()
                    return
            except Exception:
                pass

    def set_glass(self, on):
        self.cfg["general"]["glass"] = "1" if on else "0"
        self.apply_glass()      # 开和关都要落到窗口上，否则关掉不生效

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
        """还原系统外观：任务栏回满不透明、摘掉 layered，再把「透明效果」写回原值。

        自动隐藏是用户自己选的一项系统设置，这里不动它 —— 退出程序不该把
        用户设成"碰底边才出来"的用法改回常驻。
        """
        # 注入模式：先把画刷放回去（这一步依赖 explorer 里那份 DLL 还活着）。
        # 不判断当前 mode —— 上次可能异常退出、配置没落盘，但任务栏还留着透明；
        # 无条件喊一声"还原"最省事，组件不在的时候它自己会立刻返回。
        try:
            tap.restore()
        except Exception:
            pass

        self._drop_opacity()

        for h in _taskbars():
            try:
                _set_accent(h, ACCENT_DISABLED, 0)
            except Exception:
                pass
        self._applied = False

        saved = sysenv.recall_system(self.BACKUP_KEY) or {}
        if "EnableTransparency" in saved:
            _enable_transparency(bool(saved["EnableTransparency"]))
            sysenv.forget_system(self.BACKUP_KEY)
            self._backed_up = False
        self._transparency_ok = False       # 下次开启玻璃时重新确认一次
        return True


def preset_value(key):
    for k, _, v in PRESETS:
        if k == key:
            return v
    return None
