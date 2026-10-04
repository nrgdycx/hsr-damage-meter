# -*- coding: utf-8 -*-
"""
[本对话专用 · 只读] 量录屏2 的字号与字距，和录屏1（A 线训练口径）对比。

目的：把 Q1 的候选原因 (a)"大字号不在训练范围"量化成具体数字，
供线2 判断"能不能靠缩放救回来"还是"必须补帧重训"。

口径与 hud_glyphs._extract_core 一致（辉光层分割、挖空 BAR_ROWS、3px 并段），
但**不做链过滤、不做质量过滤**，这样能看到"被上游丢掉的那些段"长什么样。
用法：python -u diag_font_scale.py
"""
# [P3 整理] 原路径：diag_font_scale.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import os
import sys

import numpy as np
from PIL import Image

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)

import hud_glyphs as HG   # noqa: E402

TRUTH = {26: "140130", 29: "286055", 30: "279947", 31: "279947", 35: "100291",
         64: None, 100: "506286", 110: None, 150: None, 200: None,
         238: "2052321", 300: "123692", 340: "1371940"}

BOX = (240, 2100, 366, 2876)      # 放宽四周，避免"框切字"干扰量字
FRAME_DIR = "frames/hud2_M"


def segs(a, box, chain_px=10 ** 9):
    """返回 [(x0,x1,w,h,mass)]，绝对 x；不做质量过滤，链阈值默认无限大。"""
    y0, x0, y1, x1 = box
    c = np.asarray(a[y0:y1, x0:x1], dtype=np.int16)
    m_seg, m_glyph, _ = HG._masks(c, HG.MASK_MODE)
    ms = m_seg.copy()
    r0, r1 = max(0, HG.BAR_ROWS[0] - y0), min(ms.shape[0] - 1, HG.BAR_ROWS[1] - y0)
    if r0 <= r1 and r0 < ms.shape[0]:
        ms[r0:r1 + 1, :] = False
    col = ms.any(axis=0)
    runs, s = [], None
    for x in range(len(col)):
        if col[x] and s is None:
            s = x
        elif not col[x] and s is not None:
            runs.append([s, x - 1])
            s = None
    if s is not None:
        runs.append([s, len(col) - 1])
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] - 1 < 3:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    out = []
    for xa, xb in merged:
        m1 = m_glyph[:, xa:xb + 1]
        rows = np.where(m1.any(axis=1))[0]
        if len(rows) == 0:
            continue
        out.append((xa + x0, xb + x0, xb - xa + 1, int(rows[-1] - rows[0] + 1), int(m1.sum())))
    return out


def main():
    print("=" * 96)
    print("录屏2 字号/字距实测（框 %s，辉光分割，不做链/质量过滤）" % (BOX,))
    print("A 线训练口径参照：录屏1 常规字高约 60~79，窄'1'辉光高 29~37，字距 34~37，W_MAX=52")
    print("=" * 96)
    print("%-6s %-9s %-5s %s" % ("t", "真值", "段数", "各段（绝对x范围, 宽, 高, 质量）"))
    allh, allw, adv = [], [], []
    for t in sorted(TRUTH):
        p = os.path.join(FRAME_DIR, "t%08.2f.png" % t)
        if not os.path.exists(p):
            continue
        a = np.asarray(Image.open(p).convert("RGB"))
        ss = segs(a, BOX)
        if not ss:
            print("%-6s %-9s %-5d %s" % (t, TRUTH[t] or "(空)", 0, "无墨迹"))
            continue
        txt = " ".join("[%d-%d w%d h%d m%d]" % s for s in ss)
        print("%-6s %-9s %-5d %s" % (t, TRUTH[t] or "(空)", len(ss), txt))
        # 只统计"像字"的段（质量 >=150 且高 >=35），避免把装饰线算进字号
        big = [s for s in ss if s[4] >= 150 and s[3] >= 35]
        if big:
            allh += [s[3] for s in big]
            allw += [s[2] for s in big]
            xs = sorted(s[0] for s in big)
            if len(xs) >= 2:
                adv += [(xs[i + 1] - xs[i]) for i in range(len(xs) - 1)]

    def stat(name, v):
        if not v:
            print("%s: 无样本" % name)
            return
        v = np.asarray(v, dtype=float)
        print("%s: n=%d  min=%.0f  中位=%.0f  max=%.0f" %
              (name, len(v), v.min(), np.median(v), v.max()))

    print("\n" + "=" * 96)
    stat("录屏2 字形高度（像字的段）", allh)
    stat("录屏2 字形宽度（像字的段）", allw)
    stat("录屏2 相邻字形起点间距（字距）", adv)
    print("\n判读提示：")
    print("  · 若录屏2 字高明显 > 79（录屏1 上限），说明 (a) 大字号超训练范围成立，")
    print("    且要看能否靠**等比缩放**把 24x34 归一化补回来；")
    print("  · 若字距明显 > 20（链阈值），说明**主因是链过滤丢左侧位**（t=35 已证实链30 能救回）；")
    print("  · 若单段宽 > 52（W_MAX），该段会被当粘连大块丢弃 → 少位。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
