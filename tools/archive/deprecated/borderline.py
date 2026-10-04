# -*- coding: utf-8 -*-
"""
E 线：定「间距下限 MIN_MARGIN」（过渡/滑动中的卡两类分数几乎相同，靠分数阈值切不干净）。

做法：先用 min_margin=-9 关掉间距规则，把 249 帧的 (分数, 间距) 全打出来，
看"分数过阈值"的帧里间距分布在哪里断层，再决定 MIN_MARGIN。
用法：python axis_borderline_E.py [--n 18]
"""
# [P3 整理] 原路径：axis_borderline_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import glob
import os

import cv2
import numpy as np
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
    ap.add_argument("--n", type=int, default=18)
    ap.add_argument("--out", default="samples/E_borderline.png")
    args = ap.parse_args()
    bank = T.load_bank()
    rows = []
    for p in sorted(glob.glob(os.path.join(ROOT, "frames/glyphcache/*.png"))):
        try:
            t = float(os.path.basename(p)[1:-4])
        except ValueError:
            continue
        if not (100 <= t <= 340):
            continue
        img = cv2.imread(p, cv2.IMREAD_COLOR)
        if img is None:
            continue
        r = T.read_actor(img, bank, min_margin=-9)     # 关掉间距规则，看原始分布
        rows.append((t, r["raw"], r["score"], r["margin"]))

    passed = [r for r in rows if r[2] >= T.THR]        # 分数过阈值
    passed.sort(key=lambda r: r[3])
    print("249 帧中分数 >= %.2f 的有 %d 帧；它们的间距分布：" % (T.THR, len(passed)))
    print("  " + "  ".join("t%s:%.2f" % (T.fmt_t(t), m) for t, _, _, m in passed[:24]))
    print("\n间距最小的 18 帧（重点核对；这些就是过渡帧）：")
    for t, u, s, m in passed[:18]:
        print("   t=%-6s 判为%-5s 分数%.2f 间距%.3f" % (T.fmt_t(t), u, s, m))
    margins = np.array([r[3] for r in passed])
    print("\n间距分位：min %.3f  10%% %.3f  25%% %.3f  中位 %.3f" %
          (margins.min(), float(np.percentile(margins, 10)),
           float(np.percentile(margins, 25)), float(np.median(margins))))

    panels = []
    for t, u, s, m in passed[:args.n]:
        img = cv2.imread(FRAME % t, cv2.IMREAD_COLOR)
        sub = cv2.cvtColor(img[66:196, 62:300], cv2.COLOR_BGR2RGB)
        im = Image.fromarray(cv2.resize(sub, (238 * 2, 130 * 2), interpolation=cv2.INTER_LANCZOS4))
        cv = Image.new("RGB", (im.width, im.height + 46), (0, 0, 0))
        cv.paste(im, (0, 46))
        d = ImageDraw.Draw(cv)
        d.text((4, 3), "t=%.0f 判为%s" % (t, u), font=font(18), fill=(255, 255, 255))
        d.text((4, 24), "分数%.2f 间距%.3f" % (s, m), font=font(18), fill=(255, 255, 255))
        panels.append(cv)
    cols = 3
    rn = (len(panels) + cols - 1) // cols
    pw, ph = panels[0].size
    sheet = Image.new("RGB", (cols * pw + (cols + 1) * 8, rn * ph + (rn + 1) * 8), (25, 25, 25))
    for i, pn in enumerate(panels):
        r_, c_ = divmod(i, cols)
        sheet.paste(pn, (8 + c_ * (pw + 8), 8 + r_ * (ph + 8)))
    sheet.save(args.out)
    print("已写出 %s %s" % (args.out, sheet.size))


if __name__ == "__main__":
    main()
