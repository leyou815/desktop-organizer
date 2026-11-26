#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桌面整理 —— 命令行

  zhengli                启动（默认进托盘）
  zhengli show           唤出主窗口
  zhengli tidy           一键整理（已在运行就交给它，否则直接整理）
  zhengli scan           预览：哪些文件会被归到哪（不移动）
  zhengli undo           撤销上一次操作（整理或批量改动）
  zhengli stat           分类统计
  zhengli snip           截图（没在跑就单开一个截图器）
  zhengli pin            把剪贴板里的图钉到屏幕上
  zhengli snipcopy       截图并直接复制
  zhengli snipkeys on|off 截图快捷键总开关（关掉后 F1/F2/F3 归还给其它程序）
  zhengli panel 55       任务栏透明度设为 55%
  zhengli autohide on   任务栏自动隐藏（仅 Windows，图标零损失）
  zhengli glass on|off   玻璃质感开关
  zhengli diagnose       环境诊断
  zhengli autostart on|off
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bulkops
import config as appcfg
import rules
import sysenv
from organizer import Organizer
from panel_core import get_backend, PanelError, PRESETS
from version import VERSION


def _ctx():
    cfg = appcfg.load()
    return cfg, Organizer(cfg=cfg), get_backend(cfg)


def cmd_scan():
    cfg, org, _ = _ctx()
    # 和 tidy 用同一套口径（含 min_age）：预览项数必须等于真整理会搬的项数，
    # 否则"预览有 3 项、点整理只搬走 2 项"会让用户以为程序漏了东西。
    pend = org.scan_pending()
    if not pend:
        print("桌面很干净，没有需要归类的文件。")
        return 0
    print("待归类 %d 项（只是预览，没有移动任何东西）：\n" % len(pend))
    for src, cat, sub in pend:
        print("  %-46s → %s" % (os.path.basename(src), (cat + "/" + sub).rstrip("/")))
    min_age = cfg["general"].get("min_age", "3")
    roots = sysenv.desktop_dirs(include_public=appcfg.flag(cfg, "public_desktop"))
    print("\n口径：%s 秒内刚写过的文件跳过；扫描 %d 个桌面目录%s"
          % (min_age, len(roots), "（含公共桌面）" if len(roots) > 1 else ""))
    print("执行整理：zhengli tidy")
    return 0


def cmd_tidy():
    if _send("tidy"):
        print("已交给正在运行的「桌面整理」处理")
        return 0
    cfg, org, _ = _ctx()
    moved = org.apply()
    if not moved:
        print("桌面上没有需要归类的文件。")
        return 0
    print("已整理 %d 项：" % len(moved))
    for src, dst in moved:
        print("  %-40s → %s" % (os.path.basename(src), os.path.relpath(dst, org.root)))
    print("\n反悔了：zhengli undo")
    return 0


def cmd_snip():
    if _send("snip"):
        print("已交给正在运行的「桌面整理」")
        return 0
    # 托盘没起：自己跑一个最小的截图器，不依赖主程序
    try:
        from PyQt5.QtWidgets import QApplication
    except ImportError:
        print("缺少 python3-pyqt5，无法截图")
        return 2
    import snip as snipmod
    import ui_snip
    from theme import Palette, system_is_dark

    qapp = QApplication.instance() or QApplication(sys.argv)
    canvas, virt = snipmod.grab_virtual()
    if canvas is None:
        print("抓屏失败：拿不到屏幕内容")
        return 2
    cfg = appcfg.load()
    ov = ui_snip.SnipOverlay(canvas, virt, qapp.primaryScreen(),
                             Palette(system_is_dark()), cfg)

    def _done(pixmap, action):
        if pixmap is not None and not pixmap.isNull() and action != "cancel":
            if action in ("copy", "pin") or appcfg.flag(cfg, "snip_copy"):
                snipmod.to_clipboard(pixmap)
            if action == "save" or appcfg.flag(cfg, "snip_save"):
                path = snipmod.save(pixmap, snipmod.next_path(
                    cfg["general"].get("snip_dir") or None))
                if path:
                    print("已保存 %s" % path)
        qapp.quit()

    ov.done.connect(_done)
    ov.start()
    qapp.exec_()
    return 0


def cmd_snipcopy():
    if _send("snip-copy"):
        print("已交给正在运行的「桌面整理」")
        return 0
    print("截图并复制需要主程序在跑，先执行：zhengli")
    return 1


def cmd_snipkeys(state):
    on = state == "on"
    cfg = appcfg.load()
    appcfg.set_flag(cfg, "snip_hotkeys_on", on)
    appcfg.save(cfg)
    # 已经在跑就让那边的实例重新注册一遍，本进程改配置没用
    if _send("reboot-hotkeys"):
        print("已交给正在运行的「桌面整理」处理")
    if on:
        g = cfg["general"]
        print("截图快捷键已开启：%s 截图 / %s 截图并复制 / %s 固定尺寸 / %s 贴图 / %s 隐藏贴图"
              % (g.get("snip_hotkey"), g.get("snip_copy_hotkey"),
                 g.get("snip_fixed_hotkey"), g.get("pin_hotkey"),
                 g.get("pin_toggle_hotkey")))
    else:
        print("已关闭截图快捷键，F1/F2/F3 归还给其它程序（托盘菜单和主窗口按钮仍可截图）")
    return 0


def cmd_pin():
    if _send("pin"):
        print("已交给正在运行的「桌面整理」")
        return 0
    print("贴图需要主程序在跑，先执行：zhengli")
    return 1


def cmd_undo():
    if _send("undo"):
        print("已交给正在运行的「桌面整理」处理")
        return 0
    _, org, _ = _ctx()
    # 整理和批量删除/移动/改名共用这一个撤销入口
    _, msg = bulkops.undo_latest(org, bulkops.BulkOps(org), appcfg.LOG_FILE)
    print(msg or "没有可撤销的记录")
    return 0


def cmd_stat():
    _, org, pnl = _ctx()
    data = org.summary()
    print("桌面：      %s" % org.desktop)
    print("归档位置：  %s" % org.root)
    print("任务栏：    %d%%  ·  磨砂%s  ·  %s\n"
          % (int(pnl.get_alpha() * 100),
             {1: "低", 2: "中", 3: "高"}.get(pnl.blur_level(), "?"),
             "玻璃质感开" if pnl.glass_on() else "玻璃质感关"))
    for cat in rules.CATEGORY_ORDER:
        n = rules.count_items(cat, data.get(cat, []))
        print("  %-6s %3d %s" % (cat, n, "" if n else "（空）"))
    print("\n待整理：%d 项" % org.pending_count())
    return 0


def cmd_panel(value):
    cfg, _, pnl = _ctx()
    # 自动隐藏和整窗淡出互斥：命令行显式设了透明度，就理解为要回淡出模式，
    # 否则写进去的数值会被 autohide 模式直接忽略，看起来像"设了没反应"。
    try:
        if pnl.taskbar_mode() != pnl.MODE_FADE:
            pnl.set_taskbar_mode(pnl.MODE_FADE)
    except Exception:
        pass
    try:
        v = pnl.set_alpha(float(value) / 100.0)
    except PanelError as e:
        print("设置失败：%s" % e)
        return 2
    appcfg.save(cfg)
    cap = pnl.max_alpha()
    print("任务栏透明度 %d%%%s" % (int(v * 100),
                                "（上限 %d%%）" % int(round(cap * 100))
                                if cap < 1.0 else ""))
    return 0


def cmd_autohide(value):
    """切换任务栏形态。Windows 上这是唯一能做到"图标零损失"的办法。"""
    cfg, _, pnl = _ctx()
    if not pnl.supports_autohide():
        print("当前平台没有这个选项（麒麟用 panel 命令直接调透明度）")
        return 2
    pnl.set_taskbar_mode(pnl.MODE_AUTOHIDE if value == "on" else pnl.MODE_FADE)
    appcfg.save(cfg)
    if value == "on":
        print("任务栏已设为自动隐藏（鼠标碰底边才出来）")
    else:
        print("任务栏恢复常驻，透明度 %d%%" % int(round(pnl.get_alpha() * 100)))
    return 0


def cmd_glass(state):
    cfg, _, pnl = _ctx()
    on = state == "on"
    pnl.set_glass(on)
    appcfg.save(cfg)
    try:
        if on:
            pnl.apply_glass()
    except PanelError as e:
        print("写入失败：%s" % e)
        return 2
    print("玻璃质感已%s" % ("开启" if on else "关闭"))
    return 0


def cmd_diagnose():
    cfg, org, pnl = _ctx()
    print("== 桌面整理 %s ==" % VERSION)
    print("桌面目录    %s" % org.desktop)
    print("归档目录    %s" % org.root)
    print("-- 任务栏 --")
    for k, v in pnl.info().items():
        print("  %-8s %s" % (k, v))
    print("-- 文件 --")
    print("  待整理   %d" % org.pending_count())
    print("  已归档   %d" % org.total())
    # last_batch_info 返回的是 (批次号, 条数) 元组：不能直接塞进 % 里（会被当成多个参数）
    info = org.last_batch_info()
    print("  最近批次 %s" % ("%s（%d 项）" % info if info else "无"))
    print("-- 其它 --")
    print("  自启     %s" % ("开" if sysenv.autostart_on() else "关"))
    print("  公共桌面 %s" % ("已纳入整理" if appcfg.flag(cfg, "public_desktop")
                            else "未纳入（设置里可打开）"))
    return 0


def cmd_autostart(state):
    on = state == "on"
    entry = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cli.py")
    if sysenv.set_autostart(on, sysenv.startup_command(entry)):
        print("已开启开机自启" if on else "已关闭开机自启")
        return 0
    print("设置失败：%s" % ("注册表写入被拒绝" if sysenv.IS_WINDOWS else "写 autostart 目录失败"))
    return 2


def _send(cmd):
    from app import send_to_existing
    return send_to_existing(cmd)


def main(argv):
    p = argparse.ArgumentParser(prog="zhengli", description="桌面整理")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("run", help="启动（默认进托盘）")
    sub.add_parser("show", help="唤出主窗口")
    sub.add_parser("tidy", help="一键整理")
    sub.add_parser("scan", help="预览归类结果")
    sub.add_parser("undo", help="撤销上一次操作（整理或批量改动）")
    sub.add_parser("snip", help="截图")
    sub.add_parser("pin", help="贴图剪贴板")
    sub.add_parser("snipcopy", help="截图并直接复制")
    sp = sub.add_parser("snipkeys", help="截图快捷键总开关 on/off")
    sp.add_argument("state", choices=["on", "off"])
    sub.add_parser("stat", help="统计")
    sub.add_parser("diagnose", help="环境诊断")
    sp = sub.add_parser("panel", help="设置任务栏透明度（0-100）")
    sp.add_argument("value", type=float)
    sp = sub.add_parser("autohide", help="任务栏自动隐藏 on/off（仅 Windows）")
    sp.add_argument("state", choices=["on", "off"])
    sp = sub.add_parser("glass", help="玻璃质感 on/off")
    sp.add_argument("state", choices=["on", "off"])
    sp = sub.add_parser("autostart", help="开机自启 on/off")
    sp.add_argument("state", choices=["on", "off"])

    args = p.parse_args(argv)

    if args.cmd in (None, "run"):
        from app import run
        return run([])
    if args.cmd == "show":
        if _send("win"):
            return 0
        from app import run
        return run(["--window"])
    if args.cmd == "tidy":
        return cmd_tidy()
    if args.cmd == "scan":
        return cmd_scan()
    if args.cmd == "undo":
        return cmd_undo()
    if args.cmd == "snip":
        return cmd_snip()
    if args.cmd == "pin":
        return cmd_pin()
    if args.cmd == "snipcopy":
        return cmd_snipcopy()
    if args.cmd == "snipkeys":
        return cmd_snipkeys(args.state)
    if args.cmd == "stat":
        return cmd_stat()
    if args.cmd == "panel":
        return cmd_panel(args.value)
    if args.cmd == "autohide":
        return cmd_autohide(args.state)
    if args.cmd == "glass":
        return cmd_glass(args.state)
    if args.cmd == "diagnose":
        return cmd_diagnose()
    if args.cmd == "autostart":
        return cmd_autostart(args.state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
