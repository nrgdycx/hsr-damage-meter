# -*- coding: utf-8 -*-
"""
出「核对图」：把实机采集落盘的整屏帧 + 当时的读数拼成一张图，**请用户读数确认**。

用途（P1 的验收第 3 条）：
    `mvp/live_mvp.py --dump-frames <dir> --dump-diag <csv>` 采集完，
    跑本脚本 → 一张 `samples/实机读数核对.png`（不超过屏幕尺寸、不用颜色编码、标签是文字）
    → 用户对着图逐格看"程序读出的数"与"画面上的数"是否一致。

为什么要人工核对：项目的铁律是"跑得起来 ≠ 结论对"。
计数（`--dump-diag` 的统计）只能说明"读到了几个数"，**不能说读数是对的**；
唯一真值来源是用户看屏幕读数。

用法：
    python tools/overlay/make_live_check_sheet.py --frames samples/p1_live_probe \
        --diag out/p1_live_diag.csv --out samples/实机读数核对.png --cols 3
"""
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import csv
import glob
import os
import re
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

MAX_W = 1500          # 输出图不超过屏幕尺寸（用户屏幕 2880×1800；这里留足余量）


def font(sz):
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc",
              "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def load_diag(path):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                t = float(r["t"])
            except (TypeError, ValueError):
                continue
            rows.append(r)
    rows.sort(key=lambda r: float(r["t"]))
    return rows


def nearest(rows, t):
    lo, hi = 0, len(rows) - 1
    best = None
    for r in rows:
        d = abs(float(r["t"]) - t)
        if best is None or d < best[0]:
            best = (d, r)
    return best[1] if best else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", required=True, help="--dump-frames 落盘的整屏帧目录")
    ap.add_argument("--diag", required=True, help="--dump-diag 落盘的表")
    ap.add_argument("--out", default="samples/实机读数核对.png")
    ap.add_argument("--cols", type=int, default=3)
    ap.add_argument("--max", type=int, default=24,
                    help="最多放几格（默认 24；0=全部）")
    ap.add_argument("--prefer-read", dest="prefer_read", action="store_true", default=True,
                    help="优先挑「读出非空」的帧（默认开）—— 真值核对只需要看这些格子")
    ap.add_argument("--no-prefer-read", dest="prefer_read", action="store_false")
    ap.add_argument("--scale", type=float, default=1.6, help="每个 HUD 裁图的放大倍数")
    ap.add_argument("--pad", type=int, default=26, help="裁图上下左右留白（像素）")
    args = ap.parse_args()

    rows = load_diag(args.diag)
    if not rows:
        print("诊断表是空的：%s" % args.diag)
        return 1
    files = sorted(glob.glob(os.path.join(args.frames, "*.jpg"))
                   + glob.glob(os.path.join(args.frames, "*.png")))
    if not files:
        print("取证帧目录里没有图：%s" % args.frames)
        return 1
    if args.max and len(files) > args.max:
        # 优先挑"程序读出了东西"的帧（那才是需要人工核对真值的格子），
        # 再按时间均匀补几张"空/失败"的作对照 —— 别把用户的时间浪费在一堆空格子上。
        if args.prefer_read:
            scored = []
            for p in files:
                m = re.search(r"(\d+\.\d+)", os.path.basename(p))
                if not m:
                    continue
                r = nearest(rows, float(m.group(1)))
                scored.append((bool((r or {}).get("hud_text", "").strip()), p))
            keep = [p for hit, p in scored if hit][:int(args.max)]
            if len(keep) < int(args.max):
                rest = [p for hit, p in scored if not hit]
                need = int(args.max) - len(keep)
                if rest:
                    idx = [int(round(i * (len(rest) - 1) / float(max(1, need - 1))))
                           for i in range(need)] if need > 1 else [0]
                    keep += [rest[i] for i in dict.fromkeys(idx)]
            files = sorted(set(keep))
            print("取证帧 %d 张 → 取「读出非空」%d 张 + 均匀对照 = %d 张"
                  % (len(scored), sum(1 for h, _ in scored if h), len(files)))
        else:
            n = int(args.max)
            idx = [int(round(i * (len(files) - 1) / float(n - 1))) for i in range(n)] if n > 1 else [0]
            files = [files[i] for i in dict.fromkeys(idx)]
            print("取证帧 → 均匀取 %d 张" % len(files))
        print("（想要全部就加 --max 0）")

    cells = []
    print("%-9s %-11s %-9s %s" % ("时刻(s)", "程序读出", "框来源", "画面（人工核对用）"))
    for p in files:
        m = re.search(r"(\d+\.\d+)", os.path.basename(p))
        if not m:
            continue
        t = float(m.group(1))
        r = nearest(rows, t)
        if r is None:
            continue
        box = [int(v) for v in (r.get("hud_box") or "").split(",") if v.strip() != ""]
        if len(box) != 4:
            continue
        y0, x0, y1, x1 = box
        im = Image.open(p).convert("RGB")
        W, H = im.size
        y0p, y1p = max(0, y0 - args.pad), min(H, y1 + args.pad)
        x0p, x1p = max(0, x0 - args.pad), min(W, x1 + args.pad)
        crop = im.crop((x0p, y0p, x1p, y1p))
        crop = crop.resize((max(1, int(crop.size[0] * args.scale)),
                            max(1, int(crop.size[1] * args.scale))), Image.LANCZOS)
        cells.append((t, r.get("hud_text") or "(空)", r.get("hud_src") or "",
                      r.get("reliable") or "0", crop))
        print("%-9.2f %-11s %-9s %s" % (t, r.get("hud_text") or "(空)", r.get("hud_src"),
                                        os.path.basename(p)))

    if not cells:
        print("没凑出任何格子（诊断表与取证帧的时刻对不上？）")
        return 1

    cols = max(1, int(args.cols))
    # ⚠️ 先把格子缩放到"整张图不超过 MAX_W"——否则并列的裁图会**互相压盖**（第一版踩过）
    raw_w = max(c[4].size[0] for c in cells)
    raw_h = max(c[4].size[1] for c in cells)
    room = (MAX_W - 8 * (cols + 1)) / float(cols)
    k = min(1.0, room / float(max(1, raw_w)))
    cells = [(t, txt, src, rel,
              crop.resize((max(1, int(crop.size[0] * k)), max(1, int(crop.size[1] * k))),
                          Image.LANCZOS))
             for t, txt, src, rel, crop in cells]
    cw = max(c[4].size[0] for c in cells) + 16
    ch = max(c[4].size[1] for c in cells) + 34
    nrows = (len(cells) + cols - 1) // cols
    W = min(MAX_W, cols * cw + 8)
    sheet = Image.new("RGB", (W, nrows * ch + 34), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    d.text((8, 8), "实机读数核对：请逐格看「画面上的数字」与「程序读出」是否一致"
                   "（不一致的请报时刻+屏幕上的数）", font=font(18), fill=(255, 255, 255))
    for i, (t, txt, src, rel, crop) in enumerate(cells):
        cx, cy = 8 + (i % cols) * cw, 34 + (i // cols) * ch
        sheet.paste(crop, (cx, cy + 24))
        d.text((cx, cy + 4), "t=%.1fs  读出=%s  来源=%s  可信=%s"
               % (t, txt, src, "是" if rel == "1" else "否"), font=font(15),
               fill=(255, 255, 255))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    sheet.save(args.out)
    print("\n已写出 %s  %s（共 %d 格，缩放 %.2f）" % (args.out, sheet.size, len(cells), k))
    print("⚠️ 这只是**把证据摆出来**，读数对不对要靠人眼核对 —— 请把不一致的格子报出来。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
