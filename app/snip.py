#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— 截图引擎

只管三件事：
  1. 把屏幕抓下来（多屏拼成一张虚拟桌面）
  2. 把标注画进图里
  3. 存盘 / 进剪贴板

交互（框选遮罩、工具条、贴图窗口）在 ui_snip.py，这里不含任何 QWidget。

坐标约定：**全部用设备像素**。canvas 的 devicePixelRatio 固定为 1，
高分屏的缩放换算交给 overlay 层自己做 —— 这样 copy/pixmap 这类按像素
工作的接口不会出现半像素错位。
"""

import math
import os
import time

from PyQt5.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt5.QtGui import (QColor, QFont, QGuiApplication, QImage, QPainter,
                         QPainterPath, QPen, QPixmap, QPolygonF)

# 标注可选的颜色与线宽（跟截图工具的习惯一致：红黄绿蓝白黑）
COLORS = [
    ("红", "#E5484D"),
    ("橙", "#F5A524"),
    ("绿", "#30A46C"),
    ("蓝", "#0091FF"),
    ("白", "#FFFFFF"),
    ("黑", "#16181C"),
]
WIDTHS = [("细", 2), ("中", 3), ("粗", 5)]

# 工具顺序跟 Snipaste 的工具条一致：箭头 / 方框 / 圆形 / 折线 / 画笔 / 记号笔 / 马赛克 / 文字
TOOLS = [("arrow", "箭头", "A"), ("rect", "方框", "R"), ("ellipse", "圆形", "O"),
         ("poly", "折线", "L"), ("pen", "画笔", "P"), ("marker", "记号笔", "H"),
         ("mosaic", "马赛克", "M"), ("text", "文字", "T")]


# --------------------------------------------------------------------------- #
# 抓屏
# --------------------------------------------------------------------------- #
def grab_virtual():
    """抓整个虚拟桌面，返回 (QPixmap, QRect 虚拟桌面几何，逻辑坐标)。

    多屏时把所有屏画到同一张画布上，位置与系统排列一致。
    """
    screens = QGuiApplication.screens()
    if not screens:
        return None, QRect()

    virt = QRect()
    for s in screens:
        virt = virt.united(s.geometry())
    if virt.isEmpty():
        return None, QRect()

    dpr = max([s.devicePixelRatio() for s in screens] or [1.0])
    canvas = QPixmap(int(virt.width() * dpr), int(virt.height() * dpr))
    canvas.fill(QColor("#000000"))
    canvas.setDevicePixelRatio(1.0)          # 统一按设备像素处理

    p = QPainter(canvas)
    p.setRenderHint(QPainter.SmoothPixmapTransform, False)
    for s in screens:
        pm = s.grabWindow(0)
        if pm.isNull():
            continue
        g = s.geometry()
        target = QRect(int((g.x() - virt.x()) * dpr), int((g.y() - virt.y()) * dpr),
                       int(g.width() * dpr), int(g.height() * dpr))
        p.drawPixmap(target, pm)
    p.end()
    return canvas, virt


def looks_blank(pixmap, samples=8):
    """采样判断整张图是不是同一个颜色 —— 用来发现"抓屏其实是黑屏"。

    没有合成器（或 kwin 没启用特效）时，grabWindow(0) 只会拿到窗口内容，
    桌面背景是黑的。这时候截出来一片黑，不提示的话用户以为是自己的问题。
    """
    if pixmap is None or pixmap.isNull():
        return True
    img = pixmap.toImage()
    w, h = img.width(), img.height()
    if w < samples or h < samples:
        return False
    first = img.pixel(w // 2, h // 2)
    for i in range(samples):
        for j in range(samples):
            x = int((i + 0.5) * w / samples)
            y = int((j + 0.5) * h / samples)
            if img.pixel(x, y) != first:
                return False
    return True


def pixelate(src, rect, block=12):
    """从 src 取 rect 那块做马赛克，返回该区域大小的 QPixmap。

    缩小再放大 —— 用 FastTransformation 才是硬边方块，平滑插值会变成糊。
    """
    rect = rect.intersected(QRect(QPoint(0, 0), src.size()))
    if rect.width() < 2 or rect.height() < 2:
        return QPixmap()
    sub = src.copy(rect)
    small = sub.scaled(max(1, rect.width() // block), max(1, rect.height() // block),
                       Qt.IgnoreAspectRatio, Qt.FastTransformation)
    return small.scaled(rect.width(), rect.height(),
                        Qt.IgnoreAspectRatio, Qt.FastTransformation)


# --------------------------------------------------------------------------- #
# 一次截图
# --------------------------------------------------------------------------- #
class Shot(object):
    """原图 + 选区 + 标注。选区坐标是相对 canvas 的设备像素。"""

    def __init__(self, canvas, rect):
        self.canvas = canvas
        self.rect = QRect(rect).normalized()
        self.shapes = []
        self._redo = []
        self._cache = {}

    # -- 标注 ---------------------------------------------------------------
    def add(self, shape):
        self.shapes.append(shape)
        self._redo = []          # 画了新东西，重做链就断了
        self._cache.clear()

    def undo(self):
        if not self.shapes:
            return False
        self._redo.append(self.shapes.pop())
        self._cache.clear()
        return True

    def redo(self):
        if not self._redo:
            return False
        self.shapes.append(self._redo.pop())
        self._cache.clear()
        return True

    def can_redo(self):
        return bool(self._redo)

    def clear_shapes(self):
        self.shapes = []
        self._cache.clear()

    def add_rect(self, rect, color, width):
        self.add({"t": "rect", "rect": QRect(rect).normalized(),
                  "color": QColor(color), "w": width})

    def add_ellipse(self, rect, color, width):
        self.add({"t": "ellipse", "rect": QRect(rect).normalized(),
                  "color": QColor(color), "w": width})

    def add_arrow(self, a, b, color, width):
        self.add({"t": "arrow", "a": QPointF(a), "b": QPointF(b),
                  "color": QColor(color), "w": width})

    def add_pen(self, pts, color, width):
        if len(pts) < 2:
            return
        self.add({"t": "pen", "pts": [QPointF(p) for p in pts],
                  "color": QColor(color), "w": width})

    def add_poly(self, pts, color, width):
        if len(pts) < 2:
            return
        self.add({"t": "poly", "pts": [QPointF(p) for p in pts],
                  "color": QColor(color), "w": width})

    def add_marker(self, pts, color, width):
        if len(pts) < 2:
            return
        self.add({"t": "marker", "pts": [QPointF(p) for p in pts],
                  "color": QColor(color), "w": width})

    def add_text(self, pos, text, color, size=17):
        self.add({"t": "text", "pos": QPointF(pos), "text": text,
                  "color": QColor(color), "size": size})

    def add_mosaic(self, rect, block=12):
        self.add({"t": "mosaic", "rect": QRect(rect).normalized(), "block": block})

    # -- 渲染 ---------------------------------------------------------------
    def _mosaic_pix(self, sh):
        key = (sh["rect"].x(), sh["rect"].y(), sh["rect"].width(),
               sh["rect"].height(), sh["block"])
        if key not in self._cache:
            self._cache[key] = pixelate(self.canvas, sh["rect"], sh["block"])
        return self._cache[key]

    def _draw(self, p, sh):
        t = sh["t"]
        color = sh.get("color", QColor("#E5484D"))
        w = sh.get("w", 3)

        if t == "rect":
            p.setPen(QPen(color, w, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin))
            p.setBrush(Qt.NoBrush)
            r = sh["rect"]
            inset = w / 2.0
            p.drawRect(QRectF(r).adjusted(inset, inset, -inset, -inset))

        elif t == "ellipse":
            # 内缩半个线宽，让描边完整落在拖出来的框里（跟方框一致）
            p.setPen(QPen(color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            r = sh["rect"]
            inset = w / 2.0
            box = QRectF(r).adjusted(inset, inset, -inset, -inset)
            if box.width() > 1 and box.height() > 1:
                p.drawEllipse(box)

        elif t == "arrow":
            a, b = sh["a"], sh["b"]
            p.setPen(QPen(color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawLine(a, b)
            ang = math.atan2(b.y() - a.y(), b.x() - a.x())
            size = max(11.0, w * 4.2)
            p.setPen(QPen(color, w, Qt.SolidLine, Qt.RoundCap))
            for d in (0.44, -0.44):
                p.drawLine(b, QPointF(b.x() - size * math.cos(ang - d),
                                      b.y() - size * math.sin(ang - d)))

        elif t in ("pen", "poly"):
            p.setPen(QPen(color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF(sh["pts"]))

        elif t == "marker":
            # 荧光笔：半透明 + 粗，压在文字上还能看见底下
            hl = QColor(color)
            hl.setAlpha(95)
            pen = QPen(hl, max(w * 4, 12), Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF(sh["pts"]))

        elif t == "text":
            f = QFont()
            f.setPixelSize(sh.get("size", 17))
            f.setBold(True)
            p.setFont(f)
            fm = p.fontMetrics()
            pad = 4
            box = fm.boundingRect(sh["text"]).adjusted(-pad, -pad, pad, pad)
            box.moveTopLeft(QPoint(int(sh["pos"].x()), int(sh["pos"].y())))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 130))
            p.drawRoundedRect(QRectF(box).adjusted(-2, -1, 2, 1), 4, 4)
            p.setPen(QPen(color))
            p.drawText(QPoint(int(sh["pos"].x()), int(sh["pos"].y() + fm.ascent())),
                       sh["text"])

        elif t == "mosaic":
            pm = self._mosaic_pix(sh)
            if not pm.isNull():
                p.drawPixmap(sh["rect"].topLeft(), pm)

    def draw_shape(self, painter, shape):
        """给框选界面复用：把一条标注画到任意 painter 上。

        调用方负责先把 painter 平移到画布坐标系（translate(-选区左上角)）。
        """
        self._draw(painter, shape)

    def render(self):
        """裁出选区并画上标注。返回 QPixmap（设备像素，dpr=1）。"""
        area = self.rect.intersected(QRect(QPoint(0, 0), self.canvas.size()))
        if area.isEmpty():
            return QPixmap()
        out = self.canvas.copy(area)
        if not self.shapes:
            return out
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.translate(-area.topLeft())
        for sh in self.shapes:
            self._draw(p, sh)
        p.end()
        return out


# --------------------------------------------------------------------------- #
# 落地
# --------------------------------------------------------------------------- #
def pictures_dir():
    """找一个像样的图片目录（麒麟中文环境是 ~/图片）。"""
    home = os.path.expanduser("~")
    for name in ("图片", "Pictures", "图像"):
        d = os.path.join(home, name)
        if os.path.isdir(d):
            return d
    return home


def default_save_dir():
    return os.path.join(pictures_dir(), "截图")


def next_path(directory=None, prefix="截图"):
    directory = directory or default_save_dir()
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError:
        directory = os.path.expanduser("~")
    base = "%s_%s" % (prefix, time.strftime("%Y%m%d_%H%M%S"))
    p = os.path.join(directory, base + ".png")
    i = 2
    while os.path.exists(p):
        p = os.path.join(directory, "%s_%d.png" % (base, i))
        i += 1
    return p


def save(pixmap, path=None):
    """存 PNG，返回实际路径（失败返回空串）。"""
    if pixmap is None or pixmap.isNull():
        return ""
    path = path or next_path()
    try:
        if pixmap.save(path, "PNG"):
            return path
    except Exception:
        pass
    return ""


def to_clipboard(pixmap):
    try:
        QGuiApplication.clipboard().setPixmap(pixmap)
        return True
    except Exception:
        return False


def from_clipboard():
    """取剪贴板里的图（贴图用）。没有图返回 None。"""
    try:
        md = QGuiApplication.clipboard().mimeData()
        if md is not None and md.hasImage():
            img = QGuiApplication.clipboard().image()
            if not img.isNull():
                return QPixmap.fromImage(img)
        pm = QGuiApplication.clipboard().pixmap()
        return None if pm.isNull() else pm
    except Exception:
        return None
