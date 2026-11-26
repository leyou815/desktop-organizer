#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桌面整理 —— 纯逻辑回归测试

不依赖 PyQt5、不碰真实桌面：所有用例都在临时目录里跑，撤销日志也被重定向。
改完 organizer / rules / bulkops / atomicio 之后跑一遍，比手工点界面可靠：

    python -m unittest discover -s tests -v
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

import atomicio          # noqa: E402
import bulkops           # noqa: E402
import config as appcfg  # noqa: E402
import fuzzy             # noqa: E402
import organizer         # noqa: E402
import rules             # noqa: E402
import sysenv            # noqa: E402


def make_cfg(**kw):
    """直接拿 DEFAULTS 造配置，避免读写用户真实的 config.ini。"""
    cfg = appcfg.configparser.ConfigParser()
    cfg["general"] = dict(appcfg.DEFAULTS)
    cfg["general"]["min_age"] = "0"
    cfg["general"]["public_desktop"] = "0"
    for k, v in kw.items():
        cfg["general"][k] = v
    return cfg


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="do-test-")
        self.desk = os.path.join(self.tmp, "desk")
        os.makedirs(self.desk)
        self._saved = (organizer.LOG_FILE, bulkops.OP_FILE)
        organizer.LOG_FILE = os.path.join(self.tmp, "moves.jsonl")
        bulkops.OP_FILE = os.path.join(self.tmp, "ops.jsonl")
        self.cfg = make_cfg()
        self.org = organizer.Organizer(desktop=self.desk, cfg=self.cfg)

    def tearDown(self):
        organizer.LOG_FILE, bulkops.OP_FILE = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def touch(self, name, text="x"):
        p = os.path.join(self.desk, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p


# --------------------------------------------------------------------------- #
# 分类规则
# --------------------------------------------------------------------------- #
class RulesTest(unittest.TestCase):
    def test_office_docs_go_into_subfolder(self):
        self.assertEqual(rules.classify("报告.docx"), ("文档", "Word"))
        self.assertEqual(rules.classify("预算.XLSX"), ("文档", "Excel"))
        self.assertEqual(rules.classify("讲稿.pptx"), ("文档", "PPT"))

    def test_shortcuts_are_apps(self):
        self.assertEqual(rules.classify("微信.lnk")[0], "应用")
        self.assertEqual(rules.classify("某网站.url")[0], "应用")
        self.assertEqual(rules.classify("WPS.desktop")[0], "应用")

    def test_unknown_goes_to_other(self):
        self.assertEqual(rules.classify("数据.xyz")[0], "其他")

    def test_office_lock_files_never_move(self):
        """~$ 和 .~ 都是 Office 的临时锁文件，搬走会让 Office 报错。"""
        for name in ("~$计划.docx", ".~计划.docx", ".DS_Store", "desktop.ini"):
            skip, why = rules.should_skip(name)
            self.assertTrue(skip, "%s 应该被跳过（%s）" % (name, why))

    def test_finished_download_moving(self):
        d = tempfile.mkdtemp(prefix="do-dl-")
        try:
            part = os.path.join(d, "电影.mp4.crdownload")
            done = os.path.join(d, "电影.mp4")
            for p in (part, done):
                open(p, "w").close()
            self.assertTrue(rules.should_skip(part)[0])
            self.assertFalse(rules.should_skip(done)[0])
        finally:
            shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 搬运：不覆盖、可撤销
# --------------------------------------------------------------------------- #
class MoveTest(Base):
    def test_move_into_never_overwrites(self):
        shelf = os.path.join(self.tmp, "shelf")
        os.makedirs(shelf)
        a = self.touch("同名.txt", "first")
        b = os.path.join(self.desk, "sub", "同名.txt")
        os.makedirs(os.path.dirname(b))
        with open(b, "w", encoding="utf-8") as f:
            f.write("second")

        dst1 = organizer.move_into(a, os.path.join(shelf, "同名.txt"))
        dst2 = organizer.move_into(b, os.path.join(shelf, "同名.txt"))
        self.assertEqual(os.path.basename(dst1), "同名.txt")
        self.assertEqual(os.path.basename(dst2), "同名 (2).txt")
        with open(dst1, encoding="utf-8") as f:
            self.assertEqual(f.read(), "first")
        with open(dst2, encoding="utf-8") as f:
            self.assertEqual(f.read(), "second")

    def test_apply_then_undo_round_trip(self):
        self.touch("报告.docx")
        self.touch("照片.png")
        self.touch("脚本.py")

        moved = self.org.apply()
        self.assertEqual(len(moved), 3)
        self.assertTrue(os.path.isfile(
            os.path.join(self.org.root, "文档", "Word", "报告.docx")))
        self.assertTrue(os.path.isfile(
            os.path.join(self.org.root, "代码", "脚本.py")))
        # 桌面上已经搬空
        self.assertEqual(len(self.org.scan_pending()), 0)

        back = self.org.undo()
        self.assertEqual(len(back), 3)
        self.assertTrue(os.path.isfile(os.path.join(self.desk, "报告.docx")))
        self.assertTrue(os.path.isfile(os.path.join(self.desk, "脚本.py")))
        # 撤销过的记录不再参与下一轮撤销
        self.assertIsNone(self.org.last_batch_info())

    def test_dry_run_moves_nothing(self):
        self.touch("报告.docx")
        planned = self.org.apply(dry_run=True)
        self.assertEqual(len(planned), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.desk, "报告.docx")))
        self.assertFalse(os.path.isdir(os.path.join(self.org.root, "文档", "Word", "报告.docx")))

    def test_scan_only_looks_at_given_desktop(self):
        """构造参数 desktop 必须真的生效（多桌面扫描重构后的回归点）。"""
        self.touch("只在这个桌面.txt")
        names = [os.path.basename(p) for p, _, _ in self.org.scan_pending()]
        self.assertEqual(names, ["只在这个桌面.txt"])

    def test_skip_program_own_directory(self):
        """从桌面跑源码时，项目文件夹不能被自己搬走。"""
        own = os.path.join(self.desk, "my-project")
        os.makedirs(own)
        self.touch("普通文件.txt")
        saved = organizer.own_root
        organizer.own_root = lambda: own
        try:
            names = [os.path.basename(p) for p, _, _ in self.org.scan_pending()]
        finally:
            organizer.own_root = saved
        self.assertEqual(names, ["普通文件.txt"])


# --------------------------------------------------------------------------- #
# 只读目录：宁可不搬，也不制造"搬得进去撤不回来"
# --------------------------------------------------------------------------- #
class UnwritableRootTest(Base):
    def test_unwritable_root_is_skipped(self):
        pub = os.path.join(self.tmp, "pub")
        os.makedirs(pub)
        f = os.path.join(pub, "微信.lnk")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("x")

        self.cfg["general"]["public_desktop"] = "1"
        saved_pub, saved_w = sysenv.public_desktop_dir, sysenv.dir_writable
        sysenv.public_desktop_dir = lambda: pub
        sysenv.dir_writable = lambda p: False
        try:
            moved = self.org.apply()
        finally:
            sysenv.public_desktop_dir, sysenv.dir_writable = saved_pub, saved_w

        self.assertEqual(moved, [])
        self.assertTrue(os.path.isfile(f), "写不回去的文件不该被搬走")
        self.assertTrue(any("不允许写入" in why for _p, why in self.org.last_errors),
                        self.org.last_errors)


# --------------------------------------------------------------------------- #
# 日志：原子写 + 裁剪
# --------------------------------------------------------------------------- #
class AtomicioTest(unittest.TestCase):
    def test_trim_jsonl_keeps_newest(self):
        d = tempfile.mkdtemp(prefix="do-log-")
        try:
            p = os.path.join(d, "log.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for i in range(6000):
                    f.write(json.dumps({"i": i}) + "\n")
            self.assertTrue(atomicio.trim_jsonl(p, keep=500, max_bytes=1024))
            with open(p, encoding="utf-8") as f:
                lines = f.read().splitlines()
            self.assertEqual(len(lines), 500)
            self.assertEqual(json.loads(lines[-1])["i"], 5999)

            # 没超过阈值就不动它
            self.assertFalse(atomicio.trim_jsonl(p, keep=500, max_bytes=10 ** 9))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_atomic_write_leaves_no_tmp(self):
        d = tempfile.mkdtemp(prefix="do-aw-")
        try:
            p = os.path.join(d, "config.ini")
            self.assertTrue(atomicio.atomic_write_text(p, "a=1\n"))
            self.assertEqual(os.listdir(d), ["config.ini"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 批量操作：改名 + 撤销
# --------------------------------------------------------------------------- #
class BulkTest(Base):
    def test_rename_then_undo(self):
        p = self.touch("2024-旧报告.docx")
        ops = bulkops.BulkOps(self.org, self.cfg)
        done, failed = ops.rename([p], "旧", "新")
        self.assertEqual(failed, [])
        self.assertTrue(os.path.isfile(os.path.join(self.desk, "2024-新报告.docx")))

        _label, n, _note = ops.undo_last()
        self.assertEqual(n, 1)
        self.assertTrue(os.path.isfile(p))

    def test_refuse_to_move_category_root(self):
        ops = bulkops.BulkOps(self.org, self.cfg)
        self.org.ensure_dirs()
        cat_dir = os.path.join(self.org.root, "文档")
        done, failed = ops.move([cat_dir], os.path.join(self.org.root, "图片"))
        self.assertEqual(done, [])
        self.assertTrue(failed and "归档结构" in failed[0][1])
        self.assertTrue(os.path.isdir(cat_dir))


# --------------------------------------------------------------------------- #
# 搜索
# --------------------------------------------------------------------------- #
class FuzzyTest(unittest.TestCase):
    def test_pinyin_initials(self):
        self.assertIsNotNone(fuzzy.match("wx", "微信.lnk"))
        self.assertIsNotNone(fuzzy.match("sls", "商洛市项目.docx"))

    def test_substring_beats_incidental_match(self):
        entries = [("微信.lnk", "微信"), ("_cgi-bin_webwx-bin_abc.lnk", "webwx")]
        hits = fuzzy.search("wx", entries)
        self.assertEqual(hits[0][0], "微信.lnk")


if __name__ == "__main__":
    unittest.main(verbosity=2)
