# -*- coding: utf-8 -*-
"""
录屏2 HUD 数字待确认图 —— 用户读整串（比认孤立字形可靠得多）。

背景：录屏2（欢愉队）的 HUD 数字**字号比录屏1 大得多**，
A 线模型只在录屏1 的两种字号上训练过 → 录屏2 读数大量失败/缺高位。
所以需要用户直接读，作为录屏2 的真值。
"""
# [P3 整理] 原路径：sheet_hud2_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import os

from PIL import Image, ImageDraw, ImageFont

HUD_BOX = (2200, 225, 2870, 375)   # 覆盖住大字号（右对齐）


def font(sz):
    for p in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/arialbd.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--times", default="26,27,29,30,31,35,64,100,110,150,200,238,300")
    ap.add_argument("--out", default="samples/请看_录屏2_HUD待读.png")
    ap.add_argument("--per-row", type=int, default=2)
    args = ap.parse_args()

    tiles = []
    for v in args.times.split(","):
        t = float(v)
        p = "frames/hud2_M/t%08.2f.png" % t
        if not os.path.exists(p):
            continue
        im = Image.open(p).convert("RGB").crop(HUD_BOX)
        im = im.resize((int(im.size[0] * 1.6), int(im.size[1] * 1.6)), Image.LANCZOS)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, im.size[0] - 1, 30], fill=(0, 0, 0))
        d.text((5, 4), "t = %.0f 秒  请读这串数字" % t, font=font(20), fill=(255, 255, 0))
        d.rectangle([0, 0, im.size[0] - 1, im.size[1] - 1], outline=(130, 130, 130), width=2)
        tiles.append((t, im))

    if not tiles:
        print("没有可用帧")
        return
    per = args.per_row
    rows = (len(tiles) + per - 1) // per
    GAP = 8
    TW = max(t.size[0] for _, t in tiles)
    TH = max(t.size[1] for _, t in tiles)
    sheet = Image.new("RGB", (per * TW + (per + 1) * GAP, rows * TH + (rows + 1) * GAP + 28), (16, 16, 16))
    for i, (t, tl) in enumerate(tiles):
        r, c = divmod(i, per)
        sheet.paste(tl, (GAP + c * (TW + GAP), GAP + r * (TH + GAP)))
    d = ImageDraw.Draw(sheet)
    d.text((GAP, sheet.size[1] - 22),
           "请按帧号报数字（看不清就写\"看不清\"，不要猜）",
           font=font(17), fill=(255, 255, 255))
    if sheet.size[0] > 1600:
        k = 1600 / sheet.size[0]
        sheet = sheet.resize((1600, int(sheet.size[1] * k)), Image.LANCZOS)
    sheet.save(args.out)
    print("已写出 %s %s   帧: %s" % (args.out, sheet.size, [int(t) for t, _ in tiles]))


if __name__ == "__main__":
    main()
