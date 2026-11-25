#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— 启动器解析

桌面图标背后是什么，两个系统不一样：
  麒麟   .desktop 文本文件（Name[zh_CN] / Icon / Exec），用 Gio.DesktopAppInfo 启动
  Windows .lnk 二进制快捷方式 / .url 网页链接，用 os.startfile 启动

共同点：都能"搬到别处照样能用"——.lnk 记的是目标绝对路径，跟自己在哪无关。
"""

import os
import shlex
import subprocess
import sys

import sysenv

try:
    from gi.repository import Gio   # noqa
    _HAS_GIO = True
except Exception:
    _HAS_GIO = False

LOCALE_KEYS = ("Name[zh_CN]", "Name[zh_CN.UTF-8]", "Name[zh]", "Name")

# 系统图标（此电脑 / 回收站 / 主目录）：由平台层提供，两个系统各有一套
VIRTUAL = sysenv.VIRTUAL
open_uri = sysenv.open_virtual
virtual_hidden = sysenv.virtual_hidden
set_virtual_hidden = sysenv.set_virtual_hidden


class Launcher(object):
    __slots__ = ("path", "name", "icon", "terminal", "exec_line", "ok")

    def __init__(self, path, name, icon, terminal=False, exec_line="", ok=True):
        self.path = path
        self.name = name
        self.icon = icon
        self.terminal = terminal
        self.exec_line = exec_line
        self.ok = ok


# --------------------------------------------------------------------------- #
# .desktop（麒麟）
# --------------------------------------------------------------------------- #
def _read_fields(path):
    """按 .desktop 规范只取 [Desktop Entry] 段。"""
    fields = {}
    in_main = False
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if line.startswith("["):
                    in_main = (line.strip() == "[Desktop Entry]")
                    continue
                if not in_main or "=" not in line or line.lstrip().startswith("#"):
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                if k not in fields:          # 同名键保留第一处
                    fields[k] = v.strip()
    except OSError:
        return {}
    return fields


def _parse_desktop(path):
    f = _read_fields(path)
    if not f:
        return Launcher(path, os.path.basename(path), "", ok=False)

    name = ""
    for k in LOCALE_KEYS:
        if f.get(k):
            name = f[k]
            break
    if not name:
        name = os.path.splitext(os.path.basename(path))[0]

    return Launcher(path=path, name=name, icon=f.get("Icon", ""),
                    terminal=f.get("Terminal", "false").lower() == "true",
                    exec_line=f.get("Exec", ""))


# --------------------------------------------------------------------------- #
# .lnk / .url（Windows）
# --------------------------------------------------------------------------- #
def _parse_windows(path):
    """Windows 快捷方式：显示名就是文件名（微信.lnk → 微信），图标交给外壳。

    不解 IShellLink：取目标路径只对"显示目标"有用，启动和图标都不需要，
    为了少一个依赖（pywin32）就不解析了。
    """
    base = os.path.basename(path)
    name = os.path.splitext(base)[0] or base
    return Launcher(path=path, name=name, icon="")


def parse(path):
    if sysenv.IS_WINDOWS:
        return _parse_windows(path)
    return _parse_desktop(path)


# --------------------------------------------------------------------------- #
# 启动
# --------------------------------------------------------------------------- #
def launch(path):
    """启动一个快捷方式。返回 (成功?, 错误信息)。"""
    if sysenv.IS_WINDOWS:
        try:
            os.startfile(path)          # noqa: S606
            return True, ""
        except Exception as e:
            return False, "启动失败：%s" % e

    if _HAS_GIO:
        try:
            app = Gio.DesktopAppInfo.new_from_filename(path)
            if app is not None:
                app.launch([], None)
                return True, ""
            err = "无法解析该 .desktop"
        except Exception as e:
            err = str(e)
    else:
        err = "未安装 python3-gi"

    launcher = parse(path)
    cmd = launcher.exec_line
    if not cmd:
        return False, err
    for ph in ("%U", "%u", "%F", "%f", "%i", "%c", "%k"):
        cmd = cmd.replace(ph, "")
    parts = shlex.split(cmd.strip())
    if not parts:
        return False, err
    try:
        subprocess.Popen(parts, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, ""
    except OSError as e:
        return False, "启动失败：%s" % e


# 兼容旧调用
def gsettings_get(key):
    return None
