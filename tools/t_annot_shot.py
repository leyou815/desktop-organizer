#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染一张方框 / 圆形标注的效果图，方便肉眼验收。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))

from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication

import snip

app = QApplication([])

W, H = 640, 360
canvas = QPixmap(W, H)
canvas.fill(QColor("#F4F6FA"))

p = QPainter(canvas)
p.setRenderHint(QPainter.Antialiasing, True)
p.setPen(Qt.NoPen)
p.setBrush(QColor("#FFFFFF"))
p.drawRoundedRect(QRect(24, 24, 592, 312), 12, 12)
p.setBrush(QColor("#E8EDF7"))
p.drawRoundedRect(QRect(48, 60, 220, 120), 8, 8)
p.setBrush(QColor("#D7E2F5"))
p.drawRoundedRect(QRect(300, 60, 288, 120), 8, 8)
p.setBrush(QColor("#EAF0FA"))
p.drawRoundedRect(QRect(48, 210, 540, 96), 8, 8)
f = QFont()
f.setPixelSize(15)
f.setBold(True)
p.setFont(f)
p.setPen(QColor("#3A4A63"))
p.drawText(QRect(60, 76, 200, 24), Qt.AlignLeft, "步骤 1  选择素材")
p.drawText(QRect(312, 76, 260, 24), Qt.AlignLeft, "步骤 2  调整参数")
p.drawText(QRect(60, 226, 500, 24), Qt.AlignLeft, "步骤 3  导出")
p.end()

shot = snip.Shot(canvas, QRect(0, 0, W, H))
# 方框：框住左边那块
shot.add_rect(QRect(44, 56, 228, 128), "#E5484D", 3)
# 圆形：圈住右边标题
shot.add_ellipse(QRect(296, 40, 180, 64), "#0091FF", 3)
# Shift 正圆
shot.add_ellipse(QRect(470, 200, 96, 96), "#30A46C", 3)

OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
out = os.path.join(OUT, "annot_preview.png")
shot.render().save(out)
print("saved", out)
