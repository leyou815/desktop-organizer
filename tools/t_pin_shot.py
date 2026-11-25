import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))

from PyQt5.QtCore import QPoint
from PyQt5.QtGui import QColor, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication

import ui_snip

app = QApplication([])


class Pal(object):
    card = QColor("#FFFFFF")
    line = QColor("#DDD")
    text = QColor("#222")
    card_hi = QColor("#EEE")


pm = QPixmap(420, 260)
pm.fill(QColor("#2B3A55"))
p = QPainter(pm)
p.setPen(QColor("#8FD3FF"))
p.drawRect(10, 10, 400, 240)
p.end()

pin = ui_snip.PinWindow(pm, Pal())
pin.show_at(QPoint(100, 80))
pin._hover = True
pin._hnd = "se"
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
out = os.path.join(OUT, "pin_hover.png")
pin.grab().save(out)
print("saved", out, pin.geometry())
