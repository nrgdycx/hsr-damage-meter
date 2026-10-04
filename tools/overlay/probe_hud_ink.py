# -*- coding: utf-8 -*-
"""
实测 HUD 数字墨迹的真实边界 —— 用来判断框该多大。

背景：实机抓屏发现 HUD 框（top=260 高 80）只切到数字的上半部分，
说明实机数字比录屏参考更大/更低。本脚本扫描"淡黄墨迹"的 y/x 范围。
"""
# [P3 整理] 原路径：mvp/probe_hud_ink_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np


def main():
    from capture import Grabber, enable_dpi_awareness
    enable_dpi_awareness()
    g = Grabber()
    full = g.grab_full() if hasattr(g, "grab_full") else None
    if full is None:
        import mss
        with mss.mss() as sct:
            full = np.asarray(sct.grab(sct.monitors[1]))[:, :, :3][:, :, ::-1]
    print("整屏 (H,W):", np.shape(full)[:2])

    a = np.asarray(full).astype(np.int16)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]

    # 只搜右上角区域，避免其它 UI 干扰
    y0s, y1s, x0s, x1s = 150, 600, 2200, 2880
    sub = a[y0s:y1s, x0s:x1s]
    r, gg, b = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
    # HUD 数字：淡黄（R,G 高、B 也高）→ 用与背景（紫色）的差异来抓
    yellow = (r > 200) & (gg > 190) & ((r - b) > 30) & ((gg - b) > 10)
    print("右上角区域内黄色像素数:", int(yellow.sum()))

    if yellow.sum() > 20:
        ys = np.where(yellow.any(axis=1))[0]
        xs = np.where(yellow.any(axis=0))[0]
        print("墨迹 y 范围（绝对）: %d ~ %d   高 %d" % (y0s + ys[0], y0s + ys[-1], ys[-1] - ys[0] + 1))
        print("墨迹 x 范围（绝对）: %d ~ %d   宽 %d" % (x0s + xs[0], x0s + xs[-1], xs[-1] - xs[0] + 1))
        # 逐行统计，看有没有被"总伤害"文字干扰
        print("\n逐行黄色像素数（每 8 行）：")
        for i in range(0, len(ys), max(1, len(ys) // 20)):
            y = ys[i]
            n = int(yellow[y].sum())
            print("  y=%-5d %s%d" % (y0s + y, "#" * min(60, n // 2), n))
    else:
        print("未找到明显黄色墨迹；打印该区域的颜色统计以便判断阈值")
        print("  R 均值 %.0f  G %.0f  B %.0f" % (r.mean(), gg.mean(), b.mean()))
        print("  R-B 分位 50/90/99: %.0f / %.0f / %.0f" % tuple(
            np.percentile((r - b).ravel(), [50, 90, 99])))


if __name__ == "__main__":
    main()
