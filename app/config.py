#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桌面整理 —— 统一配置（两个模块共用一份 config.ini）"""

import configparser
import os

import atomicio
import sysenv

CONFIG_DIR = sysenv.config_dir()
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.ini")
LOG_FILE = os.path.join(CONFIG_DIR, "moves.jsonl")

DEFAULTS = {
    # 任务栏
    "alpha": "0.600",
    "glass": "1",             # 玻璃质感常驻
    "blur_level": "3",        # 磨砂强度 1/2/3
    "protect_popup": "1",     # 菜单不跟着变透
    # 文件
    "auto_tidy": "0",         # 默认不自动整理，靠"一键整理"
    "min_age": "3",           # 3 秒内刚写过的文件不动
    # Windows 公共桌面（C:\Users\Public\Desktop）默认不整理：它是系统级目录，
    # 搬走会影响本机其它账号，写回权限也不一定还在（详见 sysenv.desktop_dirs）
    "public_desktop": "0",
    # 界面
    "tray_start": "1",        # 启动直接进托盘
    "show_edge": "1",         # 屏幕右侧入口条
    "hotkey": "<Ctrl><Alt>G",
    "hotkey_enabled": "1",
    # 截图（默认照 Snipaste 那套：F1 截图 / F2 截图并复制 / Shift+F1 固定尺寸 / F3 贴图 / Shift+F3 隐藏贴图）
    "snip_dir": "",                      # 空 = 自动选 ~/图片/截图
    "snip_hotkey": "F1",
    "snip_copy_hotkey": "F2",
    "snip_fixed_hotkey": "<Shift>F1",
    "pin_hotkey": "F3",
    "pin_toggle_hotkey": "<Shift>F3",
    "snip_fixed_w": "800",
    "snip_fixed_h": "600",
    # 截图热键总开关：关掉后 F1/F2/F3 还给其它程序用（浏览器 F1 帮助、F3 查找下一个）
    "snip_hotkeys_on": "1",
    "snip_copy": "1",                    # 截完自动复制到剪贴板
    "snip_save": "0",                    # 截完自动存盘
    "pin_top": "1",                      # 贴图置顶
}


def load():
    cfg = configparser.ConfigParser()
    cfg["general"] = dict(DEFAULTS)
    if os.path.isfile(CONFIG_FILE):
        try:
            cfg.read(CONFIG_FILE, encoding="utf-8")
        except (configparser.Error, OSError):
            pass
    if "general" not in cfg:
        cfg["general"] = dict(DEFAULTS)
    for k, v in DEFAULTS.items():
        if k not in cfg["general"]:
            cfg["general"][k] = v

    # 老配置（之前截图键是 Ctrl+Alt+A）迁移到 Snipaste 那套键位。
    # hotkey_scheme 只在迁移时写，用来判断"迁过了没有"。
    if "hotkey_scheme" not in cfg["general"] and os.path.isfile(CONFIG_FILE):
        cfg["general"]["snip_hotkey"] = "F1"
        cfg["general"]["snip_copy_hotkey"] = "F2"
        cfg["general"]["snip_fixed_hotkey"] = "<Shift>F1"
        cfg["general"]["pin_hotkey"] = "F3"
        cfg["general"]["pin_toggle_hotkey"] = "<Shift>F3"
        cfg["general"]["hotkey_scheme"] = "snipaste"
        save(cfg)       # 迁移结果立刻落盘，否则下次启动会反复迁移、覆盖用户改过的键位
    return cfg


def atomic_write_text(path, text):
    """原子写文本：先写同目录的 .tmp，再 os.replace 顶上。

    实现在 atomicio 里（平台层也要用，放这里会和 sysenv 形成循环导入）：
    断电/崩溃只会留下一个孤立的 .tmp，不会被截断的 config.ini 或撤销日志，
    读端永远不会读到"写了一半"的文件。返回是否成功。
    """
    return atomicio.atomic_write_text(path, text)


def save(cfg):
    import io
    buf = io.StringIO()
    cfg.write(buf)
    return atomic_write_text(CONFIG_FILE, buf.getvalue())


def get(cfg, key, default=None):
    return cfg["general"].get(key, DEFAULTS.get(key, default))


def get_int(cfg, key, default=0):
    try:
        return int(float(cfg["general"].get(key, default)))
    except (TypeError, ValueError):
        return default


def flag(cfg, key):
    return cfg["general"].get(key, DEFAULTS.get(key, "0")) == "1"


def set_flag(cfg, key, on):
    cfg["general"][key] = "1" if on else "0"
