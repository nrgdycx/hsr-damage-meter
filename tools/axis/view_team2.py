# -*- coding: utf-8 -*-
"""
E 线：看第二个录屏（欢愉相关）的行动轴。用法：
  python axis_view2_E.py --times 5,45,90 --rect 55,50,320,1120 --scale 0.8 --per-row 5 --out samples/E2_x.png
对应 axis_view_E.py，只是帧目录换成 frames/glyphcache2_E。
"""
# [P3 整理] 原路径：axis_view2_E.py
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import os

from PIL import Image, ImageDraw, ImageFont

FRAME = "frames/glyphcache2_E/f%08.2f.png"


def font(sz):
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc",
              "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def panel(t, rect, scale, label_h=26, draw=None):
    x0, y0, x1, y1 = rect
    im = Image.open(FRAME % t).convert("RGB").crop(rect)
    im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    w, h = im.size
    d = ImageDraw.Draw(im)
    if draw:
        dx0, dy0, dx1, dy1 = draw
        d.rectangle([(dx0 - x0) * scale, (dy0 - y0) * scale,
                     (dx1 - x0) * scale, (dy1 - y0) * scale], outline=(255, 255, 255), width=1)
    canvas = Image.new("RGB", (w, h + label_h), (0, 0, 0))
    canvas.paste(im, (0, label_h))
    ImageDraw.Draw(canvas).text((4, 4), "t=%.2f" % t, font=font(16), fill=(255, 255, 255))
    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--times", required=True)
    ap.add_argument("--rect", default="55,50,320,1120")
    ap.add_argument("--scale", type=float, default=0.8)
    ap.add_argument("--per-row", type=int, default=5)
    ap.add_argument("--draw", default="")
    ap.add_argument("--out", default="samples/E2_view.png")
    args = ap.parse_args()
    times = [float(t) for t in args.times.split(",")]
    rect = tuple(int(v) for v in args.rect.split(","))
    draw = tuple(int(v) for v in args.draw.split(",")) if args.draw else None
    panels = [panel(t, rect, args.scale, draw=draw) for t in times]
    cols = max(1, min(args.per_row, len(panels)))
    rows = (len(panels) + cols - 1) // cols
    pw, ph = panels[0].size
    gap = 8
    sheet = Image.new("RGB", (cols * pw + (cols + 1) * gap, rows * ph + (rows + 1) * gap), (25, 25, 25))
    for i, pn in enumerate(panels):
        r, c = divmod(i, cols)
        sheet.paste(pn, (gap + c * (pw + gap), gap + r * (ph + gap)))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    sheet.save(args.out)
    print("已写出 %s %s" % (args.out, sheet.size))


if __name__ == "__main__":
    main()
