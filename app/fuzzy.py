#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面整理 —— 模糊搜索

三条匹配路径，取分数最高的那条：
  1. 子串包含（最准）      "报告" → 工作报告.docx
  2. 字符子序列（fzf 式）  "gzbg" → gong-zuo-bao-gao? 中文不适用，主要给英文/路径用
  3. 拼音首字母子序列      "wx" → 微信      "sls" → 商洛市

为什么要自己写首字母表：系统没装 pypinyin / xpinyin，而中文文件名只支持打全字
搜索体验很差。这里用 GB2312 一级字库的 23 个声母区间做映射，30 行搞定，
零依赖，覆盖常用汉字。
"""

# GB2312 一级汉字按拼音排序，每段起始码对应一个声母
_INITIAL_BOUNDS = [
    (0xB0A1, "a"), (0xB0C5, "b"), (0xB2C1, "c"), (0xB4EE, "d"),
    (0xB6EA, "e"), (0xB7A2, "f"), (0xB8C1, "g"), (0xB9FE, "h"),
    (0xBBF7, "j"), (0xBFA6, "k"), (0xC0AC, "l"), (0xC2E8, "m"),
    (0xC4C3, "n"), (0xC5B6, "o"), (0xC5BE, "p"), (0xC6DA, "q"),
    (0xC8BB, "r"), (0xC8F6, "s"), (0xCBFA, "t"), (0xCDDA, "w"),
    (0xCEF4, "x"), (0xD1B8, "y"), (0xD4D1, "z"),
]


def py_initial(ch):
    """取一个汉字的拼音首字母；非汉字返回空串。"""
    if "\u4e00" <= ch <= "\u9fff":
        try:
            raw = ch.encode("gb2312")
        except UnicodeEncodeError:
            return ""            # 生僻字/二级字库，放弃
        if len(raw) != 2:
            return ""
        code = (raw[0] << 8) + raw[1]
        letter = ""
        for start, lc in _INITIAL_BOUNDS:
            if code >= start:
                letter = lc
            else:
                break
        return letter
    if ch.isascii() and ch.isalnum():
        return ch.lower()
    return ""


def initials_map(text):
    """[(首字母, 原字符下标)]，用来把"首字母命中"映射回可见字符做高亮。"""
    out = []
    for i, ch in enumerate(text):
        ini = py_initial(ch)
        if ini:
            out.append((ini, i))
    return out


def _subsequence(query, seq):
    """在 seq 里按顺序找 query 的每个字符，返回命中下标列表；找不到返回 None。"""
    idx, pos = [], 0
    for qc in query:
        found = -1
        while pos < len(seq):
            if seq[pos] == qc:
                found = pos
                pos += 1
                break
            pos += 1
        if found < 0:
            return None
        idx.append(found)
    return idx


def _word_start(text, i):
    """命中的字符是不是"词首"（前面是分隔符或开头）。"""
    if i == 0:
        return True
    prev = text[i - 1]
    return prev in " -_./\\()（）【】[]、，,。"


def match(query, name):
    """返回 (分数, 高亮下标集合) 或 None。分数越大越靠前。"""
    if not query:
        return None
    q = query.strip().lower()
    if not q:
        return None
    low = name.lower()

    best = None

    # 1) 子串
    pos = low.find(q)
    if pos >= 0:
        # 关键：长文件名里"碰巧包含"不该压过短名里的真实命中。
        # 例如 _cgi-bin_mmwebwx-bin_... 里的 wx 只是 webwx 中间的巧合。
        score = 700 - min(pos, 100) * 2 - max(0, len(name) - len(q)) * 2
        if pos == 0:
            score += 260                      # 开头命中
        elif not _word_start(name, pos):
            score -= 140                      # 夹在单词中间，降权
        best = (score, list(range(pos, pos + len(q))))

    # 2) 字符子序列
    idx = _subsequence(q, low)
    if idx:
        score = 460
        consec = sum(1 for a, b in zip(idx, idx[1:]) if b == a + 1)
        score += consec * 25
        score += sum(15 for i in idx if _word_start(name, i))
        score -= max(0, (idx[-1] - idx[0] + 1) - len(idx)) * 3
        if best is None or score > best[0]:
            best = (score, idx)

    # 3) 拼音首字母（只在查询是纯字母时试，避免中文名里混字母误伤）
    if q.isascii() and q.isalpha():
        imap = initials_map(name)
        if imap:
            seq = "".join(x[0] for x in imap)
            pi = _subsequence(q, seq)
            if pi:
                score = 520
                consec = sum(1 for a, b in zip(pi, pi[1:]) if b == a + 1)
                score += consec * 25
                if pi[0] == 0:
                    score += 60
                idxs = [imap[p][1] for p in pi]
                if best is None or score > best[0]:
                    best = (score, idxs)

    return best


def search(query, entries, limit=60, weight=None):
    """entries: [(name, payload)] → 按分数排序的 [(name, payload, indices)]。

    weight(payload) 用来扣分：越深层的文件越靠后（顶层条目优先）。
    """
    hits = []
    for name, payload in entries:
        r = match(query, name)
        if r:
            s = r[0] - (weight(payload) if weight else 0)
            hits.append((s, name, payload, r[1]))
    hits.sort(key=lambda x: (-x[0], len(x[1]), x[1]))
    return [(h[1], h[2], h[3]) for h in hits[:limit]]


if __name__ == "__main__":
    names = ["微信.desktop", "WPS 文字.desktop", "商洛市数智健康城市项目建议书.docx",
             "常用文件模板", "工作报告.docx", "CherryStudio.desktop", "参会回执",
             "关于数智健康城市建设工作落实情况的报告.doc", "wx.txt", "会议录像.mp4"]
    for q in ("wx", "wps", "sls", "bg", "报告", "hy", "doc", "cherry", "zzz"):
        r = search(q, [(n, n) for n in names])
        print("查询 %-8s → %s" % (q, [x[0] for x in r[:3]] or "无结果"))
