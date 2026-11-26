#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— 任务栏透明度模块（含"玻璃质感常驻"）

实测结论（Kylin V10 SP1 / ukui-panel 3.25 / ukui-kwin）：
  * 任务栏背景 alpha 唯一来源：org.ukui.control-center.personalise:transparency
    写入后实时生效，不需要重启任务栏（QML 里 themePal.styleColorChanged 已连到 updateColor）
  * 磨砂强度：personalise:blurry（1 低 / 2 中 / 3 高），即"毛玻璃效果"本身
  * 全局模糊：org.ukui.style:enabled-global-blur，关掉就只剩半透明，没有磨砂
  * 特效总开关：personalise:effect，关掉后上述都不生效

所以"不管透明度多少都是玻璃质感"不能只靠调 transparency，必须三件事一起保证：
  1. effect = true、enabled-global-blur = true、blurry = 用户档位
  2. 透明度上限压到 0.92 —— 到 100% 就是一块实心色块，玻璃感会消失
"""

import os
import subprocess
import time

import sysenv

GSETTINGS = "/usr/bin/gsettings"

SCHEMA_P = "org.ukui.control-center.personalise"
KEY_TRANS = "transparency"
KEY_BLURRY = "blurry"
KEY_EFFECT = "effect"

SCHEMA_S = "org.ukui.style"
KEY_MENU = "menu-transparency"
KEY_SIDEBAR = "peony-side-bar-transparency"
KEY_GBLUR = "enabled-global-blur"

# 玻璃质感开启时，透明度不允许到 100%：留一点透光，磨砂才有东西可"磨"
GLASS_MAX_ALPHA = 0.92

# 预设：名字按"材质"给，不按百分比，用户更好理解
PRESETS = [
    ("mist", "浓雾", 0.90),
    ("frost", "磨砂", 0.72),
    ("glass", "玻璃", 0.52),
    ("clear", "通透", 0.28),
]

BLUR_NAMES = {1: "低", 2: "中", 3: "高"}


class PanelError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# gsettings 读写
# --------------------------------------------------------------------------- #
def _run(args, check=True):
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=8)
    except (OSError, subprocess.SubprocessError) as e:
        raise PanelError("无法执行 %s：%s" % (args[0], e))
    if check and p.returncode != 0:
        raise PanelError((p.stderr or p.stdout or "").strip() or "命令执行失败")
    return p.stdout.strip()


def _gget(schema, key, default=None):
    try:
        return _run([GSETTINGS, "get", schema, key])
    except PanelError:
        return default


def _gset(schema, key, value):
    """dconf 提交失败时 gsettings 仍返回 0，只在 stderr 警告 —— 必须显式检查。"""
    p = subprocess.run([GSETTINGS, "set", schema, key, str(value)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True, timeout=8)
    err = p.stderr or ""
    if p.returncode != 0 or "failed to commit" in err or "dconf-WARNING" in err:
        raise PanelError("写入系统设置失败（dconf 提交被拒绝）。"
                         "请确认在正常桌面会话中运行。原始信息：%s"
                         % (err.strip() or "unknown"))


def _unquote(raw):
    return raw.strip().strip("'\"") if raw else None


def schema_ok():
    try:
        return SCHEMA_P in set(_run([GSETTINGS, "list-schemas"]).split())
    except PanelError:
        return False


# --------------------------------------------------------------------------- #
# 面板后端
# --------------------------------------------------------------------------- #
class PanelCore(object):
    BACKUP_KEY = "panel_kylin"      # 系统设置原值台账里的分类名

    def __init__(self, cfg):
        self.cfg = cfg          # 与主程序共用的 configparser
        self._backed_up = False

    # -- 原值备份 -----------------------------------------------------------
    def _keys(self):
        return ((SCHEMA_P, KEY_TRANS), (SCHEMA_P, KEY_BLURRY),
                (SCHEMA_P, KEY_EFFECT), (SCHEMA_P, KEY_MENU),
                (SCHEMA_S, KEY_GBLUR), (SCHEMA_S, KEY_SIDEBAR))

    def _backup_once(self):
        """第一次动系统设置前把原值记下来，之后 restore 才有东西可还原。

        只记一次：反复拖动滑块不会把"用户原来的值"覆盖成"我们上次改的值"。
        """
        if self._backed_up:
            return
        vals = {}
        for s, k in self._keys():
            vals["%s|%s" % (s, k)] = _gget(s, k)    # None = 当时读不到，还原时不动它
        sysenv.remember_system(self.BACKUP_KEY, vals)
        self._backed_up = True

    # -- 能力 ---------------------------------------------------------------
    def supports_blur_level(self):
        return True          # 麒麟：personalise:blurry 有 低/中/高 三档

    def info(self):
        return {
            "可用": schema_ok(),
            "透明度": self.get_alpha(),
            "磨砂强度": _unquote(_gget(SCHEMA_P, KEY_BLURRY)),
            "特效": _unquote(_gget(SCHEMA_P, KEY_EFFECT)),
            "全局模糊": _unquote(_gget(SCHEMA_S, KEY_GBLUR)),
            "任务栏": self._pkg("ukui-panel"),
            "合成器": self._compositor(),
        }

    @staticmethod
    def _pkg(name):
        for exe in ("/usr/bin/dpkg-query", "/bin/dpkg-query"):
            if os.path.isfile(exe):
                try:
                    return _run([exe, "-W", "-f=${Version}", name], check=False) or "未知"
                except PanelError:
                    break
        return "未知"

    @staticmethod
    def _compositor():
        for name in ("ukui-kwin_x11", "ukui-kwin_wayland", "kwin_x11", "picom"):
            for d in os.environ.get("PATH", "").split(":"):
                p = os.path.join(d, name)
                if not os.path.isfile(p):
                    continue
                try:
                    running = _run(["pgrep", "-f", os.path.basename(p)], check=False)
                except PanelError:
                    running = ""
                return name + ("（运行中）" if running else "（已安装，未见进程）")
        return "未检测到（透明可能不生效）"

    def probe_write(self):
        """探一次写权限：把当前值原样写回，不改效果。"""
        _gset(SCHEMA_P, KEY_TRANS, "%.3f" % self.get_alpha())

    # -- 透明度 -------------------------------------------------------------
    def glass_on(self):
        return self.cfg["general"].get("glass", "1") == "1"

    def max_alpha(self):
        return GLASS_MAX_ALPHA if self.glass_on() else 1.0

    def get_alpha(self):
        raw = _unquote(_gget(SCHEMA_P, KEY_TRANS))
        try:
            return max(0.0, min(1.0, float(raw)))
        except (TypeError, ValueError):
            return 0.6

    def set_alpha(self, value, smooth=False, sync_glass=False):
        """写任务栏透明度。

        注意：这里默认 **不再** 顺带重放 apply_glass()——玻璃那三项（特效/全局模糊/
        磨砂档位）跟透明度是两件事，每拖一格都重写一遍等于把 gsettings 子进程
        放大三倍。需要联动玻璃的场景（比如切档位、开玻璃）请显式传 sync_glass=True。
        """
        value = max(0.0, min(self.max_alpha(), float(value)))
        self._backup_once()
        if smooth:
            start = self.get_alpha()
            if abs(value - start) > 0.01:
                for i in range(1, 11):
                    _gset(SCHEMA_P, KEY_TRANS, "%.3f" % (start + (value - start) * i / 10.0))
                    time.sleep(0.018)
        else:
            _gset(SCHEMA_P, KEY_TRANS, "%.3f" % value)

        actual = self.get_alpha()
        if abs(actual - value) > 0.03:
            raise PanelError("设置未生效（期望 %.2f，实际 %.2f）" % (value, actual))

        self.cfg["general"]["alpha"] = "%.3f" % value
        if sync_glass:
            self.apply_glass()
        return value

    # -- 玻璃质感 -----------------------------------------------------------
    def apply_glass(self):
        """让磨砂一直在：特效开、全局模糊开、强度按档位。

        这三项任一关掉，任务栏就只是"半透明色块"，没有玻璃质感。
        """
        if not self.glass_on():
            return
        level = self.blur_level()
        _gset(SCHEMA_P, KEY_EFFECT, "true")
        _gset(SCHEMA_S, KEY_GBLUR, "true")
        _gset(SCHEMA_P, KEY_BLURRY, level)
        # 已经把透明度拉到上限之外的，收回来
        cur = self.get_alpha()
        if cur > GLASS_MAX_ALPHA:
            _gset(SCHEMA_P, KEY_TRANS, "%.3f" % GLASS_MAX_ALPHA)

    def blur_level(self):
        try:
            v = int(self.cfg["general"].get("blur_level", "3"))
        except ValueError:
            v = 3
        return v if v in (1, 2, 3) else 3

    def set_blur_level(self, level):
        level = int(level)
        if level not in (1, 2, 3):
            return
        self.cfg["general"]["blur_level"] = str(level)
        if self.glass_on():
            self._backup_once()
            _gset(SCHEMA_P, KEY_BLURRY, level)
            _gset(SCHEMA_S, KEY_GBLUR, "true")
            _gset(SCHEMA_P, KEY_EFFECT, "true")

    def set_glass(self, on):
        self.cfg["general"]["glass"] = "1" if on else "0"
        if on:
            self.apply_glass()
        # 关掉时不动系统设置，只是不再强制

    # -- 弹窗保护 -----------------------------------------------------------
    def pin_popups(self):
        """任务栏变透时，把菜单/侧边栏钉在系统默认的 72，保持可读。"""
        if self.cfg["general"].get("protect_popup", "1") != "1":
            return
        self._backup_once()
        _gset(SCHEMA_S, KEY_MENU, 72)
        try:
            keys = set(_run([GSETTINGS, "list-keys", SCHEMA_S]).split())
        except PanelError:
            keys = set()
        if KEY_SIDEBAR in keys:
            _gset(SCHEMA_S, KEY_SIDEBAR, 72)

    # -- 备份还原 -----------------------------------------------------------
    def restore(self):
        """还原系统外观：优先写回用户原来的值，而不是一律 reset 成系统默认。"""
        saved = sysenv.recall_system(self.BACKUP_KEY)
        if not saved:
            # 没留下原值记录（历史版本改过、或上次还原后记录已清），只能踩回系统默认
            for s, k in ((SCHEMA_P, KEY_TRANS), (SCHEMA_P, KEY_BLURRY),
                         (SCHEMA_P, KEY_EFFECT), (SCHEMA_S, KEY_MENU),
                         (SCHEMA_S, KEY_GBLUR)):
                _run([GSETTINGS, "reset", s, k], check=False)
            return True
        ok = True
        for name, raw in saved.items():
            s, _, k = name.partition("|")
            if not s or not k:
                continue
            try:
                if raw is None:
                    _run([GSETTINGS, "reset", s, k], check=False)
                else:
                    _gset(s, k, raw)
            except PanelError:
                ok = False
        if ok:
            sysenv.forget_system(self.BACKUP_KEY)
            self._backed_up = False
        return ok


def get_backend(cfg):
    """按平台选任务栏后端：麒麟走 gsettings，Windows 走亚克力 API。"""
    if sysenv.IS_WINDOWS:
        from panel_win import PanelWin
        return PanelWin(cfg)
    return PanelCore(cfg)


def preset_value(key):
    for k, _, v in PRESETS:
        if k == key:
            return v
    return None
