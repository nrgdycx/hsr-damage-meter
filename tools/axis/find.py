# -*- coding: utf-8 -*-
"""
E 线：找与某个锚点帧「同款顶端卡」的所有帧（用于补稀缺类模板，如德谬歌只有 1 帧）。
用法：python axis_find_E.py --anchor 307 --top 24 [--montage samples/E_find_307.png]
"""
# [P3 整理] 原路径：axis_find_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import glob
import json
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import axis_actor as T

FRAME = "frames/glyphcache/f%08.2f.png"


def font(sz):
    for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(f, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchor", type=float, required=True)
    ap.add_argument("--top", type=int, default=24)
    ap.add_argument("--montage", default="")
    ap.add_argument("--scale", type=float, default=1.4)
    args = ap.parse_args()

    a = T.feats(T.top_art(T.load_frame(args.anchor)))
    rows = []
    for p in sorted(glob.glob("frames/glyphcache/*.png")):
        try:
            t = float(os.path.basename(p)[1:-4])
        except ValueError:
            continue
        img = cv2.imread(p, cv2.IMREAD_COLOR)
        if img is None:
            continue
        f = T.feats(T.top_art(img))
        s = T.pair_score(a, f)
        rows.append((s, t))
    rows.sort(reverse=True)
    print("锚点 t=%.0f 的前 %d 个相似帧：" % (args.anchor, args.top))
    for s, t in rows[:args.top]:
        mk, area, hue = T.marker_feat(T.load_frame(t))
        print("   t=%-6.0f 相似度%.2f  标记%s" % (t, s, mk))
    if args.montage:
        panels = []
        for s, t in rows[:args.top]:
            img = cv2.imread(FRAME % t, cv2.IMREAD_COLOR)
            sub = cv2.cvtColor(img[66:196, 70:300], cv2.COLOR_BGR2RGB)
            w = int(sub.shape[1] * args.scale)
            h = int(sub.shape[0] * args.scale)
            im = Image.fromarray(cv2.resize(sub, (w, h), interpolation=cv2.INTER_LANCZOS4))
            cv = Image.new("RGB", (im.width, im.height + 24), (0, 0, 0))
            cv.paste(im, (0, 24))
            ImageDraw.Draw(cv).text((4, 3), "t=%.0f  %.2f" % (t, s), font=font(17), fill=(255, 255, 255))
            panels.append(cv)
        cols = 3
        rn = (len(panels) + cols - 1) // cols
        pw = max(p.width for p in panels) + 8
        ph = max(p.height for p in panels) + 8
        sheet = Image.new("RGB", (cols * pw + 8, rn * ph + 8), (25, 25, 25))
        for i, pn in enumerate(panels):
            r_, c_ = divmod(i, cols)
            sheet.paste(pn, (8 + c_ * pw, 8 + r_ * ph))
        sheet.save(args.montage)
        print("已写出 %s %s" % (args.montage, sheet.size))


if __name__ == "__main__":
    main()
