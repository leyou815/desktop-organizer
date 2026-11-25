#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面抽屉 —— 整理引擎

所有动作都是「移动」，从不删除。每次移动都写进日志，支持按批次撤销。
"""

import configparser
import json
import os
import shutil
import time
import uuid

import rules

import config as appcfg
import sysenv

CONFIG_DIR = appcfg.CONFIG_DIR
CONFIG_FILE = appcfg.CONFIG_FILE
LOG_FILE = appcfg.LOG_FILE


def load_config():
    return appcfg.load()


def save_config(cfg):
    appcfg.save(cfg)


def desktop_dir():
    """桌面目录：交给平台层（麒麟看 xdg-user-dir，Windows 看 User Shell Folders）。"""
    return sysenv.desktop_dir()


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


class Organizer(object):
    def __init__(self, desktop=None, cfg=None):
        self.desktop = desktop or desktop_dir()
        self.root = rules.shelf_root(self.desktop)
        self.cfg = cfg if cfg is not None else load_config()
        self._index_cache = None

    # -- 目录 ---------------------------------------------------------------
    def ensure_dirs(self):
        os.makedirs(self.root, exist_ok=True)
        if sysenv.IS_WINDOWS:
            # Windows 不认"点开头即隐藏"，得给目录打上隐藏属性
            sysenv.set_hidden(self.root, True)
        for cat in rules.CATEGORY_ORDER:
            os.makedirs(os.path.join(self.root, cat), exist_ok=True)
        for sub in ("Word", "Excel", "PPT", "PDF", "文本"):
            os.makedirs(os.path.join(self.root, rules.DOC, sub), exist_ok=True)

    # -- 扫描 ---------------------------------------------------------------
    def scan_pending(self, min_age=None):
        """桌面上（顶层、非隐藏、非启动器）还没归档的文件。

        Windows 上「用户桌面」和「公共桌面」合并显示成一个桌面，
        所以两个目录都要扫（见 sysenv.desktop_dirs），否则公共桌面上
        软件装的快捷方式会漏掉。归档目标始终是用户桌面下的同一个抽屉。
        """
        if min_age is None:
            try:
                min_age = int(self.cfg["general"].get("min_age", "3"))
            except ValueError:
                min_age = 3
        now = time.time()
        out = []
        roots = sysenv.desktop_dirs()
        self.root = rules.shelf_root(self.desktop)   # 归档根固定在用户桌面
        seen = set()
        for root in roots:
            try:
                names = sorted(os.listdir(root))
            except OSError:
                continue
            for name in names:
                path = os.path.join(root, name)
                key = os.path.normcase(os.path.abspath(path))
                if key in seen:
                    continue          # 两个桌面目录若有同名，只处理一次
                seen.add(key)
                skip, _ = rules.should_skip(path)
                if skip:
                    continue
                try:
                    if now - os.path.getmtime(path) < min_age:
                        continue      # 刚写过的先不动，下一轮再说
                except OSError:
                    continue
                cat, sub = rules.classify(path)
                out.append((path, cat, sub))
        return out

    def pending_count(self):
        return len(self.scan_pending())

    # -- 执行 ---------------------------------------------------------------
    def apply(self, dry_run=False, limit=None):
        """整理一轮，返回 [(src, dst), ...]。dry_run 只算不做。"""
        self.ensure_dirs()
        self._index_cache = None
        moves = self.scan_pending()
        if limit:
            moves = moves[:limit]
        done = []
        batch = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        for src, cat, sub in moves:
            target_dir = rules.category_dir(self.root, cat, sub)
            dst = unique_path(os.path.join(target_dir, os.path.basename(src)))
            if dry_run:
                done.append((src, dst))
                continue
            try:
                os.makedirs(target_dir, exist_ok=True)
                shutil.move(src, dst)
            except (OSError, shutil.Error):
                continue
            self._log(batch, src, dst)
            done.append((src, dst))
        return done

    def _log(self, batch, src, dst):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "batch": batch,
               "src": src, "dst": dst}
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def history(self):
        if not os.path.isfile(LOG_FILE):
            return []
        out = []
        try:
            with open(LOG_FILE, encoding="utf-8") as f:
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

    def undo(self, batch=None):
        """撤销最近一批（或指定批次），把文件挪回桌面。"""
        self._index_cache = None
        recs = self.history()
        if not recs:
            return []
        if batch is None:
            batch = recs[-1]["batch"]
        target = [r for r in recs if r.get("batch") == batch]
        moved = []
        for r in reversed(target):
            dst, src = r.get("dst"), r.get("src")
            if not dst or not src or not os.path.exists(dst):
                continue
            try:
                back = unique_path(src)
                shutil.move(dst, back)
            except (OSError, shutil.Error):
                continue
            moved.append((dst, back))
        if moved:
            # 撤销过的记录不再参与下一轮撤销
            keep = [r for r in recs if r.get("batch") != batch]
            try:
                with open(LOG_FILE, "w", encoding="utf-8") as f:
                    for r in keep:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
            except OSError:
                pass
        return moved

    # -- 汇总 ---------------------------------------------------------------
    def summary(self):
        """{分类: [(显示名, 绝对路径, 是否子目录条目), ...]}"""
        data = {}
        for cat in rules.CATEGORY_ORDER:
            items = []
            cdir = os.path.join(self.root, cat)
            if os.path.isdir(cdir):
                for entry in sorted(os.listdir(cdir)):
                    p = os.path.join(cdir, entry)
                    if os.path.isdir(p):
                        try:
                            n = len([x for x in os.listdir(p) if not x.startswith(".")])
                        except OSError:
                            n = 0
                        items.append((entry + "/", p, True, n))
                    else:
                        items.append((entry, p, False, 0))
            data[cat] = items
        return data

    def index_entries(self, limit=20000):
        """抽屉里全部可搜索条目（递归到子目录），返回 [(名字, 路径, 分类, 是否目录)]。

        summary() 只列每个分类的顶层条目（文档分类下只有 Word/Excel 几个子目录），
        搜索必须钻进去，否则搜不到 文档/Word/xxx.docx。
        """
        if self._index_cache is not None:
            return self._index_cache
        out = []
        for cat in rules.CATEGORY_ORDER:
            base = os.path.join(self.root, cat)
            if not os.path.isdir(base):
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for d in dirnames:
                    out.append((d, os.path.join(dirpath, d), cat, True))
                for f in sorted(filenames):
                    if f.startswith("."):
                        continue
                    out.append((f, os.path.join(dirpath, f), cat, False))
                    if len(out) >= limit:
                        self._index_cache = out
                        return out
        self._index_cache = out
        return out

    def total(self):
        s = self.summary()
        return sum(rules.count_items(cat, s[cat]) for cat in s)

    def last_batch_info(self):
        recs = self.history()
        if not recs:
            return None
        b = recs[-1]["batch"]
        n = len([r for r in recs if r.get("batch") == b])
        return b, n


if __name__ == "__main__":
    o = Organizer()
    print("桌面：", o.desktop)
    print("归档根：", o.root)
    pend = o.scan_pending()
    print("待整理：", len(pend))
    for src, cat, sub in pend[:15]:
        print("  %-45s -> %s%s" % (os.path.basename(src), cat, ("/" + sub) if sub else ""))
