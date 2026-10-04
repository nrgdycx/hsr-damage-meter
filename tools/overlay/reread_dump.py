# -*- coding: utf-8 -*-
"""
取证：**把落盘的整屏帧重新读一遍**，与当时记录的读数对照 —— 分清"读错"与"时间错位"。

为什么必须有这一步
------------------
`--dump-frames` 落盘的整屏帧是在**同一次循环里、读完 HUD 之后**才抓的
（`mvp/live_mvp.py: ScreenSource.frames`：先抓 HUD 小区域 → 再抓整屏存 JPEG），
两者相差 ~50~150ms。而总伤害数字在攻击中**涨得很快**（还会随攻击开始而重置），
所以"图上的数"与"当时读出的数"不同**不一定**是读错，可能是这一两百毫秒的错位。

本脚本用**同一帧 JPEG**（就是给你核对图看的那张）重跑实时路径：
  * 若「重读该帧」读出的数 == 图上肉眼看到的数（且与记录的读数不同）
        → 那次差异是**时间错位**，不是识别缺陷；
  * 若「重读该帧」读出的数 != 图上肉眼看到的数
        → **识别/选框缺陷**，这一格要单独查（把该帧 + 框 + bar 一起看）。

用法：
    python tools/overlay/reread_dump.py --frames samples/p1_live_probe \
        --diag out/p1_live_diag.csv --out samples/实机重读对照.png --max 0
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

MAX_W = 1500


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
                float(r["t"])
            except (TypeError, ValueError):
                continue
            rows.append(r)
    rows.sort(key=lambda r: float(r["t"]))
    return rows


def nearest(rows, t):
    best = None
    for r in rows:
        d = abs(float(r["t"]) - t)
        if best is None or d < best[0]:
            best = (d, r)
    return best[1] if best else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", required=True)
    ap.add_argument("--diag", required=True)
    ap.add_argument("--out", default="samples/实机重读对照.png")
    ap.add_argument("--cols", type=int, default=3)
    ap.add_argument("--max", type=int, default=0, help="最多看几帧（0=全部）")
    ap.add_argument("--only-read", dest="only_read", action="store_true",
                    help="只保留「重读有值」的格子（给用户核对用；其余是屏幕上本来没数字的帧）")
    ap.add_argument("--pad", type=int, default=26)
    args = ap.parse_args()

    from mvp.reader import Perceiver, read_is_reliable

    rows = load_diag(args.diag)
    files = sorted(glob.glob(os.path.join(args.frames, "*.jpg"))
                   + glob.glob(os.path.join(args.frames, "*.png")))
    if args.max:
        files = files[:int(args.max)]
    perc = Perceiver(backend="onnx", check_fresh=False, span_guard=True)   # 实机同一条路径

    cells = []
    same = diff = empty = 0
    print("%-9s %-11s %-11s %-8s %s" % ("时刻(s)", "记录读数", "重读该帧", "框来源", "说明"))
    for p in files:
        m = re.search(r"(\d+\.\d+)", os.path.basename(p))
        if not m:
            continue
        t = float(m.group(1))
        r = nearest(rows, t)
        if r is None:
            continue
        box = [int(v) for v in (r.get("hud_box") or "").split(",") if v.strip() != ""]
        bar = [int(v) for v in (r.get("hud_bar") or "").split(",") if v.strip() != ""]
        if len(box) != 4 or len(bar) != 2:
            continue
        y0, x0, y1, x1 = box
        im = Image.open(p).convert("RGB")
        arr = np.asarray(im)
        crop_pad = im.crop((max(0, x0 - args.pad), max(0, y0 - args.pad),
                            min(im.size[0], x1 + args.pad), min(im.size[1], y1 + args.pad)))
        # 用**记录下来的那一对 (框, bar)** 重读这一帧，保证与当时的取图口径一致
        raw = np.ascontiguousarray(arr[y0:y1, x0:x1], dtype=np.int16)
        row = perc.read(t, region_rgb=raw, top=y0, left=x0, bar_rows=tuple(bar),
                        read_axis=False)
        txt_diag = (r.get("hud_text") or "")
        txt_now = row["text"] or ""
        note = []
        if not txt_now.strip():
            empty += 1
            note.append("重读为空" + ("（记录也为空→一致）" if not txt_diag.strip() else "（记录有值→差异）"))
        elif txt_now == txt_diag:
            same += 1
            note.append("与记录一致")
        else:
            diff += 1
            note.append("与记录不同 → 属**时间错位**（两者都是整串数字时）")
        if "?" in txt_now:
            note.append("重读含 ?")
        cells.append((t, txt_diag, txt_now, r.get("hud_src") or "", "；".join(note), crop_pad,
                      row["n"], row["nbad"]))
        print("%-9.2f %-11s %-11s %-8s %s" % (t, txt_diag or "(空)", txt_now or "(空)",
                                              r.get("hud_src"), "；".join(note)))

    n = max(1, len(cells))
    print("\n共 %d 帧：重读与记录**相同** %d（%.1f%%）、不同 %d（%.1f%%）、重读为空 %d（%.1f%%）"
          % (len(cells), same, 100.0 * same / n, diff, 100.0 * diff / n, empty, 100.0 * empty / n))
    print("说明：'不同' 且**两者都是整串数字**时，最可能是时间错位（图抓得比读数晚 50~150ms）；")
    print("      要判定识别缺陷，请看「重读该帧」是否与**图上肉眼可见的数字**一致。")

    if not cells:
        print("没有可对照的帧")
        return 1
    if args.only_read:
        keep = [c for c in cells if (c[2] or "").strip()]
        print("只保留「重读有值」的 %d 格（其余 %d 格是屏幕上本来就没有数字的帧）"
              % (len(keep), len(cells) - len(keep)))
        cells = keep
        if not cells:
            print("没有「重读有值」的格子")
            return 1
    cols = max(1, int(args.cols))
    raw_w = max(c[5].size[0] for c in cells)
    room = (MAX_W - 8 * (cols + 1)) / float(cols)
    k = min(1.0, room / float(max(1, raw_w)))
    cells = [(t, a, b, s, note, c.resize((max(1, int(c.size[0] * k)),
                                          max(1, int(c.size[1] * k))), Image.LANCZOS),
              nn, nb) for t, a, b, s, note, c, nn, nb in cells]
    cw = max(c[5].size[0] for c in cells) + 16
    ch = max(c[5].size[1] for c in cells) + 52
    nrows = (len(cells) + cols - 1) // cols
    sheet = Image.new("RGB", (min(MAX_W, cols * cw + 8), nrows * ch + 34), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    d.text((8, 8), "重读对照：左=当时记录的读数，右=把这张图重新读一遍（框/bar 用当时那一对）"
                   "  —— 若「重读」与图上数字一致，则差异属时间错位", font=font(17),
           fill=(255, 255, 255))
    for i, (t, a, b, s, note, crop, nn, nb) in enumerate(cells):
        cx, cy = 8 + (i % cols) * cw, 34 + (i // cols) * ch
        sheet.paste(crop, (cx, cy + 34))
        d.text((cx, cy + 2), "t=%.1fs 记录=%s 重读=%s" % (t, a or "(空)", b or "(空)"),
               font=font(15), fill=(255, 255, 255))
        d.text((cx, cy + 18), "来源=%s 段数=%d nbad=%d %s" % (s, nn, nb, note), font=font(13),
               fill=(200, 200, 200))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    sheet.save(args.out)
    print("\n已写出 %s %s（%d 格）" % (args.out, sheet.size, len(cells)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
