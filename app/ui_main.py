#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— 主窗口

左边一条导航，三页：
  任务栏  —— 透明度滑块 + 材质预设 + 玻璃质感/磨砂强度 + 玻璃预览
  文件    —— 一键整理（核心按钮）、分类统计、撤销
  设置    —— 开机自启、启动进托盘、右侧入口条、自动整理、快捷键
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtCore import (Qt, QRectF, QEasingCurve, QPropertyAnimation, QTimer,
                          QThreadPool, QObject, QRunnable, pyqtSignal, pyqtProperty)
from PyQt5.QtGui import (QColor, QPainter, QLinearGradient, QPainterPath, QPen,
                         QBrush, QIcon, QPixmap)
from PyQt5.QtWidgets import (QWidget, QLabel, QPushButton, QSlider, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QFrame, QStackedWidget,
                             QAbstractButton, QSizePolicy, QFileDialog, QApplication,
                             QButtonGroup)

import launchers
import rules
import sysenv
from panel_core import PRESETS, BLUR_NAMES, GLASS_MAX_ALPHA
from theme import Palette, CAT_COLORS, system_is_dark
from version import VERSION


def app_icon(pal, size=64):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#2F72E8"))
    g.setColorAt(1, QColor("#22C58B"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(g))
    p.drawRoundedRect(QRectF(size * 0.09, size * 0.09, size * 0.82, size * 0.82),
                      size * 0.22, size * 0.22)
    # 玻璃条
    p.setBrush(QColor(255, 255, 255, 165))
    p.drawRoundedRect(QRectF(size * 0.2, size * 0.62, size * 0.6, size * 0.17),
                      size * 0.06, size * 0.06)
    p.setBrush(QColor(255, 255, 255, 225))
    p.drawRoundedRect(QRectF(size * 0.2, size * 0.3, size * 0.34, size * 0.13),
                      size * 0.05, size * 0.05)
    p.end()
    return QIcon(pm)


# --------------------------------------------------------------------------- #
# 基础控件
# --------------------------------------------------------------------------- #
class StyleChips(QWidget):
    """透明度档位：横排单选胶囊按钮。点谁选谁、立刻生效，没有多余文字。

    用 QButtonGroup(exclusive) 保证单选；选中态整颗填充主题色，
    未选中是描边胶囊，悬停只换描边色。
    """

    stylePicked = pyqtSignal(str)

    def __init__(self, pal, options, parent=None):
        super(StyleChips, self).__init__(parent)
        self.pal = pal
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons = {}
        qss = self._qss()
        for key, label in options:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(30)
            b.setMinimumWidth(58)
            b.setStyleSheet(qss)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, k=key: self.stylePicked.emit(k))
            self._group.addButton(b)
            lay.addWidget(b, 1)          # 等宽撑满一行，视觉上是一根档位条
            self.buttons[key] = b

    def _qss(self):
        pal = self.pal
        return ("QPushButton{border:1px solid %s;border-radius:15px;background:%s;"
                "color:%s;font-size:12px;padding:0 8px;}"
                "QPushButton:hover{border:1px solid %s;color:%s;}"
                "QPushButton:checked{background:%s;border:1px solid %s;"
                "color:#FFFFFF;font-weight:600;}"
                % (pal.line.name(), pal.card.name(), pal.text.name(),
                   pal.accent.name(), pal.accent.name(),
                   pal.accent.name(), pal.accent.name()))

    def set_current(self, key):
        """按 key 选中。setChecked 不触发 clicked，回同步不会反过来改档位。"""
        for k, b in self.buttons.items():
            b.setChecked(k == key)


class Switch(QAbstractButton):
    def __init__(self, pal, parent=None):
        super(Switch, self).__init__(parent)
        self.pal = pal
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(42, 23)
        self._pos = 0.0
        self.anim = QPropertyAnimation(self, b"knob", self)
        self.anim.setDuration(150)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on):
        self.anim.stop()
        self.anim.setStartValue(self._pos)
        self.anim.setEndValue(1.0 if on else 0.0)
        self.anim.start()

    def set_silent(self, on):
        self.blockSignals(True)
        self.setChecked(on)
        self._pos = 1.0 if on else 0.0
        self.blockSignals(False)
        self.update()

    def get_knob(self):
        return self._pos

    def set_knob(self, v):
        self._pos = v
        self.update()

    knob = pyqtProperty(float, fget=get_knob, fset=set_knob)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        if self._pos <= 0.01:
            p.setPen(Qt.NoPen)
            p.setBrush(self.pal.line)
            p.drawRoundedRect(QRectF(0, 0, self.width(), h), h / 2.0, h / 2.0)
        else:
            g = QLinearGradient(0, 0, self.width(), 0)
            g.setColorAt(0, self.pal.accent)
            g.setColorAt(1, QColor("#22C58B"))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.setOpacity(0.4 + 0.6 * self._pos)
            p.drawRoundedRect(QRectF(0, 0, self.width(), h), h / 2.0, h / 2.0)
            p.setOpacity(1.0)
        x = 2.5 + self._pos * (self.width() - h)
        p.setBrush(QColor(255, 255, 255))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(x, 2.5, h - 5, h - 5))
        p.end()


class GlassPreview(QWidget):
    """任务栏叠在壁纸上的观感。透明度再高，也保留一层磨砂反光。"""

    def __init__(self, pal, parent=None):
        super(GlassPreview, self).__init__(parent)
        self.pal = pal
        self.alpha = 0.6
        self.glass = True
        self.setFixedHeight(132)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_state(self, alpha, glass):
        self.alpha = max(0.0, min(1.0, alpha))
        self.glass = glass
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.setClipPath(path)

        # 壁纸
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0.0, QColor("#1D3B63"))
        g.setColorAt(0.42, QColor("#5A4A86"))
        g.setColorAt(0.74, QColor("#B25778"))
        g.setColorAt(1.0, QColor("#E0895A"))
        p.fillPath(path, QBrush(g))

        bar_h = 44.0
        bar = QRectF(r.left(), r.bottom() - bar_h, r.width(), bar_h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(24, 26, 30, int(self.alpha * 255)))
        p.drawRect(bar)

        if self.glass:
            # 磨砂反光：上沿高光 + 垂直渐变，透明度 100% 时也保留
            sheen = QLinearGradient(bar.left(), bar.top(), bar.left(), bar.bottom())
            sheen.setColorAt(0.0, QColor(255, 255, 255, 46))
            sheen.setColorAt(0.45, QColor(255, 255, 255, 12))
            sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillRect(bar, QBrush(sheen))
            p.setBrush(QColor(255, 255, 255, 40))
            p.drawRect(QRectF(bar.left(), bar.top(), bar.width(), 1))

        # 任务栏上的示意元素
        ink = QColor(255, 255, 255, 232)
        p.setBrush(ink)
        p.drawEllipse(QRectF(bar.left() + 13, bar.center().y() - 7, 14, 14))
        for i in range(4):
            p.setBrush(QColor(255, 255, 255, 140))
            p.drawRoundedRect(QRectF(bar.left() + 42 + i * 22, bar.center().y() - 6, 16, 12), 3, 3)
        p.setBrush(QColor(255, 255, 255, 170))
        p.drawRoundedRect(QRectF(bar.right() - 72, bar.center().y() - 5, 58, 10), 3, 3)

        p.setClipping(False)
        p.setPen(QPen(self.pal.line, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 12, 12)
        p.end()


class StatCard(QFrame):
    def __init__(self, pal, cat):
        super(StatCard, self).__init__()
        self.pal = pal
        self.cat = cat
        self.setFixedHeight(58)
        self.setStyleSheet(
            "QFrame{background:%s;border:1px solid %s;border-radius:9px;}"
            % (pal.card_hi.name(), pal.line.name()))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)

        dot = QLabel()
        dot.setFixedSize(8, 8)
        c = QColor(CAT_COLORS.get(cat, "#8A8F98"))
        dot.setStyleSheet("background:%s;border-radius:4px;" % c.name())
        lay.addWidget(dot, 0, Qt.AlignTop)

        box = QVBoxLayout()
        box.setSpacing(0)
        self.num = QLabel("0")
        self.num.setStyleSheet("color:%s;font-size:17px;font-weight:700;border:none;"
                               % pal.text.name())
        name = QLabel(cat)
        name.setStyleSheet("color:%s;font-size:10px;border:none;" % pal.muted.name())
        box.addWidget(self.num)
        box.addWidget(name)
        lay.addLayout(box, 1)

    def set_count(self, n):
        self.num.setText(str(n))


# --------------------------------------------------------------------------- #
# 主窗口
# --------------------------------------------------------------------------- #
class _AlphaSignals(QObject):
    done = pyqtSignal(object, str)      # (实际生效值, 错误信息)


class _AlphaJob(QRunnable):
    """在线程池里跑一次 set_alpha。

    Linux 上一次 set_alpha 要串行起 6 个 gsettings 子进程（合计 0.2–0.5 秒），
    留在主线程就是一卡；挪进线程池后窗口还能继续响应拖动。
    """

    def __init__(self, panel, alpha):
        super(_AlphaJob, self).__init__()
        self.panel = panel
        self.alpha = alpha
        self.signals = _AlphaSignals()

    def run(self):
        try:
            self.panel.set_alpha(self.alpha)
            actual = self.panel.get_alpha()
            err = ""
        except Exception as e:      # 线程里抛异常没人接，必须自己兜住再回报
            actual, err = None, "%s" % e
        self.signals.done.emit(actual, err)


class MainWindow(QWidget):
    WIDTH, HEIGHT = 764, 566

    def __init__(self, app):
        super(MainWindow, self).__init__(None, Qt.FramelessWindowHint | Qt.Window)
        self.app = app                      # 控制器
        self.cfg = app.cfg
        self.pal = Palette(system_is_dark())
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setWindowTitle("桌面整理")
        self.setWindowIcon(app_icon(self.pal))
        self._drag = None
        self._stats = {}
        # 透明度落盘专用线程池：只许一条 gsettings 链在跑，避免并发写系统设置
        self._alpha_pool = QThreadPool(self)
        self._alpha_pool.setMaxThreadCount(1)
        self._alpha_job = None
        self._alpha_req = None
        self._alpha_dirty = False

        self._build()
        self.refresh()

    # -- 结构 ---------------------------------------------------------------
    def _build(self):
        pal = self.pal
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_rail())

        right = QWidget()
        right.setStyleSheet("background:transparent;")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(24, 18, 22, 18)
        rl.setSpacing(0)
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background:transparent;")
        self.stack.addWidget(self._page_panel())
        self.stack.addWidget(self._page_files())
        self.stack.addWidget(self._page_snip())
        self.stack.addWidget(self._page_settings())
        rl.addWidget(self.stack)
        root.addWidget(right, 1)

    def _build_rail(self):
        pal = self.pal
        rail = QFrame()
        rail.setFixedWidth(152)
        rail.setStyleSheet(
            "QFrame{background:%s;border:none;border-top-left-radius:14px;"
            "border-bottom-left-radius:14px;}" % pal.card_hi.name())
        lay = QVBoxLayout(rail)
        lay.setContentsMargins(14, 18, 14, 16)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(app_icon(pal).pixmap(22, 22))
        head.addWidget(logo)
        t = QLabel("01  桌面整理")
        t.setFont(pal.font_display(15))
        t.setStyleSheet("color:%s;border:none;" % pal.text.name())
        head.addWidget(t)
        head.addStretch(1)
        lay.addLayout(head)
        lay.addSpacing(14)

        self.nav = []
        for idx, (text, tip) in enumerate((("任务栏", "透明度与磨砂"),
                                           ("文件整理", "一键归类"),
                                           ("截图", "截屏与贴图"),
                                           ("设置", "启动与常驻"))):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setCheckable(True)
            b.setFixedHeight(38)
            b.setToolTip(tip)
            b.setStyleSheet(self._nav_qss())
            b.clicked.connect(lambda _=False, i=idx: self.goto(i))
            lay.addWidget(b)
            self.nav.append(b)
        self.nav[0].setChecked(True)

        lay.addStretch(1)
        self.btn_hide = QPushButton("收进托盘")
        self.btn_hide.setCursor(Qt.PointingHandCursor)
        self.btn_hide.setFixedHeight(28)
        self.btn_hide.setToolTip("窗口收起，工具继续在托盘里待命")
        self.btn_hide.setStyleSheet(
            "QPushButton{border:1px solid %s;border-radius:7px;background:transparent;"
            "color:%s;font-size:11px;}"
            "QPushButton:hover{background:rgba(127,127,127,0.14);color:%s;}"
            % (pal.line.name(), pal.muted.name(), pal.text.name()))
        self.btn_hide.clicked.connect(self.hide)
        lay.addWidget(self.btn_hide)
        lay.addSpacing(8)
        self.rail_tip = QLabel("")
        self.rail_tip.setWordWrap(True)
        self.rail_tip.setStyleSheet("color:%s;font-size:10px;border:none;" % pal.muted.name())
        lay.addWidget(self.rail_tip)
        return rail

    def _nav_qss(self):
        pal = self.pal
        return """
        QPushButton{border:none;border-radius:8px;text-align:left;padding-left:12px;
            color:%s;font-size:12.5px;background:transparent;}
        QPushButton:hover{background:rgba(127,127,127,0.13);}
        QPushButton:checked{background:%s;color:#FFFFFF;font-weight:600;}
        """ % (pal.text.name(), pal.accent.name())

    def status_hint(self, msg):
        """左下角小字提示，几秒后自己消失。

        用同一个定时器反复 start()，不要每次 singleShot：连着触发两次时，
        第一个定时器会在第 3.4 秒把第二次的提示提前清掉。
        """
        if not hasattr(self, "rail_tip"):
            return
        self.rail_tip.setText(msg)
        if getattr(self, "_hint_timer", None) is None:
            self._hint_timer = QTimer(self)
            self._hint_timer.setSingleShot(True)
            self._hint_timer.setInterval(3400)
            self._hint_timer.timeout.connect(lambda: self.rail_tip.setText(""))
        self._hint_timer.start()

    def goto(self, i):
        self.stack.setCurrentIndex(i)
        for n, b in enumerate(self.nav):
            b.setChecked(n == i)

    # -- 页 1：任务栏 -------------------------------------------------------
    def _page_panel(self):
        pal = self.pal
        page = QWidget()
        page.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        head = QHBoxLayout()
        box = QVBoxLayout()
        box.setSpacing(1)
        t = QLabel("任务栏透明度")
        t.setFont(pal.font_ui(17, bold=True))
        t.setStyleSheet("color:%s;" % pal.text.name())
        # 文案按平台分开写：Win11 的任务栏背景是 explorer 内部的 XAML 表面，
        # 进程外改不动，所以这里给的是「选一档」而不是「拖一个连续值」。
        if sysenv.IS_WINDOWS:
            sub_text = "只影响任务栏，退出程序自动还原"
        else:
            sub_text = "拉低就透出壁纸，磨砂质感始终保留"
        # 副标题一律单行：这行字折成两段会把标题区撑得很难看
        sub = QLabel(sub_text)
        sub.setWordWrap(False)
        sub.setFont(pal.font_mono(10))
        sub.setStyleSheet("color:%s;" % pal.muted.name())
        box.addWidget(t)
        box.addWidget(sub)
        head.addLayout(box)
        head.addStretch(1)
        # 百分比只对麒麟的连续可调有意义；Windows 改成固定档位后不再显示数字。
        # 注意要挂到 page 名下：Qt 里没父对象又不进布局的控件会变成独立
        # 顶层窗口浮在桌面上（「弹出一堆小窗」就是这个原因）。
        self.pct = QLabel("60%", page)
        self.pct.setFont(pal.font_display(26))
        self.pct.setStyleSheet("color:%s;" % pal.accent.name())
        if not sysenv.IS_WINDOWS:
            head.addWidget(self.pct)
        lay.addLayout(head)

        # ---------------------------------------------------------------- #
        # Windows：横排单选档位条。六档胶囊点谁选谁，立刻生效；
        # 页面不放说明文字，档位名本身就能看懂（无痕/轻纱/薄雾/磨砂/浓雾/凝实）。
        # ---------------------------------------------------------------- #
        if sysenv.IS_WINDOWS:
            self.style_chips = StyleChips(
                pal, [(k, l) for k, l, _v in self.app.panel.STYLES])
            self.style_chips.stylePicked.connect(self._on_style)
            lay.addWidget(self.style_chips)

        # 注入全透明（Windows 独有）：真把任务栏背景摘掉，图标不受影响
        self.inject_row = QWidget(page)
        self.inject_row.setStyleSheet("background:transparent;")
        r1 = QHBoxLayout(self.inject_row)
        r1.setContentsMargins(0, 0, 0, 0)
        r1t = QVBoxLayout()
        r1t.setSpacing(1)
        a1 = QLabel("任务栏完全透明")
        a1.setStyleSheet("color:%s;font-size:13px;font-weight:600;" % pal.text.name())
        b1 = QLabel("背景整块去掉、图标原样清晰。"
                    "杀软可能拦截，彻底卸载需重启资源管理器")
        b1.setWordWrap(True)
        b1.setStyleSheet("color:%s;font-size:10.5px;" % pal.muted.name())
        r1t.addWidget(a1)
        r1t.addWidget(b1)
        r1.addLayout(r1t, 1)
        self.sw_inject = Switch(pal)
        self.sw_inject.toggled.connect(self._on_inject)
        r1.addWidget(self.sw_inject, 0, Qt.AlignTop)
        if not sysenv.IS_WINDOWS:
            lay.addWidget(self.inject_row)
        supports_inject = getattr(self.app.panel, "supports_inject", lambda: False)()
        self.inject_row.setVisible(supports_inject)

        # 只在注入模式显示：这一行回答"生效了吗"和"怎么彻底卸掉"两个必然会问的问题
        self.inject_note = QLabel("已生效：任务栏背景交给壁纸，图标原样。资源管理器重启后会自动重连；"
                                  "想彻底卸掉这份组件，重启一次资源管理器即可。", page)
        self.inject_note.setWordWrap(True)
        self.inject_note.setStyleSheet("color:%s;font-size:10.5px;" % pal.muted.name())
        self.inject_note.setVisible(False)
        if not sysenv.IS_WINDOWS:
            lay.addWidget(self.inject_note)

        # 自动隐藏（Windows 独有）：这是外部程序唯一能做到"图标零损失"的办法
        self.autohide_row = QWidget(page)
        self.autohide_row.setStyleSheet("background:transparent;")
        r0 = QHBoxLayout(self.autohide_row)
        r0.setContentsMargins(0, 0, 0, 0)
        r0t = QVBoxLayout()
        r0t.setSpacing(1)
        a0 = QLabel("自动隐藏任务栏")
        a0.setStyleSheet("color:%s;font-size:13px;font-weight:600;" % pal.text.name())
        b0 = QLabel("整条让给壁纸，鼠标碰到屏幕底边才滑出来；图标零损失，随时可关")
        b0.setWordWrap(True)
        b0.setStyleSheet("color:%s;font-size:10.5px;" % pal.muted.name())
        r0t.addWidget(a0)
        r0t.addWidget(b0)
        r0.addLayout(r0t, 1)
        self.sw_autohide = Switch(pal)
        self.sw_autohide.toggled.connect(self._on_autohide)
        r0.addWidget(self.sw_autohide, 0, Qt.AlignTop)
        if not sysenv.IS_WINDOWS:
            lay.addWidget(self.autohide_row)
        self.autohide_row.setVisible(self.app.panel.supports_autohide())

        # 下面这一组是"整窗淡出"：自动隐藏开着时整组收起，两套机制不叠加
        self.fade_box = QWidget(page)
        self.fade_box.setStyleSheet("background:transparent;")
        fb = QVBoxLayout(self.fade_box)
        fb.setContentsMargins(0, 6, 0, 0)
        fb.setSpacing(10)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.setFixedHeight(26)
        self.slider.setStyleSheet("""
        QSlider::groove:horizontal{height:6px;border-radius:3px;background:%s;}
        QSlider::sub-page:horizontal{height:6px;border-radius:3px;
            background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 %s,stop:1 #22C58B);}
        QSlider::handle:horizontal{width:18px;height:18px;margin:-7px 0;border-radius:9px;
            background:#FFFFFF;border:1px solid rgba(0,0,0,42);}
        QSlider::handle:horizontal:hover{width:20px;height:20px;margin:-8px 0;
            border-radius:10px;}
        """ % (pal.line.name(), pal.accent.name()))
        self.slider.valueChanged.connect(self._on_slider)
        self.slider.sliderReleased.connect(self._commit_alpha)   # 松手立刻落盘，不等防抖
        fb.addWidget(self.slider)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.chips = {}
        for key, label, val in PRESETS:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(30)
            b.setStyleSheet(self._chip_qss())
            b.clicked.connect(lambda _=False, v=val: self._on_preset(v))
            self.chips[key] = b
            chips.addWidget(b)
        fb.addLayout(chips)

        self.preview = GlassPreview(pal)
        fb.addWidget(self.preview)
        if not sysenv.IS_WINDOWS:
            lay.addWidget(self.fade_box)

        # 玻璃质感
        self.glass_row = QWidget(page)
        self.glass_row.setStyleSheet("background:transparent;")
        row1 = QHBoxLayout(self.glass_row)
        row1.setContentsMargins(0, 0, 0, 0)
        r1t = QVBoxLayout()
        r1t.setSpacing(1)
        a = QLabel("玻璃质感")
        a.setStyleSheet("color:%s;font-size:13px;font-weight:600;" % pal.text.name())
        b = QLabel("强制开启系统磨砂，并把透明度上限压到 %d%%，避免变成实心色块"
                   % int(GLASS_MAX_ALPHA * 100))
        b.setWordWrap(True)
        b.setStyleSheet("color:%s;font-size:10.5px;" % pal.muted.name())
        r1t.addWidget(a)
        r1t.addWidget(b)
        row1.addLayout(r1t, 1)
        self.sw_glass = Switch(pal)
        self.sw_glass.toggled.connect(self._on_glass)
        row1.addWidget(self.sw_glass, 0, Qt.AlignTop)
        # 玻璃质感是麒麟特有的系统磨砂开关，Windows 上整行不进布局：
        # 留着它只会让人以为"半透明 + 玻璃质感"能叠着调。
        if not sysenv.IS_WINDOWS:
            lay.addWidget(self.glass_row)

        # 和第三方任务栏美化工具抢同一块任务栏，只能二选一
        self.tools_hint = QLabel("", page)
        self.tools_hint.setWordWrap(True)
        self.tools_hint.setFont(pal.font_mono(9.5))
        self.tools_hint.setStyleSheet("color:%s;" % pal.accent.name())
        self.tools_hint.setVisible(False)
        lay.addWidget(self.tools_hint)

        # 磨砂强度（Windows 只有系统 Acrylic 一档，整行不显示）
        self.blur_row = QWidget(page)
        self.blur_row.setStyleSheet("background:transparent;")
        row2 = QHBoxLayout(self.blur_row)
        row2.setContentsMargins(0, 0, 0, 0)
        c = QLabel("毛玻璃强度")
        c.setStyleSheet("color:%s;font-size:13px;font-weight:600;" % pal.text.name())
        row2.addWidget(c)
        row2.addStretch(1)
        self.blur_btns = {}
        for lv in (1, 2, 3):
            bb = QPushButton(BLUR_NAMES[lv])
            bb.setCheckable(True)
            bb.setCursor(Qt.PointingHandCursor)
            bb.setFixedSize(46, 26)
            bb.setStyleSheet(self._seg_qss())
            bb.clicked.connect(lambda _=False, v=lv: self._on_blur(v))
            self.blur_btns[lv] = bb
            row2.addWidget(bb)
        self.blur_row.setVisible(self.app.panel.supports_blur_level())
        lay.addWidget(self.blur_row)
        lay.addSpacing(4)
        if sysenv.IS_WINDOWS:
            # 档位制之后这些旧控件在 Windows 上不再进布局。上面已把它们挂到
            # page 名下（防止变成顶层窗口乱飘），这里再统一隐藏——否则没进
            # 布局的可见子控件会默认挤在页面 (0,0) 互相叠着。麒麟路径走
            # addWidget，不受影响。
            for w in (self.pct, self.inject_row, self.inject_note,
                      self.autohide_row, self.fade_box, self.glass_row):
                w.hide()
        else:
            lay.addWidget(self._hint_card(
                "磨砂由系统合成器（ukui-kwin）渲染。任务栏没变化时先确认两件事："
                "合成器在运行；控制中心 → 个性化 → 特效 处于开启状态。"))
        lay.addStretch(1)

        self.panel_status = QLabel("")
        self.panel_status.setStyleSheet("color:%s;font-size:11px;" % pal.muted.name())
        lay.addWidget(self.panel_status)
        return page

    # -- 页 2：文件 ---------------------------------------------------------
    def _page_files(self):
        pal = self.pal
        page = QWidget()
        page.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        t = QLabel("桌面文件整理")
        t.setFont(pal.font_ui(17, bold=True))
        t.setStyleSheet("color:%s;" % pal.text.name())
        sub = QLabel("文件照常存在桌面，想收拾的时候点一下")
        sub.setFont(pal.font_mono(10))
        sub.setStyleSheet("color:%s;" % pal.muted.name())
        lay.addWidget(t)
        lay.addWidget(sub)

        # 一键整理
        bar = QFrame()
        bar.setStyleSheet("QFrame{background:%s;border:1px solid %s;border-radius:12px;}"
                          % (pal.card_hi.name(), pal.line.name()))
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 12, 12, 12)
        bl.setSpacing(14)

        self.btn_tidy = QPushButton("一键整理")
        self.btn_tidy.setCursor(Qt.PointingHandCursor)
        self.btn_tidy.setFixedSize(150, 52)
        self.btn_tidy.setStyleSheet("""
        QPushButton{border:none;border-radius:10px;color:#FFFFFF;font-size:15px;
            font-weight:700;
            background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #2F72E8,stop:1 #22C58B);}
        QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,
            stop:0 #3D7DF0,stop:1 #2CD094);}
        QPushButton:pressed{background:#2A66D2;}
        QPushButton:disabled{background:%s;color:%s;}
        """ % (pal.line.name(), pal.muted.name()))
        self.btn_tidy.clicked.connect(self.app.tidy_from_ui)
        bl.addWidget(self.btn_tidy)

        info = QVBoxLayout()
        info.setSpacing(2)
        self.pending_lb = QLabel("桌面很干净")
        self.pending_lb.setStyleSheet("color:%s;font-size:13px;font-weight:600;border:none;"
                                      % pal.text.name())
        self.pending_sub = QLabel("桌面上没有待归类的文件")
        self.pending_sub.setWordWrap(True)
        self.pending_sub.setStyleSheet("color:%s;font-size:10.5px;border:none;"
                                       % pal.muted.name())
        info.addWidget(self.pending_lb)
        info.addWidget(self.pending_sub)
        bl.addLayout(info, 1)
        lay.addWidget(bar)

        # 结果条（整理后出现，带撤销）
        self.result = QFrame()
        self.result.setStyleSheet(
            "QFrame{background:rgba(34,197,139,0.13);border:1px solid rgba(34,197,139,0.45);"
            "border-radius:9px;}")
        rl = QHBoxLayout(self.result)
        rl.setContentsMargins(10, 6, 8, 6)
        self.result_lb = QLabel("")
        self.result_lb.setStyleSheet("color:%s;font-size:12px;border:none;" % pal.text.name())
        rl.addWidget(self.result_lb, 1)
        self.btn_undo = QPushButton("撤销")
        self.btn_undo.setCursor(Qt.PointingHandCursor)
        self.btn_undo.setFixedHeight(24)
        self.btn_undo.setStyleSheet(
            "QPushButton{border:none;background:transparent;color:#22C58B;"
            "font-size:12px;font-weight:600;padding:0 8px;border-radius:6px;}"
            "QPushButton:hover{background:rgba(34,197,139,0.18);}")
        self.btn_undo.clicked.connect(self._undo)
        rl.addWidget(self.btn_undo)
        self.result.setVisible(False)
        lay.addWidget(self.result)

        # 分类统计
        cap = QLabel("归档分布")
        cap.setStyleSheet("color:%s;font-size:11.5px;font-weight:600;" % pal.muted.name())
        lay.addWidget(cap)
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, cat in enumerate(rules.CATEGORY_ORDER):
            card = StatCard(pal, cat)
            self._stats[cat] = card
            grid.addWidget(card, i // 4, i % 4)
        lay.addLayout(grid)
        lay.addSpacing(2)
        lay.addWidget(self._hint_card(
            "只移动、不删除；重名自动改名成「名字 (2)」。"
            "桌面图标会变成抽屉「应用」里可点的磁贴，点一下照样启动。"
            ". 开头的锁文件、相对路径链接、挂载点一律不动。6 秒内可撤销。"))
        lay.addStretch(1)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        for text, slot in (("打开抽屉", self.app.toggle_drawer),
                           ("打开归档目录", self.app.open_root),
                           ("查看规则", self._show_rules)):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(30)
            b.setStyleSheet(
                "QPushButton{border:1px solid %s;border-radius:8px;background:transparent;"
                "color:%s;font-size:11.5px;padding:0 14px;}"
                "QPushButton:hover{background:%s;}"
                % (pal.line.name(), pal.text.name(), pal.card_hi.name()))
            b.clicked.connect(slot)
            foot.addWidget(b)
        foot.addStretch(1)
        lay.addLayout(foot)
        return page

    # -- 页 3：截图 ---------------------------------------------------------
    def _page_snip(self):
        pal = self.pal
        page = QWidget()
        page.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(9)

        t = QLabel("截图")
        t.setStyleSheet("color:%s;font-size:17px;font-weight:700;" % pal.text.name())
        lay.addWidget(t)
        sub = QLabel("拖出选区就拍。截完能加标注，然后复制 / 存盘 / 贴到屏幕上。")
        sub.setStyleSheet("color:%s;font-size:11px;" % pal.muted.name())
        lay.addWidget(sub)
        lay.addSpacing(3)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_snip = QPushButton("开始截图")
        self.btn_snip.setCursor(Qt.PointingHandCursor)
        self.btn_snip.setFixedHeight(40)
        self.btn_snip.setStyleSheet(
            "QPushButton{border:none;border-radius:9px;background:%s;color:#FFFFFF;"
            "font-size:13.5px;font-weight:600;}"
            "QPushButton:hover{background:%s;}"
            % (pal.accent.name(), pal.accent.darker(112).name()))
        self.btn_snip.clicked.connect(self.app.start_snip)
        row.addWidget(self.btn_snip, 1)

        self.btn_pin = QPushButton("贴图剪贴板")
        self.btn_pin.setCursor(Qt.PointingHandCursor)
        self.btn_pin.setFixedHeight(40)
        self.btn_pin.setToolTip("把剪贴板里的图钉在屏幕上")
        self.btn_pin.setStyleSheet(
            "QPushButton{border:1px solid %s;border-radius:9px;background:transparent;"
            "color:%s;font-size:13px;}"
            "QPushButton:hover{background:%s;}"
            % (pal.line.name(), pal.text.name(), pal.card_hi.name()))
        self.btn_pin.clicked.connect(self.app.pin_clipboard)
        row.addWidget(self.btn_pin, 1)
        lay.addLayout(row)

        self.snip_hk_lb = QLabel("")
        self.snip_hk_lb.setWordWrap(True)
        self.snip_hk_lb.setStyleSheet("color:%s;font-size:11px;" % pal.muted.name())
        lay.addWidget(self.snip_hk_lb)
        lay.addSpacing(2)

        path_box = QFrame()
        path_box.setStyleSheet(
            "QFrame{background:%s;border:1px solid %s;border-radius:9px;}"
            % (pal.card_hi.name(), pal.line.name()))
        pl = QHBoxLayout(path_box)
        pl.setContentsMargins(11, 7, 8, 7)
        bl = QVBoxLayout()
        bl.setSpacing(1)
        cap = QLabel("保存位置")
        cap.setStyleSheet("color:%s;font-size:10px;border:none;" % pal.muted.name())
        self.snip_path_lb = QLabel("")
        self.snip_path_lb.setStyleSheet("color:%s;font-size:11.5px;border:none;"
                                        % pal.text.name())
        bl.addWidget(cap)
        bl.addWidget(self.snip_path_lb)
        pl.addLayout(bl, 1)
        for text, slot in (("更改…", self._pick_snip_dir), ("打开", self._open_snip_dir)):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(26)
            b.setStyleSheet(
                "QPushButton{border:1px solid %s;border-radius:6px;background:transparent;"
                "color:%s;font-size:11px;padding:0 10px;}"
                "QPushButton:hover{background:rgba(127,127,127,0.16);color:%s;}"
                % (pal.line.name(), pal.muted.name(), pal.text.name()))
            b.clicked.connect(slot)
            pl.addWidget(b)
        lay.addWidget(path_box)

        self.sw_snipkeys = self._setting_row(
            lay, "启用截图快捷键",
            "关掉后 F1 / F3 归还给其它程序（浏览器帮助、查找下一个等）")
        self.sw_snipkeys.toggled.connect(self._on_snip_keys)

        self.sw_snipcopy = self._setting_row(
            lay, "截完自动复制", "不用再按一次 Ctrl+V，截完就在剪贴板里")
        self.sw_snipcopy.toggled.connect(lambda on: self._set_flag("snip_copy", on))

        self.sw_snipsave = self._setting_row(
            lay, "截完自动存盘", "每张都落到上面的保存位置，同时仍然进剪贴板")
        self.sw_snipsave.toggled.connect(lambda on: self._set_flag("snip_save", on))

        self.sw_pintop = self._setting_row(
            lay, "贴图窗口置顶", "关掉后贴图会跟其它窗口一起被盖住")
        self.sw_pintop.toggled.connect(lambda on: self._set_flag("pin_top", on))

        lay.addSpacing(2)
        lay.addWidget(self._hint_card(
            "Enter 复制 · Ctrl+S 保存 · F3 贴图 · Ctrl+A 全屏 · ESC 取消\n"
            "标注 Ctrl+Z/Y 撤销重做 · 方向键微调 · 折线逐点点击后双击收尾\n"
            "贴图贴在原位置 · 拖边角缩放（拖角锁比例）· 双击还原 100%"))
        lay.addStretch(1)
        return page

    def _on_snip_keys(self, on):
        self.app.set_snip_hotkeys(on)

    def _pick_snip_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择截图保存目录", self._app_snip_dir())
        if d:
            self.app.cfg["general"]["snip_dir"] = d
            self.app.save_cfg()
            self.refresh()

    def _open_snip_dir(self):
        d = self._app_snip_dir()
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def _app_snip_dir(self):
        d = self.cfg["general"].get("snip_dir") or ""
        import snip as snipmod
        return d if d else snipmod.default_save_dir()

    # -- 页 4：设置 ---------------------------------------------------------
    def _page_settings(self):
        pal = self.pal
        page = QWidget()
        page.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        t = QLabel("设置")
        t.setStyleSheet("color:%s;font-size:17px;font-weight:700;" % pal.text.name())
        lay.addWidget(t)
        lay.addSpacing(4)

        self.sw_auto_start = self._setting_row(
            lay, "开机自启动", "登录后自动在托盘里待命")
        self.sw_auto_start.toggled.connect(self._on_autostart)

        self.sw_tray = self._setting_row(
            lay, "启动时直接进托盘", "打开工具不弹窗，只留托盘图标")
        self.sw_tray.toggled.connect(lambda on: self._set_flag("tray_start", on))

        self.sw_edge = self._setting_row(
            lay, "显示屏幕右侧入口条", "那条很淡的小竖条，点它滑出抽屉")
        self.sw_edge.toggled.connect(self._on_edge)

        self.sw_autotidy = self._setting_row(
            lay, "自动整理新文件", "关掉后文件留在桌面，等你点「一键整理」")
        self.sw_autotidy.toggled.connect(lambda on: self._set_flag("auto_tidy", on))

        self.sw_virtual = self._setting_row(
            lay, "把系统图标收进抽屉",
            "「计算机 / 回收站 / 主目录」不是文件，搬不走；开启后隐藏桌面图标，在抽屉「应用」里给同等入口")
        self.sw_virtual.toggled.connect(self._on_virtual)

        # 说明写清楚代价：公共桌面是系统级目录，不是"多扫一个文件夹"这么简单
        self.sw_public = None
        if sysenv.IS_WINDOWS:
            self.sw_public = self._setting_row(
                lay, "整理公共桌面快捷方式",
                "「所有用户」装的软件（Office / 微信 / QQ…）图标在 C:\\Users\\Public\\Desktop。"
                "系统只给删除权限、不给写回权限，所以撤销时图标会放回你自己的桌面")
            self.sw_public.toggled.connect(self._on_public_desktop)

        lay.addSpacing(6)
        hint = QFrame()
        hint.setStyleSheet("QFrame{background:%s;border:1px solid %s;border-radius:9px;}"
                           % (pal.card_hi.name(), pal.line.name()))
        hl = QHBoxLayout(hint)
        hl.setContentsMargins(12, 10, 12, 10)
        left = QVBoxLayout()
        left.setSpacing(1)
        a = QLabel("透明度快捷键")
        a.setStyleSheet("color:%s;font-size:12px;font-weight:600;border:none;"
                        % pal.text.name())
        self.hotkey_lb = QLabel("")
        self.hotkey_lb.setStyleSheet("color:%s;font-size:10.5px;border:none;"
                                     % pal.muted.name())
        left.addWidget(a)
        left.addWidget(self.hotkey_lb)
        hl.addLayout(left, 1)
        lay.addWidget(hint)

        lay.addStretch(1)

        foot = QHBoxLayout()
        b = QPushButton("恢复任务栏系统默认")
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedHeight(30)
        b.setStyleSheet(
            "QPushButton{border:1px solid %s;border-radius:8px;background:transparent;"
            "color:%s;font-size:11.5px;padding:0 14px;}"
            "QPushButton:hover{background:%s;}"
            % (pal.line.name(), pal.muted.name(), pal.card_hi.name()))
        b.clicked.connect(self._restore_panel)
        foot.addWidget(b)
        foot.addStretch(1)
        self.ver_lb = QLabel("")
        self.ver_lb.setStyleSheet("color:%s;font-size:10px;" % pal.muted.name())
        foot.addWidget(self.ver_lb)
        lay.addLayout(foot)
        return page

    def _hint_card(self, text):
        pal = self.pal
        card = QFrame()
        card.setStyleSheet("QFrame{background:%s;border:1px solid %s;border-radius:9px;}"
                           % (pal.card_hi.name(), pal.line.name()))
        cl = QHBoxLayout(card)
        cl.setContentsMargins(11, 9, 11, 9)
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:%s;font-size:10.5px;border:none;" % pal.muted.name())
        cl.addWidget(lb)
        return card

    def _setting_row(self, lay, title, desc):
        pal = self.pal
        row = QFrame()
        row.setStyleSheet("QFrame{background:transparent;border:none;}")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 4, 0, 4)
        box = QVBoxLayout()
        box.setSpacing(1)
        a = QLabel(title)
        a.setStyleSheet("color:%s;font-size:12.5px;font-weight:600;border:none;"
                        % pal.text.name())
        b = QLabel(desc)
        b.setWordWrap(True)
        b.setStyleSheet("color:%s;font-size:10.5px;border:none;" % pal.muted.name())
        box.addWidget(a)
        box.addWidget(b)
        rl.addLayout(box, 1)
        sw = Switch(pal)
        rl.addWidget(sw, 0, Qt.AlignVCenter)
        lay.addWidget(row)
        return sw

    # -- 样式 ---------------------------------------------------------------
    def _chip_qss(self):
        pal = self.pal
        return """
        QPushButton{border:1px solid %s;border-radius:8px;background:transparent;
            font-size:12px;color:%s;padding:0 16px;}
        QPushButton:hover{background:%s;}
        QPushButton:checked{border:1px solid %s;background:%s;color:#FFFFFF;font-weight:600;}
        """ % (pal.line.name(), pal.text.name(), pal.card_hi.name(),
               pal.accent.name(), pal.accent.name())

    def _seg_qss(self):
        pal = self.pal
        return """
        QPushButton{border:1px solid %s;border-radius:7px;background:transparent;
            font-size:11px;color:%s;}
        QPushButton:hover{background:%s;}
        QPushButton:checked{border:1px solid %s;color:%s;background:%s;font-weight:600;}
        """ % (pal.line.name(), pal.muted.name(), pal.card_hi.name(),
               pal.accent.name(), pal.accent.name(), pal.card_hi.name())

    # -- 背景 ---------------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 14, 14)
        p.fillPath(path, QBrush(self.pal.bg))
        p.setPen(QPen(self.pal.line, 1))
        p.drawPath(path)
        p.end()

    # -- 数据刷新 -----------------------------------------------------------
    def refresh(self):
        cfg = self.cfg
        lo = int(round(self.app.panel.min_alpha() * 100))
        hi = int(round(self.app.panel.max_alpha() * 100))
        # 配置里可能存着后端做不到的值（老版本拖到 0，而 Windows 下限是 10%）。
        # 先夹到范围内再显示，否则会出现"数字 0% 但滑块停在 10%"的自相矛盾。
        alpha = max(lo, min(hi, int(round(self.app.panel.get_alpha() * 100)))) / 100.0
        self.slider.blockSignals(True)
        self.slider.setRange(lo, hi)
        self.slider.setValue(int(round(alpha * 100)))
        self.slider.blockSignals(False)
        self._sync_panel(alpha)

        self.sw_glass.set_silent(self.app.panel.glass_on())
        # Windows 上"玻璃质感"这个开关没有可见效果（系统磨砂由透明效果开关控制），
        # 藏起来，别留一个按了没反应的开关。
        self.glass_row.setVisible(not sysenv.IS_WINDOWS)
        self._apply_mode_ui()
        lv = self.app.panel.blur_level()
        for k, b in self.blur_btns.items():
            b.setChecked(k == lv)

        data = self.app.org.summary()
        for cat in rules.CATEGORY_ORDER:
            self._stats[cat].set_count(rules.count_items(cat, data.get(cat, [])))

        pend = self.app.org.pending_count()
        if pend:
            self.pending_lb.setText("桌面上有 %d 项待归类" % pend)
            self.pending_sub.setText("点「一键整理」按类型归到桌面的 .桌面抽屉 里，随时可撤销")
            self.btn_tidy.setEnabled(True)
        else:
            self.pending_lb.setText("桌面很干净")
            self.pending_sub.setText("没有待归类的文件；新存到桌面的文件会重新出现在这里")
            self.btn_tidy.setEnabled(False)

        if hasattr(self, "snip_path_lb"):
            self.snip_path_lb.setText(
                self.app._snip_dir().replace(os.path.expanduser("~"), "~"))
            errs = self.app.hotkey_errors()
            on = self.app.snip_hotkeys_on()
            self.sw_snipkeys.set_silent(on)
            if on:
                tip = "截图 %s · 固定尺寸 %s · 贴图 %s" % (
                    self.app.snip_hotkey_pretty(),
                    self.app.snip_fixed_hotkey_pretty(),
                    self.app.pin_hotkey_pretty())
                bad = [k for k in ("snip", "snip_fixed", "pin")
                       if k in errs]
                if bad:
                    tip += "   ⚠ 有 %d 个键没注册上" % len(bad)
            else:
                tip = "截图快捷键已关闭，F1 / F3 归还给其它程序"
            self.snip_hk_lb.setText(tip)
            self.sw_snipcopy.set_silent(self.app.flag("snip_copy"))
            self.sw_snipsave.set_silent(self.app.flag("snip_save"))
            self.sw_pintop.set_silent(self.app.flag("pin_top"))

        self.sw_auto_start.set_silent(self.app.autostart_on())
        self.sw_tray.set_silent(self.app.flag("tray_start"))
        self.sw_edge.set_silent(self.app.flag("show_edge"))
        self.sw_autotidy.set_silent(self.app.flag("auto_tidy"))
        if getattr(self, "sw_public", None) is not None:
            self.sw_public.set_silent(self.app.flag("public_desktop"))
        try:
            self.sw_virtual.set_silent(bool(launchers.virtual_hidden()))
        except Exception:
            self.sw_virtual.set_silent(False)

        self.hotkey_lb.setText("%s  ·  循环切换四档材质" % self.app.hotkey_pretty())
        try:
            self.blur_row.setVisible(self.app.panel.supports_blur_level())
        except Exception:
            pass
        self.ver_lb.setText("v%s · %s" % (VERSION, os.path.basename(self.app.org.root)))
        self.rail_tip.setText("归档位置\n%s" % self.app.org.root.replace(
            os.path.expanduser("~"), "~"))

    def _sync_panel(self, alpha):
        self.pct.setText("%d%%" % int(round(alpha * 100)))
        self.preview.set_state(alpha, self.app.panel.glass_on())
        for key, label, val in PRESETS:
            self.chips[key].setChecked(abs(alpha - val) < 0.05)

    def show_result(self, text, undoable=True):
        self.result_lb.setText(text)
        self.btn_undo.setVisible(undoable)
        self.result.setVisible(True)
        # 同一个定时器重复 start()：连续整理两次时，不能被上一次的 6 秒定时器提前藏掉
        if getattr(self, "_result_timer", None) is None:
            self._result_timer = QTimer(self)
            self._result_timer.setSingleShot(True)
            self._result_timer.setInterval(6000)
            self._result_timer.timeout.connect(lambda: self.result.setVisible(False))
        self._result_timer.start()

    # -- 交互 ---------------------------------------------------------------
    def _on_slider(self, v):
        """拖动过程中只更新预览，绝不碰系统设置。

        Linux 上一次 set_alpha 要起好几个 gsettings 子进程（每个 30–80ms，还在主线程），
        100 格全落盘就是几十秒卡顿；这里先用防抖计时器攒着，停手 180ms 后一次性提交。
        """
        alpha = v / 100.0
        try:
            self._sync_panel(alpha)
        except Exception:
            pass
        if getattr(self, "_alpha_timer", None) is None:
            self._alpha_timer = QTimer(self)
            self._alpha_timer.setSingleShot(True)
            self._alpha_timer.setInterval(180)
            self._alpha_timer.timeout.connect(self._commit_alpha)
        self._alpha_timer.start()

    def _commit_alpha(self):
        """把滑块当前值真正写进系统，并把「实际生效值」回写到滑块。

        真正写系统的那一步丢到线程池去做；上一次还没回来时只置 dirty 标记，
        等回调里补跑一次最新值——既不会并发写系统设置，也不会丢掉最后一次调整。
        """
        if getattr(self, "_alpha_timer", None) is not None:
            self._alpha_timer.stop()
        if self._alpha_job is not None:
            self._alpha_dirty = True
            return
        alpha = self.slider.value() / 100.0
        self._alpha_req = alpha
        job = _AlphaJob(self.app.panel, alpha)
        # 连到成员方法（QObject 上的槽）才会走队列连接，回到主线程执行；
        # 直接连 lambda 会在线程池线程里跑，改 UI 会崩。
        job.signals.done.connect(self._on_alpha_done)
        self._alpha_job = job
        self._alpha_pool.start(job)

    def _on_alpha_done(self, actual, err):
        """线程池回调：写盘、回弹滑块、补跑脏值，全部留在主线程。"""
        self._alpha_job = None
        requested = self._alpha_req
        if err:
            self.panel_status.setText("设置失败：%s" % err)
        else:
            try:
                self.app.save_cfg()      # 配置写盘留在主线程，别和界面抢同一份 ini
                self._sync_panel(actual)
                # 玻璃开启时系统会把透明度钳在 92%，滑块必须跟着回弹，
                # 否则 UI 显示 100% 而真实值是 92%——用户以为设置生效了。
                if requested is not None and abs(actual - requested) > 0.005:
                    self.slider.blockSignals(True)
                    self.slider.setValue(int(round(actual * 100)))
                    self.slider.blockSignals(False)
            except Exception as e:
                self.panel_status.setText("设置失败：%s" % e)
        if self._alpha_dirty:
            self._alpha_dirty = False
            self._commit_alpha()

    def _on_preset(self, val):
        """预设档位：只改滑块，落盘统一走异步提交，避免点击瞬间卡一下。"""
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(val * 100)))
        self.slider.blockSignals(False)
        self._sync_panel(val)
        self._commit_alpha()

    def _on_autohide(self, on):
        """自动隐藏与整窗淡出互斥：切过去之前先把对方的痕迹摘干净。"""
        try:
            self.app.panel.set_taskbar_mode(
                self.app.panel.MODE_AUTOHIDE if on else self.app.panel.MODE_FADE)
            self.app.save_cfg()
            if not on:
                # 关掉自动隐藏后回到淡出模式，滑块的值原样恢复
                self._apply_slider_range()
                self._sync_panel(self.app.panel.get_alpha())
            self._apply_mode_ui()
            self.panel_status.setText(
                "任务栏已设为自动隐藏：鼠标碰到屏幕底边才会滑出来" if on
                else "任务栏已恢复常驻，外观由下面的滑块控制")
        except Exception as e:
            self.panel_status.setText("设置失败：%s" % e)

    def _on_inject(self, on):
        """真·全透明：走注入。失败时把开关弹回去并把原因说清楚，不留假状态。"""
        try:
            if on:
                self.panel_status.setText("正在把透明组件送进资源管理器……")
                QApplication.processEvents()      # 注入要等对方回应，先让这句话上屏
                self.app.panel.set_taskbar_mode(self.app.panel.MODE_INJECT)
            else:
                self.app.panel.set_taskbar_mode(self.app.panel.MODE_FADE)
            self.app.save_cfg()
            if not on:
                self._apply_slider_range()
                self._sync_panel(self.app.panel.get_alpha())
            self._apply_mode_ui()
            self.panel_status.setText(
                "任务栏已完全透明：背景交给壁纸，图标不受影响。"
                "资源管理器重启后会自动重连" if on
                else "已恢复：透明画刷已还回系统，任务栏回到下面的滑块控制")
        except Exception as e:
            self.panel_status.setText("设置失败：%s" % e)
            self._apply_mode_ui()          # 以真实状态回同步，别让开关停在"开"

    def _on_style(self, key=None):
        """点档位胶囊切档。失败（注入被拦、组件被删）就把选中态拨回真实档位，
        不留假选中。"""
        if not key:
            return
        try:
            label = dict((k, l) for k, l, _v in self.app.panel.STYLES).get(key, key)
            if key != "solid":
                self.panel_status.setText("正在应用「%s」……" % label)
                QApplication.processEvents()    # 注入要等对方回应，先让这句话上屏
            self.app.panel.set_style(key)
            self.app.save_cfg()
            self._apply_mode_ui()
            self.panel_status.setText("任务栏外观已设为「%s」" % label)
        except Exception as e:
            self.panel_status.setText("设置失败：%s" % e)
            self._apply_mode_ui()

    def _apply_mode_ui(self):
        """按当前实际状态同步界面：开关位置、各组是否可见、第三方工具提示。"""
        try:
            auto = bool(self.app.panel.get_autohide()) if self.app.panel.supports_autohide() else False
        except Exception:
            auto = False
        try:
            mode = self.app.panel.taskbar_mode()
        except Exception:
            mode = "fade"
        inj = mode == getattr(self.app.panel, "MODE_INJECT", "inject")

        # Windows：档位条。档位由后端 current_style() 推导，不信界面自己的
        # 记忆——注入失败时后端会把配置退回，选中态必须跟着退。
        if hasattr(self, "style_chips"):
            try:
                key = self.app.panel.current_style()
            except Exception:
                key = "solid"
            self.style_chips.set_current(key)

        if hasattr(self, "sw_autohide"):
            self.sw_autohide.set_silent(auto)
        if hasattr(self, "sw_inject"):
            self.sw_inject.set_silent(inj)
        # 下面这批控件在 Windows 上已被「档位下拉」整体取代（见上方构建处的
        # 隐藏逻辑）。它们不在布局里，一旦 setVisible(True) 就会全部叠在页面
        # (0,0) 互相糊成一团——所以这些显隐切换只允许麒麟走，Windows 永远藏。
        if not sysenv.IS_WINDOWS:
            if hasattr(self, "inject_note"):
                self.inject_note.setVisible(inj)
            if hasattr(self, "autohide_row"):
                # 注入模式下另外两套都收起：同时出现只会让人以为能叠着用
                self.autohide_row.setVisible(self.app.panel.supports_autohide() and not inj)
            if hasattr(self, "fade_box"):
                self.fade_box.setVisible(not auto and not inj)
            if hasattr(self, "pct"):
                self.pct.setVisible(not auto and not inj)
            if hasattr(self, "glass_row"):
                self.glass_row.setVisible(not inj)      # 玻璃质感对注入模式没意义
        if hasattr(self, "tools_hint"):
            try:
                tools = self.app.panel.running_taskbar_tools()
            except Exception:
                tools = []
            if tools:
                # 只说是"第三方工具"，不点名：这页是给普通用户看的，
                # 点名既没必要，也容易让人以为必须装那个东西。
                self.tools_hint.setText(
                    "检测到有第三方任务栏美化工具正在运行：它和本工具改的是同一块任务栏，"
                    "两者同时启用会互相覆盖，建议只留一个")
            self.tools_hint.setVisible(bool(tools))

    def _on_glass(self, on):
        self.app.panel.set_glass(on)
        try:
            if on:
                self.app.panel.apply_glass()
                self._sync_panel(self.app.panel.get_alpha())
            self.app.save_cfg()
            self._apply_slider_range()
            self.panel_status.setText(
                "玻璃质感已开启：透明度上限 %d%%" % int(GLASS_MAX_ALPHA * 100) if on
                else "玻璃质感已关闭：可拉到 100%（会变成实心色块）")
        except Exception as e:
            self.panel_status.setText("设置失败：%s" % e)

    def _apply_slider_range(self):
        """玻璃开启时把滑块上限钳到 92%，别让用户拉到系统根本达不到的档位。"""
        try:
            top = int(round(self.app.panel.max_alpha() * 100))
        except Exception:
            top = 100
        cur = self.slider.value()
        self.slider.blockSignals(True)
        self.slider.setRange(0, top)
        self.slider.setValue(min(cur, top))
        self.slider.blockSignals(False)
        self._sync_panel(self.slider.value() / 100.0)

    def _on_blur(self, level):
        self.app.panel.set_blur_level(level)
        self.app.save_cfg()
        for k, b in self.blur_btns.items():
            b.setChecked(k == level)
        self.panel_status.setText("磨砂强度：%s" % BLUR_NAMES.get(level, ""))

    def _on_autostart(self, on):
        ok = self.app.set_autostart(on)
        if not ok:
            self.sw_auto_start.set_silent(not on)

    def _on_virtual(self, on):
        ok = launchers.set_virtual_hidden(on)
        if not ok:
            self.sw_virtual.set_silent(not on)
            self.panel_status.setText("需要在正常桌面会话中才能修改（dconf 写入失败）")
            return
        self.app.drawer.refresh()

    def _on_edge(self, on):
        self._set_flag("show_edge", on)
        self.app.apply_edge()

    def _on_public_desktop(self, on):
        """公共桌面纳入/移出整理：改配置 + 重建监听器 + 刷新所有视图。"""
        self._set_flag("public_desktop", on)
        try:
            self.app.rebuild_watcher()
        except Exception:
            pass
        self.refresh()
        self.app.drawer.refresh()
        if on:
            self.app._toast("已纳入公共桌面，待整理 %d 项" % self.app.org.pending_count())
        else:
            self.app._toast("公共桌面已排除：本机其它账号的图标不再受影响")

    def _set_flag(self, key, on):
        self.app.cfg["general"][key] = "1" if on else "0"
        self.app.save_cfg()

    def _undo(self):
        n = self.app.undo()
        self.refresh()
        self.show_result("已放回桌面 %d 项" % n if n else "没有可撤销的记录", undoable=False)

    def _restore_panel(self):
        try:
            self.app.panel.restore()
            self.refresh()
            self.panel_status.setText("已恢复系统默认")
        except Exception as e:
            self.panel_status.setText("恢复失败：%s" % e)

    def _show_rules(self):
        from PyQt5.QtWidgets import QMessageBox
        lines = []
        for cat in rules.CATEGORY_ORDER:
            lines.append("%-5s  %s" % (cat, rules.CATEGORY_DESC.get(cat, "")))
        lines.append("")
        lines.append("永不移动：.desktop 启动器、. 开头的锁文件、符号链接、挂载点")
        QMessageBox.information(self, "归类规则", "\n".join(lines))

    # -- 无边框拖动 ---------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()
        else:
            super(MainWindow, self).keyPressEvent(e)

    def closeEvent(self, e):
        e.ignore()
        self.hide()
