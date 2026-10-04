# -*- coding: utf-8 -*-
"""
E 线：把任意多张图拼成一张对照表（带文字标签），用于人工比对身份/部位。

用法：
  python sheet_E.py --out samples/E_x.png --per-row 4 --height 260 --labels "A,B,C" a.png b.png c.png
"""
# [P3 整理] 原路径：sheet_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import os

from PIL import Image, ImageDraw, ImageFont


def font(sz):
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc",
              "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="samples/E_sheet.png")
    ap.add_argument("--per-row", type=int, default=4)
    ap.add_argument("--height", type=int, default=260)
    ap.add_argument("--labels", default="")
    ap.add_argument("--crop", default="", help="x0,y0,x1,y1 对每张图套用同一裁剪")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("images", nargs="+")
    args = ap.parse_args()

    labels = args.labels.split(",") if args.labels else []
    crop = tuple(int(v) for v in args.crop.split(",")) if args.crop else None
    panels = []
    for i, p in enumerate(args.images):
        im = Image.open(p).convert("RGB")
        if crop:
            im = im.crop(crop)
        if args.scale != 1.0:
            im = im.resize((int(im.width * args.scale), int(im.height * args.scale)), Image.LANCZOS)
        r = args.height / im.height
        if r < 1:
            im = im.resize((max(1, int(im.width * r)), args.height), Image.LANCZOS)
        lab = labels[i] if i < len(labels) else os.path.basename(p)
        c = Image.new("RGB", (im.width, im.height + 24), (0, 0, 0))
        c.paste(im, (0, 24))
        ImageDraw.Draw(c).text((3, 4), lab, font=font(15), fill=(255, 255, 255))
        panels.append(c)

    pw = max(p.width for p in panels)
    ph = max(p.height for p in panels)
    cols = max(1, min(args.per_row, len(panels)))
    rows = (len(panels) + cols - 1) // cols
    gap = 8
    sheet = Image.new("RGB", (cols * pw + (cols + 1) * gap, rows * ph + (rows + 1) * gap), (25, 25, 25))
    for i, pn in enumerate(panels):
        r, c = divmod(i, cols)
        sheet.paste(pn, (gap + c * (pw + gap), gap + r * (ph + gap)))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    sheet.save(args.out)
    print("已写出 %s %s" % (args.out, sheet.size))
    print("ABS %s" % os.path.abspath(args.out))


if __name__ == "__main__":
    main()
