# -*- coding: utf-8 -*-
"""
把抓屏图里有疑问的三个区域放大出来，供用户核对（不靠文字描述）。

用途：避免"我描述错了、用户看不懂我在说什么"。
每块都标出**在原图（2880x1800）里的坐标**，便于精确讨论。
"""
# [P3 整理] 原路径：mvp/crop_regions_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import os

from PIL import Image, ImageDraw, ImageFont

# 原图坐标（2880x1800）
REGIONS = [
    ("A_行动轴整列", 40, 0, 340, 1300),
    ("B_HUD总伤害", 2200, 200, 2880, 420),
    ("C_队伍栏", 60, 1400, 1600, 1800),
    ("D_左上角标记", 0, 0, 300, 220),
]


def font(sz):
    for p in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/arialbd.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", default="samples/M_grab_full.png")
    ap.add_argument("--out", default="samples")
    args = ap.parse_args()

    im = Image.open(args.png).convert("RGB")
    W, H = im.size
    k = 2880.0 / W          # 本图 → 原图坐标的倍数

    for name, x0, y0, x1, y1 in REGIONS:
        bx0, by0 = int(x0 / k), int(y0 / k)
        bx1, by1 = min(W, int(x1 / k)), min(H, int(y1 / k))
        c = im.crop((bx0, by0, bx1, by1))
        # 放大到合适尺寸（宽度不超过 900）
        z = max(1.0, min(4.0, 900.0 / max(1, c.size[0])))
        c = c.resize((int(c.size[0] * z), int(c.size[1] * z)), Image.LANCZOS)
        d = ImageDraw.Draw(c)
        d.rectangle([0, 0, c.size[0] - 1, 30], fill=(0, 0, 0))
        d.text((5, 4), "%s   原图坐标 x%d-%d y%d-%d   放大 %.2fx"
               % (name, x0, x1, y0, y1, z), font=font(17), fill=(255, 255, 0))
        d.rectangle([0, 0, c.size[0] - 1, c.size[1] - 1], outline=(150, 150, 150), width=2)
        out = os.path.join(args.out, "M_chk_%s.png" % name.split("_")[0])
        c.save(out)
        print("写出 %s  %s" % (out, c.size))


if __name__ == "__main__":
    main()
