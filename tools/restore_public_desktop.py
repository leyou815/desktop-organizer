#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性修复：把被搬进抽屉的「公共桌面」快捷方式搬回 C:\\Users\\Public\\Desktop

背景：早期版本把 C:\\Users\\Public\\Desktop（公共桌面）也纳入了整理。那个目录是
系统级目录，普通权限往往**删得掉、写不回**，于是出现"搬得进去、撤不回来"。
新版本已默认不再碰它（设置里可显式打开，且搬运前会探写权限），
这个脚本只负责把已经搬走的那批放回原位。

用法：
    python tools/restore_public_desktop.py           # 预演：只列出会搬哪些
    python tools/restore_public_desktop.py --yes     # 真的搬（权限不够会自动请求管理员）

搬完确认桌面图标回来了，这个文件和同目录的 .bat 都可以删掉。
"""

import ctypes
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "app"))

import rules      # noqa: E402
import sysenv     # noqa: E402

# 被误搬走的那批（按文件名写死，避免把用户自己整理进抽屉的快捷方式也扫进去）
NAMES = [
    "Access", "Bandizip", "Excel", "HiBit Uninstaller", "NVIDIA App",
    "OBS Studio", "OneNote", "PowerPoint", "QQ", "QQ音乐", "ToDesk", "Word",
    "iSlide", "分区助手 10.7.0", "向日葵远程控制", "夸克", "微信",
    "提示词大师", "火绒安全软件", "百度网盘",
]


def shelf_apps():
    return os.path.join(sysenv.desktop_dir(), rules.SHELF_DIRNAME, rules.APP)


def plan():
    src_dir = shelf_apps()
    pub = sysenv.public_desktop_dir()
    out = []
    for name in NAMES:
        src = os.path.join(src_dir, name + ".lnk")
        if os.path.isfile(src):
            out.append((src, os.path.join(pub, name + ".lnk")))
    return out, pub


def writable(path):
    try:
        fd, probe = tempfile.mkstemp(prefix=".do-probe-", dir=path)
        os.close(fd)
        os.remove(probe)
        return True
    except OSError:
        return False


def elevate():
    """写不进去就请求一次管理员权限重跑自己（UAC 弹窗）。"""
    try:
        params = '"%s" --yes --elevated' % os.path.abspath(__file__)
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        return rc > 32
    except Exception:
        return False


def main(argv):
    yes = "--yes" in argv
    elevated = "--elevated" in argv

    pairs, pub = plan()
    print("== 公共桌面快捷方式还原 ==")
    print("   抽屉：%s" % shelf_apps())
    print("   目标：%s" % pub)
    print()

    if not pairs:
        print("抽屉里没找到这批快捷方式——可能已经还原过了，无需处理。")
        return 0

    print("待还原 %d 项：" % len(pairs))
    for src, dst in pairs:
        print("   %-24s -> %s" % (os.path.basename(src), "已存在，将跳过"
                                  if os.path.exists(dst) else "搬回"))
    print()

    if not yes:
        print("这是预演，没有移动任何文件。确认无误后执行：")
        print("    python tools/restore_public_desktop.py --yes")
        return 0

    if not writable(pub):
        if elevated:
            print("即使提权后仍无法写入 %s，请手动把抽屉里的 .lnk 拖回公共桌面。" % pub)
            return 2
        print("当前权限不允许写入公共桌面，正在请求管理员权限……")
        if elevate():
            print("已在新窗口里以管理员身份继续，请在弹出的窗口里确认结果。")
            return 0
        print("提权被取消。可以：右键用「以管理员身份运行」打开终端，再执行本命令。")
        return 2

    ok, skip, bad = 0, 0, []
    for src, dst in pairs:
        if os.path.exists(dst):
            skip += 1
            continue
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            ok += 1
        except Exception as e:
            bad.append((os.path.basename(src), "%s" % e))

    print("搬回 %d 项，已存在跳过 %d 项，失败 %d 项" % (ok, skip, len(bad)))
    for name, why in bad:
        print("   %s：%s" % (name, why))
    if not bad:
        print("\n完成。桌面图标应该已经回来了（资源管理器可能需要按 F5 刷新）。")
        print("确认无误后可以删掉 tools/restore_public_desktop.py 和 .bat。")
    return 0 if not bad else 1


if __name__ == "__main__":
    if not sysenv.IS_WINDOWS:
        print("这个脚本只用于 Windows。")
        sys.exit(1)
    sys.exit(main(sys.argv[1:]))
