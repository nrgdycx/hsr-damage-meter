# -*- coding: utf-8 -*-
"""
[A 线工具] 原始像素 / 各种掩膜 对照图（多帧、多模式）。

用法: python view_A.py 102 303 [--mode glow,union,fill,core]
上半：原始 RGB；以下每张：对应掩膜模式（放大 NEAREST）
"""
# [P3 整理] 原路径：view_A.py（已移入 tools/，功能见 tools/README.md）
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

Y0, Y1 = 250, 350
X0, X1 = 2330, 2876
SCALE = 3


def render(t, modes):
    png = frame(float(t))
    a = np.asarray(Image.open(png).convert("RGB")).astype(np.int16)
    c = a[Y0:Y1, X0:X1]
    H, W = c.shape[:2]
    n = 1 + len(modes)
    sheet = Image.new("RGB", (W * SCALE, (H * SCALE + 8) * n), (0, 0, 0))
    sheet.paste(Image.fromarray(c.astype(np.uint8)).resize((W * SCALE, H * SCALE), Image.NEAREST), (0, 0))
    for k, md in enumerate(modes, 1):
        m = HG._masks(c, md)[1]        # 展示「取字形像素」用的掩膜（hybrid 下即核心∪辉光）
        img = Image.fromarray((m * 255).astype(np.uint8)).convert("RGB")
        sheet.paste(img.resize((W * SCALE, H * SCALE), Image.NEAREST), (0, k * (H * SCALE + 8)))
    out = "samples/diag_A/modes_t%03d.png" % int(t)
    sheet.save(out)
    print("写出", out, sheet.size, "模式顺序:", ["raw"] + modes)


if __name__ == "__main__":
    argv = sys.argv[1:]
    modes = ["glow", "union"]
    if "--mode" in argv:
        i = argv.index("--mode")
        modes = argv[i + 1].split(",")
        argv = argv[:i]
    os.makedirs("samples/diag_A", exist_ok=True)
    for t in (argv or ["102"]):
        render(t, modes)
