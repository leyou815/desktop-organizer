"""任务栏背景透明度测量（GDI 截屏 + 取样）。

用途：注入前后各跑一次，比较任务栏中段的平均亮度和纵向方差。
背景真的消失了 → 采样区变成壁纸，亮度和方差都会明显变化；
只是"变淡" → 变化幅度小；图标还在 → 文字锐利度（方差）不会归零。

必须 SetProcessDPIAware()：本机 2560x1440 @125%，不做 DPI 感知会拿到逻辑坐标，
取样框整体落到壁纸上，读数永远不变。
"""
import ctypes
import ctypes.wintypes as wt
import sys

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def grab(x, y, w, h):
    """返回 [(r,g,b), ...] 逐像素。"""
    screen = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, screen, x, y, SRCCOPY)
    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h          # 负值 = 自上而下
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), DIB_RGB_COLORS)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, screen)
    raw = buf.raw
    return [(raw[i + 2], raw[i + 1], raw[i]) for i in range(0, len(raw), 4)]


def stats(px):
    lum = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px]
    n = len(lum)
    mean = sum(lum) / n
    var = sum((v - mean) ** 2 for v in lum) / n
    return mean, var ** 0.5


def main():
    user32.SetProcessDPIAware()
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    # 任务栏：底部 48px（Win11 默认高），取样中间一段，避开开始按钮和托盘区
    bar_h = 48
    y = sh - bar_h
    print(f"屏幕 {sw}x{sh}  任务栏 y={y}..{sh}")

    regions = {
        "整条背景(中段 800px)": (sw // 2 - 400, y + 8, 800, 30),
        "图标区(dock 中间)": (sw // 2 - 200, y + 6, 400, 36),
    }
    for label, (x, yy, w, h) in regions.items():
        px = grab(x, yy, w, h)
        mean, sd = stats(px)
        print(f"  {label:22s} 平均亮度 {mean:6.2f}   标准差 {sd:6.2f}")


if __name__ == "__main__":
    main()
