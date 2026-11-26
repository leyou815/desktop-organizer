#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 winmd 里读接口的方法槽位（临时诊断用，可删）。

为什么要它：WinRT 接口的 vtable 槽位 = IInspectable(0..5) + 接口自己按元数据顺序排列的
方法（从 6 起）。猜错一格就会调到别的方法上，把 explorer 直接干崩（已经付过一次学费）。
所以动 vtable 之前，先用元数据把「第几格是哪个方法」查清楚。

用法：
    python tools/winmd_dump.py Windows.UI.Xaml.IUIElement put_Opacity
"""

import glob
import struct
import sys

import pefile


class Md:
    def __init__(self, path):
        pe = pefile.PE(path, fast_load=True)
        cor = pe.OPTIONAL_HEADER.DATA_DIRECTORY[14]
        cor_off = pe.get_offset_from_rva(cor.VirtualAddress)
        md_rva = struct.unpack_from("<I", pe.__data__, cor_off + 8)[0]
        md_size = struct.unpack_from("<I", pe.__data__, cor_off + 12)[0]
        base = pe.get_offset_from_rva(md_rva)
        self.data = pe.__data__[base:base + md_size]
        self.strings = b""
        self.blob = b""
        self.tbl = b""
        self._read_streams()
        self._read_tables()

    # -- 流 -----------------------------------------------------------------
    def _read_streams(self):
        d = self.data
        ver_len = struct.unpack_from("<I", d, 12)[0]
        off = 16 + ver_len            # 跳过版本串（已 4 字节对齐）
        n = struct.unpack_from("<H", d, off + 2)[0]
        off += 4
        for _ in range(n):
            pos = struct.unpack_from("<I", d, off)[0]
            size = struct.unpack_from("<I", d, off + 4)[0]
            end = d.index(b"\0", off + 8)
            name = d[off + 8:end].decode()
            off += 8 + ((end - (off + 8)) // 4 + 1) * 4
            if name == "#Strings":
                self.strings = d[pos:pos + size]
            elif name == "#Blob":
                self.blob = d[pos:pos + size]
            elif name == "#~":
                self.tbl = d[pos:pos + size]

    def s(self, i):
        e = self.strings.index(b"\0", i)
        return self.strings[i:e].decode()

    # -- 表 -----------------------------------------------------------------
    def _read_tables(self):
        t = self.tbl
        heap = t[6]
        valid = struct.unpack_from("<Q", t, 8)[0]
        counts = {}
        pos = 24
        for i in range(64):
            if valid >> i & 1:
                counts[i] = struct.unpack_from("<I", t, pos)[0]
                pos += 4
        self.counts = counts
        self.str_idx = 4 if heap & 1 else 2
        self.guid_idx = 4 if heap & 2 else 2
        self.blob_idx = 4 if heap & 4 else 2

        def idx(tbl):
            return 2 if counts.get(tbl, 0) < 0x10000 else 4

        def coded(tables, bits):
            mx = max(counts.get(x, 0) for x in tables)
            return 2 if mx < (1 << (16 - bits)) else 4

        self.td_or_ref = coded([0x02, 0x01, 0x1B], 2)
        self.idx_field = idx(0x04)
        self.idx_method = idx(0x06)
        has_ca = coded([0x00, 0x01, 0x02, 0x04, 0x05, 0x06, 0x08, 0x09, 0x0A, 0x0B,
                        0x0C, 0x0D, 0x0E, 0x11, 0x14, 0x15, 0x17, 0x18, 0x19, 0x1A,
                        0x1C, 0x23], 5)
        ca_type = coded([0x06, 0x0A], 3)
        mrp = coded([0x02, 0x01, 0x1A, 0x06, 0x1B], 3)
        has_const = coded([0x04, 0x08, 0x17], 2)
        scope = coded([0x00, 0x1A, 0x23, 0x01], 2)

        sizes = {
            0x00: 2 + self.str_idx + self.guid_idx * 3,
            0x01: scope + self.str_idx * 2,
            0x02: 4 + self.str_idx * 2 + self.td_or_ref + self.idx_field + self.idx_method,
            0x03: self.idx_field,
            0x04: 2 + self.str_idx + self.blob_idx,
            0x05: self.idx_method,
            0x06: 4 + 2 + 2 + self.str_idx + self.blob_idx,
            0x07: idx(0x08),
            0x08: 2 + 2 + self.str_idx,
            0x09: idx(0x02) + self.td_or_ref,
            0x0A: mrp + self.str_idx + self.blob_idx,
            0x0B: 2 + has_const + self.blob_idx,
            0x0C: has_ca + ca_type + self.blob_idx,
        }
        self.rows = {}
        p = pos
        for tbl in range(0x0D):
            cnt = counts.get(tbl, 0)
            rs = sizes[tbl]
            self.rows[tbl] = (p, rs, cnt)
            p += rs * cnt

    def _rh(self, off):
        if self.str_idx == 2:
            return struct.unpack_from("<H", self.data, off)[0]
        return struct.unpack_from("<I", self.data, off)[0]

    def typedefs(self):
        p, rs, cnt = self.rows[0x02]
        out = []
        for i in range(cnt):
            o = p + rs * i
            name = self.s(self._rh(o + 4))
            ns_o = o + 4 + self.str_idx
            ns = self.s(self._rh(ns_o))
            ml_o = ns_o + self.str_idx + self.td_or_ref + self.idx_field
            ml = struct.unpack_from("<H", self.data, ml_o)[0] if self.idx_method == 2 \
                else struct.unpack_from("<I", self.data, ml_o)[0]
            out.append((i, ns, name, ml))
        return out

    def method_names(self, start, end):
        p, rs, cnt = self.rows[0x06]
        names = []
        for i in range(start - 1, min(end - 1, cnt)):
            o = p + rs * i
            names.append(self.s(struct.unpack_from("<H", self.data, o + 8)[0]
                                if self.str_idx == 2
                                else struct.unpack_from("<I", self.data, o + 8)[0]))
        return names

    def methods_of(self, ns, name):
        tds = [t for t in self.typedefs() if t[1] == ns and t[2] == name]
        if not tds:
            return None
        i, _ns, _n, ml = tds[0]
        nxt = next((t for t in self.typedefs() if t[0] == i + 1), None)
        end = nxt[3] if nxt else self.counts.get(0x06, 0) + 1
        return self.method_names(ml, end)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    full = sys.argv[1].split(".")
    ns, name = ".".join(full[:-1]), full[-1]
    heads = glob.glob(r"C:\Windows\System32\WinMetadata\*.winmd")
    target = None
    for h in heads:
        if h.endswith(ns.split(".")[0] + "." + ns.split(".")[1] + ".winmd"):
            target = h
    if target is None:
        print("找不到包含 %s 的 winmd" % ns)
        return
    md = Md(target)
    ms = md.methods_of(ns, name)
    if ms is None:
        print("找不到接口 %s.%s" % (ns, name))
        return
    print("%s.%s 共 %d 个方法（vtable 从 6 起）" % (ns, name, len(ms)))
    want = sys.argv[2] if len(sys.argv) > 2 else None
    for i, m in enumerate(ms):
        if want is None or want in m:
            print("  idx=%-3d slot=%-3d %s" % (i, i + 6, m))


if __name__ == "__main__":
    main()
