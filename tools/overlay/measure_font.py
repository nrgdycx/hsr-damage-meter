# -*- coding: utf-8 -*-
"""
精确量实机 HUD 数字的「字号」与边界 —— 判断是哪一档字号。

线7 实测过两种字号：常规 61px、大 93px（≈1.5 倍）。框是按常规档算的，
所以如果实机是"大"档，框就会切掉数字。

做法：从抓屏图里按行统计"淡黄墨迹"密度，用密度骤增/骤减定位数字的上下边界，
排除上方「总伤害」标签的干扰。
"""
# [P3 整理] 原路径：mvp/measure_font_M.py（已移入 tools/，功能见 tools/README.md）
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
    args = ap.parse_args()

    im = Image.open(args.png).convert("RGB")
    W, H = im.size
    k = 2880.0 / W
    a = np.asarray(im).astype(np.int16)

    # 原图坐标 → 本图坐标
    def X(v):
        return int(v / k)

    sub = a[X(2300):X(2880), X(200):X(420)]
    # 注意：numpy 切片是 [y, x]，上面写反了，这里重来
    sub = a[X(200):X(420), X(2300):X(2880)]
    r, g, b = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
    yellow = (r > 190) & (g > 175) & ((r - b) > 25)

    rows = yellow.sum(axis=1)
    nz = np.where(rows > 0)[0]
    if not len(nz):
        print("未找到黄色墨迹")
        return

    print("逐行黄色像素数（原图 y）：")
    prev = None
    for y in nz:
        ay = int((X(200) + y) * k)
        n = int(rows[y])
        bar = "#" * min(70, n // 3)
        print("  y=%-5d %-6d %s" % (ay, n, bar))

    # 找"密度骤增"的位置 = 数字上边界（标签是稀疏的一行，数字是稠密块）
    dense = np.where(rows > max(10, rows.max() * 0.25))[0]
    if len(dense):
        top = int((X(200) + dense[0]) * k)
        bot = int((X(200) + dense[-1]) * k)
        print("\n密度>25%%峰值的行：y %d ~ %d   高 %d px" % (top, bot, bot - top + 1))

    # 列方向：在"数字所在行带"里量宽度
    if len(dense):
        band = yellow[dense[0]:dense[-1] + 1]
        cols = band.sum(axis=0)
        cnz = np.where(cols > 0)[0]
        if len(cnz):
            x0 = int((X(2300) + cnz[0]) * k)
            x1 = int((X(2300) + cnz[-1]) * k)
            print("数字 x 范围（原图）：%d ~ %d   宽 %d px" % (x0, x1, x1 - x0 + 1))

    print("\n参考（线7 实测的两档）:")
    print("  常规档：字高 61px  → 框 y 260~340")
    print("  大  档：字高 93px  → 框 y 257~380（线7 给的是 (257,2074,380,2876)）")
    print("  录屏参考数字：y ≈ 272~330（高约 58）")


if __name__ == "__main__":
    main()
