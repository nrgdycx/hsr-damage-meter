# -*- coding: utf-8 -*-
"""【线2】把 HUD 数字区放大出图（带刻度），用来肉眼核对"模型看到的是不是屏幕上的那个数"。

用法：
  python hud2_view_L2.py --times 26,31 --zoom 3                # 整段数字区
  python hud2_view_L2.py --times 26 --x 2440,2700 --zoom 4     # 只看某一段（绝对 x）
"""
# [P3 整理] 原路径：hud2_view_L2.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)

import hud_read_team2 as H      # noqa: E402

FULL_DIR = "frames/hud2_M"
CROP_DIR = "frames/axis2_L2"


def font(sz):
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except OSError:
                pass
    return ImageFont.load_default()


def get_region(t):
    """优先用抽帧缓存里已裁好的小块，没有就用整帧裁。"""
    p = os.path.join(CROP_DIR, "t%08.2f_hud.png" % t)
    if os.path.exists(p):
        img = np.asarray(Image.open(p).convert("RGB"))
        return img, H.HUD_REGION[1], H.HUD_REGION[0]      # (x0, y0)
    p = os.path.join(FULL_DIR, "t%08.2f.png" % t)
    if not os.path.exists(p):
        return None, None, None
    a = np.asarray(Image.open(p).convert("RGB"))
    y0, x0, y1, x1 = H.HUD_REGION
    return a[y0:min(y1, a.shape[0]), x0:min(x1, a.shape[1])], x0, y0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--times", default="26,29,30,31,35")
    ap.add_argument("--zoom", type=float, default=3.0)
    ap.add_argument("--x", default="", help="绝对 x 范围，如 2440,2700")
    ap.add_argument("--out", default="samples/L2_hud_zoom.png")
    args = ap.parse_args()
    times = [float(x) for x in args.times.split(",") if x.strip()]
    xr = [int(v) for v in args.x.split(",")] if args.x else None

    rows = []
    for t in times:
        region, x0, y0 = get_region(t)
        if region is None:
            print("t=%s 缺帧" % t)
            continue
        if xr:
            a, b = max(0, xr[0] - x0), min(region.shape[1], xr[1] - x0)
            region = region[:, a:b]
        z = args.zoom
        img = Image.fromarray(region).resize((int(region.shape[1] * z), int(region.shape[0] * z)),
                                             Image.LANCZOS)
        head = 30
        canvas = Image.new("RGB", (img.width, img.height + head), (16, 16, 16))
        canvas.paste(img, (0, head))
        d = ImageDraw.Draw(canvas)
        d.text((4, 4), "t=%s  帧内 x 起点=%d（绝对坐标，刻度每 50px 一条）"
               % (H.__dict__ and t, (xr[0] if xr else x0)), font=font(15), fill=(255, 235, 120))
        step = 50
        start = ((xr[0] if xr else x0) // step + 1) * step
        for ax in range(start, (xr[1] if xr else x0 + region.shape[1]), step):
            xx = int((ax - (xr[0] if xr else x0)) * z)
            d.line([(xx, head), (xx, head + img.height)], fill=(120, 120, 120))
            d.text((xx + 1, head + 1), str(ax), font=font(12), fill=(200, 200, 200))
        rows.append(canvas)
    if not rows:
        return 1
    W = max(r.width for r in rows)
    Hh = sum(r.height for r in rows) + 6 * len(rows)
    out = Image.new("RGB", (W, Hh), (0, 0, 0))
    y = 0
    for r in rows:
        out.paste(r, (0, y))
        y += r.height + 6
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    out.save(args.out)
    print("已写出 %s（%dx%d）" % (args.out, out.width, out.height))
    return 0


if __name__ == "__main__":
    sys.exit(main())
