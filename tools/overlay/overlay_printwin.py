# -*- coding: utf-8 -*-
"""
用 `PrintWindow` 抓悬浮窗自身的内容 —— 验证它到底画出了什么。

为什么不用 mss/BitBlt：**BitBlt 抓不到 layered 窗口**（会返回它背后的桌面内容），
所以之前用 mss 截的图里"只有聊天界面、没有悬浮窗"，不能用来判断悬浮窗渲染。

`PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT=2)` 能把窗口自身内容画到 HDC 里，
是抓 layered 窗口的正确做法。
"""
# [P3 整理] 原路径：mvp/overlay_printwin_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image


def capture_hwnd(hwnd):
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(ctypes.c_void_p(int(hwnd)), ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    hdc = user32.GetWindowDC(ctypes.c_void_p(int(hwnd)))
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    PW_RENDERFULLCONTENT = 0x00000002
    ok = user32.PrintWindow(ctypes.c_void_p(int(hwnd)), mem, PW_RENDERFULLCONTENT)

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    bmi = BMI()
    bmi.biSize = ctypes.sizeof(BMI)
    bmi.biWidth = w
    bmi.biHeight = -h                 # 负 = 自上而下
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)[:, :, :3][:, :, ::-1]
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(ctypes.c_void_p(int(hwnd)), hdc)
    return arr, ok


def main():
    from mvp.overlay import Overlay, FIXTURE

    ov = Overlay(x=40, y=40, alpha=0.97, debug=True, hotkey=None)
    ov.update(FIXTURE)
    for _ in range(40):
        ov.pump()
        time.sleep(0.03)
    ov.update(FIXTURE)
    ov.pump()

    print("Tk 窗口 %dx%d @ (%d,%d)  alpha=%s"
          % (ov.root.winfo_width(), ov.root.winfo_height(),
             ov.root.winfo_rootx(), ov.root.winfo_rooty(),
             ov.root.attributes("-alpha")))
    print("句柄:", [hex(h) for h in ov.hwnds])

    for i, h in enumerate(ov.hwnds):
        r = capture_hwnd(h)
        if r is None:
            print("  句柄%d 抓取失败" % i)
            continue
        arr, ok = r
        out = "samples/M_overlay_printwin_%d.png" % i
        Image.fromarray(arr).save(out)
        uniq = len(np.unique(arr.reshape(-1, 3), axis=0))
        print("  句柄%d  hwnd=0x%X  PrintWindow ok=%s  尺寸=%s  不同颜色数=%d  → %s"
              % (i, int(h), bool(ok), arr.shape[:2], uniq, out))
    ov.destroy()
    print("\n打开上面尺寸最大那张图，就能看到悬浮窗自己的内容。")


if __name__ == "__main__":
    import ctypes.wintypes  # noqa
    main()
