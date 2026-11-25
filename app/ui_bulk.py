#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— 批量操作对话框

都是无边框卡片：跟着抽屉的配色走，不用系统原生对话框（那套在深色主题下很扎眼）。
四个：
  MoveDialog     挑目标文件夹（抽屉内目录 / 新建 / 其他位置）
  RenameDialog   查找替换，带实时预览
  PromptDialog   单行输入
  ConfirmDialog  危险动作确认
"""

import os

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QBrush, QFont
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QLineEdit, QListWidget, QListWidgetItem, QCheckBox,
                             QScrollArea, QWidget, QFrame, QFileDialog)


class Sheet(QDialog):
    """卡片式对话框基类：标题 + 说明 + 内容 + 底部按钮。"""

    def __init__(self, parent, pal, title, subtitle="", width=352):
        super(Sheet, self).__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.pal = pal
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setFixedWidth(width)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)

        t = QLabel(title)
        t.setStyleSheet("color:%s;font-size:14px;font-weight:700;background:transparent;"
                        % pal.text.name())
        outer.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setWordWrap(True)
            s.setStyleSheet("color:%s;font-size:11px;background:transparent;"
                            % pal.muted.name())
            outer.addWidget(s)

        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body, 1)

        self.foot = QHBoxLayout()
        self.foot.setSpacing(8)
        outer.addLayout(self.foot)

    # -- 按钮 ---------------------------------------------------------------
    def button(self, text, slot, primary=False, danger=False):
        b = QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedHeight(30)
        b.setMinimumWidth(64)
        if danger:
            bg, hover, fg = "#E05A5A", "#C94B4B", "#FFFFFF"
        elif primary:
            bg, hover, fg = (self.pal.accent.name(),
                             self.pal.accent.darker(112).name(), "#FFFFFF")
        else:
            bg, hover, fg = "transparent", self.pal.card_hi.name(), self.pal.text.name()
        border = "none" if (primary or danger) else "1px solid %s" % self.pal.line.name()
        b.setStyleSheet(
            "QPushButton{border:%s;border-radius:8px;background:%s;color:%s;"
            "font-size:12px;padding:0 14px;}"
            "QPushButton:hover{background:%s;}"
            "QPushButton:disabled{color:%s;background:transparent;}"
            % (border, bg, fg, hover, self.pal.line.name()))
        b.clicked.connect(slot)
        return b

    # -- 外观 ---------------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 14, 14)
        p.fillPath(path, QBrush(self.pal.card))
        p.setPen(QColor(self.pal.line))
        p.drawPath(path)
        p.end()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.reject()
        else:
            super(Sheet, self).keyPressEvent(e)

    def center_on_parent(self):
        par = self.parent()
        if par is None:
            return
        g = par.geometry()
        self.move(g.center().x() - self.width() // 2,
                  max(40, g.center().y() - self.height() // 2))


# --------------------------------------------------------------------------- #
# 输入
# --------------------------------------------------------------------------- #
class PromptDialog(Sheet):
    def __init__(self, parent, pal, title, label, default=""):
        super(PromptDialog, self).__init__(parent, pal, title)
        lb = QLabel(label)
        lb.setStyleSheet("color:%s;font-size:11px;background:transparent;"
                         % pal.muted.name())
        self.body.addWidget(lb)

        self.edit = QLineEdit(default)
        self.edit.setFixedHeight(32)
        self.edit.setStyleSheet(
            "QLineEdit{border:1px solid %s;border-radius:8px;background:%s;color:%s;"
            "font-size:12px;padding:0 10px;}"
            "QLineEdit:focus{border:1px solid %s;}"
            % (pal.line.name(), pal.card_hi.name(), pal.text.name(), pal.accent.name()))
        self.edit.returnPressed.connect(self.accept)
        self.body.addWidget(self.edit)

        self.err = QLabel("")
        self.err.setStyleSheet("color:#E05A5A;font-size:10.5px;background:transparent;")
        self.err.setVisible(False)
        self.body.addWidget(self.err)

        self.foot.addStretch(1)
        self.foot.addWidget(self.button("取消", self.reject))
        self.foot.addWidget(self.button("确定", self._ok, primary=True))
        self.adjustSize()

    def _ok(self):
        if not self.edit.text().strip():
            self.err.setText("名字不能为空")
            self.err.setVisible(True)
            return
        self.accept()

    def value(self):
        return self.edit.text().strip()

    def showEvent(self, e):
        super(PromptDialog, self).showEvent(e)
        self.edit.setFocus()
        self.edit.selectAll()


class ConfirmDialog(Sheet):
    def __init__(self, parent, pal, title, text, ok_text="确定", danger=True):
        super(ConfirmDialog, self).__init__(parent, pal, title, width=340)
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:%s;font-size:11.5px;line-height:150%%;background:transparent;"
                         % pal.text.name())
        self.body.addWidget(lb)
        self.foot.addStretch(1)
        self.foot.addWidget(self.button("取消", self.reject))
        self.foot.addWidget(self.button(ok_text, self.accept, danger=danger))
        self.adjustSize()


# --------------------------------------------------------------------------- #
# 移动
# --------------------------------------------------------------------------- #
class MoveDialog(Sheet):
    """挑一个目标目录。列表里是抽屉现有目录，也可以新建或另选。"""

    def __init__(self, parent, pal, count, targets, start_dir, ops):
        super(MoveDialog, self).__init__(
            parent, pal, "移动到文件夹",
            "已选 %d 项。选一个目标，文件会搬过去，原位置不再保留。" % count,
            width=368)
        self.ops = ops
        self.target = None
        self._targets = list(targets)

        self.listw = QListWidget()
        self.listw.setFixedHeight(246)
        self.listw.setStyleSheet(
            "QListWidget{background:%s;border:1px solid %s;border-radius:9px;"
            "color:%s;font-size:12px;padding:4px;outline:none;}"
            "QListWidget::item{height:26px;border-radius:6px;padding-left:8px;}"
            "QListWidget::item:selected{background:%s;color:#FFF;}"
            "QListWidget::item:hover{background:%s;}"
            % (pal.card_hi.name(), pal.line.name(), pal.text.name(),
               pal.accent.name(), pal.line.name()))
        self.listw.itemDoubleClicked.connect(lambda _: self._ok())
        self.body.addWidget(self.listw)
        self._fill(self._targets, os.path.abspath(start_dir) if start_dir else "")

        self.tip = QLabel("")
        self.tip.setWordWrap(True)
        self.tip.setStyleSheet("color:%s;font-size:10.5px;background:transparent;"
                               % pal.muted.name())
        self.body.addWidget(self.tip)

        self.foot.addWidget(self.button("新建文件夹", self._new_dir))
        self.foot.addWidget(self.button("其他位置…", self._browse))
        self.foot.addStretch(1)
        self.foot.addWidget(self.button("取消", self.reject))
        self.foot.addWidget(self.button("移动", self._ok, primary=True))

    def _fill(self, targets, select_path=""):
        self.listw.clear()
        for name, path, depth in targets:
            it = QListWidgetItem(("　" * depth) + name)
            it.setData(Qt.UserRole, path)
            it.setToolTip(path)
            self.listw.addItem(it)
        # 默认选中离当前文件最近的那个目录
        for i in range(self.listw.count()):
            if self.listw.item(i).data(Qt.UserRole) == select_path:
                self.listw.setCurrentRow(i)
                break

    def _current_dir(self):
        it = self.listw.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _new_dir(self):
        parent = self._current_dir() or os.path.dirname(self._targets[0][1])
        dlg = PromptDialog(self, self.pal, "新建文件夹",
                           "会在「%s」下面创建" % os.path.basename(parent), "新建文件夹")
        dlg.center_on_parent()
        if dlg.exec_() != QDialog.Accepted:
            return
        try:
            newpath = self.ops.make_dir(parent, dlg.value())
        except Exception as e:
            self.tip.setText(str(e))
            return
        # 新建的目录直接插进列表并选中
        rel = os.path.relpath(newpath, os.path.dirname(newpath) and
                              os.path.dirname(self._targets[0][1]) or "")
        self._targets.append((os.path.basename(newpath), newpath, 1))
        self._fill(self._targets, newpath)
        self.tip.setText("已新建「%s」，已自动选中" % os.path.basename(newpath))

    def _browse(self):
        start = os.path.expanduser("~")
        d = QFileDialog.getExistingDirectory(self, "选择目标文件夹", start)
        if not d:
            return
        self.target = d
        self.listw.clearSelection()
        self.tip.setText("已选外部目录：%s" % d)

    def _ok(self):
        self.accept()

    def accept(self):
        """不管从哪条路确认（按钮 / 双击 / 回车），都要保证 target 有值。"""
        if not self.target:
            self.target = self._current_dir()
        if not self.target:
            self.tip.setText("还没选目标目录")
            return
        super(MoveDialog, self).accept()


# --------------------------------------------------------------------------- #
# 重命名
# --------------------------------------------------------------------------- #
class RenameDialog(Sheet):
    """查找 → 替换，实时预览。默认不动扩展名。"""

    PREVIEW_MAX = 40

    def __init__(self, parent, pal, paths, ops):
        super(RenameDialog, self).__init__(
            parent, pal, "批量重命名",
            "把文件名里的某个词统一换掉。扩展名默认不动。", width=376)
        self.ops = ops
        self.paths = list(paths)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.old = QLineEdit()
        self.old.setPlaceholderText("查找（比如 报告）")
        self.new = QLineEdit()
        self.new.setPlaceholderText("替换为（留空=删掉这个词）")
        for e in (self.old, self.new):
            e.setFixedHeight(30)
            e.setStyleSheet(
                "QLineEdit{border:1px solid %s;border-radius:8px;background:%s;"
                "color:%s;font-size:12px;padding:0 9px;}"
                "QLineEdit:focus{border:1px solid %s;}"
                % (pal.line.name(), pal.card_hi.name(), pal.text.name(),
                   pal.accent.name()))
            e.textChanged.connect(self._update)
        row1.addWidget(self.old, 1)
        arrow = QLabel("→")
        arrow.setStyleSheet("color:%s;font-size:13px;background:transparent;"
                            % pal.muted.name())
        row1.addWidget(arrow)
        row1.addWidget(self.new, 1)
        self.body.addLayout(row1)

        self.with_ext = QCheckBox("连扩展名一起改")
        self.with_ext.setStyleSheet(
            "QCheckBox{color:%s;font-size:11px;background:transparent;}"
            "QCheckBox::indicator{width:13px;height:13px;border-radius:3px;"
            "border:1px solid %s;background:%s;}"
            "QCheckBox::indicator:checked{background:%s;border:1px solid %s;}"
            % (pal.muted.name(), pal.line.name(), pal.card_hi.name(),
               pal.accent.name(), pal.accent.name()))
        self.with_ext.stateChanged.connect(self._update)
        self.body.addWidget(self.with_ext)

        self.scroll = QScrollArea()
        self.scroll.setFixedHeight(158)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet(
            "QScrollArea{background:%s;border:1px solid %s;border-radius:9px;}"
            "QScrollBar:vertical{width:6px;background:transparent;margin:2px 0;}"
            "QScrollBar::handle:vertical{background:rgba(140,146,156,0.45);"
            "border-radius:3px;min-height:24px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            % (pal.card_hi.name(), pal.line.name()))
        self.view = QWidget()
        self.view.setStyleSheet("background:transparent;")
        self.vl = QVBoxLayout(self.view)
        self.vl.setContentsMargins(9, 7, 9, 7)
        self.vl.setSpacing(3)
        self.scroll.setWidget(self.view)
        self.body.addWidget(self.scroll)

        self.count_lb = QLabel("")
        self.count_lb.setStyleSheet("color:%s;font-size:11px;background:transparent;"
                                    % pal.muted.name())
        self.body.addWidget(self.count_lb)

        self.foot.addStretch(1)
        self.foot.addWidget(self.button("取消", self.reject))
        self.btn_ok = self.button("重命名", self._ok, primary=True)
        self.foot.addWidget(self.btn_ok)
        self.adjustSize()

        self._update()

    def _plan(self):
        return self.ops.rename_preview(
            self.paths, self.old.text(), self.new.text(),
            include_ext=self.with_ext.isChecked())

    def _update(self):
        while self.vl.count():
            item = self.vl.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        plan = self._plan()
        will = [p for p in plan if p[2]]
        self.btn_ok.setEnabled(bool(self.old.text()) and bool(will))

        if not self.old.text():
            self.count_lb.setText("输入要查找的词，下面会实时预览改名结果")
        else:
            rest = len(plan) - len(will)
            self.count_lb.setText("%d 个会改名" % len(will)
                                  + ("，%d 个不含该词、跳过" % rest if rest else ""))

        for path, oldname, newname, why in plan[:self.PREVIEW_MAX]:
            row = QLabel()
            row.setWordWrap(True)
            row.setStyleSheet("background:transparent;font-size:11px;")
            if newname:
                row.setText(
                    "<span style='color:%s;text-decoration:line-through'>%s</span>"
                    "<span style='color:%s'>&nbsp;&nbsp;→&nbsp;&nbsp;</span>"
                    "<span style='color:%s;font-weight:600'>%s</span>"
                    % (self.pal.muted.name(), oldname,
                       self.pal.muted.name(), self.pal.accent.name(), newname))
            else:
                row.setText("<span style='color:%s;text-decoration:line-through'>%s</span>"
                            "<span style='color:%s'>　%s</span>"
                            % (self.pal.line.name(), oldname,
                               self.pal.muted.name(), why or "跳过"))
            self.vl.addWidget(row)
        if len(plan) > self.PREVIEW_MAX:
            more = QLabel("…还有 %d 项" % (len(plan) - self.PREVIEW_MAX))
            more.setStyleSheet("color:%s;font-size:10.5px;background:transparent;"
                               % self.pal.muted.name())
            self.vl.addWidget(more)
        self.vl.addStretch(1)

    def _ok(self):
        if not self.old.text():
            return
        self.accept()

    def showEvent(self, e):
        super(RenameDialog, self).showEvent(e)
        self.old.setFocus()
