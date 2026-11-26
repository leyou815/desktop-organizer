#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面抽屉 —— 分类规则

设计原则：
  1. 宁可不归类，也不归错类。拿不准的一律进「其他」。
  2. 绝不碰两类东西：.desktop（桌面启动器，移走快捷方式就废了）、
     以及任何临时/锁文件——Office 的 `~$文档.docx`、WPS 的 `.~文档.docx`、
     以 . 开头的隐藏文件。这些是"程序还开着"的标记，搬走会让 Office 报错。
  3. 图标有专属位置：svg/ico/icns 直接归图标；
     带透明通道、正方形、边长 ≤256 的 png 也算图标（读 IHDR 判断，不依赖 Pillow）。
"""

import os
import struct

import sysenv

# 归档根目录（放在桌面目录下的隐藏文件夹里）
SHELF_DIRNAME = sysenv.shelf_dirname()

DOC = "文档"
FOLDER = "文件夹"
APP = "应用"
LINK = "快捷方式"
IMG = "图片"
ICON = "图标"
VIDEO = "视频"
AUDIO = "音频"
ARCHIVE = "压缩包"
PKG = "安装包"
CODE = "代码"
OTHER = "其他"

# 面板里的显示顺序
CATEGORY_ORDER = [DOC, FOLDER, APP, LINK, IMG, ICON, VIDEO, AUDIO,
                  ARCHIVE, PKG, CODE, OTHER]

# 每个分类的说明（面板里做副标题，也用来自检）
CATEGORY_DESC = {
    DOC: "Word / Excel / PPT / PDF / 文本",
    FOLDER: "桌面上的文件夹，整包搬进来",
    APP: "桌面图标背后的启动器，点一下就开",
    LINK: "指向别处的快捷方式，点一下跳过去",
    IMG: "照片、截图、位图素材",
    ICON: "svg / ico / icns，以及小尺寸带透明的 png",
    VIDEO: "视频文件",
    AUDIO: "录音、音频",
    ARCHIVE: "zip / rar / 7z 等",
    PKG: "deb / rpm / AppImage 等",
    CODE: "脚本、源码、配置文件",
    OTHER: "认不出类型的东西",
}

# 扩展名 -> (分类, 子目录)；子目录为空表示直接放在分类根下
EXT_MAP = {}

def _reg(cat, exts, sub=""):
    for e in exts:
        EXT_MAP[e] = (cat, sub)

_reg(DOC, [".doc", ".docx", ".wps", ".rtf", ".odt", ".dot", ".dotx", ".docm"], "Word")
_reg(DOC, [".xls", ".xlsx", ".xlsm", ".et", ".ett", ".csv", ".ods", ".numbers"], "Excel")
_reg(DOC, [".ppt", ".pptx", ".pps", ".ppsx", ".dps", ".odp", ".key"], "PPT")
_reg(DOC, [".pdf", ".ofd", ".xps"], "PDF")
_reg(DOC, [".txt", ".md", ".markdown", ".log", ".tex", ".epub", ".mobi", ".azw3",
           ".pages", ".rtfd", ".chm"], "文本")

_reg(IMG, [".jpg", ".jpeg", ".jpe", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff",
           ".heic", ".heif", ".avif", ".psd", ".xcf", ".raw", ".cr2", ".nef", ".arw",
           ".dng", ".jfif", ".jxl"])

_reg(ICON, [".svg", ".svgz", ".ico", ".icns", ".cur"])

# Windows 桌面图标：.lnk 快捷方式、.url 网页链接
_reg(APP, [".lnk", ".url", ".pif"])

_reg(VIDEO, [".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm", ".m4v",
             ".mpg", ".mpeg", ".ts", ".rmvb", ".3gp"])
_reg(AUDIO, [".mp3", ".wav", ".flac", ".aac", ".ogg", ".oga", ".m4a", ".wma",
             ".ape", ".opus", ".amr", ".mid", ".midi"])

_reg(ARCHIVE, [".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".zst",
               ".cab", ".iso", ".lz", ".lzma"])

_reg(PKG, [".deb", ".rpm", ".appimage", ".apk", ".exe", ".msi", ".run", ".bin",
           ".flatpakref", ".flatpak", ".snap", ".pkg", ".dmg"])

_reg(CODE, [".py", ".pyw", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".json", ".jsonc",
            ".sh", ".bash", ".zsh", ".bat", ".ps1", ".c", ".h", ".cpp", ".hpp", ".cc",
            ".java", ".kt", ".go", ".rs", ".rb", ".php", ".lua", ".pl", ".swift",
            ".html", ".htm", ".css", ".scss", ".less", ".sql", ".yml", ".yaml",
            ".toml", ".ini", ".conf", ".cfg", ".xml", ".vue", ".svelte", ".ipynb"])

# 系统占位 / 未完成下载，永远不动
SKIP_EXT = {".directory", ".trashinfo", ".part", ".crdownload", ".tmp"}
# 按文件名跳过（.ini 本身要按扩展名归到代码里，只有 desktop.ini 这类是系统文件）
SYS_PLACEHOLDERS = {"desktop.ini", "thumbs.db", ".ds_store"}
# Office 系列的属主锁文件前缀：Word/Excel/PPT 打开文件时生成 `~$文件名.docx`，
# 用不着点开头也藏不住，但它跟 `.~` 一样是"程序还开着"的标记。
# 搬走轻则 Office 提示"文件已被他人占用"，重则写入失败丢内容。
LOCK_PREFIXES = ("~$",)

# 图标类 png 的判定阈值
ICON_MAX_SIDE = 256


def shelf_root(desktop):
    return os.path.join(desktop, SHELF_DIRNAME)


def category_dir(root, cat, sub=""):
    return os.path.join(root, cat, sub) if sub else os.path.join(root, cat)


def rel_target(cat, sub=""):
    return (cat, sub) if sub else (cat,)


# --------------------------------------------------------------------------- #
# 文件判定
# --------------------------------------------------------------------------- #
def should_skip(path):
    """返回 (是否跳过, 原因)。"""
    name = os.path.basename(path)
    if name.startswith("."):
        # .~xxx.docx 是 Word/WPS 的锁文件，隐藏文件也不该被搬走
        return True, "隐藏/临时文件"
    if name.startswith(LOCK_PREFIXES):
        # ~$xxx.docx：Office 的属主锁文件，程序关掉才会消失
        return True, "Office 临时锁文件（文件正在被打开）"
    if sysenv.is_hidden(path):
        # Windows 上隐藏/系统属性的文件（desktop.ini 等）同样不动
        return True, "隐藏或系统文件"
    if os.path.islink(path):
        # 绝对目标的链接搬到哪都能用；相对目标的搬走就断，原地留着
        try:
            target = os.readlink(path)
        except OSError:
            return True, "读不出链接目标"
        if not os.path.isabs(target):
            return True, "相对路径符号链接（搬走会断）"
        return False, ""
    if os.path.isdir(path):
        if os.path.ismount(path):
            return True, "挂载点（搬不动，也不该搬）"
        return False, ""          # 普通文件夹：归到「文件夹」分类
    if not os.path.isfile(path):
        return True, "不是普通文件"
    if name.lower() in SYS_PLACEHOLDERS:
        return True, "系统占位文件"
    ext = os.path.splitext(name)[1].lower()
    if ext in SKIP_EXT:
        return True, "未完成下载/系统占位文件"
    return False, ""


def _png_has_trns(path, limit=262144):
    """调色板 PNG 的透明是靠 tRNS 块表达的，得在 IDAT 之前找一下。"""
    try:
        with open(path, "rb") as f:
            data = f.read(limit)
    except OSError:
        return False
    idat = data.find(b"IDAT")
    scope = data[:idat] if idat > 0 else data
    return b"tRNS" in scope


def png_looks_like_icon(path):
    """读 PNG 头：正方形 + 边长 ≤256 + 带透明通道 → 当作图标。

    透明通道有三种表达，缺一不可漏：
      color_type 4 = 灰度+alpha，6 = RGBA，3 = 调色板（靠 tRNS 块给透明）
    """
    try:
        with open(path, "rb") as f:
            head = f.read(33)
    except OSError:
        return False
    if len(head) < 33 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return False
    width, height = struct.unpack(">II", head[16:24])
    color_type = head[25]
    if color_type in (4, 6):
        has_alpha = True
    elif color_type == 3:
        has_alpha = _png_has_trns(path)
    else:
        has_alpha = False
    return has_alpha and width == height and 0 < width <= ICON_MAX_SIDE


def classify(path):
    """返回 (分类, 子目录)。认不出就给「其他」。"""
    if os.path.islink(path):
        return LINK, ""
    if os.path.isdir(path):
        return FOLDER, ""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".desktop":
        return APP, ""
    if ext == ".png" and png_looks_like_icon(path):
        return ICON, ""
    cat, sub = EXT_MAP.get(ext, (OTHER, ""))
    return cat, sub


def count_items(cat, items):
    """统计口径：文件夹/应用/快捷方式数「几个条目」，其他分类数文件个数。"""
    if cat in (FOLDER, APP, LINK):
        return len(items)
    return sum(i[3] if (len(i) > 3 and i[2]) else 1 for i in items)


def explain(name, path=None):
    """给 CLI / 面板用：解释一个文件会被归到哪。

    传了 path 才能对 png 做尺寸/透明判定，否则只按扩展名说。
    """
    ext = os.path.splitext(name)[1].lower()
    if name.lower() in SYS_PLACEHOLDERS:
        return "跳过（系统占位文件）"
    if ext in SKIP_EXT:
        return "跳过（未完成下载）"
    if name.startswith("."):
        return "跳过（隐藏/临时文件）"
    if name.startswith(LOCK_PREFIXES):
        return "跳过（Office 锁文件）"
    if path and os.path.islink(path):
        return LINK
    if path and os.path.isdir(path):
        return FOLDER
    if ext == ".desktop":
        return APP
    if path and ext == ".png" and png_looks_like_icon(path):
        return ICON
    cat, sub = EXT_MAP.get(ext, (OTHER, ""))
    return "%s/%s" % (cat, sub) if sub else cat


if __name__ == "__main__":
    import sys
    for n in sys.argv[1:]:
        print("%-40s -> %s" % (n, explain(n)))
