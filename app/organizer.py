#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面抽屉 —— 整理引擎

所有动作都是「移动」，从不删除。每次移动都写进日志，支持按批次撤销。
"""

import json
import os
import shutil
import sys
import time
import uuid

import rules

import atomicio
import config as appcfg
import sysenv

CONFIG_DIR = appcfg.CONFIG_DIR
CONFIG_FILE = appcfg.CONFIG_FILE
LOG_FILE = appcfg.LOG_FILE


def own_root():
    """程序自己所在的目录。

    源码运行时是项目根（app 的上一级），打包后是 exe 所在目录。
    从桌面直接跑源码的人，桌面上那个项目文件夹正好就是程序的家——
    搬进抽屉后快捷方式、自启命令、下次启动全会找不到，所以永不搬它。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config():
    return appcfg.load()


def save_config(cfg):
    appcfg.save(cfg)


def desktop_dir():
    """桌面目录：交给平台层（麒麟看 xdg-user-dir，Windows 看 User Shell Folders）。"""
    return sysenv.desktop_dir()


def unique_path(dst):
    """目标重名时生成「名字 (2).ext」，绝不覆盖。

    注意：这个函数只负责"算出名字"，它返回的路径随时可能被别人抢走。
    真正要落地请用 move_into()——那里是原子占位，不存在 TOCTOU 窗口。
    """
    if not os.path.exists(atomicio.win_long(dst)):
        return dst
    base, ext = os.path.splitext(dst)
    i = 2
    while True:
        cand = "%s (%d)%s" % (base, i, ext)
        # Windows 上归档路径容易顶到 MAX_PATH，存在性判断要走长路径形态
        if not os.path.exists(atomicio.win_long(cand)):
            return cand
        i += 1


def reserve_path(dst, is_dir=False):
    """原子地占住一个不重名的目标路径，返回真正占到的路径。

    文件用 O_CREAT|O_EXCL 建空占位，目录用 os.mkdir：两者都是
    "要么占到、要么 FileExistsError"，不会出现两个进程算出同一个名字后互相覆盖。
    """
    cand = dst
    for _ in range(1000):
        long_cand = atomicio.win_long(cand)
        try:
            if is_dir:
                os.mkdir(long_cand)
            else:
                fd = os.open(long_cand, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                os.close(fd)
            return cand
        except FileExistsError:
            cand = unique_path(cand)      # 被抢了就换名字再抢一次
    raise OSError("找不到可用的目标名字：%s" % dst)


def move_into(src, dst):
    """把 src 搬进 dst（dst 允许已被占用，会自动换名），绝不覆盖别人。

    做法：先原子占位，再把内容落到占位上；任一步失败都会清掉占位，
    绝不留下空壳（空壳会让用户以为文件已经归档，实际却掉了）。
    返回真正落地的路径，异常向上抛由调用方汇总。
    """
    is_dir = os.path.isdir(src)
    cand = reserve_path(dst, is_dir=is_dir)
    # 实际文件操作统一走长路径形态，>260 的归档路径才不会在 Windows 上直接失败
    long_src = atomicio.win_long(src)
    long_cand = atomicio.win_long(cand)
    try:
        if is_dir:
            os.rmdir(long_cand)                  # 目录没法"占位后覆盖"，先让位再搬
            shutil.move(long_src, long_cand)
        else:
            try:
                os.replace(long_src, long_cand)  # 同卷：原子覆盖自己占的空文件
            except OSError:
                shutil.copy2(long_src, long_cand)  # 跨卷：拷过去再删源
                os.remove(long_src)
        return cand
    except Exception:
        # 占位失败要清干净：留下空壳会让用户以为已经归档，实际文件却丢了
        try:
            if os.path.isdir(long_cand) and not os.path.islink(long_cand):
                os.rmdir(long_cand)
            elif os.path.isfile(long_cand):
                os.remove(long_cand)
        except OSError:
            pass
        raise


class Organizer(object):
    def __init__(self, desktop=None, cfg=None):
        self.desktop = desktop or desktop_dir()
        self.root = rules.shelf_root(self.desktop)
        self.cfg = cfg if cfg is not None else load_config()
        self._index_cache = None
        self.last_errors = []      # 上一轮 apply/undo 里失败的项：[(路径, 原因)]

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
        但公共桌面是系统级目录，默认不扫（设置里可显式打开，见
        sysenv.desktop_dirs）。归档目标始终是用户桌面下的同一个抽屉。
        """
        if min_age is None:
            try:
                min_age = int(self.cfg["general"].get("min_age", "3"))
            except ValueError:
                min_age = 3
        now = time.time()
        out = []
        # primary 传 self.desktop：测试和自定义桌面（ORGANIZER_DESKTOP / 构造参数）
        # 才不会在改多桌面扫描之后被悄悄忽略
        roots = sysenv.desktop_dirs(
            include_public=appcfg.flag(self.cfg, "public_desktop"),
            primary=self.desktop)
        self.root = rules.shelf_root(self.desktop)   # 归档根固定在用户桌面
        seen = set()
        own = os.path.normcase(os.path.abspath(own_root()))
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
                # 程序自己的目录（或它的上级）永不搬：从桌面跑源码时，
                # 那个项目文件夹搬走了，程序就"把自己搬丢了"
                if key == own or own.startswith(key + os.sep):
                    continue
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
        """整理一轮，返回 [(src, dst), ...]。dry_run 只算不做。

        搬失败的项不进返回值，但会逐条记进 self.last_errors，由上层汇总给用户看——
        绝不静默 continue 假装一切正常。
        """
        self.ensure_dirs()
        self._index_cache = None
        self.last_errors = []
        moves = self.scan_pending()
        if limit:
            moves = moves[:limit]
        done = []
        batch = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]

        # 搬出去只需要"能删掉源目录里的条目"，搬回来还需要"能写进源目录"。
        # 公共桌面这类 ACL 特殊的目录正好卡在后半段：先写个临时文件探一次，
        # 探不通的目录整批不搬，免得用户拿到"搬得进去、撤不回来"的结果。
        unwritable = {}
        if not dry_run:
            primary = os.path.normcase(os.path.abspath(self.desktop))
            for src, _cat, _sub in moves:
                d = os.path.dirname(src)
                if d in unwritable:
                    continue
                if os.path.normcase(os.path.abspath(d)) == primary:
                    continue          # 自己的桌面不探，省得平白多写一个临时文件
                unwritable[d] = not sysenv.dir_writable(d)

        for src, cat, sub in moves:
            target_dir = rules.category_dir(self.root, cat, sub)
            dst = unique_path(os.path.join(target_dir, os.path.basename(src)))
            if dry_run:
                done.append((src, dst))
                continue
            if unwritable.get(os.path.dirname(src)):
                self.last_errors.append(
                    (src, "所在目录不允许写入，搬出去就撤不回来，已跳过"))
                continue
            try:
                os.makedirs(target_dir, exist_ok=True)
                dst = move_into(src, dst)        # 原子占位 + 搬运，重名绝不覆盖
            except (OSError, shutil.Error) as e:
                self.last_errors.append((src, "%s" % e))
                continue
            if not self._log(batch, src, dst):
                self.last_errors.append((src, "已移动，但撤销日志写入失败"))
            done.append((src, dst))

        # 多数项搬不动时整批退回。停在"半搬"状态最难收拾：用户既不知道
        # 哪些已经进了抽屉，也记不住它们原来在桌面的什么位置。
        if (not dry_run and done and self.last_errors
                and len(self.last_errors) * 2 >= len(moves)):
            n_fail = len(self.last_errors)
            back, stuck = self.rollback_batch(batch, done)
            note = "本批 %d 项搬不动，已整批回滚（%d 项退回原处）" % (n_fail, back)
            if stuck:
                note += "，其中 %d 项退不回去" % len(stuck)
            # 结论放最前：上层只拿 last_errors[0] 拼提示，先说"已回滚"才有用
            self.last_errors = [("", note)] + stuck + self.last_errors
            return []

        return done

    def rollback_batch(self, batch, done):
        """把一批已搬动的项原路退回，并把这一批从撤销日志里抹掉。

        返回 (退回条数, [(路径, 原因), ...])。只要还有退不回去的，日志就留着——
        用户还能再撤一次，不会因为回滚失败把记录弄丢。
        """
        self._index_cache = None
        back = 0
        stuck = []
        for src, dst in reversed(done):
            try:
                if os.path.exists(atomicio.win_long(dst)):
                    move_into(dst, src)          # 原子占位：桌面同名不会被覆盖
                    back += 1
            except (OSError, shutil.Error) as e:
                stuck.append((dst, "%s" % e))
        if not stuck:
            recs = [r for r in self.history() if r.get("batch") != batch]
            lines = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs)
            appcfg.atomic_write_text(LOG_FILE, lines)
        return back, stuck

    def _log(self, batch, src, dst):
        """追加一条撤销记录，返回是否写成功（失败要让用户知道，否则撤销不了）。"""
        rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "ts_num": time.time(),
               "batch": batch, "src": src, "dst": dst}
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            return False
        # 日志只追加不删，用久了全量读会变慢；超阈值裁掉很老的批次
        try:
            atomicio.trim_jsonl(LOG_FILE)
        except OSError:
            pass
        return True

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
            # 用记录里的 ts_num 判序，而不是文件行顺序：日志被手工补写或
            # 多进程追加时不至于撤错批次。
            newest = max(recs, key=lambda r: float(r.get("ts_num") or 0))
            batch = newest.get("batch")
        target = [r for r in recs if r.get("batch") == batch]
        moved = []
        errors = []
        for r in reversed(target):
            dst, src = r.get("dst"), r.get("src")
            if not dst or not src:
                continue
            if not os.path.exists(atomicio.win_long(dst)):
                errors.append((dst, "归档位置已不存在，跳过"))
                continue
            try:
                back = move_into(dst, src)     # 原子占位：桌面同名不会被覆盖
            except (OSError, shutil.Error) as e:
                errors.append((dst, "%s" % e))
                continue
            moved.append((dst, back))
        self.last_errors = errors
        if moved:
            # 撤销过的记录不再参与下一轮撤销；原子重写，断电不会留下半截日志
            keep = [r for r in recs if r.get("batch") != batch]
            lines = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep)
            appcfg.atomic_write_text(LOG_FILE, lines)
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
        # 与 undo() 同一套判序规则：认 ts_num，不认文件行序
        b = max(recs, key=lambda r: float(r.get("ts_num") or 0)).get("batch")
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
