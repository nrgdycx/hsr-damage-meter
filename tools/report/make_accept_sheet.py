# -*- coding: utf-8 -*-
"""
出「验收图」—— 给用户辨认：这一刻是谁在攻击 + 总伤害是多少。

背景：用户的主要目的是研究【欢愉队出伤占比】，所以重点放在**阿哈时刻**。
数据源：录屏2 `records/屏幕录制 2026-09-30 192031.mp4`（欢愉队，2870x1800）。

每格显示：
  * 行动轴顶端卡（x60-320, y40-200）—— 看框里头像是谁 / 是不是面具框
  * HUD 总伤害数字（x2350-2870, y250-350）—— 这一刻屏幕上显示的数值
  * 时间戳 + 我在 CSV 里的判定（供你对照，认不出就写"看不清"）

⚠️ 按项目约定：给用户看的图 **不超过屏幕尺寸**、**不用颜色编码传信息**、标签用文字。
"""
# [P3 整理] 原路径：make_accept_sheet_M.py
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from ffmpeg_path import require_ffmpeg as _req_ff
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import csv
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

VIDEO2 = "records/屏幕录制 2026-09-30 192031.mp4"
FFMPEG = _req_ff()   # 见 ffmpeg_path.py（可用 HSR_FFMPEG 指定）
TMP = "frames/accept_M"

# 两个裁剪区（按录屏2 的 2870x1800 标定；行动轴与录屏1 同坐标）
AXIS_BOX = (60, 40, 320, 205)      # 行动轴顶端卡
# HUD 数字【右对齐】，右缘约 x2868 → 往左留足 12 位（每字约 34px=408px），再留余量
HUD_BOX = (2300, 240, 2868, 356)


def font(sz):
    for p in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/arialbd.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def grab(t, out):
    if os.path.exists(out):
        return True
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run([FFMPEG, "-ss", "%.3f" % t, "-i", VIDEO2, "-frames:v", "1", "-y", out],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.exists(out)


def load_cache():
    """读 E 线在录屏2 上的判定，供对照。"""
    p = "out/axis_actors_E_video2.csv"
    if not os.path.exists(p):
        return {}
    out = {}
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        try:
            out[round(float(r["t"]), 1)] = r
        except Exception:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--times", default="20,21,22,24,26,28,30,32,64,100,110,150,200,238,300")
    ap.add_argument("--out", default="samples/请看_欢愉队验收图.png")
    ap.add_argument("--per-row", type=int, default=3)
    args = ap.parse_args()

    times = [float(v) for v in args.times.split(",")]
    cache = load_cache()
    tiles = []
    for t in times:
        png = os.path.join(TMP, "t%08.2f.png" % t)
        if not grab(t, png):
            print("抽帧失败 t=%.1f" % t)
            continue
        im = Image.open(png).convert("RGB")
        ax = im.crop(AXIS_BOX)
        hud = im.crop(HUD_BOX)
        # 行动轴放大 2 倍，HUD 放大 2 倍
        ax = ax.resize((ax.size[0] * 2, ax.size[1] * 2), Image.LANCZOS)
        hud = hud.resize((int(hud.size[0] * 1.2), int(hud.size[1] * 1.2)), Image.LANCZOS)
        W = ax.size[0] + hud.size[0] + 20
        H = max(ax.size[1], hud.size[1]) + 46
        tile = Image.new("RGB", (W, H), (18, 18, 18))
        d = ImageDraw.Draw(tile)
        r = cache.get(t)
        judge = "?"
        if r:
            judge = "%s/%s/%s" % (r.get("unit") or "待复核", r.get("owner") or "-",
                                  r.get("card_type") or "-")
        d.rectangle([0, 0, W - 1, 42], fill=(0, 0, 0))
        d.text((5, 2), "t=%.1f 秒" % t, font=font(20), fill=(255, 255, 0))
        d.text((5, 22), "我的判定: %s" % judge, font=font(15), fill=(0, 255, 0))
        tile.paste(ax, (6, 46))
        tile.paste(hud, (ax.size[0] + 14, 46))
        d.rectangle([0, 0, W - 1, H - 1], outline=(140, 140, 140), width=2)
        tiles.append(tile)

    if not tiles:
        print("没有可用帧")
        return
    per = args.per_row
    rows = (len(tiles) + per - 1) // per
    GAP = 8
    TW = max(t.size[0] for t in tiles)
    TH = max(t.size[1] for t in tiles)
    sheet = Image.new("RGB", (per * TW + (per + 1) * GAP, rows * TH + (rows + 1) * GAP + 30), (16, 16, 16))
    for i, tl in enumerate(tiles):
        r_, c_ = divmod(i, per)
        sheet.paste(tl, (GAP + c_ * (TW + GAP), GAP + r_ * (TH + GAP)))
    d = ImageDraw.Draw(sheet)
    d.text((GAP, sheet.size[1] - 24),
           "每格 = 左:行动轴顶端卡  右:总伤害数字。请按帧号告诉我：框里是谁 / 数字是多少",
           font=font(16), fill=(255, 255, 255))
    # 控制尺寸 <= 1600 宽
    if sheet.size[0] > 1600:
        k = 1600 / sheet.size[0]
        sheet = sheet.resize((1600, int(sheet.size[1] * k)), Image.LANCZOS)
    sheet.save(args.out)
    print("已写出 %s %s  帧: %s" % (args.out, sheet.size, [int(t) for t in times]))


if __name__ == "__main__":
    main()
