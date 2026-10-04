# -*- coding: utf-8 -*-
"""
从已保存的抓屏图里量「HUD 数字墨迹」的真实位置与字号。

为什么要单独做：实机抓屏发现固定框（top=260 高 80）装不下数字。
本脚本离线量出真实边界，用来判断**框该多大**，以及**是走墨迹自适应还是改框**。
"""
# [P3 整理] 原路径：mvp/measure_ink_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", default="samples/M_grab_full.png")
    ap.add_argument("--scale", type=float, default=None,
                    help="若给的是缩放图，填原图宽/图宽 的倍数（默认按 2880/图宽 自动）")
    args = ap.parse_args()

    im = Image.open(args.png).convert("RGB")
    W, H = im.size
    k = args.scale or (2880.0 / W)
    print("图尺寸 %dx%d，换算倍数 %.4f（→ 原图 %dx%d）" % (W, H, k, int(W * k), int(H * k)))

    a = np.asarray(im).astype(np.int16)
    # 只搜右上角：原图 x>2200 且 y 在 150~600 之间 → 换算到本图坐标
    x0, x1 = int(2200 / k), min(W, int(2880 / k))
    y0, y1 = int(150 / k), min(H, int(600 / k))
    sub = a[y0:y1, x0:x1]
    r, g, b = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]

    # 淡黄：R、G 高，B 明显低
    for tag, mask in (
        ("严格(淡黄)", (r > 200) & (g > 185) & ((r - b) > 40)),
        ("宽松", (r > 180) & (g > 170) & ((r - b) > 25)),
    ):
        n = int(mask.sum())
        print("\n[%s] 命中像素 %d" % (tag, n))
        if n < 20:
            continue
        ys = np.where(mask.any(axis=1))[0]
        xs = np.where(mask.any(axis=0))[0]
        ay0, ay1 = int((y0 + ys[0]) * k), int((y0 + ys[-1]) * k)
        ax0, ax1 = int((x0 + xs[0]) * k), int((x0 + xs[-1]) * k)
        print("  墨迹 y（原图坐标）: %d ~ %d   高 %d" % (ay0, ay1, ay1 - ay0 + 1))
        print("  墨迹 x（原图坐标）: %d ~ %d   宽 %d" % (ax0, ax1, ax1 - ax0 + 1))
        # 逐行计数，看是不是"数字"（应该有几段高的行）
        rows = mask.sum(axis=1)
        nz = np.where(rows > 0)[0]
        if len(nz):
            prof = [(int((y0 + y) * k), int(rows[y])) for y in nz[::max(1, len(nz) // 14)]]
            print("  行分布:", prof)
        break

    # 对照：模型预测的框
    try:
        from mvp.reader import hud_region_for
        reg, bar, geom = hud_region_for((1800, 2880))
        print("\n模型预测框: %s  bar_rows=%s  src=%s" % (reg, bar, geom.get("src")))
    except Exception as e:
        print("(读 hud_region_for 失败: %r)" % (e,))


if __name__ == "__main__":
    main()
