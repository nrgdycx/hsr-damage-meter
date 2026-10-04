# -*- coding: utf-8 -*-
"""
诊断字形残缺：把整个 HUD 数字区域的掩膜 + 列分割结果打印出来。

目的：看清 t=226 / t=275 的数字列，找出字形为什么只有 23px 宽（正常 30px）。
可能是：被相邻字形粘住后切开、被 BAR_ROWS 挖空切断、或数字仍在动画中出现。
"""
# [P3 整理] 原路径：diag_mask_M.py（已移入 tools/，功能见 tools/README.md）
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
import read_hud  # noqa: E402
from digit_truth import HOLDOUT  # noqa: E402

CX0, CX1, CY0, CY1 = read_hud.CX0, read_hud.CX1, read_hud.CY0, read_hud.CY1
BAR = read_hud.BAR_ROWS

RAMP = " .:-=+*#%@"


def main():
    for t in (226.0, 275.0, 261.0):
        png = "frames/glyphcache/f%08.2f.png" % t
        if not os.path.exists(png):
            continue
        a = np.asarray(Image.open(png).convert("RGB")).astype(np.int16)
        c = a[CY0:CY1, CX0:CX1]
        R, G, B = c[:, :, 0], c[:, :, 1], c[:, :, 2]
        m = (R > 225) & (G > 225) & (B >= 185) & ((R - B) > 25)

        print("=" * 100)
        print("t=%.0f  期望 %s   掩膜区域 %dx%d（x%d-%d, y%d-%d）" %
              (t, HOLDOUT.get(int(t), "?"), m.shape[1], m.shape[0], CX0, CX1, CY0, CY1))

        # 掩膜整体（只打印有内容的列范围）
        cols = np.where(m.any(axis=0))[0]
        if len(cols):
            x0, x1 = max(0, cols[0] - 2), min(m.shape[1], cols[-1] + 3)
        else:
            x0, x1 = 0, m.shape[1]
        print("掩膜有内容的列: x%d-%d（相对裁剪框）；BAR_ROWS=(%d,%d) → 挖空相对行 %d-%d" %
              (cols[0] if len(cols) else -1, cols[-1] if len(cols) else -1,
               BAR[0], BAR[1], BAR[0] - CY0, BAR[1] - CY0))
        print("\n掩膜字符画（# = 掩膜；挖空带用 '~' 标出）:")
        for y in range(m.shape[0]):
            row = []
            for x in range(x0, x1):
                if BAR[0] - CY0 <= y <= BAR[1] - CY0:
                    row.append("~" if m[y, x] else " ")
                else:
                    row.append("#" if m[y, x] else " ")
            print("  y%-3d|%s|" % (y + CY0, "".join(row)))
        print()

        # 分割结果
        gs = read_hud.extract_glyphs(png)
        print("分割出 %d 段: %s" % (len(gs), [(w, h) for _, w, h in gs]))
        print()


if __name__ == "__main__":
    main()
