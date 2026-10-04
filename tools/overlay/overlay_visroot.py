# -*- coding: utf-8 -*-
"""
悬浮窗可见性根因测试 —— 逐层剥离，定位"为什么用户看不到"。

关键手法：**用 mss 截图并检查像素**。
  · 普通 Tk 窗口**不是** layered 窗口 → mss(BitBlt) 能抓到 → 若像素里有颜色，
    说明窗口**确实显示在屏幕上**（只是用户没看到 / 或被别的东西盖住）。
  · 若连普通 Tk 窗口都抓不到颜色，说明是抓屏/显示器层面的问题。

依次测 4 种配置，每种都：显示 → mss 抓窗口矩形 → 统计像素颜色。
"""
# [P3 整理] 原路径：mvp/overlay_visroot_M.py（已移入 tools/，功能见 tools/README.md）
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

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
ROOT = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
for _p in (ROOT, os.path.join(ROOT, "vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

BRIGHT = "#00e5ff"      # 亮青：不可能与桌面混淆
TEXT = "#101010"


def paint(w, bg):
    try:
        w.configure(bg=bg)
    except Exception:
        pass
    for c in w.winfo_children():
        paint(c, bg)


def sample(rect):
    """抓窗口矩形区域，返回 (平均亮度, 主要颜色, 与背景色接近的像素占比)。"""
    import mss
    x, y, w, h = rect
    w = max(1, min(w, 400))
    h = max(1, min(h, 300))
    with mss.mss() as sct:
        shot = np.asarray(sct.grab({"left": x, "top": y, "width": w, "height": h}))[:, :, :3]
    b, g, r = shot[:, :, 0].astype(int), shot[:, :, 1].astype(int), shot[:, :, 2].astype(int)
    # 亮青 = R低 G高 B高
    cyan = ((g > 180) & (b > 180) & (r < 120)).mean()
    mean = float(shot.mean())
    # 众数颜色
    flat = shot.reshape(-1, 3)
    vals, counts = np.unique(flat, axis=0, return_counts=True)
    top = vals[counts.argmax()]
    return mean, tuple(int(v) for v in top[::-1]), float(cyan)


def run_case(name, use_topmost, use_alpha, use_win32, seconds=5.0):
    import tkinter as tk
    r = tk.Tk()
    r.overrideredirect(True)
    r.geometry("+120+120")
    r.configure(bg=BRIGHT)
    lbl = tk.Label(r, text="悬浮窗可见性测试\nABC 123", bg=BRIGHT, fg=TEXT,
                   font=("Microsoft YaHei UI", 20, "bold"))
    lbl.pack(padx=20, pady=20)
    if use_topmost:
        r.attributes("-topmost", True)
    if use_alpha is not None:
        try:
            r.attributes("-alpha", use_alpha)
        except Exception as e:
            print("    (-alpha 设置失败 %r)" % (e,))
    r.update_idletasks()
    r.update()

    if use_win32:
        # 复刻 overlay 的扩展样式
        GWL_EXSTYLE = -20
        WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = \
            0x00080000, 0x00000020, 0x00000080, 0x08000000
        u = ctypes.windll.user32
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        hwnds = [r.winfo_id()]
        p = int(u.GetParent(r.winfo_id()) or 0)
        if p:
            hwnds.append(p)
        g = int(u.GetAncestor(r.winfo_id(), 2) or 0)
        if g and g not in hwnds:
            hwnds.append(g)
        for h in hwnds:
            cur = int(u.GetWindowLongPtrW(int(h), GWL_EXSTYLE)) & 0xFFFFFFFF
            u.SetWindowLongPtrW(int(h), GWL_EXSTYLE,
                                cur | WS_EX_LAYERED | WS_EX_TRANSPARENT
                                | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        r.update()

    # 显示并抓屏
    end = time.perf_counter() + seconds
    best = None
    while time.perf_counter() < end:
        r.update()
        time.sleep(0.05)
        if best is None or time.perf_counter() > end - seconds + 1.5:
            rect = (r.winfo_rootx(), r.winfo_rooty(), r.winfo_width(), r.winfo_height())
            best = (sample(rect), rect)
    (mean, top, cyan), rect = best
    print("  %-34s 矩形%s 平均亮度%6.1f 众数色%s 亮青占比%.3f  %s"
          % (name, rect, mean, top, cyan,
             "→ 屏幕上有颜色 ✓" if cyan > 0.15 else "→ 抓不到内容 ✗"))
    r.destroy()
    time.sleep(0.3)
    return cyan > 0.15


def main():
    print("每档显示 5 秒；用 mss 抓窗口矩形并统计像素")
    print()
    run_case("A 普通 Tk（topmost+alpha1.0）", True, 1.0, False)
    run_case("B + alpha=0.97", True, 0.97, False)
    run_case("C + alpha=0.85", True, 0.85, False)
    run_case("D + Win32 扩展样式(同 overlay)", True, 0.97, True)
    print()
    print("说明：A/B/C 是普通 Tk 窗口（mss 抓得到）；D 加上 layered+穿透（mss 可能抓不到）。")
    print("如果 A 都抓不到颜色 → 是抓屏/显示器层面的问题，不是窗口样式。")


if __name__ == "__main__":
    main()
