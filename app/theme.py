#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桌面整理 —— 统一配色（跟随系统深浅色）"""

from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

# 每个分类的标识色，面板里用来做色块
CAT_COLORS = {
    "文档": "#4C8DFF",
    "文件夹": "#C08B52",
    "应用": "#6C6CF0",
    "快捷方式": "#86A34D",
    "图片": "#22C58B",
    "图标": "#F2A33C",
    "视频": "#A66BFF",
    "音频": "#F26D9C",
    "压缩包": "#6D8BA8",
    "安装包": "#E2683C",
    "代码": "#39BFC6",
    "其他": "#8A8F98",
}


class Palette(object):
    def __init__(self, dark=True):
        self.dark = dark
        if dark:
            self.bg = QColor("#1B1D21")
            self.card = QColor("#24272C")
            self.card_hi = QColor("#2F333A")
            self.line = QColor("#34383F")
            self.text = QColor("#E9EBEF")
            self.muted = QColor("#8C929C")
            self.accent = QColor("#4C8DFF")
        else:
            self.bg = QColor("#F4F5F7")
            self.card = QColor("#FFFFFF")
            self.card_hi = QColor("#EEF1F5")
            self.line = QColor("#E1E4E9")
            self.text = QColor("#1B1E23")
            self.muted = QColor("#6B7280")
            self.accent = QColor("#2F72E8")


def system_is_dark():
    app = QApplication.instance()
    pal = app.palette() if app else QPalette()
    return pal.color(QPalette.Window).lightness() < 128
