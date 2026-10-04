# -*- coding: utf-8 -*-
"""
E 线：抽样核对"待复核"帧里到底有没有我方的卡（判断"漏检率"）。
用法：python axis_unknown_E.py [--n 24]
"""
# [P3 整理] 原路径：axis_unknown_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import csv
import glob
import os

import cv2
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
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--out", default="samples/E_unknown.png")
    args = ap.parse_args()
    rows = [r for r in csv.DictReader(open("out/axis_actors_E.csv", encoding="utf-8-sig"))
            if not r["unit"].strip()]
    rows.sort(key=lambda r: float(r["t"]))
    # 均匀抽样
    step = max(1, len(rows) // args.n)
    picks = rows[::step][:args.n]
    print("待复核共 %d 帧，均匀抽 %d 帧做人工核对：" % (len(rows), len(picks)))
    panels = []
    for r in picks:
        t = float(r["t"])
        img = Image.open(FRAME % t).convert("RGB").crop((62, 60, 320, 210))
        im = img.resize((im_w := img.width * 2, img.height * 2), Image.LANCZOS)
        cv = Image.new("RGB", (im.width, im.height + 48), (0, 0, 0))
        cv.paste(im, (0, 48))
        d = ImageDraw.Draw(cv)
        d.text((4, 3), "t=%s 待复核" % T.fmt_t(t), font=font(18), fill=(255, 255, 255))
        d.text((4, 25), "分数%.2f 标记%s" % (float(r["score"]), r["marker"]),
               font=font(17), fill=(210, 210, 210))
        panels.append(cv)
    cols = 4
    rn = (len(panels) + cols - 1) // cols
    pw, ph = panels[0].size
    sheet = Image.new("RGB", (cols * pw + (cols + 1) * 6, rn * ph + (rn + 1) * 6), (25, 25, 25))
    for i, pn in enumerate(panels):
        r_, c_ = divmod(i, cols)
        sheet.paste(pn, (6 + c_ * (pw + 6), 6 + r_ * (ph + 6)))
    sheet.save(args.out)
    print("已写出 %s %s" % (args.out, sheet.size))


if __name__ == "__main__":
    main()
