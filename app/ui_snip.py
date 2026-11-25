#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— 截图交互

三个窗口：
  SnipOverlay   全屏遮罩：拖选、调整、标注
  SnipBar       浮在选区旁边的工具条
  PinWindow     贴在屏幕上的图（可拖、可缩放、可调透明度）
"""

import os

from PyQt5.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (QColor, QFont, QCursor, QGuiApplication, QIcon, QPainter,
                         QPainterPath, QPen, QPixmap, QPolygonF)
from PyQt5.QtWidgets import (QAbstractButton, QApplication, QFileDialog, QFrame,
                             QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
                             QToolTip, QVBoxLayout, QWidget)

import snip

HANDLE = 7          # 把手半边长
MIN_SEL = 4         # 小于这个尺寸当作误触


def shape_rect(p0, p1, shift=None):
    """方框／圆形的外接矩形。

    shift=None 时读当前键盘状态；按住 Shift 边长取两边较大的那个，
    变正方形／正圆，拖动方向（四个象限）不变。
    """
    if shift is None:
        shift = bool(QApplication.keyboardModifiers() & Qt.ShiftModifier)
    x0, y0, x1, y1 = p0.x(), p0.y(), p1.x(), p1.y()
    if shift:
        side = max(abs(x1 - x0), abs(y1 - y0))
        x1 = x0 + (side if x1 >= x0 else -side)
        y1 = y0 + (side if y1 >= y0 else -side)
    return QRect(QPoint(x0, y0), QPoint(x1, y1)).normalized()


# --------------------------------------------------------------------------- #
# 小部件
# --------------------------------------------------------------------------- #
def draw_glyph(p, kind, r, color):
    """在 r 里画一个 18×18 的图标。工具条不依赖图标主题，自己画最稳。"""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(color, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    x, y, w, h = r.x(), r.y(), r.width(), r.height()

    def pt(fx, fy):
        return QPointF(x + w * fx, y + h * fy)

    if kind == "arrow":
        p.drawLine(pt(0.18, 0.82), pt(0.80, 0.20))
        p.drawLine(pt(0.80, 0.20), pt(0.52, 0.24))
        p.drawLine(pt(0.80, 0.20), pt(0.76, 0.48))

    elif kind == "rect":
        p.drawRect(QRectF(x + w * 0.16, y + h * 0.18, w * 0.68, h * 0.64))

    elif kind == "ellipse":
        p.drawEllipse(QRectF(x + w * 0.16, y + h * 0.18, w * 0.68, h * 0.64))

    elif kind == "poly":
        p.drawPolyline(QPolygonF([pt(0.14, 0.74), pt(0.40, 0.26),
                                  pt(0.62, 0.66), pt(0.86, 0.22)]))

    elif kind == "pen":
        p.drawLine(pt(0.22, 0.78), pt(0.74, 0.26))
        p.setBrush(QColor(color))
        p.drawPolygon(QPolygonF([pt(0.20, 0.80), pt(0.36, 0.74), pt(0.26, 0.64)]))

    elif kind == "marker":
        # 斜放的马克笔：笔杆 + 斜头
        p.drawLine(QPointF(x + w * 0.34, y + h * 0.66), QPointF(x + w * 0.78, y + h * 0.22))
        p.drawLine(QPointF(x + w * 0.34, y + h * 0.66), QPointF(x + w * 0.22, y + h * 0.78))
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(x + w * 0.20, y + h * 0.80),
                                 QPointF(x + w * 0.40, y + h * 0.74),
                                 QPointF(x + w * 0.26, y + h * 0.60)]))

    elif kind == "mosaic":
        p.setPen(Qt.NoPen)
        for i in range(3):
            for j in range(3):
                if (i + j) % 2 == 0:
                    p.setBrush(QColor(color))
                    p.drawRect(QRectF(x + w * (0.16 + i * 0.24), y + h * (0.16 + j * 0.24),
                                      w * 0.20, h * 0.20))

    elif kind == "text":
        f = QFont()
        f.setPixelSize(int(h * 0.82))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QPen(color))
        p.drawText(r, Qt.AlignCenter, "T")

    elif kind == "undo":
        path = QPainterPath()
        path.moveTo(x + w * 0.30, y + h * 0.70)
        path.lineTo(x + w * 0.30, y + h * 0.40)
        path.cubicTo(x + w * 0.34, y + h * 0.22, x + w * 0.72, y + h * 0.22,
                     x + w * 0.74, y + h * 0.52)
        p.drawPath(path)
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(x + w * 0.30, y + h * 0.78),
                                 QPointF(x + w * 0.18, y + h * 0.62),
                                 QPointF(x + w * 0.42, y + h * 0.62)]))

    elif kind == "redo":
        p.save()
        p.translate(x + w, y)
        p.scale(-1, 1)
        p.translate(-x, -y)
        draw_glyph(p, "undo", r, color)
        p.restore()

    elif kind == "pin":
        # 图钉：梯形帽 + 竖针
        p.drawPolygon(QPolygonF([pt(0.32, 0.18), pt(0.68, 0.18),
                                 pt(0.58, 0.46), pt(0.42, 0.46)]))
        p.drawLine(pt(0.50, 0.46), pt(0.50, 0.82))

    elif kind == "save":
        p.drawLine(pt(0.50, 0.16), pt(0.50, 0.58))
        p.drawPolyline(QPolygonF([pt(0.30, 0.40), pt(0.50, 0.60), pt(0.70, 0.40)]))
        p.drawLine(pt(0.20, 0.78), pt(0.80, 0.78))

    elif kind == "copy":
        p.drawRect(QRectF(x + w * 0.16, y + h * 0.16, w * 0.44, h * 0.44))
        p.drawRect(QRectF(x + w * 0.38, y + h * 0.38, w * 0.44, h * 0.44))

    elif kind == "close":
        p.drawLine(pt(0.28, 0.28), pt(0.72, 0.72))
        p.drawLine(pt(0.72, 0.28), pt(0.28, 0.72))

    p.restore()


class ToolButton(QAbstractButton):
    """工具条上的方按钮：自己画图标，选中/悬停有自己的底色。"""

    def __init__(self, glyph, tip, pal, checkable=False, size=28, text=None):
        super(ToolButton, self).__init__()
        self.glyph = glyph
        self.text = text
        self.pal = pal
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(checkable)
        self.setFixedSize(size, 26)
        self.setFocusPolicy(Qt.NoFocus)
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pal = self.pal
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        if self.isChecked():
            p.setPen(Qt.NoPen)
            p.setBrush(pal.accent)
            p.drawRoundedRect(r, 6, 6)
        elif self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(127, 127, 127, 46))
            p.drawRoundedRect(r, 6, 6)

        fg = QColor("#FFFFFF") if self.isChecked() else QColor(pal.text)
        if not self.isEnabled():
            fg.setAlpha(70)

        if self.text:
            f = QFont()
            f.setPixelSize(12)
            p.setFont(f)
            p.setPen(QPen(fg))
            p.drawText(self.rect(), Qt.AlignCenter, self.text)
        else:
            side = min(self.width(), self.height()) - 6
            box = QRect(0, 0, side, side)
            box.moveCenter(self.rect().center())
            draw_glyph(p, self.glyph, QRectF(box), fg)
        p.end()


class ColorDot(QWidget):
    """颜色圆点。选中的那个外面加一圈白环。"""

    picked = pyqtSignal(str)

    def __init__(self, hex_color, pal):
        super(ColorDot, self).__init__()
        self.hex = hex_color
        self.pal = pal
        self.active = False
        self._hover = False
        self.setFixedSize(20, 20)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(hex_color)

    def set_active(self, on):
        if self.active != on:
            self.active = on
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.picked.emit(self.hex)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        if self.active:
            p.setPen(QPen(QColor("#FFFFFF"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(1.5, 1.5, self.width() - 3, self.height() - 3))
        r = 6.5 if not self._hover else 7.5
        p.setPen(QPen(QColor(0, 0, 0, 70), 1))
        p.setBrush(QColor(self.hex))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()


# --------------------------------------------------------------------------- #
# 工具条
# --------------------------------------------------------------------------- #
class SnipBar(QWidget):
    """浮在选区旁边的工具条。布局照 Snipaste：工具 / 颜色 / 线宽 / 撤销重做 / 输出。"""

    toolPicked = pyqtSignal(str)
    colorPicked = pyqtSignal(str)
    widthPicked = pyqtSignal(int)
    acted = pyqtSignal(str)          # undo / redo / pin / save / copy / close

    def __init__(self, pal, color="#E5484D", width=3):
        super(SnipBar, self).__init__(None, Qt.Tool | Qt.FramelessWindowHint |
                                      Qt.WindowStaysOnTopHint)
        self.pal = pal
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(1)

        # 工具
        self.tools = {}
        for key, name, _ in snip.TOOLS:
            b = ToolButton(key, "%s（再点一次取消）" % name, pal, checkable=True)
            b.clicked.connect(lambda _=False, k=key: self._tool(k))
            lay.addWidget(b)
            self.tools[key] = b

        lay.addSpacing(5)
        lay.addWidget(self._sep())

        # 颜色
        lay.addSpacing(4)
        self.dots = []
        for _, hx in snip.COLORS:
            d = ColorDot(hx, pal)
            d.picked.connect(self.colorPicked.emit)
            lay.addWidget(d)
            self.dots.append(d)

        lay.addSpacing(5)
        lay.addWidget(self._sep())

        # 线宽（用逐渐变粗的圆点表示）
        lay.addSpacing(4)
        self.widths = {}
        for name, w in snip.WIDTHS:
            b = WidthButton(w, "线宽 %d px" % w, pal)
            b.clicked.connect(lambda _=False, v=w: self._width(v))
            lay.addWidget(b)
            self.widths[w] = b

        lay.addSpacing(5)
        lay.addWidget(self._sep())

        # 撤销 / 重做
        lay.addSpacing(4)
        self.btn_undo = ToolButton("undo", "撤销上一个标注  Ctrl+Z", pal)
        self.btn_undo.clicked.connect(lambda: self.acted.emit("undo"))
        lay.addWidget(self.btn_undo)

        self.btn_redo = ToolButton("redo", "重做  Ctrl+Y", pal)
        self.btn_redo.clicked.connect(lambda: self.acted.emit("redo"))
        lay.addWidget(self.btn_redo)

        lay.addSpacing(5)
        lay.addWidget(self._sep())

        # 输出
        lay.addSpacing(4)
        self.btn_pin = ToolButton("pin", "贴到屏幕上  F3", pal)
        self.btn_pin.clicked.connect(lambda: self.acted.emit("pin"))
        lay.addWidget(self.btn_pin)

        self.btn_save = ToolButton("save", "保存到截图文件夹  Ctrl+S", pal)
        self.btn_save.clicked.connect(lambda: self.acted.emit("save"))
        lay.addWidget(self.btn_save)

        self.btn_copy = ToolButton("copy", "复制到剪贴板  Enter", pal)
        self.btn_copy.clicked.connect(lambda: self.acted.emit("copy"))
        lay.addWidget(self.btn_copy)

        lay.addWidget(self._sep())
        b = ToolButton("close", "取消  ESC", pal)
        b.clicked.connect(lambda: self.acted.emit("close"))
        lay.addWidget(b)

        self.set_color(color)
        self.set_width(width)
        self.adjustSize()

    def _sep(self):
        f = QFrame()
        f.setFixedWidth(1)
        f.setFixedHeight(18)
        f.setStyleSheet("background:%s;border:none;" % self.pal.line.name())
        return f

    # -- 状态 ---------------------------------------------------------------
    def _tool(self, key):
        active = self.tools[key].isChecked()
        for k, b in self.tools.items():
            b.setChecked(False)
        if active:
            self.tools[key].setChecked(True)
            self.toolPicked.emit(key)
        else:
            self.toolPicked.emit("")     # 取消标注工具，回到框选

    def _width(self, w):
        for k, b in self.widths.items():
            b.setChecked(k == w)
        self.widthPicked.emit(w)

    def set_color(self, hex_color):
        for d in self.dots:
            d.set_active(d.hex.lower() == hex_color.lower())

    def set_width(self, w):
        for k, b in self.widths.items():
            b.setChecked(k == w)

    def clear_tool(self):
        for b in self.tools.values():
            b.setChecked(False)

    def set_undo_redo(self, can_undo, can_redo):
        self.btn_undo.setEnabled(can_undo)
        self.btn_redo.setEnabled(can_redo)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 9, 9)
        p.fillPath(path, QColor(self.pal.card))
        p.setPen(QPen(QColor(self.pal.line), 1))
        p.drawPath(path)
        p.end()


class WidthButton(ToolButton):
    """线宽按钮：画一个由细到粗的圆点，比写"细/中/粗"省地方。"""

    def __init__(self, width, tip, pal):
        super(WidthButton, self).__init__("", tip, pal, checkable=True, size=26)
        self.line_width = width

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isChecked():
            p.setPen(Qt.NoPen)
            p.setBrush(self.pal.accent)
            p.drawRoundedRect(r, 6, 6)
        elif self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(127, 127, 127, 46))
            p.drawRoundedRect(r, 6, 6)
        fg = QColor("#FFFFFF") if self.isChecked() else QColor(self.pal.text)
        rad = 2 + self.line_width
        p.setPen(Qt.NoPen)
        p.setBrush(fg)
        p.drawEllipse(QPointF(self.width() / 2.0, self.height() / 2.0), rad, rad)
        p.end()


# --------------------------------------------------------------------------- #
# 框选遮罩
# --------------------------------------------------------------------------- #
class SnipOverlay(QWidget):
    """全屏遮罩：拖出选区 → 调整 → 标注 → 复制 / 保存 / 贴图。"""

    done = pyqtSignal(object, str)     # (QPixmap 或 None, 动作)

    def __init__(self, canvas, virt, screen, pal, cfg,
                 fixed_size=None, auto_copy=False):
        super(SnipOverlay, self).__init__(None, Qt.FramelessWindowHint |
                                          Qt.WindowStaysOnTopHint | Qt.Tool)
        self.canvas = canvas
        self.virt = virt
        self.screen_geo = screen.geometry()
        self.dpr = screen.devicePixelRatio() or 1.0
        self.pal = pal
        self.cfg = cfg

        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setGeometry(self.screen_geo)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)

        # 这块屏幕在 canvas 里的起点（设备像素）
        self.origin = QPoint(int((self.screen_geo.x() - virt.x()) * self.dpr),
                             int((self.screen_geo.y() - virt.y()) * self.dpr))

        self.shot = None            # 有选区之后才建
        self.state = "idle"         # idle / selecting / adjust / moving / resizing / drawing
        self.sel = QRect()          # 设备像素，相对本控件
        self._press = QPoint()
        self._origin_sel = QRect()
        self._handle = ""
        self._pts = []
        self._temp = None
        self._cursor = QPoint()

        self.tool = ""
        self.color = snip.COLORS[0][1]
        self.pen_w = snip.WIDTHS[1][1]
        self.bar = None
        self._text = None
        self.pin_pos = None     # 贴图该放在哪（选区左上角的全局坐标）

        # 固定尺寸截图（Shift+F1）：选区始终保持这个尺寸，拖着定位
        if fixed_size is None:
            self.fixed_size = None
        elif isinstance(fixed_size, QSize):
            self.fixed_size = QSize(fixed_size)
        else:
            self.fixed_size = QSize(int(fixed_size[0]), int(fixed_size[1]))
        # 截屏并自动复制（F2）：框完直接复制，不进标注
        self.auto_copy = auto_copy
        self._poly_done = False

    # -- 坐标 ---------------------------------------------------------------
    def dev(self, pt):
        """控件逻辑坐标 → 设备像素坐标（相对控件）。"""
        return QPoint(int(pt.x() * self.dpr), int(pt.y() * self.dpr))

    def _canvas_rect(self, dev_rect):
        """控件设备坐标 → canvas 坐标。"""
        return dev_rect.translated(self.origin)

    # -- 生命周期 -----------------------------------------------------------
    def start(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)

    def close_all(self, pixmap=None, action="cancel"):
        if self._text is not None:
            self._text.hide()
        if self.bar is not None:
            self.bar.hide()
            self.bar.deleteLater()
            self.bar = None
        self.hide()
        self.done.emit(pixmap, action)
        self.deleteLater()

    # -- 绘制 ---------------------------------------------------------------
    def paintEvent(self, e):
        if self.canvas is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        p.scale(1.0 / self.dpr, 1.0 / self.dpr)

        w = int(self.width() * self.dpr)
        h = int(self.height() * self.dpr)
        full = QRect(0, 0, w, h)
        src = QRect(self.origin, QSize(w, h))

        # 底图 + 压暗
        p.drawPixmap(full, self.canvas, src)
        p.fillRect(full, QColor(0, 0, 0, 118))

        sel = self.sel
        if sel.width() > 0 and sel.height() > 0:
            # 选区内恢复亮度
            p.drawPixmap(sel, self.canvas, self._canvas_rect(sel))

            # 标注（已完成的 + 正在画的）
            if self.shot is not None:
                p.save()
                p.translate(-sel.topLeft())
                for sh in self.shot.shapes:
                    self.shot.draw_shape(p, sh)
                if self._temp:
                    self.shot.draw_shape(p, self._temp)
                p.restore()

            # 边框
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#FFFFFF"), 1))
            p.drawRect(QRectF(sel).adjusted(-0.5, -0.5, -0.5, -0.5))

            # 把手
            if self.state in ("adjust", "resizing", "idle") and not self.tool:
                p.setPen(QPen(QColor(self.pal.accent), 1))
                p.setBrush(QColor("#FFFFFF"))
                for pt in self._handle_points().values():
                    p.drawRect(QRectF(pt.x() - HANDLE / 2.0, pt.y() - HANDLE / 2.0,
                                      HANDLE, HANDLE))
            self._draw_size_tip(p, sel)
        else:
            self._draw_tips(p)

        self._draw_magnifier(p)
        p.end()

    def _handle_points(self):
        s = self.sel
        x1, y1, x2, y2 = s.left(), s.top(), s.right(), s.bottom()
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        return {"tl": QPoint(x1, y1), "tr": QPoint(x2, y1),
                "bl": QPoint(x1, y2), "br": QPoint(x2, y2),
                "l": QPoint(x1, int(cy)), "r": QPoint(x2, int(cy)),
                "t": QPoint(int(cx), y1), "b": QPoint(int(cx), y2)}

    def _draw_size_tip(self, p, sel):
        text = "%d × %d" % (sel.width(), sel.height())
        f = QFont()
        f.setPixelSize(12)
        p.setFont(f)
        fm = p.fontMetrics()
        tw = fm.width(text) + 12
        th = fm.height() + 6
        # 优先放选区左上角外面，放不下就放里面
        x = sel.left()
        y = sel.top() - th - 4
        if y < 0:
            y = sel.top() + 4
        if x + tw > self.width() * self.dpr:
            x = sel.right() - tw
        box = QRectF(x, y, tw, th)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(22, 24, 28, 220))
        p.drawRoundedRect(box, 4, 4)
        p.setPen(QPen(QColor("#FFFFFF")))
        p.drawText(box, Qt.AlignCenter, text)

    def _draw_tips(self, p):
        f = QFont()
        f.setPixelSize(13)
        p.setFont(f)
        text = "拖动框选区域  ·  ESC 取消"
        fm = p.fontMetrics()
        w = fm.width(text) + 26
        h = fm.height() + 16
        cx = int(self.width() * self.dpr / 2 - w / 2)
        cy = int(self.height() * self.dpr / 2 - h / 2)
        box = QRectF(cx, cy, w, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(22, 24, 28, 205))
        p.drawRoundedRect(box, 8, 8)
        p.setPen(QPen(QColor("#FFFFFF")))
        p.drawText(box, Qt.AlignCenter, text)

    def _draw_magnifier(self, p):
        """鼠标旁边的像素放大镜 —— 像素级对齐全指望它。"""
        # 只在还在挑区域的时候显示放大镜；框定之后再显示就纯挡视线了
        if self.state not in ("idle", "selecting"):
            return
        if self.canvas is None:
            return
        step = 40
        cur = self._cursor
        src = QRect(cur.x() - step // 2, cur.y() - step // 2, step, step)
        src = src.intersected(QRect(QPoint(0, 0), self.canvas.size()))
        if src.width() < 4:
            return
        zoom = 4
        size = step * zoom
        pm = self.canvas.copy(src).scaled(size, size, Qt.IgnoreAspectRatio,
                                          Qt.FastTransformation)

        w = self.width() * self.dpr
        h = self.height() * self.dpr
        x = cur.x() + 22
        y = cur.y() + 22
        if x + size + 4 > w:
            x = cur.x() - size - 22
        if y + size + 30 > h:
            y = h - size - 30
        y = max(4, y)
        p.drawPixmap(QPoint(int(x), int(y)), pm)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 160), 1))
        p.drawRect(QRectF(x - 0.5, y - 0.5, size + 1, size + 1))
        # 准星
        p.setPen(QPen(QColor(self.pal.accent), 1))
        cx = x + size / 2.0
        cy = y + size / 2.0
        p.drawLine(QPointF(cx, y), QPointF(cx, y + size))
        p.drawLine(QPointF(x, cy), QPointF(x + size, cy))

        # 坐标 + 颜色
        tip = "%d, %d" % (src.center().x(), src.center().y())
        f = QFont()
        f.setPixelSize(11)
        p.setFont(f)
        fm = p.fontMetrics()
        box = QRectF(x, y + size + 3, size, fm.height() + 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(22, 24, 28, 200))
        p.drawRoundedRect(box, 3, 3)
        p.setPen(QPen(QColor("#FFFFFF")))
        p.drawText(box, Qt.AlignCenter, tip)

    # -- 鼠标 ---------------------------------------------------------------
    def _bound(self):
        return QRect(0, 0, int(self.width() * self.dpr), int(self.height() * self.dpr))

    def _press_for_fixed(self, pt):
        """固定尺寸模式：以鼠标为中心放一个固定大小的框。"""
        w = int(self.fixed_size.width() * self.dpr)
        h = int(self.fixed_size.height() * self.dpr)
        r = QRect(pt.x() - w // 2, pt.y() - h // 2, w, h)
        # 贴边时别跑出屏幕
        if r.left() < 0:
            r.moveLeft(0)
        if r.top() < 0:
            r.moveTop(0)
        if r.right() > self._bound().right():
            r.moveRight(self._bound().right())
        if r.bottom() > self._bound().bottom():
            r.moveBottom(self._bound().bottom())
        return r

    def mousePressEvent(self, e):
        self.setFocus(Qt.OtherFocusReason)
        pt = self.dev(e.pos())
        self._cursor = pt

        if e.button() == Qt.RightButton:
            if self.state == "polying":
                self._finish_poly()           # 右键先收尾折线
            elif self.tool:
                self._set_tool("")            # 再退工具
            else:
                self.close_all(None, "cancel")
            return

        if e.button() != Qt.LeftButton:
            return

        if self._text is not None:
            self._commit_text()

        # 折线：点一下加一个折点，双击/回车/右键收尾
        if self.tool == "poly" and self.state in ("adjust", "polying"):
            if self.state != "polying":
                self._pts = [pt + self._canvas_rect(self.sel).topLeft()]
                self.state = "polying"
            else:
                self._pts.append(pt + self._canvas_rect(self.sel).topLeft())
            self._sync_poly_preview(pt)
            self.update()
            return

        if self.state == "adjust":
            handle = self._hit_handle(pt)
            if handle:
                self.state = "resizing"
                self._handle = handle
                self._press = pt
                self._origin_sel = QRect(self.sel)
                return
            if self.sel.contains(pt) and self.tool:
                self.state = "drawing"
                self._press = pt
                self._start_shape(pt)
                return
            if self.sel.contains(pt):
                self.state = "moving"
                self._press = pt
                self._origin_sel = QRect(self.sel)
                return

        # 重新开一个选区
        self._press = pt
        self.shot = None
        self._temp = None
        if self.fixed_size:
            self.state = "adjust"
            self.sel = self._press_for_fixed(pt)
            self._enter_adjust()
        else:
            self.state = "selecting"
            self.sel = QRect(pt, pt)
            self.update()

    def mouseMoveEvent(self, e):
        pt = self.dev(e.pos())
        self._cursor = pt

        if self.state == "selecting":
            self.sel = QRect(self._press, pt).normalized().intersected(self._bound())
            self.update()

        elif self.state == "polying":
            self._sync_poly_preview(pt)
            self.update()

        elif self.state == "moving":
            delta = pt - self._press
            moved = self._origin_sel.translated(delta)
            bound = self._bound()
            # 别让选区整体挪出屏幕
            dx = min(0, bound.right() - moved.right()) + max(0, bound.left() - moved.left())
            dy = min(0, bound.bottom() - moved.bottom()) + max(0, bound.top() - moved.top())
            self.sel = moved.translated(dx, dy) if (dx or dy) else moved
            self.update()

        elif self.state == "resizing":
            self._resize_to(pt)
            self.update()

        elif self.state == "drawing":
            self._drag_shape(pt)
            self.update()

        else:
            if self.state != "adjust":
                self.state = "idle"
            self.update()

    def _sync_poly_preview(self, pt):
        """折线预览：已定的点 + 当前鼠标位置，看得见下一段往哪走。"""
        base = self._canvas_rect(self.sel).topLeft()
        pts = list(self._pts) + [pt + base]
        self._temp = {"t": "poly", "pts": [QPointF(p) for p in pts],
                      "color": QColor(self.color), "w": self.pen_w}

    def _finish_poly(self):
        if self.state != "polying":
            return
        if len(self._pts) >= 2 and self.shot is not None:
            self.shot.add_poly(self._pts, self.color, self.pen_w)
        self._pts = []
        self._temp = None
        self.state = "adjust"
        self._refresh_bar_state()
        self.update()

    def _resize_to(self, pt):
        r = QRect(self._origin_sel)
        h = self._handle
        if "l" in h:
            r.setLeft(min(pt.x(), r.right() - MIN_SEL))
        if "r" in h:
            r.setRight(max(pt.x(), r.left() + MIN_SEL))
        if "t" in h:
            r.setTop(min(pt.y(), r.bottom() - MIN_SEL))
        if "b" in h:
            r.setBottom(max(pt.y(), r.top() + MIN_SEL))
        self.sel = r.normalized()

    def _hit_handle(self, pt):
        if self.sel.isNull():
            return ""
        for name, p in self._handle_points().items():
            if abs(pt.x() - p.x()) <= HANDLE and abs(pt.y() - p.y()) <= HANDLE:
                return name
        return ""

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pt = self.dev(e.pos())

        if self.state == "selecting":
            self.sel = QRect(self._press, pt).normalized().intersected(
                QRect(0, 0, int(self.width() * self.dpr), int(self.height() * self.dpr)))
            if self.sel.width() < MIN_SEL or self.sel.height() < MIN_SEL:
                self.sel = QRect()
                self.state = "idle"
                self.update()
                return
            self._enter_adjust()
            if self.auto_copy:
                # F2「截屏并自动复制」：框完直接复制走，不弹标注工具条
                self._do("copy")
            return

        if self.state in ("moving", "resizing"):
            self.state = "adjust"
            self._place_bar()
            self.update()
            return

        if self.state == "drawing":
            self._finish_shape(pt)

    def mouseDoubleClickEvent(self, e):
        if self.state == "polying":
            self._finish_poly()
            return
        if self.state == "adjust" and self.sel.contains(self.dev(e.pos())) \
                and not self.tool:
            self._do("copy")

    def _enter_adjust(self):
        self.state = "adjust"
        self.shot = snip.Shot(self.canvas, self._canvas_rect(self.sel))
        self._show_bar()
        self.update()

    # -- 标注 ---------------------------------------------------------------
    def _start_shape(self, pt):
        c = self._canvas_rect(self.sel).topLeft()
        base = pt + c            # 转成 canvas 坐标
        self._pts = [base]       # 起点统一记在这里，几种形状共用
        if self.tool in ("pen", "marker"):
            self._temp = {"t": self.tool, "pts": [QPointF(base)],
                          "color": QColor(self.color), "w": self.pen_w}
        elif self.tool in ("rect", "ellipse", "mosaic"):
            self._temp = {"t": self.tool, "rect": QRect(base, base),
                          "color": QColor(self.color), "w": self.pen_w,
                          "block": 14}
        elif self.tool == "arrow":
            self._temp = {"t": "arrow", "a": QPointF(base), "b": QPointF(base),
                          "color": QColor(self.color), "w": self.pen_w}
        elif self.tool == "text":
            self._begin_text(pt)

    @staticmethod
    def _shape_rect(p0, p1):
        """拖出来的外接框。按住 Shift 就是正方形／正圆，方向仍跟鼠标走。"""
        return shape_rect(p0, p1)

    def _drag_shape(self, pt):
        if not self._temp:
            return
        c = self._canvas_rect(self.sel).topLeft()
        base = pt + c
        if self.tool in ("pen", "marker"):
            self._pts.append(base)
            self._temp["pts"] = [QPointF(p) for p in self._pts]
        elif self.tool in ("rect", "ellipse"):
            self._temp["rect"] = self._shape_rect(self._pts[0], base)
        elif self.tool == "mosaic":
            self._temp["rect"] = QRect(self._pts[0], base).normalized()
        elif self.tool == "arrow":
            self._temp["b"] = QPointF(base)

    def _finish_shape(self, pt):
        if not self._temp:
            self.state = "adjust"
            return
        c = self._canvas_rect(self.sel).topLeft()
        base = pt + c
        sh = self._temp
        if sh["t"] in ("pen", "marker"):
            self._pts.append(base)
            if len(self._pts) >= 2:
                self.shot.add({"t": sh["t"], "pts": [QPointF(p) for p in self._pts],
                               "color": QColor(self.color), "w": self.pen_w})
        elif sh["t"] in ("rect", "ellipse"):
            r = self._shape_rect(self._pts[0], base)
            if r.width() > 2 and r.height() > 2:
                self.shot.add({"t": sh["t"], "rect": r, "color": QColor(self.color),
                               "w": self.pen_w})
        elif sh["t"] == "mosaic":
            r = QRect(self._pts[0], base).normalized()
            if r.width() > 2 and r.height() > 2:
                self.shot.add({"t": "mosaic", "rect": r, "block": 14})
        elif sh["t"] == "arrow":
            a = sh["a"]
            b = QPointF(base)
            if abs(a.x() - b.x()) + abs(a.y() - b.y()) > 6:
                self.shot.add({"t": "arrow", "a": a, "b": b,
                               "color": QColor(self.color), "w": self.pen_w})
        self._temp = None
        self._pts = []
        self.state = "adjust"
        self._refresh_bar_state()
        self.update()

    # -- 文字 ---------------------------------------------------------------
    def _begin_text(self, pt):
        self._temp = None
        self._pts = []
        self.state = "adjust"
        if self._text is not None:
            self._text.deleteLater()
        ed = QLineEdit(self)
        ed.setPlaceholderText("输入文字，回车确认")
        ed.setFixedWidth(max(160, min(320, int(self.sel.width() / self.dpr) - 20)))
        ed.setStyleSheet(
            "QLineEdit{border:1px solid %s;border-radius:5px;background:#FFFFFF;"
            "color:#16181C;font-size:13px;padding:3px 6px;}"
            % self.pal.accent.name())
        ed.move(int(pt.x() / self.dpr) + 4, int(pt.y() / self.dpr) + 2)
        ed.returnPressed.connect(self._commit_text)
        ed.show()
        ed.setFocus()
        self._text = ed
        self._text_at = pt + self._canvas_rect(self.sel).topLeft()

    def _commit_text(self):
        if self._text is None:
            return
        text = self._text.text().strip()
        pos = getattr(self, "_text_at", QPoint(0, 0))
        self._text.deleteLater()
        self._text = None
        self.setFocus(Qt.OtherFocusReason)
        if text and self.shot is not None:
            self.shot.add_text(pos, text, self.color)
        self.update()

    # -- 工具条 -------------------------------------------------------------
    def _show_bar(self):
        if self.bar is None:
            self.bar = SnipBar(self.pal, self.color, self.pen_w)
            self.bar.toolPicked.connect(self._set_tool)
            self.bar.colorPicked.connect(self._set_color)
            self.bar.widthPicked.connect(self._set_width)
            self.bar.acted.connect(self._do)
        self.bar.show()
        self.bar.raise_()
        self._place_bar()

    def _place_bar(self):
        if self.bar is None or self.sel.isNull():
            return
        self.bar.adjustSize()
        bw, bh = self.bar.width(), self.bar.height()
        sel = self.sel
        dpr = self.dpr
        # 选区下方，放不下就上方
        x = int(sel.left() / dpr)
        y = int(sel.bottom() / dpr) + 10
        if y + bh > self.height():
            y = int(sel.top() / dpr) - bh - 10
        y = max(6, min(y, self.height() - bh - 6))
        x = max(6, min(x, self.width() - bw - 6))
        self.bar.move(self.mapToGlobal(QPoint(x, y)))
        self.bar.show()

    def _set_tool(self, key):
        self.tool = key
        if self.bar:
            self.bar.clear_tool()
            if key:
                self.bar.tools[key].setChecked(True)
        if self.state == "polying" and key != "poly":
            self._finish_poly()
        if key == "text":
            self.setCursor(Qt.IBeamCursor)
        else:
            self.setCursor(Qt.CrossCursor)
        self.update()

    def _refresh_bar_state(self):
        if self.bar is None or self.shot is None:
            return
        self.bar.set_undo_redo(bool(self.shot.shapes), self.shot.can_redo())

    def _set_color(self, hex_color):
        self.color = hex_color
        if self.bar:
            self.bar.set_color(hex_color)

    def _set_width(self, w):
        self.pen_w = w
        if self.bar:
            self.bar.set_width(w)

    # -- 动作 ---------------------------------------------------------------
    def _do(self, action):
        if self.shot is None:
            return
        if action == "undo":
            self.shot.undo()
            self._refresh_bar_state()
            self.update()
            return
        if action == "redo":
            self.shot.redo()
            self._refresh_bar_state()
            self.update()
            return
        if action == "close":
            self.close_all(None, "cancel")
            return

        pm = self.shot.render()
        if pm.isNull():
            return
        # 选区的左上角换算成全局逻辑坐标 —— 贴图要飞回原来那块地方
        self.pin_pos = QPoint(
            int(self.screen_geo.x() + self.sel.x() / self.dpr),
            int(self.screen_geo.y() + self.sel.y() / self.dpr))
        # 这里只负责出图并把动作报出去。复制/存盘统一由接收方做，
        # 否则"点保存"和"配置里开了自动存盘"会各存一次，落两个文件。
        self.close_all(pm, action)

    # -- 键盘 ---------------------------------------------------------------
    def keyPressEvent(self, e):
        k = e.key()
        mods = e.modifiers()

        if k == Qt.Key_Escape:
            if self._text is not None:
                self._text.deleteLater()
                self._text = None
                return
            if self.state == "polying":
                # 折线画到一半：先丢掉这条，不退工具
                self._pts = []
                self._temp = None
                self.state = "adjust"
                self.update()
                return
            if self.tool:
                self._set_tool("")
                return
            self.close_all(None, "cancel")
            return

        if k in (Qt.Key_Return, Qt.Key_Enter):
            if self.state == "polying":
                self._finish_poly()
            elif self._text is None:
                self._do("copy")
            return

        if k == Qt.Key_S and (mods & Qt.ControlModifier):
            self._do("save")
            return

        if k == Qt.Key_Z and (mods & Qt.ControlModifier):
            if self.shot is not None:
                self.shot.undo()
                self._refresh_bar_state()
                self.update()
            return

        if k == Qt.Key_Y and (mods & Qt.ControlModifier):
            if self.shot is not None:
                self.shot.redo()
                self._refresh_bar_state()
                self.update()
            return

        if k == Qt.Key_F3:
            self._do("pin")
            return

        if k == Qt.Key_A and (mods & Qt.ControlModifier):
            # 全屏
            self.sel = QRect(0, 0, int(self.width() * self.dpr),
                             int(self.height() * self.dpr))
            self._enter_adjust()
            return

        if k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) \
                and self.state == "adjust":
            step = 10 if (mods & Qt.ShiftModifier) else 1
            dx = (-step if k == Qt.Key_Left else step if k == Qt.Key_Right else 0)
            dy = (-step if k == Qt.Key_Up else step if k == Qt.Key_Down else 0)
            self.sel = self.sel.translated(dx, dy)
            if self.shot is not None:
                self.shot.rect = self._canvas_rect(self.sel)
            self._place_bar()
            self.update()
            return

        super(SnipOverlay, self).keyPressEvent(e)

    def closeEvent(self, e):
        if self.bar is not None:
            self.bar.hide()
        super(SnipOverlay, self).closeEvent(e)


# --------------------------------------------------------------------------- #
# 贴图窗口
# --------------------------------------------------------------------------- #
class PinWindow(QWidget):
    """钉在屏幕上的一张图：拖动移动，拖边角缩放，滚轮缩放，Ctrl+滚轮调透明度。

    默认贴在截图原本的位置（由调用方传入 pos），没有就用屏幕中间 —— 这样
    "贴图"看起来就是把刚框的那一块贴在原地，而不是飞到屏幕中央。
    """

    closed = pyqtSignal(object)

    MIN_SIDE = 24       # 最小边长
    HND = 14            # 角落热区边长
    EDG = 7             # 边热区厚度
    _CURSORS = {"nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
                "sw": Qt.SizeBDiagCursor, "ne": Qt.SizeBDiagCursor,
                "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
                "w": Qt.SizeHorCursor, "e": Qt.SizeHorCursor}

    def __init__(self, pixmap, pal, on_close=None, keep_top=True):
        flags = Qt.Tool | Qt.FramelessWindowHint
        if keep_top:
            flags |= Qt.WindowStaysOnTopHint
        super(PinWindow, self).__init__(None, flags)
        self.pal = pal
        self.on_close = on_close
        self._src = pixmap
        self._drag = None          # 移动：按下点相对窗口左上角的偏移
        self._rs = None            # 缩放：(手柄名, 按下时的几何, 按下时全局坐标)
        self._hnd = ""             # 当前悬停的手柄
        self._hover = False
        self.setMouseTracking(True)
        self.setWindowOpacity(1.0)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("拖动移动 · 拖边角缩放 · 滚轮缩放 · Ctrl+滚轮透明度 · "
                        "双击还原 100% · 右键菜单 · ESC 关闭")

        # 图上像素 → 逻辑像素（高分屏下别把图放大一倍）
        sdpr = pixmap.devicePixelRatio() or 1.0
        self._nat = QSize(max(self.MIN_SIDE, int(round(pixmap.width() / sdpr))),
                          max(self.MIN_SIDE, int(round(pixmap.height() / sdpr))))
        w, h = self._nat.width(), self._nat.height()
        # 太大就缩到屏幕的 80%
        scr = QGuiApplication.primaryScreen().availableGeometry()
        if w > scr.width() * 0.8 or h > scr.height() * 0.8:
            k = min(scr.width() * 0.8 / w, scr.height() * 0.8 / h)
            w, h = int(w * k), int(h * k)
        self.resize(w, h)

    # -- 位置 ---------------------------------------------------------------
    def show_at(self, pos=None):
        """pos 是全局逻辑坐标（一般是原截图的左上角）。"""
        if pos is None:
            scr = QGuiApplication.primaryScreen().availableGeometry()
            pos = QPoint(scr.center().x() - self.width() // 2,
                         scr.center().y() - self.height() // 2)
        pos = QPoint(int(pos.x()), int(pos.y()))
        # 至少留一角在屏幕里，免得贴到看不见的地方
        scr = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        x = min(max(pos.x(), g.left() - self.width() + 80), g.right() - 80)
        y = min(max(pos.y(), g.top()), g.bottom() - 40)
        self.move(x, y)
        self.show()
        self.raise_()

    # -- 绘制 ---------------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.drawPixmap(self.rect(), self._src)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        p.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        p.setPen(QPen(QColor(255, 255, 255, 135), 1))
        p.drawRect(QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5))

        if self._hover:
            self._paint_handles(p)
            # 右上角关闭点
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawEllipse(QPoint(self.width() - 13, 13), 9, 9)
            p.setPen(QPen(QColor("#FFFFFF"), 1.6))
            p.drawLine(QPoint(self.width() - 17, 9), QPoint(self.width() - 9, 17))
            p.drawLine(QPoint(self.width() - 9, 9), QPoint(self.width() - 17, 17))

            f = QFont()
            f.setPixelSize(11)
            p.setFont(f)
            zoom = int(round(self.width() * 100.0 / max(1, self._nat.width())))
            tip = "%d×%d  %d%%" % (self.width(), self.height(), zoom)
            op = int(round(self.windowOpacity() * 100))
            if op < 100:
                tip += "  不透明 %d%%" % op
            fm = p.fontMetrics()
            box = QRectF(6, self.height() - fm.height() - 10,
                         fm.width(tip) + 10, fm.height() + 4)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawRoundedRect(box, 4, 4)
            p.setPen(QPen(QColor("#FFFFFF")))
            p.drawText(box, Qt.AlignCenter, tip)
        p.end()

    def _paint_handles(self, p):
        """在四条边 + 三个角画小方块（右上角留给关闭按钮）。"""
        if self.width() < 56 or self.height() < 56:
            return
        w, h = self.width(), self.height()
        i = 3.5                      # 往里收一点，方块才不会被边框切掉一半
        pts = [(w / 2.0, i), (w / 2.0, h - i), (i, h / 2.0), (w - i, h / 2.0),
               (i, i), (i, h - i), (w - i, h - i)]
        side = 7.0
        p.setPen(QPen(QColor(0, 0, 0, 120), 1))
        p.setBrush(QColor(255, 255, 255, 240))
        for cx, cy in pts:
            p.drawRect(QRectF(cx - side / 2.0, cy - side / 2.0, side, side))

    # -- 命中判断 -----------------------------------------------------------
    def _close_zone(self, pos):
        return (pos.x() >= self.width() - self.HND and pos.y() <= self.HND)

    def _hit(self, pos):
        """鼠标落在哪个缩放手柄上，返回 nw/n/ne/e/se/s/sw/w 或空串。"""
        if self.width() < 56 or self.height() < 56:
            return ""
        if self._close_zone(pos):
            return ""
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        H, E = self.HND, self.EDG
        if x <= H and y <= H:
            return "nw"
        if x <= H and y >= h - H:
            return "sw"
        if x >= w - H and y >= h - H:
            return "se"
        if y <= E:
            return "n"
        if y >= h - E:
            return "s"
        if x <= E:
            return "w"
        if x >= w - E:
            return "e"
        return ""

    def _apply_cursor(self):
        self.setCursor(self._CURSORS.get(self._hnd, Qt.OpenHandCursor))

    # -- 交互 ---------------------------------------------------------------
    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self._hnd = ""
        self.setCursor(Qt.OpenHandCursor)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self._menu(e.globalPos())
            return
        if e.button() != Qt.LeftButton:
            return
        if self._close_zone(e.pos()):
            self.close_pin()
            return
        hnd = self._hit(e.pos())
        if hnd:
            self._rs = (hnd, QRect(self.geometry()), e.globalPos())
            self._hnd = hnd
            self._apply_cursor()
            return
        self._drag = e.globalPos() - self.frameGeometry().topLeft()
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._rs is not None:
            self._apply_resize(e.globalPos())
            return
        if self._drag is not None:
            self.move(e.globalPos() - self._drag)
            return
        hnd = self._hit(e.pos())
        if hnd != self._hnd:
            self._hnd = hnd
            self._apply_cursor()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._rs is not None:
            self._rs = None
            self._hnd = self._hit(e.pos())
            self._apply_cursor()
            self.update()
            return
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.LeftButton or self._hit(e.pos()):
            return
        # 双击 = 100% 原图尺寸 / 回到铺满前的比例，以中心为锚点
        if self.width() == self._nat.width() and self.height() == self._nat.height():
            scr = QGuiApplication.screenAt(e.globalPos()) or \
                QGuiApplication.primaryScreen()
            g = scr.availableGeometry()
            k = min(g.width() * 0.8 / self._nat.width(),
                    g.height() * 0.8 / self._nat.height(), 1.0)
            nw, nh = int(self._nat.width() * k), int(self._nat.height() * k)
        else:
            nw, nh = self._nat.width(), self._nat.height()
        c = self.geometry().center()
        self.setGeometry(c.x() - nw // 2, c.y() - nh // 2,
                         max(self.MIN_SIDE, nw), max(self.MIN_SIDE, nh))
        self.update()

    # -- 缩放 ---------------------------------------------------------------
    def _apply_resize(self, gpos):
        hnd, g0, p0 = self._rs
        dx = gpos.x() - p0.x()
        dy = gpos.y() - p0.y()
        w0, h0 = g0.width(), g0.height()
        l, t, w, h = g0.left(), g0.top(), w0, h0
        mn = self.MIN_SIDE
        free = bool(QApplication.keyboardModifiers() & Qt.ShiftModifier)

        if hnd in ("nw", "ne", "sw", "se"):
            nw = (w0 - dx) if hnd in ("nw", "sw") else (w0 + dx)
            nh = (h0 - dy) if hnd in ("nw", "ne") else (h0 + dy)
            nw, nh = max(mn, nw), max(mn, nh)
            if not free:
                # 角拖默认锁比例：按变化更大的那个方向定缩放，图不会变形
                rw = float(nw) / max(1, w0) - 1.0
                rh = float(nh) / max(1, h0) - 1.0
                k = (float(nw) / max(1, w0)) if abs(rw) >= abs(rh) \
                    else (float(nh) / max(1, h0))
                k = min(k, 30.0)
                nw = max(mn, int(round(w0 * k)))
                nh = max(mn, int(round(h0 * k)))
            w, h = nw, nh
            if hnd in ("nw", "sw"):
                l = g0.right() + 1 - w
            if hnd in ("nw", "ne"):
                t = g0.bottom() + 1 - h
        elif hnd in ("n", "s"):
            h = max(mn, (h0 - dy) if hnd == "n" else (h0 + dy))
            if hnd == "n":
                t = g0.bottom() + 1 - h
        else:   # w / e
            w = max(mn, (w0 - dx) if hnd == "w" else (w0 + dx))
            if hnd == "w":
                l = g0.right() + 1 - w

        if (l, t, w, h) != (g0.left(), g0.top(), w0, h0):
            self.setGeometry(l, t, w, h)
            self.update()

    def _scale_by(self, k):
        nw = max(self.MIN_SIDE, min(6000, int(round(self.width() * k))))
        nh = max(self.MIN_SIDE, min(6000, int(round(self.height() * k))))
        if (nw, nh) == (self.width(), self.height()):
            return
        c = self.geometry().center()      # 以中心为锚点，看起来不飘
        self.setGeometry(c.x() - nw // 2, c.y() - nh // 2, nw, nh)
        self.update()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            op = self.windowOpacity() + (0.06 if e.angleDelta().y() > 0 else -0.06)
            self.setWindowOpacity(max(0.15, min(1.0, op)))
            self.update()
            return
        step = 1.1 if e.angleDelta().y() > 0 else 1 / 1.1
        self._scale_by(step)

    def _menu(self, gpos):
        m = QMenu(self)
        m.setStyleSheet(
            "QMenu{background:%s;border:1px solid %s;padding:5px;border-radius:8px;}"
            "QMenu::item{padding:6px 22px;border-radius:5px;font-size:12.5px;color:%s;}"
            "QMenu::item:selected{background:%s;}"
            % (self.pal.card.name(), self.pal.line.name(),
               self.pal.text.name(), self.pal.card_hi.name()))
        a = m.addAction("复制")
        b = m.addAction("另存为…")
        m.addSeparator()
        z = m.addAction("还原为 100%")
        m.addSeparator()
        c = m.addAction("不透明度 100%")
        d = m.addAction("不透明度 70%")
        e = m.addAction("不透明度 40%")
        m.addSeparator()
        f = m.addAction("关闭")
        act = m.exec_(gpos)
        if act is a:
            snip.to_clipboard(self._src)
        elif act is b:
            path, _ = QFileDialog.getSaveFileName(self, "另存为", snip.next_path(),
                                                  "PNG 图片 (*.png)")
            if path:
                self._src.save(path, "PNG")
        elif act is z:
            c0 = self.geometry().center()
            nw = max(self.MIN_SIDE, self._nat.width())
            nh = max(self.MIN_SIDE, self._nat.height())
            self.setGeometry(c0.x() - nw // 2, c0.y() - nh // 2, nw, nh)
            self.update()
        elif act is c:
            self.setWindowOpacity(1.0)
            self.update()
        elif act is d:
            self.setWindowOpacity(0.7)
            self.update()
        elif act is e:
            self.setWindowOpacity(0.4)
            self.update()
        elif act is f:
            self.close_pin()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close_pin()

    def close_pin(self):
        self.hide()
        if self.on_close:
            self.on_close(self)
        self.deleteLater()
