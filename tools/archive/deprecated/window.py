# -*- coding: utf-8 -*-
"""
E 线：多帧投票演示（给 C 会话看怎么用）。

实时抓屏是 30fps，一次攻击的 HUD 停留 1~1.5s → 对这段时间内的所有帧做投票，
比单帧稳得多。这里用抽帧缓存（1s 间隔）做同样的演示。
用法：python axis_window_E.py [--half 1.0] [--events 109,134,152,...]
"""
# [P3 整理] 原路径：axis_window_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import glob
import os

import axis_actor as T


def cached(lo, hi):
    out = []
    for p in sorted(glob.glob("frames/glyphcache/*.png")):
        try:
            t = float(os.path.basename(p)[1:-4])
        except ValueError:
            continue
        if lo - 1e-6 <= t <= hi + 1e-6:
            out.append((t, p))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default="100,109,134,152,167,195,226,261,275,284,311")
    ap.add_argument("--half", type=float, default=0.5)
    args = ap.parse_args()
    bank = T.load_bank()
    print("事件时刻 ± %.1fs 窗口投票（用抽帧缓存，1s 间隔）" % args.half)
    for e in [float(x) for x in args.events.split(",")]:
        fr = cached(e - args.half, e + args.half)
        if not fr:
            continue
        r = T.read_window([p for _, p in fr], bank)
        detail = " ".join("t%s:%s" % (T.fmt_t(t), (d["unit"] or "待复核"))
                          for (t, _), d in zip(fr, r["detail"]))
        print("  事件 t=%-6.0f -> 归属 %-6s (票数 %d/%d)   分帧: %s" %
              (e, r["owner"] or "待复核", r["votes"], r["n"], detail))


if __name__ == "__main__":
    main()
