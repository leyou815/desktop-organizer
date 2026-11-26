#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— 视觉系统「01 / Blueprint Terminal」

设计主张：和 01comfyui 壁纸同频的技术图纸美学。
  - 浅色 = 冷白画布 + 青(#1E9CC7)→紫(#6D5CE7) 双主色
  - 深色 = 墨蓝底(#0B1624) + 同色相提亮
  - 两套共用同一组色相，只换明度，保证和壁纸完全契合
  - 西文 Bahnschrift（DIN 风格，对应壁纸大号 01）+ Cascadia Mono（等宽标签）
  - 中文 微软雅黑 / 系统默认

所有色值、字体、字号、间距都从这里取，UI 层不写死。
"""

from PyQt5.QtGui import QColor, QPalette, QFont
from PyQt5.QtWidgets import QApplication

# --------------------------------------------------------------------------- #
# 品牌色（两个主题共用，深浅只换明度/透明度）
# --------------------------------------------------------------------------- #
CYAN = "#1E9CC7"       # 壁纸左半的青
CYAN_LT = "#38B8DB"    # 深色底上提亮的青
PURPLE = "#6D5CE7"     # 壁纸右半的紫
PURPLE_LT = "#8B7CF6"  # 深色底上提亮的紫

# 字体家族：优先用壁纸同款气质的字体，缺了就用系统等价
FONT_DISPLAY = "Bahnschrift"      # 大标题 / 编号 / 数字（DIN 气质）
FONT_MONO = "Cascadia Mono"       # 等宽标签（对应 NODE / ORIGIN / FLOW）
FONT_UI = "Microsoft YaHei"       # 中文正文（Qt 内可用 family 名）
FONT_UI_FALLBACK = "SimHei"

# 字号标度（px）
SZ_MICRO = 10         # 标签 / 角标
SZ_SMALL = 11         # 辅助说明
SZ_BODY = 12          # 正文
SZ_TITLE = 15         # 标题
SZ_DISPLAY = 34       # 大编号 / hero

# 圆角 / 间距（px）
R_SM = 6
R_MD = 9
R_LG = 13
GAP = 8

# 每个分类的标识色 —— 统一到青紫蓝图色系，保留少量辅助色做区分
CAT_COLORS = {
    "文档": CYAN,
    "文件夹": "#C08B52",
    "应用": PURPLE,
    "快捷方式": "#86A34D",
    "图片": "#22C58B",
    "图标": "#F2A33C",
    "视频": "#A66BFF",
    "音频": "#F26D9C",
    "压缩包": "#6D8BA8",
    "安装包": "#E2683C",
    "代码": CYAN,
    "其他": "#8A8F98",
}


class Palette(object):
    """Blueprint 双主题令牌。UI 层只读属性，不自行调色。"""

    def __init__(self, dark=True):
        self.dark = dark
        if dark:
            # 深色：墨蓝底，青紫提亮
            self.bg = QColor("#0B1624")
            self.card = QColor("#101E30")
            self.card_hi = QColor("#16283E")
            self.line = QColor("#1E344C")
            self.text = QColor("#E4EDF5")
            self.muted = QColor("#8CA3B8")
            self.accent = QColor(CYAN_LT)
            self.accent_2 = QColor(PURPLE_LT)
            self.grid = QColor(255, 255, 255, 12)      # 网格底纹
            self.tint_cyan = QColor(CYAN_LT)
            self.tint_purple = QColor(PURPLE_LT)
            self.shadow = QColor(0, 0, 0, 90)
        else:
            # 浅色：冷白画布，青紫原色
            self.bg = QColor("#F5F8FC")
            self.card = QColor("#FFFFFF")
            self.card_hi = QColor("#EEF3F9")
            self.line = QColor("#DCE6F0")
            self.text = QColor("#16263B")
            self.muted = QColor("#6C8299")
            self.accent = QColor(CYAN)
            self.accent_2 = QColor(PURPLE)
            self.grid = QColor(30, 90, 150, 14)        # 网格底纹
            self.tint_cyan = QColor(CYAN)
            self.tint_purple = QColor(PURPLE)
            self.shadow = QColor(20, 50, 90, 26)

        # 由此派生的语义色
        self.success = QColor("#22C58B") if not dark else QColor("#3DD9A0")
        self.danger = QColor("#E05A5A")

    # -- 字体 ----------------------------------------------------------------
    def font_ui(self, size=SZ_BODY, bold=False):
        f = QFont()
        f.setFamily(FONT_UI)
        f.setPointSizeF(size * 0.75)     # px -> pt 近似，Qt 用 pt
        f.setBold(bold)
        return f

    def font_display(self, size=SZ_DISPLAY, bold=True):
        f = QFont()
        f.setFamily(FONT_DISPLAY)
        f.setPointSizeF(size * 0.75)
        f.setBold(bold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.5)
        return f

    def font_mono(self, size=SZ_MICRO):
        f = QFont()
        f.setFamily(FONT_MONO)
        f.setPointSizeF(size * 0.75)
        return f

    # -- 样式表片段 ----------------------------------------------------------
    def ss_input(self):
        """输入框统一样式（青紫描边焦点态）。"""
        return ("border:1px solid %s;border-radius:%dpx;background:%s;"
                "color:%s;font-size:%dpx;padding-left:10px;padding-right:6px;"
                % (self.line.name(), R_MD, self.card.name(),
                   self.text.name(), SZ_BODY))

    def ss_input_focus(self):
        return "border:1px solid %s;" % self.accent.name()

    def ss_mono_tag(self):
        """等宽小标签：对应壁纸角落的 NODE / ORIGIN / FLOW。"""
        return ("font-family:'%s';font-size:%dpx;letter-spacing:1px;color:%s;"
                % (FONT_MONO, SZ_MICRO, self.muted.name()))


def system_is_dark():
    app = QApplication.instance()
    pal = app.palette() if app else QPalette()
    return pal.color(QPalette.Window).lightness() < 128
