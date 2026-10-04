# -*- coding: utf-8 -*-
"""
留出集评测 —— 用【不参与训练】的帧检验读取器真实准确率。

为什么单独做这件事：拿训练过的帧自夸没有意义（必然接近 100%）。
只有"从没见过的帧"上的表现，才是"换一局新战斗还能不能读对"的真实答案。

留出帧（用户读图确认，未加入 LABELED）：
    226: 49065     261: 721193    275: 904004    284: 111860    311: 379852
"""

import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from read_hud import (load_model, extract_glyphs, classify, CY0, CY1, CX0, CX1)  # noqa: E402
from collect_glyphs import frame  # noqa: E402

HOLDOUT = {226: "49065", 261: "721193", 275: "904004", 284: "111860", 311: "379852"}


def main():
    model = load_model()
    print("留出集（不参与训练）评测：\n")
    g_ok = g_tot = f_ok = 0
    for t, val in sorted(HOLDOUT.items()):
        png = frame(float(t))
        gs = extract_glyphs(png)
        res = classify(model, gs)
        read = "".join(str(d) if c >= 0.55 else "?" for d, c in res)
        # 分割是否切全
        seg_ok = len(gs) == len(val)
        # 逐位比较（右对齐）
        n = min(len(res), len(val))
        hits = sum(1 for i in range(1, n + 1) if res[-i][0] == int(val[-i]))
        g_ok += hits
        g_tot += len(val)
        f_ok += (read == val)
        print("   t=%-4s 期望 %-8s(%d位)" % (t, val, len(val)))
        print("        切出 %d 段 %s   读出 %-9s %s" % (
            len(gs), "✓" if seg_ok else "✗(分割不全)", read, "✓整串正确" if read == val else ""))
        print("        逐位: %s" % " ".join(
            "%s%s" % (val[-i], "✓" if i <= len(res) and res[-i][0] == int(val[-i]) else "✗")
            for i in range(1, len(val) + 1)))
    print("\n留出集逐字准确率: %d/%d = %.1f%%" % (g_ok, g_tot, g_ok / g_tot * 100 if g_tot else 0))
    print("留出集整串正确率:   %d/%d" % (f_ok, len(HOLDOUT)))


if __name__ == "__main__":
    main()
