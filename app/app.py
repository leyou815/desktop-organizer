#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— 控制器

一个进程里装三个模块：任务栏透明度、文件整理、截图贴图。
启动后进托盘（可在设置里改），托盘和主窗口是同一份状态的两种入口。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtCore import QObject, QPoint, QTimer, QFileSystemWatcher
from PyQt5.QtWidgets import (QApplication, QDialog, QSystemTrayIcon, QMenu, QAction)
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

import config as appcfg
import crashlog
import rules
import snip
import sysenv
from organizer import Organizer
from panel_core import get_backend, PRESETS, PanelError
from hotkey import HotkeySet
from theme import Palette, system_is_dark
from ui_drawer import Panel, Trigger
from ui_main import MainWindow, app_icon
from ui_snip import PinWindow, SnipOverlay

APP_NAME = "桌面整理"
SERVER_KEY = "desktop-organizer"

# 自启位置由平台层决定：麒麟写 autostart/*.desktop，Windows 写注册表 Run 项
AUTOSTART_FILE = sysenv.autostart_path()


def pretty_combo(text):
    import re
    if not text:
        return "未设置"
    tokens = [a or b for a, b in re.findall(r"<([^>]+)>|([^<]+)", text)]
    return "+".join(t.strip() for t in tokens if t.strip())


class App(QObject):
    def __init__(self, argv):
        super(App, self).__init__()
        self.cfg = appcfg.load()
        self.org = Organizer(cfg=self.cfg)
        self.panel = get_backend(self.cfg)
        self.pal = Palette(system_is_dark())
        self._panel_ok = True

        # 任务栏：先把玻璃质感摁住（特效 / 全局模糊 / 磨砂强度）
        try:
            self.panel.probe_write()
            self.panel.apply_glass()
            self.panel.pin_popups()
        except PanelError as e:
            self._panel_ok = False
            self._panel_err = str(e)

        self.win = MainWindow(self)
        self.drawer = Panel(self.org, self.pal, cfg=self.cfg,
                            on_hide=self._trigger_back, on_show=self._trigger_to_drawer)
        self.trigger = Trigger(self.pal)
        self.trigger.clicked.connect(self.toggle_drawer)
        self._tx = 0
        self._ty = 0
        self._place_trigger()

        self.pins = []                  # 贴在屏幕上的图
        self._overlay = None            # 正在进行的截图
        self._snip_busy = False
        self._busy = False          # 整理/撤销互斥闸，防止五入口重入
        self._tray_timer = None
        self._win_timer = None

        self.tray = self._build_tray()
        self.hotkeys = self._build_hotkeys()
        self.watcher = self._build_watcher()

        self.apply_edge()

        # Windows 上 explorer 重启会让任务栏句柄失效，隔几秒复查一次
        self._keep = QTimer(self)
        self._keep.setInterval(4000)
        self._keep.timeout.connect(self._keep_panel)
        self._keep.start()
        if not self._panel_ok:
            self.win.panel_status.setText("任务栏设置不可用：%s" % getattr(self, "_panel_err", ""))

    # ------------------------------------------------------------------ 入口
    def start(self, show_window=None):
        if show_window is None:
            show_window = not self.flag("tray_start")
        if show_window:
            self.show_window()
        QTimer.singleShot(300, self._refresh_all)

    def show_window(self):
        self.win.refresh()
        self.win.show()
        self.win.raise_()
        self.win.activateWindow()
        scr = QApplication.primaryScreen().availableGeometry()
        if not self.win.geometry().intersects(scr):
            self.win.move(scr.center().x() - self.win.width() // 2,
                          scr.center().y() - self.win.height() // 2)

    # ------------------------------------------------------------------ 配置
    def save_cfg(self):
        appcfg.save(self.cfg)

    def flag(self, key):
        return appcfg.flag(self.cfg, key)

    def hotkey_pretty(self):
        return pretty_combo(self.cfg["general"].get("hotkey", ""))

    # ---------------------------------------------------------------- 托盘
    def _build_tray(self):
        tray = QSystemTrayIcon(app_icon(self.pal), self)
        tray.setToolTip(APP_NAME)
        menu = QMenu()
        menu.setStyleSheet(
            "QMenu{background:%s;border:1px solid %s;padding:6px;border-radius:8px;}"
            "QMenu::item{padding:7px 24px;border-radius:5px;font-size:12.5px;color:%s;}"
            "QMenu::item:selected{background:%s;}"
            "QMenu::separator{height:1px;background:%s;margin:5px 8px;}"
            % (self.pal.card.name(), self.pal.line.name(), self.pal.text.name(),
               self.pal.card_hi.name(), self.pal.line.name()))

        on = self.snip_hotkeys_on()
        a = QAction("截图    %s" % self.snip_hotkey_pretty(), self)
        a.triggered.connect(lambda: self.start_snip())
        menu.addAction(a)

        a = QAction("截图并复制    %s" % self.snip_copy_hotkey_pretty(), self)
        a.triggered.connect(lambda: self.start_snip(auto_copy=True))
        menu.addAction(a)

        a = QAction("自定义截屏    %s" % self.snip_fixed_hotkey_pretty(), self)
        a.triggered.connect(lambda: self.start_snip(fixed=True))
        menu.addAction(a)

        a = QAction("贴图        %s" % self.pin_hotkey_pretty(), self)
        a.triggered.connect(self.pin_clipboard)
        menu.addAction(a)

        self.act_pin_toggle = QAction("隐藏/显示所有贴图    %s"
                                      % self.pin_toggle_hotkey_pretty(), self)
        self.act_pin_toggle.triggered.connect(self.toggle_pins_visible)
        menu.addAction(self.act_pin_toggle)

        menu.addSeparator()
        self.act_snip_hotkeys = QAction("启用截图快捷键", self)
        self.act_snip_hotkeys.setCheckable(True)
        self.act_snip_hotkeys.setChecked(on)
        self.act_snip_hotkeys.setToolTip("关掉后 F1/F2/F3 归还给其它程序")
        self.act_snip_hotkeys.triggered.connect(self.set_snip_hotkeys)
        menu.addAction(self.act_snip_hotkeys)

        menu.addSeparator()
        a = QAction("打开主窗口", self)
        a.triggered.connect(self.show_window)
        menu.addAction(a)

        a = QAction("打开抽屉", self)
        a.triggered.connect(self.open_drawer)
        menu.addAction(a)

        menu.addSeparator()
        self.act_tidy = QAction("一键整理", self)
        self.act_tidy.triggered.connect(lambda: self.tidy(notify=True))
        menu.addAction(self.act_tidy)

        self.act_undo = QAction("撤销上次整理", self)
        self.act_undo.triggered.connect(self._undo_from_tray)
        menu.addAction(self.act_undo)

        menu.addSeparator()
        self.act_drawer_entry = QAction("显示右侧入口条", self)
        self.act_drawer_entry.setCheckable(True)
        self.act_drawer_entry.setChecked(self.flag("show_edge"))
        self.act_drawer_entry.triggered.connect(self._toggle_edge_from_tray)
        menu.addAction(self.act_drawer_entry)

        a = QAction("退出", self)
        a.triggered.connect(self.quit)
        menu.addAction(a)

        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_click)
        tray.show()
        return tray

    def _on_tray_click(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window()

    def _rebuild_tray_state(self):
        if getattr(self, "act_snip_hotkeys", None) is not None:
            self.act_snip_hotkeys.setChecked(self.snip_hotkeys_on())
        pend = self.org.pending_count()
        self.act_tidy.setText("一键整理" + ("（%d 项）" % pend if pend else ""))
        self.act_tidy.setEnabled(pend > 0)
        last = self.org.last_batch_info()
        self.act_undo.setEnabled(bool(last))
        if self.tray:
            self.tray.setToolTip("%s · 待整理 %d 项" % (APP_NAME, pend))
        self.act_drawer_entry.setChecked(self.flag("show_edge"))

    def _undo_from_tray(self):
        n = self.undo()
        if self.tray:
            self.tray.showMessage(APP_NAME, "已放回桌面 %d 项" % n if n else "没有可撤销的记录",
                                  QSystemTrayIcon.Information, 2500)

    def _toggle_edge_from_tray(self, on):
        self.cfg["general"]["show_edge"] = "1" if on else "0"
        self.save_cfg()
        self.apply_edge()

        # Windows 上 explorer 重启会让任务栏句柄失效，隔几秒复查一次。
        # 定时器只建一次、复用同一个：每次都 new 一个会让老定时器无人回收，
        # 反复点菜单就会攒出一堆同时跑的回调。
        if getattr(self, "_keep", None) is None:
            self._keep = QTimer(self)
            self._keep.setInterval(4000)
            self._keep.timeout.connect(self._keep_panel)
        if on:
            self._keep.start()
        else:
            self._keep.stop()
        if hasattr(self.win, "refresh"):
            self.win.refresh()

    # ---------------------------------------------------------------- 快捷键
    def _build_hotkeys(self):
        """全局热键共用一个 X 连接。截图那组受开关控制，关掉就完全不动那几个键。"""
        if not self.flag("hotkey_enabled"):
            return None
        g = self.cfg["general"]
        hks = HotkeySet(self)
        hks.add("material", g.get("hotkey", "<Ctrl><Alt>G"))

        if self.flag("snip_hotkeys_on"):
            hks.add("snip", g.get("snip_hotkey", "F1"))
            hks.add("snip_copy", g.get("snip_copy_hotkey", "F2"))
            hks.add("snip_fixed", g.get("snip_fixed_hotkey", "<Shift>F1"))
            hks.add("pin", g.get("pin_hotkey", "F3"))
            hks.add("pin_toggle", g.get("pin_toggle_hotkey", "<Shift>F3"))

        hks.triggered.connect(self._on_hotkey)
        if hks.start():
            self.hk_errors = dict(hks.errors)
            return hks
        self.hk_error = next(iter(hks.errors.values()), "快捷键注册失败")
        self.hk_errors = dict(hks.errors)
        return None

    def reboot_hotkeys(self):
        """重新注册全部热键（截图开关切换、或改了键位之后调）。"""
        try:
            if self.hotkeys is not None:
                self.hotkeys.stop()
        except Exception:
            pass
        self.hotkeys = self._build_hotkeys()

    def set_snip_hotkeys(self, on):
        """截图快捷键总开关：关掉 → F1/F2/F3 还给其它程序。"""
        appcfg.set_flag(self.cfg, "snip_hotkeys_on", on)
        self.save_cfg()
        self.reboot_hotkeys()
        if self.tray:
            self.tray.showMessage(
                APP_NAME,
                "截图快捷键已开启（F1 / F2 / Shift+F1 / F3 / Shift+F3）" if on
                else "截图快捷键已关闭，F1/F2/F3 归还给其它程序",
                QSystemTrayIcon.Information, 2600)
        self.win.refresh()

    def snip_hotkeys_on(self):
        return self.flag("snip_hotkeys_on")

    def _on_hotkey(self, label):
        if label == "material":
            self._cycle_material()
        elif label == "snip":
            self.start_snip()
        elif label == "snip_copy":
            self.start_snip(auto_copy=True)
        elif label == "snip_fixed":
            self.start_snip(fixed=True)
        elif label == "pin":
            self.pin_clipboard()
        elif label == "pin_toggle":
            self.toggle_pins_visible()

    def hotkey_errors(self):
        return getattr(self, "hk_errors", {}) or {}

    def hotkey_labels(self):
        """当前真正抓着的热键标签（诊断和自检用）。"""
        return list(getattr(self.hotkeys, "_binds", {}).keys())

    def snip_hotkey_pretty(self):
        return pretty_combo(self.cfg["general"].get("snip_hotkey", "F1"))

    def snip_copy_hotkey_pretty(self):
        return pretty_combo(self.cfg["general"].get("snip_copy_hotkey", "F2"))

    def snip_fixed_hotkey_pretty(self):
        return pretty_combo(self.cfg["general"].get("snip_fixed_hotkey", "<Shift>F1"))

    def pin_hotkey_pretty(self):
        return pretty_combo(self.cfg["general"].get("pin_hotkey", "F3"))

    def pin_toggle_hotkey_pretty(self):
        return pretty_combo(self.cfg["general"].get("pin_toggle_hotkey", "<Shift>F3"))

    def _cycle_material(self):
        vals = [v for _, _, v in PRESETS]
        cur = self.panel.get_alpha()
        nxt = vals[0]
        for i, v in enumerate(vals):
            if abs(cur - v) < 0.06:
                nxt = vals[(i + 1) % len(vals)]
                break
        try:
            self.panel.set_alpha(nxt)
            self.save_cfg()
            if self.tray:
                self.tray.showMessage(APP_NAME, "任务栏透明度 %d%%" % int(nxt * 100),
                                      QSystemTrayIcon.Information, 1400)
            self.win.refresh()
        except PanelError:
            pass

    # ---------------------------------------------------------------- 截图
    def start_snip(self, auto_copy=False, fixed=False):
        """抓屏 → 弹框选遮罩。

        auto_copy=True  （F2）框完直接复制走，不进标注界面
        fixed=True      （Shift+F1）先问一个固定尺寸，拖着框定位
        """
        if self._overlay is not None:
            try:
                self._overlay.raise_()
                self._overlay.activateWindow()
            except Exception:
                pass
            return

        self._pending_auto_copy = bool(auto_copy)
        self._pending_fixed = None

        if fixed:
            size = self._ask_fixed_size()
            if size is None:
                return
            self._pending_fixed = size

        # 先把主窗口收起来，免得把自己截进去
        self._was_visible = self.win.isVisible()
        if self._was_visible:
            self.win.hide()
            QTimer.singleShot(140, self._begin_overlay)
        else:
            QTimer.singleShot(60, self._begin_overlay)

    def _ask_fixed_size(self):
        """问一次固定尺寸，记住上次用的值。"""
        from ui_bulk import PromptDialog
        g = self.cfg["general"]
        default = "%sx%s" % (g.get("snip_fixed_w", "800"), g.get("snip_fixed_h", "600"))
        was_visible = self.win.isVisible()
        if was_visible:
            self.win.hide()
        dlg = PromptDialog(None, self.pal, "自定义截屏",
                           "输入尺寸，格式 宽x高（例如 800x600）", default)
        dlg.center_on_parent = lambda: dlg.move(
            QApplication.primaryScreen().availableGeometry().center().x() - dlg.width() // 2,
            QApplication.primaryScreen().availableGeometry().center().y() - dlg.height() // 2)
        dlg.center_on_parent()
        ok = dlg.exec_() == QDialog.Accepted
        text = dlg.value() if ok else ""
        if was_visible:
            self.win.show()
        if not ok:
            return None
        raw = text.lower().replace("×", "x").replace("*", "x").replace(" ", "")
        try:
            w, h = [int(v) for v in raw.split("x")[:2]]
            if w < 8 or h < 8:
                raise ValueError
        except Exception:
            self._toast("尺寸看不懂，用 800x600 这种格式")
            return None
        g = self.cfg["general"]
        g["snip_fixed_w"] = str(w)
        g["snip_fixed_h"] = str(h)
        self.save_cfg()
        return (w, h)

    def _begin_overlay(self):
        canvas, virt = snip.grab_virtual()
        if canvas is None:
            self._toast("抓屏失败：拿不到屏幕内容")
            self._restore_win()
            return
        if snip.looks_blank(canvas):
            self._toast("抓到的画面是纯色。若截出来一片黑，请在控制中心开启桌面特效")
        screen = QApplication.primaryScreen()
        self._overlay = SnipOverlay(canvas, virt, screen, self.pal, self.cfg,
                                    fixed_size=getattr(self, "_pending_fixed", None),
                                    auto_copy=getattr(self, "_pending_auto_copy", False))
        self._overlay.done.connect(self._on_snip_done)
        self._overlay.start()

    def _on_snip_done(self, pixmap, action):
        ov = self._overlay
        self._overlay = None
        self._restore_win()
        if pixmap is None or pixmap.isNull() or action == "cancel":
            return

        if action in ("copy", "pin") or self.flag("snip_copy"):
            snip.to_clipboard(pixmap)

        if action == "save" or self.flag("snip_save"):
            path = snip.save(pixmap, snip.next_path(self._snip_dir()))
            if path:
                self.cfg["general"]["snip_dir"] = os.path.dirname(path)
                self.save_cfg()
                self._toast("已保存 %s" % path)
                self.win.refresh()

        if action == "pin":
            # 贴在原截图的位置，而不是飞到屏幕中间
            self._add_pin(pixmap, getattr(ov, "pin_pos", None))

    def _snip_dir(self):
        d = self.cfg["general"].get("snip_dir") or ""
        return d if d else snip.default_save_dir()

    def pin_clipboard(self):
        pm = snip.from_clipboard()
        if pm is None or pm.isNull():
            self._toast("剪贴板里没有图片")
            return
        self._add_pin(pm)

    def _add_pin(self, pixmap, pos=None):
        """pos 给了就贴在那儿（截图原位），没给就居中并逐张错开。"""
        if pos is None:
            self._pin_n = getattr(self, "_pin_n", 0) + 1
            off = (self._pin_n % 6) * 24
            scr = QApplication.primaryScreen().availableGeometry()
            pos = QPoint(scr.center().x() - pixmap.width() // 2 + off,
                         scr.center().y() - pixmap.height() // 2 + off)
        pin = PinWindow(pixmap, self.pal, on_close=self._forget_pin,
                        keep_top=self.flag("pin_top"))
        self.pins.append(pin)
        if getattr(self, "_pins_hidden", False):
            self._pins_hidden = False          # 新贴图总得看得见
            for p in self.pins:
                p.setVisible(True)
        pin.show_at(pos)
        pin.raise_()

    def toggle_pins_visible(self):
        """Shift+F3：把所有贴图临时藏起来／放出来。"""
        if not self.pins:
            self._toast("现在没有贴图")
            return
        hidden = not getattr(self, "_pins_hidden", False)
        self._pins_hidden = hidden
        for p in self.pins:
            p.setVisible(not hidden)
        if self.tray:
            self.tray.showMessage(APP_NAME,
                                  "已隐藏 %d 张贴图" % len(self.pins) if hidden
                                  else "已显示 %d 张贴图" % len(self.pins),
                                  QSystemTrayIcon.Information, 1800)

    def _forget_pin(self, pin):
        if pin in self.pins:
            self.pins.remove(pin)

    def _restore_win(self):
        if getattr(self, "_was_visible", False):
            self.win.show()
            self._was_visible = False

    def _toast(self, msg):
        if self.tray is not None and self.tray.isVisible():
            self.tray.showMessage(APP_NAME, msg, QSystemTrayIcon.Information, 2400)
        if self.win.isVisible():
            self.win.status_hint(msg)

    # ---------------------------------------------------------------- 监听
    def _desktop_roots(self):
        """要监听/整理的桌面目录。

        Windows 的公共桌面按「设置 → 整理公共桌面快捷方式」决定，默认不含：
        那是系统级目录，搬走会影响本机其它账号，写回权限也不一定还在。
        """
        return sysenv.desktop_dirs(include_public=self.flag("public_desktop"))

    def _build_watcher(self):
        # 防抖定时器只建一次：重建监听器时不能顺手再挂一个 QTimer
        if getattr(self, "_debounce", None) is None:
            self._debounce = QTimer(self)
            self._debounce.setSingleShot(True)
            self._debounce.setInterval(1500)
            self._debounce.timeout.connect(self._auto_tidy)
        w = QFileSystemWatcher(self)
        for d in self._desktop_roots():
            if os.path.isdir(d):
                w.addPath(d)
        w.directoryChanged.connect(self._on_fs)
        return w

    def rebuild_watcher(self):
        """改了要监听的桌面目录之后重建一次监听器。"""
        old = getattr(self, "watcher", None)
        self.watcher = self._build_watcher()
        if old is not None:
            try:
                old.deleteLater()
            except Exception:
                pass
        self._rebuild_tray_state()

    def _on_fs(self, _path):
        if self.flag("auto_tidy"):
            self._debounce.start()
        # 固定两个定时器反复 start()：原来每次变动都排一个 singleShot，
        # 浏览器/下载工具一次写几百个文件就会堆出几百个待执行回调。
        if getattr(self, "_tray_timer", None) is None:
            self._tray_timer = QTimer(self)
            self._tray_timer.setSingleShot(True)
            self._tray_timer.setInterval(400)
            self._tray_timer.timeout.connect(self._rebuild_tray_state)
            self._win_timer = QTimer(self)
            self._win_timer.setSingleShot(True)
            self._win_timer.setInterval(700)
            self._win_timer.timeout.connect(self._refresh_window_safe)
        self._tray_timer.start()
        # 窗口开着的时候，桌面来了新文件要立刻反映出来，
        # 否则「一键整理」按钮一直是灰的，点了像没反应
        if self.win.isVisible():
            self._win_timer.start()

    def _refresh_window_safe(self):
        if self.win.isVisible() and not self.win.slider.isSliderDown():
            self.win.refresh()

    def _auto_tidy(self):
        if not self.flag("auto_tidy"):
            return
        moved = self.tidy(notify=False)
        if moved and self.drawer.is_open:
            self.drawer.refresh()

    # ---------------------------------------------------------------- 整理
    def tidy(self, notify=False, open_drawer=False):
        """一键整理：扫描桌面 → 归类 → 刷新界面 / 托盘 / 抽屉。

        _busy 是五入口（按钮 / 托盘 / 自动整理 / IPC / CLI）的互斥闸：
        重入时两路会同时扫到同一批文件，正好撞上搬运占位冲突。
        """
        if getattr(self, "_busy", False):
            return []
        self._busy = True
        try:
            return self._tidy_inner(notify, open_drawer)
        finally:
            self._busy = False

    def _tidy_inner(self, notify=False, open_drawer=False):
        try:
            moved = self.org.apply()
        except Exception as e:
            if self.tray:
                self.tray.showMessage(APP_NAME, "整理失败：%s" % e,
                                      QSystemTrayIcon.Warning, 3000)
            return []
        self.win.refresh()
        self.drawer.refresh()
        self._rebuild_tray_state()

        # 搬失败/记账失败的项必须让用户看到，否则"整理完了"是假象
        errs = list(getattr(self.org, "last_errors", []) or [])
        tail = ""
        if errs:
            first = errs[0]
            # first[0] 为空是"整批回滚"这类整体结论，没有具体文件可点名
            who = (os.path.basename(first[0]) or first[0]) if first[0] else ""
            tail = "；%d 项没搬成（%s%s）" % (
                len(errs), (who + "：") if who else "", first[1])
        if moved:
            self.win.show_result("已整理 %d 项，归档到「%s」%s"
                                 % (len(moved), rules.SHELF_DIRNAME, tail))
            if open_drawer:
                self.open_drawer()
        elif errs:
            self.win.show_result("有 %d 项没能归档%s" % (len(errs), tail), undoable=False)
        else:
            self.win.show_result("桌面上没有需要归类的文件", undoable=False)
        if notify and self.tray:
            msg = "已整理 %d 项" % len(moved) if moved else "桌面已经很干净"
            if errs:
                msg += "，%d 项失败" % len(errs)
            self.tray.showMessage(APP_NAME, msg, QSystemTrayIcon.Information, 3000)
        return moved

    def tidy_from_ui(self):
        return self.tidy(notify=False)

    def undo(self):
        if getattr(self, "_busy", False):
            # 正在整理时撤销会把两边状态搅乱，直接忽略（按钮此时也该是灰的）
            return 0
        self._busy = True
        try:
            return self._undo_inner()
        finally:
            self._busy = False

    def _undo_inner(self):
        n = len(self.org.undo())
        errs = list(getattr(self.org, "last_errors", []) or [])
        notes = list(getattr(self.org, "last_notes", []) or [])
        self.win.refresh()
        self.drawer.refresh()
        self._rebuild_tray_state()
        if errs:
            # 撤不回来的项也要说清楚，不能让用户以为已经放回去了
            if n:
                self.win.show_result("已放回 %d 项，%d 项没撤成（%s）"
                                     % (n, len(errs), errs[0][1]), undoable=False)
            else:
                self.win.show_result("撤销失败：%s" % errs[0][1], undoable=False)
        elif notes and n:
            # 公共桌面里的图标写不回去，改放用户自己的桌面——不是失败，但要说清
            self.win.show_result("已放回 %d 项。%s" % (n, notes[0]), undoable=False)
        return n

    def open_root(self):
        from PyQt5.QtGui import QDesktopServices
        from PyQt5.QtCore import QUrl
        self.org.ensure_dirs()
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.org.root))

    # ---------------------------------------------------------------- 抽屉
    def _place_trigger(self):
        scr = QApplication.primaryScreen().availableGeometry()
        self._tx = scr.right() - Trigger.W + 2
        self._ty = scr.top() + (scr.height() - Trigger.H) // 2
        self.trigger.move(self._tx, self._ty)

    def apply_edge(self):
        if self.flag("show_edge"):
            if not self.drawer.is_open:
                self._place_trigger()
                self.trigger.show()
                self.trigger.raise_()
        else:
            self.trigger.hide()
            if self.drawer.is_open:
                self.drawer.slide_out()

    def _trigger_back(self):
        self._place_trigger()
        if self.flag("show_edge"):
            self.trigger.show()
            self.trigger.raise_()

    def _trigger_to_drawer(self):
        self.trigger.move(self.drawer._x_shown - Trigger.W + 4, self._ty)
        self.trigger.show()
        self.trigger.raise_()

    def toggle_drawer(self):
        if self.drawer.is_open:
            self.drawer.slide_out()
        else:
            self.drawer.slide_in()

    def open_drawer(self):
        if not self.flag("show_edge"):
            self.trigger.show()
        self.drawer.slide_in()

    # ---------------------------------------------------------------- 自启
    def autostart_on(self):
        return sysenv.autostart_on()

    def set_autostart(self, on):
        entry = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cli.py")
        return sysenv.set_autostart(on, sysenv.startup_command(entry))

    def _keep_panel(self):
        fn = getattr(self.panel, "keep_alive", None)
        if fn:
            try:
                fn()
            except Exception:
                pass

    # ---------------------------------------------------------------- 其它
    def _refresh_all(self):
        self.win.refresh()
        self._rebuild_tray_state()

    def quit(self):
        if getattr(self, "_quiting", False):     # aboutToQuit 也会进来，别跑两遍
            return
        self._quiting = True
        if getattr(self, "hotkeys", None):
            self.hotkeys.stop()
        # 退出前把自己动过的系统设置写回原值。任务栏透明度、隐藏的系统图标
        # 都是"程序活着才有意义"的状态：不还原等于把用户系统留在半改状态。
        panel = getattr(self, "panel", None)
        if panel is not None:
            try:
                panel.restore()
            except Exception:
                pass
        for pin in list(getattr(self, "pins", [])):
            try:
                pin.close()
            except Exception:
                pass
        QApplication.instance().quit()


# --------------------------------------------------------------------------- #
# 单实例 IPC
# --------------------------------------------------------------------------- #
def send_to_existing(cmd, timeout=250):
    s = QLocalSocket()
    s.connectToServer(SERVER_KEY)
    if not s.waitForConnected(timeout):
        s.abort()
        s.deleteLater()
        return False
    s.write(cmd.encode())
    s.flush()
    s.waitForBytesWritten(timeout)
    s.disconnectFromServer()
    s.deleteLater()
    return True


def running_instance(pid_probe=False):
    """探一下有没有实例在监听（只连一下、不发命令、不清理 socket）。

    只在连上的瞬间返回 True，调用方据此决定"转发命令"还是"自己接管"。
    """
    s = QLocalSocket()
    s.connectToServer(SERVER_KEY)
    ok = bool(s.waitForConnected(250))
    s.abort()              # 不 disconnectFromServer，避免服务端收到空行
    s.deleteLater()
    return ok


def run(argv=None):
    argv = argv or sys.argv[1:]
    # 尽早装上：QApplication 构造阶段崩也要留痕
    crashlog.install(os.path.join(appcfg.CONFIG_DIR, "crash.log"))
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    # 关键顺序：先探测、再接管。
    # 以前是"先 removeServer 再 listen"，等于把正在服役的实例的 socket 抢走：
    # 老实例还在跑、还在处理文件，新实例又起来了，两边抢同一批桌面文件。
    if running_instance():
        send_to_existing("show")
        return 0

    server = QLocalServer()
    if not server.listen(SERVER_KEY):
        # 探测说没人监听，listen 却失败：多半是上次崩溃留下的僵尸 socket。
        # 这种才清掉重试一次；重试还不行说明真有人占着，转过去就好。
        QLocalServer.removeServer(SERVER_KEY)
        server = QLocalServer()
        if not server.listen(SERVER_KEY):
            send_to_existing("show")
            return 0

    ctl = App(argv)
    app._app = ctl

    def _on_conn():
        c = server.nextPendingConnection()
        if c is None:
            return
        # 一次 readAll 不保证拿到完整命令（write 可能被拆包），
        # 读到没有新数据为止，再按行/大小上限兜底。
        data = bytearray()
        c.waitForReadyRead(300)
        while len(data) < 4096:
            chunk = bytes(c.readAll())
            if not chunk:
                if not c.waitForReadyRead(150):     # 已经没有后续数据了
                    break
                continue
            data += chunk
        c.disconnectFromServer()
        c.deleteLater()          # 连接对象不释放会跟着新连接一起堆积
        try:
            cmd = bytes(data).decode("utf-8", "ignore").strip()
        except Exception:
            cmd = ""
        if not cmd:
            # 空包＝探活连接（第二个实例启动、卸载脚本探活都只连不发），什么都不做
            return
        if cmd == "tidy":
            ctl.tidy(notify=True)
        elif cmd == "undo":
            n = ctl.undo()
            if ctl.tray:
                ctl.tray.showMessage(APP_NAME, "已放回桌面 %d 项" % n if n else "没有可撤销的记录",
                                     QSystemTrayIcon.Information, 2500)
        elif cmd == "drawer":
            ctl.open_drawer()
        elif cmd == "snip":
            ctl.start_snip()
        elif cmd == "snip-copy":
            ctl.start_snip(auto_copy=True)
        elif cmd == "snip-fixed":
            ctl.start_snip(fixed=True)
        elif cmd == "pin-toggle":
            ctl.toggle_pins_visible()
        elif cmd == "reboot-hotkeys":
            ctl.reboot_hotkeys()
        elif cmd == "pin":
            ctl.pin_clipboard()
        elif cmd == "win":
            ctl.show_window()
        elif cmd == "quit":
            ctl.quit()          # 卸载/升级时让运行中的实例自己优雅退出
        else:
            ctl.show_window()

    server.newConnection.connect(_on_conn)
    app._server = server

    show = True if "--window" in argv else None
    ctl.start(show_window=show)
    app.aboutToQuit.connect(ctl.quit)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(run())
