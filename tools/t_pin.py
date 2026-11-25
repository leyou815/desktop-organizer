#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离屏自测：贴图定位 + 鼠标拖拽缩放。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import QApplication

import ui_snip

app = QApplication([])


class Pal(object):
    card = QColor("#FFFFFF")
    line = QColor("#DDDDDD")
    text = QColor("#222222")
    card_hi = QColor("#EEEEEE")


fails = []


def check(name, got, want):
    ok = got == want
    print("%-28s %-24s %s" % (name, str(got), "OK" if ok else "期望 %s  <-- 失败" % (want,)))
    if not ok:
        fails.append(name)


def geo(p):
    g = p.geometry()
    return (g.x(), g.y(), g.width(), g.height())


pm = QPixmap(300, 200)
pm.fill(QColor("#3366AA"))

# ---- 1. 贴图落在原截图位置 ------------------------------------------------
pin = ui_snip.PinWindow(pm, Pal())
pin.show_at(QPoint(120, 80))
check("贴图位置(原位)", geo(pin)[:2], (120, 80))
check("贴图尺寸", geo(pin)[2:], (300, 200))

# ---- 2. 拖右下角：锁比例放大 ---------------------------------------------
g0 = QRect(pin.geometry())
pin._rs = ("se", g0, QPoint(g0.x(), g0.y()))
pin._apply_resize(QPoint(g0.x() + 60, g0.y() + 40))       # 宽 +20%
check("拖右下角(比例锁定)", geo(pin), (120, 80, 360, 240))
pin._rs = None

# ---- 3. 拖左上角：锁比例，左下锚点不动 -----------------------------------
pin.setGeometry(120, 80, 300, 200)
g0 = QRect(pin.geometry())
pin._rs = ("nw", g0, QPoint(g0.x(), g0.y()))
pin._apply_resize(QPoint(g0.x() - 30, g0.y() - 20))       # 宽 +10% 高 +10%
check("拖左上角(比例锁定)", geo(pin), (90, 60, 330, 220))
check("右下角锚点不动", (geo(pin)[0] + geo(pin)[2], geo(pin)[1] + geo(pin)[3]),
      (g0.x() + g0.width(), g0.y() + g0.height()))
pin._rs = None

# ---- 4. 拖左边：只改宽 ---------------------------------------------------
pin.setGeometry(120, 80, 300, 200)
g0 = QRect(pin.geometry())
pin._rs = ("w", g0, QPoint(g0.x(), g0.y() + 100))
pin._apply_resize(QPoint(g0.x() - 40, g0.y() + 100))
check("拖左边(只改宽)", geo(pin), (80, 80, 340, 200))
pin._rs = None

# ---- 5. 拖下边：只改高 ---------------------------------------------------
pin.setGeometry(120, 80, 300, 200)
g0 = QRect(pin.geometry())
pin._rs = ("s", g0, QPoint(g0.x() + 150, g0.y()))
pin._apply_resize(QPoint(g0.x() + 150, g0.y() + 50))
check("拖下边(只改高)", geo(pin), (120, 80, 300, 250))
pin._rs = None

# ---- 6. 缩到最小时到底线 ------------------------------------------------
pin.setGeometry(120, 80, 300, 200)
g0 = QRect(pin.geometry())
pin._rs = ("se", g0, QPoint(g0.x(), g0.y()))
pin._apply_resize(QPoint(g0.x() - 2000, g0.y() - 2000))
check("最小边长 %d" % ui_snip.PinWindow.MIN_SIDE, geo(pin)[2:],
      (ui_snip.PinWindow.MIN_SIDE, ui_snip.PinWindow.MIN_SIDE))
pin._rs = None

# ---- 7. 手柄命中 ---------------------------------------------------------
pin.setGeometry(120, 80, 300, 200)
check("命中 右下角", pin._hit(QPoint(298, 198)), "se")
check("命中 左上角", pin._hit(QPoint(1, 1)), "nw")
check("命中 上边", pin._hit(QPoint(150, 2)), "n")
check("命中 右边", pin._hit(QPoint(298, 100)), "e")
check("中间=移动", pin._hit(QPoint(150, 100)), "")
check("右上角=关闭", pin._hit(QPoint(295, 3)), "")

# ---- 8. 滚轮缩放以中心为锚 ----------------------------------------------
pin.setGeometry(120, 80, 300, 200)
c0 = pin.geometry().center()
pin._scale_by(1.1)
c1 = pin.geometry().center()
check("滚轮缩放 尺寸", geo(pin)[2:], (330, 220))
check("滚轮缩放 中心不动", (abs(c0.x() - c1.x()) <= 1, abs(c0.y() - c1.y()) <= 1),
      (True, True))

# ---- 9. 高分屏：图不会被放大一倍 ----------------------------------------
pm2 = QPixmap(600, 400)
pm2.fill(QColor("#AA3366"))
pm2.setDevicePixelRatio(2.0)
pin2 = ui_snip.PinWindow(pm2, Pal())
check("dpr=2 图逻辑尺寸", (pin2.width(), pin2.height()), (300, 200))

# ---- 10. 遮罩把选区位置算成全局坐标 --------------------------------------
canvas = QPixmap(800, 600)
canvas.fill(QColor("#202020"))
screen = app.primaryScreen()
ov = ui_snip.SnipOverlay(canvas, QRect(0, 0, 800, 600), screen, Pal(), {})
ov.sel = QRect(100, 50, 200, 120)
ov.shot = ui_snip.snip.Shot(canvas, QRect(100, 50, 200, 120))
got = {}
ov.done.connect(lambda pm, act: got.update(pm=pm, act=act, pos=ov.pin_pos))
ov._do("pin")
check("遮罩发出的动作", got.get("act"), "pin")
check("贴图目标位置(全局)", (got["pos"].x(), got["pos"].y()), (100, 50))
check("贴图内容尺寸", (got["pm"].width(), got["pm"].height()), (200, 120))

print()
print("失败 %d 项" % len(fails) if fails else "全部通过")
sys.exit(1 if fails else 0)
