# -*- coding: utf-8 -*-
"""
[C 线] 逐帧扫描：对抽帧缓存里每一帧同时读「HUD 总伤害数值（A 线）」与「行动轴顶端行动者（E 线）」，
落地成一张宽表 out/frames_C.csv —— C 线事件引擎的唯一输入。

为什么要先落地成表：
  * 读一整帧 PNG 要 ~400ms（解码 2876x1798），这一层是 C 线里最慢的；
  * 事件切分/归属规则会反复调参，不能每次都重跑识别；
  * 表是可复现的中间产物，对账时能直接指认"这一帧读到什么"。

用法：
  python scan_C.py                     # 默认 frames/glyphcache，t=100~340
  python scan_C.py --dir frames/xxx --range 0,382 --out out/frames_C2.csv
"""
# [P3 整理] 原路径：scan_C.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import csv
import glob
import os
import sys
import time

import numpy as np
import torch
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hud_glyphs  # noqa: E402
import hud_profiles as HP  # noqa: E402
import read_hud  # noqa: E402
import axis_actor as T  # noqa: E402

COLS = ["t", "hud_text", "hud_n", "hud_minconf", "hud_nbad", "hud_profile",
        "unit", "owner", "score", "margin", "marker", "inserted", "card_type",
        "actor_ok"]


def scans(frame_dir="frames/glyphcache", lo=100.0, hi=340.0, out="out/frames_C.csv"):
    paths = []
    for p in sorted(glob.glob(os.path.join(frame_dir, "*.png"))):
        try:
            t = float(os.path.basename(p)[1:-4])
        except ValueError:
            continue
        if lo <= t <= hi:
            paths.append((t, p))
    if not paths:
        print("目录 %s 里没有 t∈[%s,%s] 的帧" % (frame_dir, lo, hi))
        return 1

    model = read_hud.load_model()          # 常规字体（本录屏全队都是常规字体）
    bank = T.load_bank()
    rows = []
    t0 = time.time()
    for i, (t, p) in enumerate(paths):
        # ── A 线：HUD 数值 ──
        a = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
        text, conf, detail = read_hud.read_array(model, a, profile="default")
        nbad = sum(1 for r in detail if r["digit"] is None or r["conf"] < 0.55)
        # ── E 线：行动轴顶端 ──
        import cv2
        bgr = cv2.cvtColor(a.astype(np.uint8), cv2.COLOR_RGB2BGR)
        r = T.read_actor(bgr, bank)
        rows.append([t, text or "", len(detail), round(float(conf), 3), nbad, "default",
                     r["unit"] or "", r["owner"] or "", round(float(r["score"]), 3),
                     round(float(r["margin"]), 3), r["marker"] or "",
                     "" if r["inserted"] is None else int(r["inserted"]),
                     r["card_type"] or "", int(bool(r["unit"]))])
        if (i + 1) % 25 == 0 or i + 1 == len(paths):
            el = time.time() - t0
            print("  %3d/%d 帧  %.1fs  平均 %.0f ms/帧（预计剩余 %.0fs）" %
                  (i + 1, len(paths), el, el * 1000 / (i + 1),
                   el / (i + 1) * (len(paths) - i - 1)), flush=True)

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        w.writerows(rows)
    named = sum(1 for r in rows if r[6])
    print("\n已写出 %s（%d 帧）" % (out, len(rows)))
    print("有读数的帧 %d/%d，行动者已确认 %d/%d" %
          (sum(1 for r in rows if r[1]), len(rows), named, len(rows)))
    print("读数分布：")
    for r in rows:
        print("   t=%-7s HUD=%-10s(n=%d,bad=%d,minc=%.2f)  顶端=%-6s 归属=%-6s 卡型=%-7s 分数%.2f/%.2f" %
              (T.fmt_t(r[0]), r[1] or "(空)", r[2], r[4], r[3], r[6] or "-", r[7] or "-",
               r[12] or "-", r[8], r[9]))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="frames/glyphcache")
    ap.add_argument("--range", default="100,340")
    ap.add_argument("--out", default="out/frames_C.csv")
    args = ap.parse_args()
    lo, hi = [float(x) for x in args.range.split(",")]
    return scans(args.dir, lo, hi, args.out)


if __name__ == "__main__":
    sys.exit(main())
