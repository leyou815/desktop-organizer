"""抓「桌面整理」设置窗口（开发机验收用）。用法：python tools/t_win_shot.py 输出.png [等秒]

用 PrintWindow 直接渲染窗口内容，而不是抓屏幕区域：
前面几回实测，屏幕抓法会被叠在上面的别的窗口盖住（截图抓到的是别人）。
"""
import ctypes
import ctypes.wintypes as wt
import sys
import time

sys.path.insert(0, __file__.rsplit("\\", 2)[0] + "\\inject")
from shot import BI, BIH  # noqa: E402
from PIL import Image  # noqa: E402

u = ctypes.WinDLL("user32")
g = ctypes.WinDLL("gdi32")
k = ctypes.WinDLL("kernel32")
u.SetProcessDPIAware()

out = sys.argv[1] if len(sys.argv) > 1 else "panel.png"
wait = float(sys.argv[2]) if len(sys.argv) > 2 else 1.5


def exe_of(hwnd):
    pid = wt.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = k.OpenProcess(0x1000, False, pid.value)
    if not h:
        return ""
    buf = ctypes.create_unicode_buffer(260)
    n = wt.DWORD(260)
    k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
    k.CloseHandle(h)
    return buf.value


def find():
    hwnds = []
    EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(h, _l):
        n = u.GetWindowTextLengthW(h)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, buf, n + 1)
            if buf.value == "桌面整理" and "python" in exe_of(h).lower():
                r = wt.RECT()
                u.GetWindowRect(h, ctypes.byref(r))
                hwnds.append((h, buf.value, r))
        return True

    u.EnumWindows(EnumProc(cb), 0)
    return hwnds


def grab_window(hwnd):
    r = wt.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    w, hh = r.right - r.left, r.bottom - r.top
    hdc = u.GetWindowDC(hwnd)
    mem = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, hh)
    old = g.SelectObject(mem, bmp)
    # PW_RENDERFULLCONTENT(2)：DirectComposition/Qt 的内容也能拿到
    ok = u.PrintWindow(hwnd, mem, 2)
    g.SelectObject(mem, old)
    bi = BI()
    bi.bmiHeader.biSize = ctypes.sizeof(BIH)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -hh
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    buf = ctypes.create_string_buffer(w * hh * 4)
    g.GetDIBits(mem, bmp, 0, hh, buf, ctypes.byref(bi), 0)
    g.DeleteObject(bmp)
    g.DeleteDC(mem)
    u.ReleaseDC(hwnd, hdc)
    if not ok:
        return None
    return Image.frombuffer("RGB", (w, hh), buf.raw, "raw", "BGRX", 0, 1)


time.sleep(wait)
cands = [c for c in find() if (c[2].right - c[2].left) > 300]
if not cands:
    print("没找到主窗口")
    raise SystemExit(1)
h, title, _r = cands[0]
im = grab_window(h)
if im is None:
    print("PrintWindow 失败")
    raise SystemExit(1)
print("窗口", title, im.size)
im.save(out)
print("已存", out)
