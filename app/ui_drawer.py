#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— 抽屉界面

屏幕右侧一根不起眼的小竖条，点一下往左滑出抽屉：
分类文件夹 + 文件列表 + 一键整理 / 撤销。再点把手（或 ESC / 点别处）收起。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtCore import (Qt, QRectF, QTimer, QPropertyAnimation, QEasingCurve,
                          pyqtSignal, QUrl, QPoint, QEvent, QFileInfo)
from PyQt5.QtGui import (QColor, QPainter, QPainterPath, QLinearGradient, QPen,
                         QBrush, QFontMetrics, QIcon, QDesktopServices)
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QPushButton, QVBoxLayout,
                             QHBoxLayout, QScrollArea, QFrame, QGridLayout, QLineEdit,
                             QFileIconProvider, QStyle, QDialog, QSizePolicy)

import atomicio
import bulkops
import config as appcfg
import fuzzy
import launchers
import rules
import sysenv
from theme import CAT_COLORS
from ui_bulk import ConfirmDialog, MoveDialog, RenameDialog


# --------------------------------------------------------------------------- #
# 右侧触发条
# --------------------------------------------------------------------------- #
class Trigger(QWidget):
    """贴在屏幕右边缘的小竖条。平时半透明，鼠标移上去才亮。"""

    clicked = pyqtSignal()

    W, H = 11, 116

    def __init__(self, pal):
        super(Trigger, self).__init__(None, Qt.FramelessWindowHint |
                                      Qt.Tool | Qt.WindowStaysOnTopHint)
        self.pal = pal
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("桌面抽屉")
        self.setWindowOpacity(0.34)
        self._hover = False
        self.anim = QPropertyAnimation(self, b"windowOpacity", self)
        self.anim.setDuration(160)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 画得比窗口宽，让右侧被屏幕边缘裁掉，只留下左侧圆角
        r = QRectF(0, 0, self.W + 14, self.H)
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)

        g = QLinearGradient(0, 0, 0, self.H)
        base = self.pal.accent
        g.setColorAt(0.0, QColor(base.red(), base.green(), base.blue(), 255 if self._hover else 210))
        g.setColorAt(1.0, QColor(base.red(), base.green(), base.blue(), 200 if self._hover else 160))
        p.fillPath(path, QBrush(g))

        # 三个小点，提示"这里能拉开"
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 225))
        cy = self.H / 2.0
        for dy in (-9, 0, 9):
            p.drawEllipse(QRectF(3.5, cy + dy - 1.6, 3.2, 3.2))
        p.end()

    def enterEvent(self, e):
        self._hover = True
        self.anim.stop()
        self.anim.setStartValue(self.windowOpacity())
        self.anim.setEndValue(0.92)
        self.anim.start()
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.anim.stop()
        self.anim.setStartValue(self.windowOpacity())
        self.anim.setEndValue(0.34)
        self.anim.start()
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


# --------------------------------------------------------------------------- #
# 分类行
# --------------------------------------------------------------------------- #
class FileRow(QWidget):
    """一个文件（或子文件夹）条目，点击打开。"""

    def __init__(self, pal, name, path, is_dir=False, count=0, tag=""):
        super(FileRow, self).__init__()
        self.pal = pal
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.count = count
        self.tag = tag          # 右侧灰字：子分类名（Word / Excel …）或文件数
        self.setFixedHeight(26)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(path)
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self.pal.accent.red(), self.pal.accent.green(),
                              self.pal.accent.blue(), 38))
            p.drawRoundedRect(r, 5, 5)

        # 小方块图标
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 40) if self.pal.dark else QColor(0, 0, 0, 26))
        p.drawRoundedRect(QRectF(8, 9, 7, 8), 2, 2)

        fm = QFontMetrics(self.font())
        avail = self.width() - 34
        if self.is_dir:
            tail = "  %d" % self.count if self.count else "  空"
        else:
            tail = ("  " + self.tag) if self.tag else ""
        text = fm.elidedText(self.name, Qt.ElideMiddle, avail - fm.width(tail))
        p.setPen(QPen(self.pal.text))
        p.drawText(QRectF(22, 0, avail, self.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        if tail:
            p.setPen(QPen(self.pal.muted))
            p.drawText(QRectF(22, 0, avail, self.height()),
                       Qt.AlignVCenter | Qt.AlignRight, tail)
        p.end()


_ICON_PROVIDER = None


def load_icon(spec=None, path=None):
    """取图标。Windows 用系统外壳图标（.lnk/.exe 的真实图标），麒麟用 Icon 字段。"""
    global _ICON_PROVIDER
    if sysenv.IS_WINDOWS and path:
        if _ICON_PROVIDER is None:
            _ICON_PROVIDER = QFileIconProvider()
        try:
            ic = _ICON_PROVIDER.icon(QFileInfo(path))
            if not ic.isNull():
                return ic
        except Exception:
            pass
    if spec:
        if os.path.isabs(spec) and os.path.exists(atomicio.win_long(spec)):
            ic = QIcon(spec)
            if not ic.isNull():
                return ic
        ic = QIcon.fromTheme(spec)
        if not ic.isNull():
            return ic
    return QIcon.fromTheme("application-x-executable")


_STD_ICONS = {
    "此电脑": QStyle.SP_DriveHDIcon, "计算机": QStyle.SP_ComputerIcon,
    "回收站": QStyle.SP_TrashIcon,
    "用户文件夹": QStyle.SP_DirHomeIcon, "主目录": QStyle.SP_DirHomeIcon,
}


def virtual_icon(name, theme):
    if theme:
        ic = QIcon.fromTheme(theme)
        if not ic.isNull():
            return ic
    std = _STD_ICONS.get(name)
    if std is not None:
        try:
            return QApplication.style().standardIcon(std)
        except Exception:
            pass
    return QIcon.fromTheme("folder")


def _wrap2(text, fm, width):
    """把名字折成最多两行，超出用省略号。

    有空格时按词折（不然 Google Chrome 会被切成 "Google Chrom / e"），
    中文没空格再按字折。
    """
    if fm.width(text) <= width:
        return [text]

    words = text.split(" ")
    if len(words) > 1:
        line1, i = "", 0
        while i < len(words) and fm.width((line1 + " " + words[i]).strip()) <= width:
            line1 = (line1 + " " + words[i]).strip()
            i += 1
        if line1:
            if i >= len(words):
                return [line1]
            rest = " ".join(words[i:])
            return [line1, fm.elidedText(rest, Qt.ElideRight, width)]

    lines, cur = [], ""
    for ch in text:
        if fm.width(cur + ch) > width:
            lines.append(cur)
            cur = ch
            if len(lines) == 2:
                lines[-1] = fm.elidedText(lines[-1] + ch, Qt.ElideRight, width)
                return lines
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines[:2]


class AppTile(QWidget):
    """抽屉里的一个图标：上面图标、下面名字，点一下就启动。"""

    W, H = 82, 86

    def __init__(self, pal, name, icon, on_click, tooltip="", width=None):
        super(AppTile, self).__init__()
        self.pal = pal
        self.name = name
        self.on_click = on_click
        self.setFixedSize(width or self.W, self.H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip or name)
        self._hover = False
        self.pix = icon.pixmap(38, 38)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.on_click:
            self.on_click()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self.pal.accent.red(), self.pal.accent.green(),
                              self.pal.accent.blue(), 36))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)

        x = (self.width() - 38) / 2.0
        p.drawPixmap(int(x), 8, self.pix)

        f = self.font()
        f.setPointSizeF(8.2)
        p.setFont(f)
        p.setPen(QPen(self.pal.text))
        fm = QFontMetrics(f)
        lines = _wrap2(self.name, fm, self.width() - 8)
        y = 52
        for line in lines:
            p.drawText(QRectF(4, y, self.width() - 8, 14),
                       Qt.AlignHCenter | Qt.AlignTop, line)
            y += 14
        p.end()


def tile_grid(avail, gap=6):
    """按可用宽度算图标网格的（列数, 每格宽度）。

    抽屉固定 386px，4 列要 334px，而内容区只有 ~300px，第 4 列会被
    窗口右边缘切掉。这里按实际可用宽度反算，多出来的横向余量摊给
    每格，所以不会溢出，也不会在右侧空出一道。
    """
    cols = max(2, min(5, int((avail + gap) // (AppTile.W + gap))))
    width = max(AppTile.W, (avail - (cols - 1) * gap) // cols)
    return cols, width


class TabButton(QWidget):
    """竖排 tab 按钮：文字一个字一行，选中态主题色底白字。"""
    def __init__(self, pal, text, on_click):
        super(TabButton, self).__init__()
        self.pal = pal
        self._label = text
        self.on_click = on_click
        self.active = False
        self._hover = False
        self.setFixedSize(44, 62)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.on_click:
            self.on_click()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        if self.active:
            # 选中态：青→紫渐变，对应壁纸 01 的双色
            grad = QLinearGradient(r.left(), r.top(), r.left(), r.bottom())
            grad.setColorAt(0, self.pal.accent)
            grad.setColorAt(1, self.pal.accent_2)
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(r, 8, 8)
            fg = QColor("#FFFFFF")
        elif self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(self.pal.card_hi)
            p.drawRoundedRect(r, 8, 8)
            fg = self.pal.text
        else:
            fg = self.pal.muted
        p.setFont(self.pal.font_ui(12, bold=self.active))
        p.setPen(QPen(fg))
        y = 6
        for ch in self._label:
            p.drawText(QRectF(0, y, self.width(), 20), Qt.AlignHCenter | Qt.AlignVCenter, ch)
            y += 20
        p.end()


_ICON_CACHE = {}
_NAME_CACHE = {}


def display_name(path, name, cat):
    """应用要用 .desktop 里的中文名（微信），而不是文件名（wechat.desktop）。"""
    if cat != rules.APP or not name.lower().endswith(".desktop"):
        return name
    if path in _NAME_CACHE:
        return _NAME_CACHE[path]
    try:
        dn = launchers.parse(path).name or name
    except Exception:
        dn = name
    _NAME_CACHE[path] = dn
    return dn


def entry_icon(path, cat, is_dir):
    """搜索结果用的小图标（带缓存，18 个应用每次按键都要取，不缓存会卡）。"""
    key = (path, cat, is_dir)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    if cat == rules.APP:
        ic = load_icon(launchers.parse(path).icon, path)
    elif is_dir:
        ic = QIcon.fromTheme("folder")
    else:
        ic = QIcon.fromTheme("text-x-generic")
    if ic.isNull():
        ic = QIcon.fromTheme("text-x-generic")
    _ICON_CACHE[key] = ic
    return ic


class ResultRow(QWidget):
    """一条搜索结果：勾选框 + 图标 + 高亮文件名 + 分类标签。

    点左边的勾选框是"选中"，点其它地方是"打开"——和文件管理器一致，
    既不会误开文件，也不至于为了勾选去瞄一个 16px 的小方块。
    """

    CHECK_ZONE = 30          # 这个宽度以内算点勾选框
    ICON_X = 32
    TEXT_X = 54

    def __init__(self, pal, name, path, cat, is_dir, indices, on_open, tag=None,
                 on_check=None):
        super(ResultRow, self).__init__()
        self.pal = pal
        self.name = name
        self.path = path
        self.cat = cat
        self.tag = tag or cat
        self.is_dir = is_dir
        self.indices = set(indices or [])
        self.on_open = on_open
        self.on_check = on_check
        self.checked = False
        self.selected = False
        self._hover = False
        self.setFixedHeight(36)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("%s\n点左边勾选，点名字打开" % path)
        self.pix = entry_icon(path, cat, is_dir).pixmap(18, 18)

    def set_selected(self, on):
        self.selected = on
        self.update()

    def set_checked(self, on):
        if self.checked != on:
            self.checked = on
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if e.x() <= self.CHECK_ZONE or (e.modifiers() & Qt.ControlModifier):
            if self.on_check:
                self.on_check(self, e.modifiers())
            return
        self.on_open()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.selected or self._hover or self.checked:
            p.setPen(Qt.NoPen)
            alpha = 52 if self.selected else (34 if self.checked else 30)
            p.setBrush(QColor(self.pal.accent.red(), self.pal.accent.green(),
                              self.pal.accent.blue(), alpha))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 7, 7)

        # 勾选框
        box = QRectF(9, (self.height() - 16) / 2.0, 16, 16)
        if self.checked:
            p.setPen(Qt.NoPen)
            p.setBrush(self.pal.accent)
            p.drawRoundedRect(box, 4.5, 4.5)
            pen = QPen(QColor(255, 255, 255), 1.9)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.drawLine(QPoint(int(box.left() + 4), int(box.center().y())),
                       QPoint(int(box.left() + 7), int(box.bottom() - 5)))
            p.drawLine(QPoint(int(box.left() + 7), int(box.bottom() - 5)),
                       QPoint(int(box.right() - 4), int(box.top() + 5)))
        else:
            p.setPen(QPen(QColor(self.pal.muted.red(), self.pal.muted.green(),
                                 self.pal.muted.blue(), 150 if self._hover else 95), 1.4))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box, 4.5, 4.5)

        p.drawPixmap(self.ICON_X, 9, self.pix)

        # 右侧分类标签
        f = self.font()
        f.setPointSizeF(f.pointSizeF() - 1.6)
        p.setFont(f)
        fm_tag = QFontMetrics(f)
        tag = self.tag
        tag_w = fm_tag.width(tag) + 4
        p.setPen(QPen(self.pal.muted))
        p.drawText(QRectF(self.width() - tag_w - 10, 0, tag_w, self.height()),
                   Qt.AlignVCenter | Qt.AlignRight, tag)

        # 文件名（逐字绘制以支持高亮）
        f2 = self.font()
        f2.setPointSizeF(f2.pointSizeF() - 0.3)
        p.setFont(f2)
        fm = QFontMetrics(f2)
        avail = self.width() - self.TEXT_X - tag_w - 16
        x, y = self.TEXT_X, (self.height() + fm.ascent() - fm.descent()) / 2.0
        limit = self.TEXT_X + avail
        for i, ch in enumerate(self.name):
            w = fm.width(ch)
            if x + w > limit:
                p.setPen(QPen(self.pal.muted))
                p.drawText(QRectF(x, 0, limit - x, self.height()),
                           Qt.AlignVCenter | Qt.AlignLeft, "…")
                break
            p.setPen(QPen(self.pal.accent if i in self.indices else self.pal.text))
            p.drawText(QRectF(x, 0, w + 1, self.height()), Qt.AlignVCenter | Qt.AlignLeft, ch)
            x += w
        p.end()


class CatHeader(QWidget):
    toggled = pyqtSignal()

    def __init__(self, pal, cat, desc, count, expanded):
        super(CatHeader, self).__init__()
        self.pal = pal
        self.cat = cat
        self.desc = desc
        self.count = count
        self.expanded = expanded
        self.setFixedHeight(50)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.toggled.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 18) if self.pal.dark else QColor(0, 0, 0, 12))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 8, 8)

        # 蓝图节点方块：描边 + 内点，对应壁纸折线的连接点
        col = QColor(CAT_COLORS.get(self.cat, "#8A8F98"))
        p.setPen(QPen(col, 1.4))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(10, 10, 30, 30), 7, 7)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(QRectF(20, 20, 10, 10))

        # 标题（UI 字体）
        p.setFont(self.pal.font_ui(13, bold=True))
        p.setPen(QPen(self.pal.text))
        p.drawText(QRectF(52, 7, w - 100, 21), Qt.AlignVCenter | Qt.AlignLeft, self.cat)

        # 数量 + 说明（等宽标签，对应 NODE / ORIGIN / FLOW）
        p.setFont(self.pal.font_mono(10))
        p.setPen(QPen(col))
        # 两位数字只要 26px，别让它占到 46px 把说明挤窄
        p.drawText(QRectF(52, 27, 26, 16), Qt.AlignVCenter | Qt.AlignLeft,
                   "%02d" % self.count)
        p.setPen(QPen(self.pal.muted))
        # 说明原文最长 290px，直接画会被硬切一半，用省略号收尾
        desc = p.fontMetrics().elidedText(self.desc, Qt.ElideRight, int(w - 114))
        p.drawText(QRectF(82, 27, w - 114, 16), Qt.AlignVCenter | Qt.AlignLeft,
                   desc)

        # 展开箭头
        p.setPen(QPen(self.pal.muted, 1.6))
        cx, cy = w - 20.0, h / 2.0
        if self.expanded:
            p.drawLine(int(cx - 4), int(cy - 1), int(cx), int(cy + 4))
            p.drawLine(int(cx), int(cy + 4), int(cx + 4), int(cy - 1))
        else:
            p.drawLine(int(cx - 4), int(cy - 4), int(cx + 1), int(cy))
            p.drawLine(int(cx + 1), int(cy), int(cx - 4), int(cy + 4))
        p.end()


class CatRow(QWidget):
    def __init__(self, pal, cat, desc, items, cfg=None):
        super(CatRow, self).__init__()
        self.pal = pal
        self.cfg = cfg
        self.cat = cat
        self.items = items
        self.expanded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        n = rules.count_items(cat, items)
        self.header = CatHeader(pal, cat, desc, n, False)
        self.header.toggled.connect(self.toggle)
        lay.addWidget(self.header)

        self.body = QWidget()
        self.body.setVisible(False)
        self.bl = QVBoxLayout(self.body)
        self.bl.setContentsMargins(14, 0, 12, 6)
        self.bl.setSpacing(1)
        self._filled = False
        lay.addWidget(self.body)

    def toggle(self):
        self.expanded = not self.expanded
        self.header.expanded = self.expanded
        self.header.update()
        if self.expanded and not self._filled:
            self._fill()
            self._filled = True
        self.body.setVisible(self.expanded)

    def _fill(self):
        if self.cat == rules.APP:
            self._fill_grid()
        elif self.cat == rules.FOLDER:
            self._fill_folders()
        else:
            self._fill_files()

    def _fill_folders(self):
        """文件夹分类：每一项本来就是文件夹，点开等于进目录，不用钻。"""
        shown = 0
        for name, path, is_dir, count in self.items:
            if shown >= 40:
                self._more(len(self.items) - shown)
                break
            self.bl.addWidget(FileRow(self.pal, name, path, is_dir, count))
            shown += 1
        if not self.items:
            self._empty()

    def _fill_files(self):
        """其他分类：钻到子分类目录底下，直接平铺文件名。

        以前展开「文档」只看到 Word/ Excel/ PDF/ 几个子文件夹，还得再点
        一层才见到文件。现在一次列全，点名字就用默认程序打开；子分类名
        缩成右侧灰字，信息不丢但不占地方。
        """
        rows = []
        for name, path, is_dir, count in self.items:
            if not is_dir:
                rows.append((name, path, ""))
                continue
            tag = name.rstrip("/")
            for dirpath, dirnames, filenames in os.walk(path):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for f in filenames:
                    if f.startswith(".") or f.startswith("~$"):
                        continue
                    rows.append((f, os.path.join(dirpath, f), tag))
        rows.sort(key=lambda r: (r[0].lower(), r[2]))

        shown = 0
        for name, path, tag in rows:
            if shown >= 80:
                self._more(len(rows) - shown)
                break
            self.bl.addWidget(FileRow(self.pal, name, path, False, 0, tag=tag))
            shown += 1
        if not rows:
            self._empty()

    def _more(self, n):
        more = QLabel("…… 还有 %d 个" % n)
        more.setStyleSheet("color:%s;font-size:11px;padding-left:22px;"
                           % self.pal.muted.name())
        self.bl.addWidget(more)

    def _empty(self):
        empty = QLabel("暂无文件")
        empty.setStyleSheet("color:%s;font-size:11px;padding-left:22px;"
                            % self.pal.muted.name())
        self.bl.addWidget(empty)


# --------------------------------------------------------------------------- #
# 抽屉面板
# --------------------------------------------------------------------------- #
    # -- 图标网格（应用 / 快捷方式） -----------------------------------------
    def _fill_grid(self):
        entries = []
        try:
            show_virtual = launchers.virtual_hidden()   # 藏了才在抽屉里补位，避免重复
        except Exception:
            show_virtual = False

        if self.cat == rules.APP:
            for name, path, is_dir, count in self.items:
                lc = launchers.parse(path)
                entries.append((lc.name, load_icon(lc.icon, path), path,
                                lambda p=path: self._launch_app(p)))
            if show_virtual:
                for vname, uri, theme in launchers.VIRTUAL:
                    entries.append((vname, virtual_icon(vname, theme), uri,
                                    lambda u=uri: launchers.open_uri(u)))
        else:
            for name, path, is_dir, count in self.items:
                ic = QIcon.fromTheme("folder-symbolic") if is_dir else \
                     QIcon.fromTheme("inode-symlink")
                if ic.isNull():
                    ic = load_icon("folder")
                entries.append((name.rstrip("/"), ic, path,
                                lambda p=path: self._open_path(p)))

        if not entries:
            tip = QLabel("还没有已归档的%s" % self.cat)
            tip.setStyleSheet("color:%s;font-size:11px;padding-left:22px;"
                              % self.pal.muted.name())
            self.bl.addWidget(tip)
            return

        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 4)
        grid.setHorizontalSpacing(Panel.GAP_X)
        grid.setVerticalSpacing(6)
        # 减掉 body 的左右缩进（14+12）和滚动条让位，避免又顶到右边缘
        cols, tile_w = tile_grid(Panel.WIDTH - Panel.CHROME_W - 34)
        for i, (name, icon, path, slot) in enumerate(entries):
            grid.addWidget(AppTile(self.pal, name, icon, slot, path, width=tile_w),
                           i // cols, i % cols)
        wrap = QWidget()
        wrap.setLayout(grid)
        self.bl.addWidget(wrap)

    def _launch_app(self, path):
        ok, err = launchers.launch(path)
        if not ok:
            self._notify("启动失败：%s" % err)

    def _open_path(self, path):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            self._notify("打不开：%s" % path)

    def _notify(self, msg):
        # 面板上给个轻提示，不弹窗
        if self.window() and hasattr(self.window(), "_flash"):
            self.window()._flash(msg)


class Panel(QWidget):
    WIDTH = 386

    def __init__(self, org, pal, on_hide=None, on_show=None, cfg=None):
        super(Panel, self).__init__(None, Qt.FramelessWindowHint |
                                    Qt.Tool | Qt.WindowStaysOnTopHint)
        self.org = org
        self.pal = pal
        self.on_hide = on_hide
        self.on_show = on_show
        self.cfg = cfg
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(self.WIDTH)

        # 批量操作（勾选后移动 / 重命名 / 删除）
        self.ops = bulkops.BulkOps(org, cfg)
        self._checked = []          # 按勾选顺序存的路径
        self._anchor = None         # Shift 连选的起点
        self._pending = []          # 最近一次批量操作的结果，用于提示

        self.is_open = False
        self._sync_geometry()          # 尺寸与贴边位置按当前主屏算

        # 多屏 / 改分辨率 / 任务栏换边后要重算，否则抽屉会飘到屏幕外或高度错位
        self._watch_screens()
        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setDuration(230)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(200)

        self._build()
        self.search_box.setVisible(False)   # 默认应用页，搜索只在文件页
        self.refresh()

    # -- 几何 ---------------------------------------------------------------
    def _sync_geometry(self):
        """按当前主屏重算高度与左右两个停靠位。

        availableGeometry 已经把任务栏算掉了：任务栏换到左边/上边时
        scr.right()/scr.height() 也跟着变，所以不能缓存成常量。
        """
        scr = QApplication.primaryScreen().availableGeometry()
        self._top = scr.top() + 46
        self.setFixedHeight(max(240, scr.height() - 92))
        self._x_shown = scr.right() - self.WIDTH + 1   # 贴死屏幕右边缘，不留缝
        self._x_hidden = scr.right() + 8
        self.move(self._x_shown if self.is_open else self._x_hidden, self._top)

    def _watch_screens(self):
        """插拔显示器 / 改分辨率时重算几何，避免抽屉跑到已拔掉的屏幕上。"""
        app = QApplication.instance()
        if app is None:
            return
        for sig in ("screenAdded", "screenRemoved", "primaryScreenChanged"):
            signal = getattr(app, sig, None)
            if signal is None:
                continue
            try:
                signal.connect(self._on_screens_changed)
            except Exception:
                pass
        self._bind_screen(QApplication.primaryScreen())

    def _bind_screen(self, scr):
        if scr is None:
            return
        try:
            scr.availableGeometryChanged.disconnect(self._on_screens_changed)
        except Exception:
            pass
        try:
            scr.availableGeometryChanged.connect(self._on_screens_changed)
        except Exception:
            pass

    def _on_screens_changed(self, *_):
        # 主屏可能已经换人，重新绑定后再算几何
        try:
            self._bind_screen(QApplication.primaryScreen())
            self._sync_geometry()
            if self.is_open:
                self._x_shown = QApplication.primaryScreen().availableGeometry().right() \
                    - self.WIDTH + 1
        except Exception:
            pass

    # -- 结构 ---------------------------------------------------------------
    def _build(self):
        pal = self.pal
        # 外层：左侧竖排 tab 条 + 右侧内容区
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        tabbar = QFrame()
        tabbar.setFixedWidth(52)
        tabbar.setStyleSheet(
            "QFrame{background:%s;border-right:1px solid %s;}"
            % (pal.card.name(), pal.line.name()))
        tbl = QVBoxLayout(tabbar)
        tbl.setContentsMargins(4, 14, 4, 8)
        tbl.setSpacing(6)
        self.tab = "apps"          # 当前页：apps / files
        self.tab_btns = {}
        for key, label in (("apps", "应用"), ("files", "文件")):
            b = TabButton(pal, label, lambda k=key: self._switch_tab(k))
            self.tab_btns[key] = b
            tbl.addWidget(b)
        tbl.addStretch(1)
        root.addWidget(tabbar)

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(16, 14, 14, 14)
        lay.setSpacing(8)
        root.addWidget(content, 1)
        self._style_tabs()

        head = QHBoxLayout()
        head.setSpacing(8)
        # 大号 01 编号（壁纸 hero）
        no = QLabel("01")
        no.setFont(pal.font_display(27))
        no.setStyleSheet("color:%s;" % pal.accent.name())
        head.addWidget(no)
        # 竖线分隔
        sep = QFrame()
        sep.setFixedSize(1, 34)
        sep.setStyleSheet("background:%s;" % pal.line.name())
        head.addWidget(sep)
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        t = QLabel("桌面抽屉")
        t.setFont(pal.font_ui(15, bold=True))
        t.setStyleSheet("color:%s;" % pal.text.name())
        self.sub = QLabel("")
        self.sub.setFont(pal.font_mono(10))
        self.sub.setStyleSheet("color:%s;" % pal.muted.name())
        # Minimum 策略：头一行本来就窄，默认策略会把这段压到裁字
        self.sub.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        title_box.addWidget(t)
        title_box.addWidget(self.sub)
        head.addLayout(title_box)
        head.addStretch(1)

        # 这里只有 ~274px，四个元素平分不过来：长按钮会把右边的字挤掉
        self.btn_open = self._mini_btn("目录", self._open_root)
        self.btn_open.setToolTip("打开归档目录")
        head.addWidget(self.btn_open)
        self.btn_close = self._mini_btn("✕", self.slide_out)
        self.btn_close.setToolTip("收起（Esc）")
        head.addWidget(self.btn_close)
        lay.addLayout(head)

        # 搜索框（只在文件页显示）
        self._query = ""
        self._rows = []
        self._sel = -1
        self.search = QLineEdit()
        self.search.setFont(pal.font_ui(12))
        self.search.setPlaceholderText("搜索 / SEARCH  ·  wx / sls / 报告")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedHeight(34)
        self.search.setStyleSheet("""
        QLineEdit{border:1px solid %s;border-radius:9px;background:%s;
            color:%s;font-size:12px;padding-left:10px;padding-right:6px;}
        QLineEdit:focus{border:1px solid %s;background:%s;}
        """ % (pal.line.name(), pal.card_hi.name(), pal.text.name(),
               pal.accent.name(), pal.card.name()))
        self.search.addAction(QIcon.fromTheme("edit-find"), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._queue_search)
        self.search.installEventFilter(self)

        self.hint = QLabel("")
        self.hint.setStyleSheet("color:%s;font-size:10px;padding-left:4px;" % pal.muted.name())
        self.hint.setVisible(False)

        # 搜索区（只在文件页显示）
        self.search_box = QWidget()
        sl = QVBoxLayout(self.search_box)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        sl.addWidget(self.search)
        sl.addWidget(self.hint)
        lay.addWidget(self.search_box)

        # 勾选后浮出来的操作条
        self.opsbar = QFrame()
        self.opsbar.setStyleSheet(
            "QFrame{background:rgba(76,141,255,0.10);"
            "border:1px solid rgba(76,141,255,0.30);border-radius:9px;}")
        ol = QVBoxLayout(self.opsbar)
        ol.setContentsMargins(9, 7, 9, 8)
        ol.setSpacing(7)

        top = QHBoxLayout()
        top.setSpacing(4)
        self.sel_lb = QLabel("")
        self.sel_lb.setStyleSheet("color:%s;font-size:11px;font-weight:600;border:none;"
                                  % pal.text.name())
        top.addWidget(self.sel_lb, 1)
        for text, slot in (("全选", self._select_all),
                           ("反选", self._invert_sel),
                           ("清空", self._clear_sel)):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setFlat(True)
            b.setFixedHeight(20)
            b.setStyleSheet(
                "QPushButton{border:none;background:transparent;color:%s;font-size:10.5px;"
                "padding:0 6px;border-radius:5px;}"
                "QPushButton:hover{background:rgba(127,127,127,0.18);color:%s;}"
                % (pal.accent.name(), pal.text.name()))
            b.clicked.connect(slot)
            top.addWidget(b)
        ol.addLayout(top)

        acts = QHBoxLayout()
        acts.setSpacing(6)
        self.btn_move = self._op_btn("移动到…", self._bulk_move, "搬进抽屉里别的分类，或新建文件夹")
        self.btn_rename = self._op_btn("重命名", self._bulk_rename, "把文件名里的某个词统一换掉")
        self.btn_trash = self._op_btn("删除", self._bulk_trash, "放进回收站，可从这里撤销",
                                      danger=True)
        for b in (self.btn_move, self.btn_rename, self.btn_trash):
            acts.addWidget(b)
        ol.addLayout(acts)

        self.opsbar.setVisible(False)
        lay.addWidget(self.opsbar)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._run_search)

        # 待整理提示条
        self.banner = QFrame()
        self.banner.setStyleSheet(
            "QFrame{background:rgba(76,141,255,0.12);border:1px solid rgba(76,141,255,0.35);"
            "border-radius:8px;}")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(10, 7, 8, 7)
        self.banner_lb = QLabel("")
        self.banner_lb.setStyleSheet("color:%s;font-size:12px;border:none;" % pal.text.name())
        bl.addWidget(self.banner_lb, 1)
        self.btn_clean = QPushButton("一键整理")
        self.btn_clean.setCursor(Qt.PointingHandCursor)
        self.btn_clean.setFixedHeight(24)
        self.btn_clean.setStyleSheet(
            "QPushButton{border:none;border-radius:6px;background:%s;color:#FFF;"
            "font-size:11px;padding:0 12px;font-weight:600;}"
            "QPushButton:hover{background:%s;}"
            % (pal.accent.name(), pal.accent.darker(115).name()))
        self.btn_clean.clicked.connect(self.organize)
        bl.addWidget(self.btn_clean)
        self.banner.setVisible(False)
        lay.addWidget(self.banner)

        # 分类滚动区
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{width:6px;background:transparent;margin:2px 0;}"
            "QScrollBar::handle:vertical{background:rgba(140,146,156,0.45);border-radius:3px;"
            "min-height:30px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:none;}")
        self.scroll.viewport().setAutoFillBackground(False)
        self.body = QWidget()
        self.body.setStyleSheet("background:transparent;")
        self.bl = QVBoxLayout(self.body)
        self.bl.setContentsMargins(0, 0, 4, 0)
        self.bl.setSpacing(2)
        self.scroll.setWidget(self.body)
        lay.addWidget(self.scroll, 1)

        # 底部
        self.path_hint = QLabel("")
        self.path_hint.setStyleSheet("color:%s;font-size:10px;" % pal.muted.name())
        self.path_hint.setWordWrap(True)
        lay.addWidget(self.path_hint)

        foot = QHBoxLayout()
        self.status = QLabel("")
        self.status.setStyleSheet("color:%s;font-size:11px;" % pal.muted.name())
        foot.addWidget(self.status, 1)
        self.btn_undo = self._mini_btn("撤销上次", self.undo)
        foot.addWidget(self.btn_undo)
        lay.addLayout(foot)

    def _style_tabs(self):
        """竖排 tab 的选中态交给 TabButton 自绘。"""
        for key, b in self.tab_btns.items():
            b.active = key == self.tab
            b.update()

    def _switch_tab(self, key):
        if key == self.tab:
            return
        self.tab = key
        self._style_tabs()
        # 搜索只在文件页用：切到应用页时清掉查询，免得搜索结果盖住图标
        if key == "apps":
            self._query = ""
            self.search.clear()
        self.search_box.setVisible(key == "files")
        self.scroll.verticalScrollBar().setValue(0)
        self.refresh()

    def _fill_app_page(self, items):
        """应用页：所有图标直接铺开（含系统虚拟图标），单击即启动。"""
        pal = self.pal
        entries = []
        for name, path, is_dir, count in items:
            lc = launchers.parse(path)
            entries.append((lc.name, load_icon(lc.icon, path), path,
                            lambda p=path: self._launch_app(p), path))
        try:
            if launchers.virtual_hidden():       # 系统图标藏了才在抽屉里补位
                for vname, uri, theme in launchers.VIRTUAL:
                    entries.append((vname, virtual_icon(vname, theme), uri,
                                    lambda u=uri: launchers.open_uri(u), uri))
        except Exception:
            pass

        if not entries:
            tip = QLabel("还没有已归档的应用")
            tip.setStyleSheet("color:%s;font-size:12px;padding:18px 6px;" % pal.muted.name())
            self.bl.addWidget(tip)
            return

        head = QLabel("APPLICATIONS  /  %02d" % len(entries))
        head.setFont(pal.font_mono(10))
        head.setStyleSheet("color:%s;padding:2px 4px 7px;" % pal.accent.name())
        self.bl.addWidget(head)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 4)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(8)
        cols, tile_w = self._app_grid()
        for i, (name, icon, path, slot, tiptext) in enumerate(entries):
            grid.addWidget(AppTile(pal, name, icon, slot, tiptext, width=tile_w),
                           i // cols, i % cols)
        wrap = QWidget()
        wrap.setLayout(grid)
        self.bl.addWidget(wrap)

    # 386px 的面板里 4 列要 334px，而内容区只有 ~300px，第 4 列会被
    # 窗口边缘切掉。改成按可用宽度算列数，并把余量摊到每格宽度上，
    # 这样以后调面板宽度也不会溢出，也不会在右侧留一道空。
    CHROME_W = 52 + 16 + 14 + 4      # tab 条 + 内容左右边距 + 滚动区右留白
    GAP_X = 6

    def _app_grid(self):
        return tile_grid(self.WIDTH - self.CHROME_W, self.GAP_X)

    def _launch_app(self, path):
        ok, err = launchers.launch(path)
        if not ok:
            self._flash("启动失败：%s" % err)

    def _mini_btn(self, text, slot):
        b = QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setFlat(True)
        b.setFixedHeight(24)
        b.setStyleSheet(
            "QPushButton{border:none;background:transparent;color:%s;font-size:11px;"
            "padding:0 8px;border-radius:6px;}"
            "QPushButton:hover{background:%s;color:%s;}"
            % (self.pal.muted.name(), self.pal.card_hi.name(), self.pal.text.name()))
        b.clicked.connect(slot)
        return b

    def _op_btn(self, text, slot, tip="", danger=False):
        b = QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedHeight(28)
        b.setToolTip(tip)
        if danger:
            fg, hover_fg, hover_bg = "#D9534F", "#FFFFFF", "rgba(217,83,79,0.85)"
        else:
            fg, hover_fg, hover_bg = self.pal.text.name(), "#FFFFFF", self.pal.accent.name()
        b.setStyleSheet(
            "QPushButton{border:1px solid %s;border-radius:7px;background:%s;"
            "color:%s;font-size:11.5px;padding:0 10px;}"
            "QPushButton:hover{background:%s;color:%s;border:1px solid %s;}"
            % (self.pal.line.name(), self.pal.card_hi.name(), fg,
               hover_bg, hover_fg, hover_bg))
        b.clicked.connect(slot)
        return b

    # -- 背景 ---------------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        path = QPainterPath()
        # 只圆左边两个角：向右多画 32px，右侧圆角落到窗口外被裁掉
        path.addRoundedRect(QRectF(-16, 0, w + 32, h), 16, 16)
        p.fillPath(path, QBrush(self.pal.card))

        # 蓝图网格：壁纸同款细网格，仅在内容区（跳过左侧 52px tab 条）
        p.save()
        # 用 setClipPath 而不是 clipPath：PyQt5 里 clipPath 同时是
        # "读取当前裁剪路径" 的无参版本，传参会被判成 too many arguments，
        # 在 paintEvent 里抛异常等于整进程 abort。
        p.setClipPath(path)
        gp = self.pal.grid
        p.setPen(QPen(gp, 1))
        step = 28
        for x in range(52, w, step):
            p.drawLine(x, 0, x, h)
        for y in range(0, h, step):
            p.drawLine(52, y, w, y)
        p.restore()

        # 青→紫渐变脊线（唯一记忆点：对应壁纸大 01 的颜色过渡）
        grad = QLinearGradient(0, 20, 0, h - 20)
        grad.setColorAt(0, self.pal.accent)
        grad.setColorAt(1, self.pal.accent_2)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRect(QRectF(0, 16, 3, h - 32))
        # 脊线上两个节点，对应壁纸折线的连接点
        for cy in (18, h - 18):
            p.setBrush(self.pal.card)
            p.setPen(QPen(self.pal.accent if cy < h / 2 else self.pal.accent_2, 2))
            p.drawEllipse(QRectF(0, cy - 4, 8, 8))
        p.end()

    # -- 搜索 ---------------------------------------------------------------
    def _queue_search(self, text):
        self._query = text.strip()
        if not self._query:
            # 清空搜索框等于放弃这轮勾选，免得"已选 3 项"悬在那儿没处看
            self._checked = []
            self._anchor = None
        self._search_timer.start()

    def _clear_body(self):
        while self.bl.count():
            item = self.bl.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _run_search(self):
        q = self._query
        if not q:
            self.hint.setVisible(False)
            self._rows = []
            self._sel = -1
            self.refresh()
            return

        base_root = self.org.root
        rows = []
        for (name, path, cat, is_dir) in self.org.index_entries():
            shown = display_name(path, name, cat)
            depth = os.path.relpath(path, os.path.join(base_root, cat)).count(os.sep)
            tag = os.path.basename(os.path.dirname(path)) if depth else cat

            best = fuzzy.match(q, shown)
            idxs = list(best[1]) if best else []
            if shown != name:
                # 文件名也认（有人习惯搜 wechat）
                r2 = fuzzy.match(q, name)
                if r2 and (best is None or r2[0] - 40 > best[0]):
                    best, idxs = r2, []
            if not best:
                continue
            rows.append((best[0] - depth * 90, shown, path, cat, is_dir, idxs, tag))

        rows.sort(key=lambda r: (-r[0], len(r[1]), r[1]))
        rows = rows[:60]

        self._clear_body()
        self._rows = []
        for _, shown, path, cat, is_dir, idxs, tag in rows:
            row = ResultRow(self.pal, shown, path, cat, is_dir, idxs,
                            lambda x=path, c=cat, d=is_dir: self._open_entry(x, c, d),
                            tag=tag, on_check=self._on_row_check)
            row.set_checked(path in self._checked)
            self.bl.addWidget(row)
            self._rows.append(row)
        self.bl.addStretch(1)

        if rows:
            self.hint.setText("找到 %d 项（点左边勾选，↑↓ 选，回车打开）" % len(rows))
            self._sel = 0
            self._rows[0].set_selected(True)
        else:
            self.hint.setText("没有匹配的文件")
            self._sel = -1
        self.hint.setVisible(True)
        self._refresh_opsbar()

    def _move_sel(self, step):
        if not self._rows:
            return
        self._rows[self._sel].set_selected(False) if 0 <= self._sel < len(self._rows) else None
        self._sel = max(0, min(len(self._rows) - 1, self._sel + step))
        self._rows[self._sel].set_selected(True)
        self.scroll.ensureWidgetVisible(self._rows[self._sel], 0, 30)

    def _open_sel(self):
        if 0 <= self._sel < len(self._rows):
            self._rows[self._sel].on_open()

    def _open_entry(self, path, cat, is_dir):
        if cat == rules.APP:
            ok, err = launchers.launch(path)
            if not ok:
                self._flash("启动失败：%s" % err)
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            self._flash("打不开：%s" % path)

    # -- 勾选 ---------------------------------------------------------------
    def _on_row_check(self, row, mods):
        """点勾选框：Shift 连选一段，其它情况切换单个。"""
        if (mods & Qt.ShiftModifier) and self._anchor:
            paths = [r.path for r in self._rows]
            if self._anchor in paths and row.path in paths:
                a, b = sorted((paths.index(self._anchor), paths.index(row.path)))
                for r in self._rows[a:b + 1]:
                    if r.path not in self._checked:
                        self._checked.append(r.path)
                    r.set_checked(True)
                self._refresh_opsbar()
                return

        if row.path in self._checked:
            self._checked.remove(row.path)
            row.set_checked(False)
        else:
            self._checked.append(row.path)
            row.set_checked(True)
        self._anchor = row.path
        self._refresh_opsbar()

    def _select_all(self):
        for r in self._rows:
            if r.path not in self._checked:
                self._checked.append(r.path)
            r.set_checked(True)
        self._refresh_opsbar()

    def _invert_sel(self):
        for r in self._rows:
            if r.path in self._checked:
                self._checked.remove(r.path)
                r.set_checked(False)
            else:
                self._checked.append(r.path)
                r.set_checked(True)
        self._refresh_opsbar()

    def _clear_sel(self):
        self._checked = []
        self._anchor = None
        for r in self._rows:
            r.set_checked(False)
        self._refresh_opsbar()

    def _refresh_opsbar(self):
        """操作条的显隐和文案。

        勾选是跨搜索保留的：搜「报告」勾三个，再搜「总结」勾两个，
        一起删掉很顺手。所以这里要说明有几项不在当前结果里。
        """
        n = len(self._checked)
        if not n:
            self.opsbar.setVisible(False)
            self.hint.setVisible(bool(self._query))
            return
        visible = sum(1 for r in self._rows if r.path in self._checked)
        txt = "已选 %d 项" % n
        if visible < n:
            txt += "（其中 %d 项不在此结果里）" % (n - visible)
        self.sel_lb.setText(txt)
        self.opsbar.setVisible(True)
        self.hint.setVisible(False)

        people = [p for p in self._checked if os.path.exists(atomicio.win_long(p))]
        n_dir = len([p for p in people if os.path.isdir(p)])
        tail = "（含 %d 个文件夹，会整包处理）" % n_dir if n_dir else ""
        self.btn_move.setToolTip("搬进抽屉里别的分类，或新建一个文件夹" + tail)
        self.btn_rename.setToolTip("把文件名里的某个词统一换掉" + tail)
        self.btn_trash.setToolTip("放进回收站，可从这里撤销" + tail)

    # -- 批量动作 -----------------------------------------------------------
    def _bulk_paths(self):
        paths = [p for p in self._checked if os.path.exists(atomicio.win_long(p))]
        if not paths:
            self._flash("选中的项目已经不在了")
            self._clear_sel()
            self.refresh()
        return paths

    def _bulk_move(self):
        paths = self._bulk_paths()
        if not paths:
            return
        dlg = MoveDialog(self, self.pal, len(paths), self.ops.target_dirs(),
                         os.path.dirname(paths[0]), self.ops)
        dlg.center_on_parent()
        if dlg.exec_() != QDialog.Accepted or not dlg.target:
            return
        done, failed = self.ops.move(paths, dlg.target)
        self._checked = []
        self._anchor = None
        self.refresh()
        msg = "已移动 %d 项到「%s」" % (len(done), os.path.basename(dlg.target))
        if failed:
            msg += "，%d 项没动（%s）" % (len(failed), failed[0][1])
        self._flash(msg)

    def _bulk_rename(self):
        paths = self._bulk_paths()
        if not paths:
            return
        dlg = RenameDialog(self, self.pal, paths, self.ops)
        dlg.center_on_parent()
        if dlg.exec_() != QDialog.Accepted:
            return
        done, failed = self.ops.rename(paths, dlg.old.text(), dlg.new.text(),
                                       include_ext=dlg.with_ext.isChecked())
        self._checked = []          # 路径全变了，旧的勾选没意义了
        self._anchor = None
        self.refresh()
        msg = "已改名 %d 项" % len(done)
        if failed:
            msg += "，%d 项跳过（%s）" % (len(failed), failed[0][1])
        self._flash(msg)

    def _bulk_trash(self):
        paths = self._bulk_paths()
        if not paths:
            return
        n_dir = len([p for p in paths if os.path.isdir(p)])
        text = ("会放进系统回收站，不是永久删除。\n"
                "删完点「撤销上次」就能拿回来。")
        if n_dir:
            text += "\n其中 %d 个是文件夹，会连同里面的内容一起进去。" % n_dir
        dlg = ConfirmDialog(self, self.pal, "删除 %d 项？" % len(paths), text,
                            ok_text="放进回收站")
        dlg.center_on_parent()
        if dlg.exec_() != QDialog.Accepted:
            return
        done, failed = self.ops.trash(paths)
        self._checked = []
        self._anchor = None
        self.refresh()
        msg = "已把 %d 项放进回收站" % len(done)
        if failed:
            msg += "，%d 项没动（%s）" % (len(failed), failed[0][1])
        self._flash(msg)

    def eventFilter(self, obj, ev):
        if obj is self.search and ev.type() == QEvent.KeyPress:
            k = ev.key()
            if k == Qt.Key_Down:
                self._move_sel(1); return True
            if k == Qt.Key_Up:
                self._move_sel(-1); return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self._open_sel(); return True
            if k == Qt.Key_Escape:
                if self.search.text():
                    self.search.clear()
                else:
                    self.slide_out()
                return True
        return super(Panel, self).eventFilter(obj, ev)

    # -- 数据 ---------------------------------------------------------------
    def refresh(self):
        data = self.org.summary()
        total = sum(rules.count_items(c, data[c]) for c in data)
        # 头部横向只有 ~274px，加上 ITEMS 会顶开右边的按钮，所以只留数字
        self.sub.setText("ARCHIVED  %d" % total)
        self.path_hint.setText("归档位置：%s"
                               % self.org.root.replace(os.path.expanduser("~"), "~"))

        pend = self.org.pending_count()
        if pend:
            self.banner_lb.setText("桌面上还有 %d 项待归类" % pend)
            self.banner.setVisible(True)
        else:
            self.banner.setVisible(False)

        # 正在搜索时不要被分类列表覆盖，把搜索结果重跑一遍
        if self._query:
            self._run_search()
            self._update_undo_btn()
            return

        self._rows = []
        self.opsbar.setVisible(False)
        self._clear_body()
        if self.tab == "apps":
            self._fill_app_page(data.get(rules.APP, []))
        else:
            # 文件页不再重复显示应用分类（应用已在应用页铺开）
            for cat in rules.CATEGORY_ORDER:
                if cat == rules.APP:
                    continue
                row = CatRow(self.pal, cat, rules.CATEGORY_DESC.get(cat, ""),
                             data.get(cat, []), cfg=self.cfg)
                self.bl.addWidget(row)
        self.bl.addStretch(1)
        self._update_undo_btn()

    def _update_undo_btn(self):
        has = bool(self.org.last_batch_info()) or bool(self.ops.last_info())
        self.btn_undo.setEnabled(has)
        self.btn_undo.setStyleSheet(
            "QPushButton{border:none;background:transparent;color:%s;font-size:11px;"
            "padding:0 8px;border-radius:6px;}"
            "QPushButton:hover{background:%s;color:%s;}"
            % ((self.pal.muted.name() if has else self.pal.line.name()),
               self.pal.card_hi.name(), self.pal.text.name()))

    # -- 动作 ---------------------------------------------------------------
    def organize(self):
        try:
            moved = self.org.apply()
        except Exception as e:
            self._flash("整理失败：%s" % e)
            return
        self.refresh()
        self._flash("已归类 %d 项" % len(moved) if moved else "没有需要整理的")

    def undo(self):
        """撤销最近一次操作：一键整理和批量操作共用这个按钮，谁的更近撤谁。"""
        n, msg = bulkops.undo_latest(self.org, self.ops, appcfg.LOG_FILE)
        self.refresh()
        self._flash(msg or "没有可撤销的记录")

    def _open_root(self):
        self.org.ensure_dirs()
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.org.root))

    def _flash(self, msg):
        self.status.setText(msg)
        QTimer.singleShot(3200, lambda: self.status.setText(""))

    # -- 滑动 ---------------------------------------------------------------
    def slide_in(self):
        if self.is_open:
            return
        self.refresh()
        self.is_open = True
        self.setWindowOpacity(0.0)
        self.move(self._x_hidden, self._top)
        self.show()
        self.raise_()
        try:
            self.activateWindow()
        except Exception:
            pass
        self._anim.stop()
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(QPoint(self._x_shown, self._top))
        self._anim.start()
        if self.on_show:
            self.on_show()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def slide_out(self):
        if not self.is_open and not self.isVisible():
            return
        self.is_open = False
        self._anim.stop()
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(QPoint(self._x_hidden, self._top))
        self._anim.start()
        self._anim.finished.connect(self._after_out)

    def _after_out(self):
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self.hide()
        if self.on_hide:
            self.on_hide()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.slide_out()
        else:
            super(Panel, self).keyPressEvent(e)

    def changeEvent(self, e):
        # 点到别处就收起，但拖动画期间不响应
        if e.type() == e.ActivationChange and not self.isActiveWindow() \
                and self.is_open and self._anim.state() != QPropertyAnimation.Running:
            QTimer.singleShot(120, self._maybe_hide)
        super(Panel, self).changeEvent(e)

    def _maybe_hide(self):
        if self.is_open and not self.isActiveWindow():
            self.slide_out()


