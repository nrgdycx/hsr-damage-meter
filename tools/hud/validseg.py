# -*- coding: utf-8 -*-
"""
[A 线] 分割校验 —— 不需要训练，就能客观比较掩膜/分割参数。

指标：对每个已确认帧，切出的字形数是否等于真值位数（容许"只缺最左边 1 位"，
      因为 HUD 右对齐，缺左 1 位仍可按右对齐贴上正确标签；缺 ≥2 位则弃用）。

用法: python validseg_A.py [mode1 mode2 ...]
"""
# [P3 整理] 原路径：validseg_A.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hud_glyphs as HG  # noqa
from collect_glyphs import frame  # noqa
from digit_truth import LABELED, HOLDOUT  # noqa

ALL = dict(LABELED)
ALL.update(HOLDOUT)
MODES = ["glow", "fill", "union", "union_s", "union_sf"]


def counts(t, mode):
    p = frame(float(t))
    if not p:
        return None
    a = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
    return [h for _, _, h in HG.extract(a, mode=mode)]


def main():
    modes = sys.argv[1:] or MODES
    summary = {}
    for mode in modes:
        exact = minus1 = bad = 0
        problems = []
        for t, val in sorted(ALL.items()):
            hs = counts(t, mode)
            if hs is None:
                problems.append("t=%s 无帧" % t)
                continue
            n, L = len(hs), len(val)
            if n == L:
                exact += 1
            elif n == L - 1:
                minus1 += 1
                problems.append("t=%-4s %-8s 缺左1位(%d/%d)" % (t, val, n, L))
            else:
                bad += 1
                problems.append("t=%-4s %-8s ✗ %d/%d" % (t, val, n, L))
        summary[mode] = (exact, minus1, bad)
        print("\n=== mode=%-9s 全对 %2d/%d  缺左1位 %d  不合格 %d ===" % (
            mode, exact, len(ALL), minus1, bad))
        for p in problems:
            print("    " + p)
    print("\n汇总（全对 / 缺左1位 / 不合格，共 %d 帧）:" % len(ALL))
    for m, (e, m1, b) in summary.items():
        print("   %-9s %2d / %d / %d   可用率 %.0f%%" % (
            m, e, m1, b, (e + m1) / len(ALL) * 100))


if __name__ == "__main__":
    main()
