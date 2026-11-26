#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— Windows 任务栏后端

⚠️ 实测结论（Windows 11 10.0.26200 / 25H2，2026-11-26 复核）
任务栏背景由 explorer 的 XAML 层自己绘制，外部进程改不动。以下全部实测无效，
任务栏背景亮度波动 ≤2 级（等于纹丝不动）：
  - SetWindowCompositionAttribute：AccentState 1/2/3/4/5 × alpha 0~255
  - DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE = 2/3/4)：HRESULT=0 但无变化
  - 注册表 TaskbarAcrylicOpacity：重启 explorer 后依然无变化
  - 对 XAML 子窗口 DesktopWindowContentBridge 单独贴 accent
TranslucentTB 能做到「背景透明 + 图标清晰」，是因为它注入 explorer 进程后在内部
改渲染（Detour + SetWindowsHookEx），不是外部 API 调用；纯 Python 无法复刻。

所以本后端在 Win11 上只提供一种真实可控的手段：
  WS_EX_LAYERED + SetLayeredWindowAttributes —— 整窗不透明度。
代价：图标与文字会跟着等比变淡，这是整窗合成的物理结果，不是 bug。

Win10（build < 22000）上 AccentPolicy 的 alpha 仍然有效，走 accent 分支，
可以做到「背景透、图标清晰」；Win11 才被迫退回整窗方案。

流程：
  1. 确保「设置 → 个性化 → 颜色 → 透明效果」是开的（EnableTransparency=1）
  2. FindWindow("Shell_TrayWnd") 拿主任务栏，再枚举 Shell_SecondaryTrayWnd 拿副屏
  3. Win11：设 layered 不透明度；Win10：下发 ACCENT_POLICY 的 alpha
  4. 资源管理器重启后窗口句柄会变，定期复查句柄，变了就重新贴
"""

import ctypes
import sys
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
        """资源管理器重启会换句柄，另外它自己也可能把 layered 标志冲掉。"""
        if not IS_WINDOWS:
            return
        hwnds = tuple(_taskbars())
        if hwnds != self._last_hwnds:
            self.apply_glass()
            return
        # 句柄没变但 layered 位没了（explorer 重绘/主题切换），补一次
        for h in hwnds:
            try:
                if not (_get_exstyle(h) & WS_EX_LAYERED):
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
        """还原系统外观：任务栏回满不透明、摘掉 layered，再把「透明效果」写回原值。"""
        for h, ex in list(self._ex_style.items()):
            _clear_opacity(h, ex)
        self._ex_style.clear()

        for h in _taskbars():
            try:
                # 没记录过的残留（上次异常退出留下的 layered）也一并清掉，
                # 否则任务栏会一直挂着一个"不透明的分层窗口"状态。
                ex = _get_exstyle(h)
                if ex & WS_EX_LAYERED:
                    _clear_opacity(h, ex & ~WS_EX_LAYERED)
            except Exception:
                pass
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
