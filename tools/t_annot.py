#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离屏自测：方框 / 圆形工具（含 Shift 正方形、正圆）。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))

from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import QApplication

import snip
import ui_snip

app = QApplication([])

fails = []


def check(name, got, want):
    ok = got == want
    print("%-30s %-26s %s" % (name, str(got), "OK" if ok else "期望 %s  <-- 失败" % (want,)))
    if not ok:
        fails.append(name)


class Pal(object):
    card = QColor("#FFFFFF")
    line = QColor("#DDD")
    text = QColor("#222")
    card_hi = QColor("#EEE")
    muted = QColor("#888")
    accent = QColor("#E5484D")


# ---- 1. 工具表 -----------------------------------------------------------
keys = [k for k, _, _ in snip.TOOLS]
check("工具表含方框/圆形", ("rect" in keys, "ellipse" in keys), (True, True))
check("工具顺序", keys, ["arrow", "rect", "ellipse", "poly", "pen", "marker",
                        "mosaic", "text"])

# ---- 2. Shift 约束 -------------------------------------------------------
p0 = QPoint(0, 0)
# QRect(QPoint, QPoint) 是两端都含的，所以 120px 的拖动量宽高是 121
check("自由拖 = 原样", (ui_snip.shape_rect(p0, QPoint(120, 40)),
                        ui_snip.shape_rect(p0, QPoint(120, 40), False)),
      (QRect(0, 0, 121, 41), QRect(0, 0, 121, 41)))
r = ui_snip.shape_rect(p0, QPoint(120, 40), True)
check("Shift 正方形(取长边)", (r.x(), r.y(), r.width(), r.height()), (0, 0, 121, 121))
r = ui_snip.shape_rect(QPoint(200, 200), QPoint(160, 210), True)
check("Shift 反向拖仍正向", (r.x(), r.y(), r.width(), r.height()),
      (160, 200, 41, 41))
r = ui_snip.shape_rect(QPoint(200, 200), QPoint(260, 150), True)
check("Shift 右上拖", (r.x(), r.y(), r.width(), r.height()), (200, 140, 61, 61))

# ---- 3. 真实绘制一张 -----------------------------------------------------
canvas = QPixmap(400, 300)
canvas.fill(QColor("#FFFFFF"))
shot = snip.Shot(canvas, QRect(0, 0, 400, 300))
shot.add_rect(QRect(20, 20, 100, 60), "#E5484D", 3)
shot.add_ellipse(QRect(150, 20, 120, 120), "#0091FF", 3)
pm = shot.render()
img = pm.toImage()


def near(c, hex_target, tol=60):
    t = QColor(hex_target)
    return (abs(c.red() - t.red()) + abs(c.green() - t.green())
            + abs(c.blue() - t.blue())) < tol


def px(x, y):
    return QColor(img.pixel(x, y))


check("方框左边描边", near(px(20, 40), "#E5484D"), True)
check("方框上边描边", near(px(70, 20), "#E5484D"), True)
check("方框内部不填充", near(px(70, 40), "#FFFFFF", 20), True)
check("方框外仍是白的", near(px(10, 40), "#FFFFFF", 20), True)
check("圆形顶端描边", near(px(210, 21), "#0091FF"), True)
check("圆形左端描边", near(px(151, 80), "#0091FF"), True)
check("圆形框角是空的", near(px(153, 23), "#FFFFFF", 20), True)
check("圆内不填充", near(px(210, 80), "#FFFFFF", 20), True)

# ---- 4. 撤销 / 重做 ------------------------------------------------------
check("形状数=2", len(shot.shapes), 2)
shot.undo()
shot.undo()
check("两次撤销后剩 0", len(shot.shapes), 0)
shot.redo()
check("重做回来 1 条", [s["t"] for s in shot.shapes], ["rect"])

# ---- 5. 遮罩里真的能拖出来 ----------------------------------------------
big = QPixmap(640, 480)
big.fill(QColor("#202020"))
screen = app.primaryScreen()
ov = ui_snip.SnipOverlay(big, QRect(0, 0, 640, 480), screen, Pal(), {})
ov.sel = QRect(100, 50, 400, 300)
ov._enter_adjust()
ov._set_tool("rect")
ov._start_shape(QPoint(10, 10))
ov._drag_shape(QPoint(110, 60))
ov._finish_shape(QPoint(110, 60))
g = ov.shot.shapes[-1]["rect"]
check("方框落在画布坐标", (g.x(), g.y(), g.width(), g.height()), (110, 60, 101, 51))

ov._set_tool("ellipse")
ov._start_shape(QPoint(200, 100))
ov._drag_shape(QPoint(140, 180))
ov._finish_shape(QPoint(140, 180))
g = ov.shot.shapes[-1]
check("圆形落在画布坐标", (g["rect"].x(), g["rect"].y(),
                          g["rect"].width(), g["rect"].height()),
      (240, 150, 61, 81))
check("圆形类型", g["t"], "ellipse")
check("画完回到可调整态", ov.state, "adjust")

ov._do("undo")
check("撤销消掉圆形", [s["t"] for s in ov.shot.shapes], ["rect"])

# ---- 5b. 拖动中的实时预览 ------------------------------------------------
ov._set_tool("ellipse")
ov._start_shape(QPoint(200, 150))    # 控件坐标；内部会加上选区偏移
ov._drag_shape(QPoint(260, 210))
ov.update()
snap = ov.grab().toImage()
c = QColor(snap.pixel(200, 180))     # 椭圆左边框中点
c2 = QColor(snap.pixel(230, 150))    # 椭圆上边框中点
print("预览像素 左 %s / 上 %s" % (c.name(), c2.name()))
check("拖动时就有预览", (near(c, "#E5484D", 90), near(c2, "#E5484D", 90)), (True, True))
ov._temp = None
ov._pts = []
ov.state = "adjust"

# ---- 6. 工具条能装下、图标画得出来 --------------------------------------
bar = ui_snip.SnipBar(Pal())
bar.adjustSize()
check("工具条有 8 个工具", len(bar.tools), 8)
check("方框按钮在", "rect" in bar.tools and "ellipse" in bar.tools, True)
print("工具条宽度 %d px（屏幕 %d px）" % (bar.width(), screen.availableGeometry().width()))
check("工具条不超屏", bar.width() < screen.availableGeometry().width(), True)

bar.set_color("#E5484D")
bar.set_width(3)
bar.tools["ellipse"].setChecked(True)
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
out = os.path.join(OUT, "bar_preview.png")
bar.grab().save(out)

print()
print("失败 %d 项" % len(fails) if fails else "全部通过")
sys.exit(1 if fails else 0)
