#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— 原子写 + 系统设置原值台账

两件事在这里，都是"别把用户的东西弄丢"的底座：
  1. atomic_write_text  先写同目录 .tmp 再 os.replace，断电不会留下半截文件
  2. 系统设置原值台账   改注册表 / gsettings 之前先记原值，restore 才还原得回去

台账放在配置目录下的 system_state.json，只记"第一次改动前"的原值：
反复开关不会把用户本来的设置冲成我们改过的值。
"""

import json
import os

import sysenv

STATE_NAME = "system_state.json"

# 归档层级是「桌面/.桌面抽屉/文档/Word/xxx.docx」，用户文件名再长一点就顶到
# MAX_PATH 260；留 10 个字符给 "(12)" 这类重名后缀。
LONG_PATH_LIMIT = 249


def state_file():
    return os.path.join(sysenv.config_dir(), STATE_NAME)


def win_long(path):
    """Windows 长路径：超限时加 \\\\?\\ 前缀，绕开 MAX_PATH 260 的限制。

    非 Windows 或本就带前缀的原样返回，调用方可以无脑套一层。
    """
    if os.name != "nt":
        return path
    try:
        p = os.path.abspath(path)
    except (OSError, ValueError):
        return path
    if p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):              # UNC：\\server\share\...
        return "\\\\?\\UNC\\" + p[2:]
    if len(p) <= LONG_PATH_LIMIT:
        return p
    return "\\\\?\\" + p


def atomic_write_text(path, text):
    """原子写文本：先写同目录的 .tmp，再 os.replace 顶上。返回是否成功。"""
    d = os.path.dirname(path)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        if d:
            os.makedirs(d, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


# 撤销日志是只追加的（.jsonl），用久了会一路长到几十 MB：
# 启动、刷新托盘、打开抽屉都要读全量，越用越慢。超过阈值就裁掉老记录。
LOG_KEEP_LINES = 4000
LOG_MAX_BYTES = 2 * 1024 * 1024


def trim_jsonl(path, keep=LOG_KEEP_LINES, max_bytes=LOG_MAX_BYTES):
    """日志过大时只保留最近 keep 条，返回是否真的重写过。

    裁掉的都是很老的批次——它们对应的文件早就不在归档位置，
    撤销也只会得到"已不存在，跳过"，所以裁掉不损失可用功能。
    用 atomic_write_text 落地：裁一半崩了也不会把日志截断成半截。
    """
    try:
        if os.path.getsize(path) <= max_bytes:
            return False
        with open(path, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
    except OSError:
        return False
    if len(lines) <= keep:
        return False
    return atomic_write_text(path, "".join(lines[-keep:]))


def _load_state():
    path = state_file()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(data):
    return atomic_write_text(state_file(), json.dumps(data, ensure_ascii=False, indent=2))


def remember_system(kind, values):
    """记下某类系统设置的原值。

    已经有记录就沿用第一次那份（不覆盖），这样重复开关/重复启动都还原得回去。
    值为 None 的项表示"当时读不到"，不记，restore 时也就不动它。
    """
    clean = dict((k, v) for k, v in dict(values or {}).items() if v is not None)
    if not clean:
        return {}
    data = _load_state()
    if isinstance(data.get(kind), dict) and data[kind]:
        return data[kind]
    data[kind] = clean
    _save_state(data)
    return clean


def recall_system(kind):
    """取回当初记下的原值；没有记录时返回空 dict。"""
    val = _load_state().get(kind)
    return val if isinstance(val, dict) else {}


def forget_system(kind):
    """还原完成之后清掉记录，下次改动重新记一次新的原值。"""
    data = _load_state()
    if data.pop(kind, None) is not None:
        _save_state(data)
