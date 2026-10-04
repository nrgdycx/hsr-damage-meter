# -*- coding: utf-8 -*-
"""
E 线看图工具：从录屏抽帧缓存里裁一小块并放大/叠网格，输出单张 PNG 供人工查看。

用法示例：
  python axis_view_E.py --times 226,152,167,307 --rect 60,60,340,250 --scale 3 --out samples/E_topcards.png
  python axis_view_E.py --times 226 --rect 60,60,340,250 --scale 4 --grid 10 --out samples/E_top226_grid.png

设计约束（交接文档第 8 节）：
  * 图片不超过屏幕尺寸、不超出画布
  * 不用颜色编码传递信息（只用文字标签）
"""
# [P3 整理] 原路径：axis_view_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FRAME = "frames/glyphcache/f%08.2f.png"


def font(sz):
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc",
              "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def load(t):
    p = FRAME % t
    if not os.path.exists(p):
        raise FileNotFoundError(p)
    return Image.open(p).convert("RGB")


def panel(t, rect, scale, grid, label_h=26, draw=None):
    x0, y0, x1, y1 = rect
    im = load(t).crop(rect)
    w, h = im.size
    im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    w, h = im.size
    d = ImageDraw.Draw(im)
    if draw:
        dx0, dy0, dx1, dy1 = draw
        d.rectangle([(dx0 - x0) * scale, (dy0 - y0) * scale,
                     (dx1 - x0) * scale, (dy1 - y0) * scale], outline=(255, 255, 255), width=1)
    if grid:
        f = font(11)
        # 竖线
        for x in range(x0 - x0 % grid, x1 + 1, grid):
            px = (x - x0) * scale
            major = (x % (grid * 5) == 0)
            d.line([px, 0, px, h * scale], fill=(90, 90, 90) if not major else (150, 150, 150), width=1)
            if major:
                d.text((px + 2, 2), str(x), font=f, fill=(255, 255, 255))
        # 横线
        for y in range(y0 - y0 % grid, y1 + 1, grid):
            py = (y - y0) * scale
            major = (y % (grid * 5) == 0)
            d.line([0, py, w * scale, py], fill=(90, 90, 90) if not major else (150, 150, 150), width=1)
            if major:
                d.text((2, py + 2), str(y), font=f, fill=(255, 255, 255))
    # 顶部标题条
    canvas = Image.new("RGB", (w, h + label_h), (0, 0, 0))
    canvas.paste(im, (0, label_h))
    dd = ImageDraw.Draw(canvas)
    dd.text((4, 4), "t=%.2f  rect=%d,%d,%d,%d  x%d" % (t, x0, y0, x1, y1, scale),
            font=font(16), fill=(255, 255, 255))
    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--times", required=True)
    ap.add_argument("--rect", default="60,60,340,250")
    ap.add_argument("--scale", type=float, default=3.0)
    ap.add_argument("--grid", type=int, default=0)
    ap.add_argument("--per-row", type=int, default=3)
    ap.add_argument("--out", default="samples/E_view.png")
    ap.add_argument("--draw", default="", help="x0,y0,x1,y1 用白框标出（绝对坐标）")
    args = ap.parse_args()

    times = [float(t) for t in args.times.split(",") if t.strip()]
    rect = tuple(int(v) for v in args.rect.split(","))
    draw = tuple(int(v) for v in args.draw.split(",")) if args.draw else None
    panels = [panel(t, rect, args.scale, args.grid, draw=draw) for t in times]
    pw, ph = panels[0].size
    cols = max(1, min(args.per_row, len(panels)))
    rows = (len(panels) + cols - 1) // cols
    gap = 10
    sheet = Image.new("RGB", (cols * pw + (cols + 1) * gap, rows * ph + (rows + 1) * gap), (25, 25, 25))
    for i, pn in enumerate(panels):
        r, c = divmod(i, cols)
        sheet.paste(pn, (gap + c * (pw + gap), gap + r * (ph + gap)))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    sheet.save(args.out)
    print("已写出 %s  %s  面板=%s" % (args.out, sheet.size, (pw, ph)))
    print("ABS %s" % os.path.abspath(args.out))


if __name__ == "__main__":
    main()
