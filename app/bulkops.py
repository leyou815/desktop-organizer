#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— 批量操作

搜索结果里勾选若干项之后能干的事：
  移动到   搬进抽屉内任意目录，或你自己挑的目录
  重命名   统一替换文件名主干里的某个词
  删除     放进系统回收站（不是 rm），能从这里撤销，也能在文件管理器回收站还原

三条硬规矩：
  1. 删除只进回收站，永不 os.remove
  2. 每一步都记账（ops.jsonl），按批次可逆序撤销
  3. 归档根、分类根、桌面目录本身永远不许被删或被搬

日志和整理用的 moves.jsonl 分开放：整理是"桌面 → 抽屉"的单向搬运，
批量操作是任意方向的用户意图，混在一起会让 undo 的语义变糊。
"""

import json
import os
import shutil
import time
import uuid

import config as appcfg
import rules
import sysenv

OP_FILE = os.path.join(appcfg.CONFIG_DIR, "ops.jsonl")


def unique_path(dst):
    """目标重名时生成「名字 (2).ext」，绝不覆盖。"""
    if not os.path.exists(dst):
        return dst
    base, ext = os.path.splitext(dst)
    i = 2
    while True:
        cand = "%s (%d)%s" % (base, i, ext)
        if not os.path.exists(cand):
            return cand
        i += 1


def _unique_in(directory, name):
    """回收站里的重名规则是 name / name.2 / name.3（跟 gvfs 保持一致）。"""
    cand = os.path.join(directory, name)
    if not os.path.exists(cand):
        return cand
    i = 2
    while True:
        cand = os.path.join(directory, "%s.%d" % (name, i))
        if not os.path.exists(cand):
            return cand
        i += 1


def trash_dirs():
    """freedesktop 规定的用户回收站位置。"""
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")
    root = os.path.join(base, "Trash")
    return os.path.join(root, "files"), os.path.join(root, "info")


def _quote(path):
    """trashinfo 里的 Path 必须是 URL 编码的绝对路径。"""
    from urllib.parse import quote
    return quote(os.path.abspath(path), safe="/")


class BulkError(RuntimeError):
    pass


class BulkOps(object):
    """勾选后的批量动作。org 用来判断哪些路径属于归档目录。"""

    def __init__(self, org=None, cfg=None):
        self.org = org
        self.root = org.root if org is not None else None
        self.cfg = cfg

    # -- 安全 ---------------------------------------------------------------
    def is_protected(self, path):
        """归档骨架、桌面目录本身、以及比它们更上层的目录都不许动。"""
        p = os.path.abspath(path)
        desk = os.path.abspath(self.org.desktop) if self.org is not None else ""
        if desk and p == desk:
            return True
        if self.root:
            root = os.path.abspath(self.root)
            if p == root:
                return True
            parent = os.path.dirname(p)
            if parent == root and os.path.basename(p) in rules.CATEGORY_ORDER:
                return True        # 分类根，删了归档结构就散了
        return False

    def why_blocked(self, paths):
        bad = [p for p in paths if self.is_protected(p)]
        return bad

    # -- 目标目录 -----------------------------------------------------------
    def target_dirs(self):
        """抽屉里能当作移动目标的目录：[(显示名, 路径, 深度)]，只列目录。"""
        out = []
        if not self.root or not os.path.isdir(self.root):
            return out
        for cat in rules.CATEGORY_ORDER:
            cdir = os.path.join(self.root, cat)
            if not os.path.isdir(cdir):
                continue
            out.append((cat, cdir, 0))
            try:
                subs = sorted(d for d in os.listdir(cdir)
                              if os.path.isdir(os.path.join(cdir, d)) and not d.startswith("."))
            except OSError:
                subs = []
            for sub in subs:
                out.append(("%s / %s" % (cat, sub), os.path.join(cdir, sub), 1))
        return out

    # -- 移动 ---------------------------------------------------------------
    def move(self, paths, target_dir):
        """把 paths 搬进 target_dir，返回 (成功列表[(src,dst)], 失败列表[(src,原因)])。"""
        target_dir = os.path.abspath(target_dir)
        if not os.path.isdir(target_dir):
            raise BulkError("目标目录不存在：%s" % target_dir)

        batch = self._new_batch()
        done, failed = [], []
        for src in paths:
            if self.is_protected(src):
                failed.append((src, "归档结构目录，不能移动"))
                continue
            if os.path.dirname(os.path.abspath(src)) == target_dir:
                failed.append((src, "已经在这个文件夹里了"))
                continue
            if os.path.isdir(src):
                # 不能把目录搬进它自己或它的子目录里
                if target_dir == os.path.abspath(src) or \
                        target_dir.startswith(os.path.abspath(src) + os.sep):
                    failed.append((src, "不能移动到它自己里面"))
                    continue
            dst = unique_path(os.path.join(target_dir, os.path.basename(src)))
            try:
                shutil.move(src, dst)
            except (OSError, shutil.Error) as e:
                failed.append((src, str(e)))
                continue
            self._log(batch, "move", src=src, dst=dst)
            done.append((src, dst))
        self._invalidate()
        return done, failed

    # -- 删除（进回收站）----------------------------------------------------
    def trash(self, paths):
        """放进回收站，返回 (成功列表[(src, 回收站路径)], 失败列表)。

        Linux：自己按 freedesktop 规范搬进 ~/.local/share/Trash，
               这样我们知道落点，撤销时能精确移回来。
        Windows：交给 SHFileOperation，落点无法可靠取回，撤销要靠系统回收站。
        """
        if sysenv.IS_WINDOWS:
            return self._trash_win(paths)

        files_dir, info_dir = trash_dirs()
        try:
            os.makedirs(files_dir, exist_ok=True)
            os.makedirs(info_dir, exist_ok=True)
        except OSError as e:
            raise BulkError("回收站目录不可用：%s" % e)

        batch = self._new_batch()
        done, failed = [], []
        for src in paths:
            if not os.path.exists(src):
                failed.append((src, "文件已不存在"))
                continue
            if self.is_protected(src):
                failed.append((src, "归档结构目录，不能删除"))
                continue
            name = os.path.basename(src)
            dst = _unique_in(files_dir, name)
            info = dst + ".trashinfo"
            try:
                shutil.move(src, dst)
            except (OSError, shutil.Error) as e:
                failed.append((src, str(e)))
                continue
            try:
                with open(os.path.join(info_dir, os.path.basename(info)),
                          "w", encoding="utf-8") as f:
                    f.write("[Trash Info]\nPath=%s\nDeletionDate=%s\n"
                            % (_quote(src), time.strftime("%Y-%m-%dT%H:%M:%S")))
            except OSError:
                # 写 info 失败也要把文件放回去，否则回收站里会出现无主条目
                try:
                    shutil.move(dst, src)
                except (OSError, shutil.Error):
                    pass
                failed.append((src, "回收站信息写入失败"))
                continue
            self._log(batch, "trash", src=src, dst=dst,
                      info=os.path.join(info_dir, os.path.basename(info)))
            done.append((src, dst))
        self._invalidate()
        return done, failed

    def _trash_win(self, paths):
        import ctypes
        batch = self._new_batch()
        done, failed = [], []
        for src in paths:
            if self.is_protected(src):
                failed.append((src, "归档结构目录，不能删除"))
                continue
            try:
                # FOF_ALLOWUNDO 才进回收站；没有它等于永久删除
                class SHFILEOPSTRUCTW(ctypes.Structure):
                    _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint),
                                ("pFrom", ctypes.c_wchar_p), ("pTo", ctypes.c_wchar_p),
                                ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", ctypes.c_int),
                                ("hNameMappings", ctypes.c_void_p),
                                ("lpszProgressTitle", ctypes.c_wchar_p)]

                op = SHFILEOPSTRUCTW()
                op.wFunc = 3                      # FO_DELETE
                op.pFrom = os.path.abspath(src) + "\0\0"
                op.fFlags = 0x0040 | 0x0010 | 0x0004   # ALLOWUNDO | NOCONFIRMATION | SILENT
                if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) != 0:
                    failed.append((src, "回收站操作失败"))
                    continue
            except Exception as e:
                failed.append((src, str(e)))
                continue
            self._log(batch, "trash_win", src=src, dst="")
            done.append((src, ""))
        self._invalidate()
        return done, failed

    # -- 重命名 -------------------------------------------------------------
    def rename_preview(self, paths, old, new, include_ext=False):
        """不落地，先算出改完长什么样。返回 [(path, 旧名, 新名 or None, 跳过原因)]。"""
        out = []
        if not old:
            return out
        taken = set(os.path.abspath(p) for p in paths)
        for p in paths:
            name = os.path.basename(p)
            if include_ext:
                stem, ext = name, ""
            else:
                stem, ext = os.path.splitext(name)
            if old not in stem:
                out.append((p, name, None, "文件名里没有「%s」" % old))
                continue
            new_stem = stem.replace(old, new)
            if not new_stem.strip():
                out.append((p, name, None, "替换后名字会变成空"))
                continue
            new_name = new_stem + ext
            if new_name == name:
                out.append((p, name, None, "名字没变化"))
                continue
            cand = os.path.join(os.path.dirname(p), new_name)
            # 同批里的其它文件会让位，不算冲突
            if os.path.exists(cand) and os.path.abspath(cand) not in taken:
                cand = unique_path(cand)
            out.append((p, name, os.path.basename(cand), ""))
        return out

    def rename(self, paths, old, new, include_ext=False):
        """统一替换文件名里的词，返回 (成功[(src,dst)], 失败[(src,原因)])。"""
        if not old:
            raise BulkError("要替换的词不能为空")
        batch = self._new_batch()
        done, failed = [], []
        plan = self.rename_preview(paths, old, new, include_ext)

        # 先把会让位的路径记下来，避免 A→B 和 B→C 互相踩
        moving = set(os.path.abspath(p) for p, _, n, _ in plan if n)
        for src, oldname, newname, why in plan:
            if not newname:
                if why and why != "名字没变化":
                    failed.append((src, why))
                continue
            dst = os.path.join(os.path.dirname(src), newname)
            if os.path.exists(dst):
                if os.path.abspath(dst) in moving:
                    dst = unique_path(dst)
                else:
                    dst = unique_path(dst)
            try:
                os.rename(src, dst)
            except OSError as e:
                failed.append((src, str(e)))
                continue
            self._log(batch, "rename", src=src, dst=dst)
            done.append((src, dst))
        self._invalidate()
        return done, failed

    # -- 新建文件夹 ---------------------------------------------------------
    def make_dir(self, parent, name):
        name = (name or "").strip().strip("/")
        if not name:
            raise BulkError("文件夹名不能为空")
        if name in (".", ".."):
            raise BulkError("文件夹名不合法")
        dst = os.path.join(parent, name)
        if os.path.exists(dst):
            raise BulkError("「%s」已经存在了" % name)
        try:
            os.makedirs(dst)
        except OSError as e:
            raise BulkError("创建失败：%s" % e)
        self._invalidate()
        return dst

    # -- 记账 ---------------------------------------------------------------
    def _new_batch(self):
        return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]

    def _log(self, batch, op, **fields):
        os.makedirs(os.path.dirname(OP_FILE), exist_ok=True)
        rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "batch": batch, "op": op}
        rec.update(fields)
        try:
            with open(OP_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def history(self):
        if not os.path.isfile(OP_FILE):
            return []
        out = []
        try:
            with open(OP_FILE, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            return []
        return out

    def last_info(self):
        """最近一批批量操作：(中文标签, 条数, 时间戳) 或 None。"""
        recs = self.history()
        if not recs:
            return None
        batch = recs[-1]["batch"]
        items = [r for r in recs if r.get("batch") == batch]
        label = {"move": "移动", "trash": "删除", "rename": "重命名",
                 "trash_win": "删除"}.get(items[0].get("op"), "操作")
        return label, len(items), items[0].get("ts", "")

    # -- 撤销 ---------------------------------------------------------------
    def undo_last(self):
        """撤销最近一批批量操作，返回 (标签, 实际撤回条数, 提示)。"""
        recs = self.history()
        if not recs:
            return None, 0, ""
        batch = recs[-1]["batch"]
        items = [r for r in recs if r.get("batch") == batch]
        op = items[0].get("op")
        label = {"move": "移动", "trash": "删除", "rename": "重命名",
                 "trash_win": "删除"}.get(op, "操作")

        note = ""
        if op == "trash_win":
            return label, 0, "Windows 的删除进了系统回收站，请在回收站里还原"

        count = 0
        for r in reversed(items):
            src, dst = r.get("src"), r.get("dst")
            try:
                if op == "rename":
                    if dst and os.path.exists(dst):
                        back = unique_path(src) if os.path.exists(src) else src
                        os.rename(dst, back)
                        count += 1
                elif op == "move":
                    if dst and os.path.exists(dst):
                        back = unique_path(src) if os.path.exists(src) else src
                        os.makedirs(os.path.dirname(src), exist_ok=True)
                        shutil.move(dst, back)
                        count += 1
                elif op == "trash":
                    if dst and os.path.exists(dst):
                        back = unique_path(src) if os.path.exists(src) else src
                        os.makedirs(os.path.dirname(src), exist_ok=True)
                        shutil.move(dst, back)
                        info = r.get("info")
                        if info and os.path.isfile(info):
                            os.remove(info)
                        count += 1
            except (OSError, shutil.Error) as e:
                note = str(e)
                continue

        if count == 0 and items and not note:
            note = "这些文件已经不在原处了，撤不回来"

        # 一条都没撤回来就别删记录 —— 用户把文件挪回去之后还能再撤一次
        keep = recs if count == 0 else [r for r in recs if r.get("batch") != batch]
        try:
            os.makedirs(os.path.dirname(OP_FILE), exist_ok=True)
            with open(OP_FILE, "w", encoding="utf-8") as f:
                for r in keep:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        except OSError:
            pass
        self._invalidate()
        return label, count, note

    # -- 工具 ---------------------------------------------------------------
    def _invalidate(self):
        if self.org is not None:
            self.org._index_cache = None


def undo_latest(org, ops, log_file):
    """撤销最近一次动作 —— 整理和批量操作共用一个入口。

    两套日志各记各的（整理是"桌面→抽屉"单向搬运，批量操作是任意方向的
    用户意图），所以靠文件修改时间判断谁更近。返回 (撤回条数, 提示语)。
    """
    op_t = os.path.getmtime(OP_FILE) if os.path.isfile(OP_FILE) else 0
    mv_t = os.path.getmtime(log_file) if log_file and os.path.isfile(log_file) else 0

    if op_t and op_t >= mv_t:
        label, n, note = ops.undo_last()
        if n:
            return n, "已撤销%s %d 项" % (label, n)
        if note:
            return 0, note

    back = org.undo()
    if back:
        return len(back), "已放回桌面 %d 项" % len(back)
    info = org.last_batch_info()
    if info:
        return 0, "上次整理的 %d 项已经不在原处了，撤不回来" % info[1]
    return 0, ""


if __name__ == "__main__":
    o = BulkOps()
    print("归档根:", o.root)
    for name, path, depth in o.target_dirs()[:6]:
        print("  %s%s" % ("  " * depth, name))
