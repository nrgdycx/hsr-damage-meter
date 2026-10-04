# -*- coding: utf-8 -*-
"""
悬浮窗渲染根因实验 —— 5 种窗口实现逐个显示，请用户回答看到什么。

背景（用户的观察，非常关键）：
  · `PrintWindow` 抓到窗口**自己的内容** = 正常浅色卡片
  · 但用户**在屏幕上看** = 半透明黑
  ⇒ 不是 Tk 画错了，而是 **DWM 合成到屏幕时不对**。
    `PrintWindow` 读的是窗口绘制缓冲、绕过合成，所以看不出这个问题。

本实验逐个测，每种都用**巨大的纯亮黄字**，便于一眼判断：
  A 纯 Tk，完全不设任何窗口属性（连 topmost 都不设）
  B Tk + topmost
  C Tk + topmost + -alpha=1.0（显式设不透明）
  D Tk + topmost + 我们现有的 Win32 扩展样式（layered+穿透+noactivate）
  E 纯 Win32 原生窗口（ctypes 直接 CreateWindowEx + 填色，完全不经 Tk）

用法：python mvp/render_probe_M.py --seconds 7
"""
# [P3 整理] 原路径：mvp/render_probe_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import ctypes
import os
import sys
import time

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
ROOT = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
for _p in (ROOT, os.path.join(ROOT, "vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

YELLOW = "#ffe600"
BLACK = "#000000"


def tk_window(label, topmost=False, set_alpha=None, win32_style=False, seconds=7.0,
              x=300, y=250):
    import tkinter as tk
    r = tk.Tk()
    r.overrideredirect(True)
    r.geometry("+%d+%d" % (x, y))
    r.configure(bg=YELLOW)
    f = tk.Frame(r, bg=YELLOW)
    f.pack(fill="both", expand=True, padx=6, pady=6)
    tk.Label(f, text=label, bg=YELLOW, fg=BLACK,
             font=("Microsoft YaHei UI", 40, "bold")).pack(padx=30, pady=(40, 10))
    tk.Label(f, text="（如果这块是黄色，请告诉我是哪个字母）", bg=YELLOW, fg=BLACK,
             font=("Microsoft YaHei UI", 18)).pack(padx=30, pady=(0, 40))
    if topmost:
        r.attributes("-topmost", True)
    if set_alpha is not None:
        try:
            r.attributes("-alpha", set_alpha)
        except Exception:
            pass
    r.update()

    if win32_style:
        u = ctypes.windll.user32
        GWL_EXSTYLE = -20
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        bits = 0x00080000 | 0x00000020 | 0x00000080 | 0x08000000  # LAYERED|TRANSPARENT|TOOLWINDOW|NOACTIVATE
        hs = [r.winfo_id()]
        p = int(u.GetParent(r.winfo_id()) or 0)
        if p:
            hs.append(p)
        g = int(u.GetAncestor(r.winfo_id(), 2) or 0)
        if g and g not in hs:
            hs.append(g)
        for h in hs:
            cur = int(u.GetWindowLongPtrW(int(h), GWL_EXSTYLE)) & 0xFFFFFFFF
            u.SetWindowLongPtrW(int(h), GWL_EXSTYLE, cur | bits)
        r.update()

    print("  显示 %s …" % label, flush=True)
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        r.update()
        time.sleep(0.03)
    r.destroy()
    time.sleep(0.4)


def native_window(label, seconds=7.0, x=300, y=250):
    """纯 Win32 原生窗口（不经 Tk）：验证"是不是 Tk 的渲染问题"。"""
    u = ctypes.windll.user32
    g = ctypes.windll.gdi32
    W, H = 700, 260
    hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
    WS_POPUP, WS_VISIBLE = 0x80000000, 0x10000000
    hwnd = u.CreateWindowExW(0x00000008, "STATIC", label, WS_POPUP | WS_VISIBLE,
                             x, y, W, H, None, None, hinst, None)
    if not hwnd:
        print("  纯 Win32 窗口创建失败 (err=%d)" % ctypes.get_last_error())
        return
    print("  显示 %s (hwnd=0x%X) …" % (label, hwnd), flush=True)
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        hdc = u.GetDC(hwnd)
        brush = g.CreateSolidBrush(0x0000E6FF)   # BGR: 亮黄
        rect = ctypes.wintypes.RECT(0, 0, W, H)
        u.FillRect(hdc, ctypes.byref(rect), brush)
        g.DeleteObject(brush)
        g.SetBkMode(hdc, 1)
        g.SetTextColor(hdc, 0x00000000)
        g.TextOutW(hdc, 20, 90, "E 纯 Win32 原生窗口（非 Tk）")
        u.ReleaseDC(hwnd, hdc)
        u.UpdateWindow(hwnd)
        time.sleep(0.05)
    u.DestroyWindow(hwnd)
    time.sleep(0.4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=7.0)
    a = ap.parse_args()
    print("每个窗口显示 %.0f 秒，位置 (300,250)，纯亮黄底 + 黑字。" % a.seconds)
    print("请记住：哪几个能看到、分别是什么颜色/内容是黑的。")
    print()
    tk_window("A 纯 Tk（不设任何属性）", seconds=a.seconds)
    tk_window("B Tk + topmost", topmost=True, seconds=a.seconds)
    tk_window("C Tk + topmost + alpha=1.0", topmost=True, set_alpha=1.0, seconds=a.seconds)
    tk_window("D Tk + topmost + Win32扩展样式", topmost=True, set_alpha=1.0,
              win32_style=True, seconds=a.seconds)
    try:
        native_window("E", seconds=a.seconds)
    except Exception as e:
        print("  E 失败:", repr(e)[:100])
    print("\n实验结束。请告诉我 A/B/C/D/E 各自看到什么。")


if __name__ == "__main__":
    import ctypes.wintypes  # noqa
    main()
