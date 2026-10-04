# -*- coding: utf-8 -*-
"""
E 线：把 100~340 帧的顶端卡识别结果导出成 CSV（给 C 会话做归属用）+ 生成验收图。

  out/axis_actors_E.csv : t, unit, owner, score, margin, marker
  samples/E_accept.png  : 抽查帧的顶端卡 + 识别结论（文字标注，不用颜色编码）
"""
# [P3 整理] 原路径：axis_export_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import csv
import glob
import os
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import axis_actor as T

FRAME = "frames/glyphcache/f%08.2f.png"
OUT_CSV = "out/axis_actors_E.csv"

# 用户口径与铁律.md 里记的"用户真值"（顶端=归属口径）+ E 线实测更正（见 行动轴识别.md 第 6 节）
DOC_TRUTH = T.TRUTH_OWNER


def font(sz):
    for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(f, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def times(lo=100.0, hi=340.0, frame_dir="frames/glyphcache"):
    out = []
    for p in sorted(glob.glob(os.path.join(frame_dir, "*.png"))):
        try:
            t = float(os.path.basename(p)[1:-4])
        except ValueError:
            continue
        if lo <= t <= hi:
            out.append(t)
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="frames/glyphcache")
    ap.add_argument("--range", default="100,340")
    ap.add_argument("--out", default=OUT_CSV)
    ap.add_argument("--no-accept", action="store_true")
    args = ap.parse_args()
    lo, hi = [float(x) for x in args.range.split(",")]
    bank = T.load_bank()
    rows = []
    t0 = time.time()
    for t in times(lo, hi, args.dir):
        img = cv2.imread(os.path.join(args.dir, "f%08.2f.png" % t), cv2.IMREAD_COLOR)
        if img is None:
            continue
        r = T.read_actor(img, bank)
        rows.append([t, r["unit"] or "", r["owner"] or "", r["score"], r["margin"], r["marker"],
                     "" if r["inserted"] is None else int(r["inserted"]), r["card_type"]])
    dt = time.time() - t0
    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["t", "unit", "owner", "score", "margin", "marker", "inserted", "card_type"])
        w.writerows(rows)
    print("已写出 %s（%d 帧，含解码共 %.1fs，平均 %.1f ms/帧）" %
          (args.out, len(rows), dt, dt * 1000 / max(1, len(rows))))
    if args.no_accept:
        from collections import Counter
        print("卡型分布:", dict(Counter(r[7] for r in rows)))
        print("标记分布:", dict(Counter(r[5] for r in rows)))
        print("识别到我方 %d/%d 帧" % (sum(1 for r in rows if r[1]), len(rows)))
        return

    # 纯推理耗时（图已在内存里，实时抓屏走这条路）
    img = cv2.imread(FRAME % 226, cv2.IMREAD_COLOR)
    t1 = time.time()
    for _ in range(50):
        T.read_actor(img, bank)
    print("纯推理（不含读盘）：%.1f ms/帧" % ((time.time() - t1) * 1000 / 50))

    named = [r for r in rows if r[1]]
    print("有名字 %d 帧 / 判定待复核 %d 帧" % (len(named), len(rows) - len(named)))
    from collections import Counter
    print("单位分布:", dict(Counter(r[1] for r in named)))

    print("\n=== 验收：对 用户口径与铁律.md 记录的用户真值帧 ===")
    byt = {r[0]: r for r in rows}
    ok = bad = 0
    for t, exp in sorted(DOC_TRUTH.items()):
        r = byt.get(float(t))
        if r is None:
            print("  t=%-5d 缺帧" % t)
            continue
        got = r[2] or "待复核"
        if exp is None:
            flag = "OK" if r[2] == "" else "!!"
            if flag == "OK":
                ok += 1
            else:
                bad += 1
            print("  t=%-5d 期望 非我方/空   实得 %-6s %s (分数%.2f)" % (t, got, flag, r[3]))
        else:
            flag = "OK" if r[2] == exp else "!!"
            if flag == "OK":
                ok += 1
            else:
                bad += 1
            print("  t=%-5d 期望 %-5s 实得 %-6s %s (分数%.2f 顶端=%s)" %
                  (t, exp, got, flag, r[3], r[1] or "-"))
    print("  一致 %d / 不一致 %d" % (ok, bad))

    # 验收图
    picks = [100, 109, 140, 156, 159, 167, 191, 221, 226, 251, 293, 307, 311]
    panels = []
    for t in picks:
        r = byt.get(float(t))
        img = cv2.imread(FRAME % t, cv2.IMREAD_COLOR)
        sub = cv2.cvtColor(img[66:196, 62:300], cv2.COLOR_BGR2RGB)
        im = Image.fromarray(cv2.resize(sub, (238 * 2, 130 * 2), interpolation=cv2.INTER_LANCZOS4))
        cv = Image.new("RGB", (im.width, im.height + 46), (0, 0, 0))
        cv.paste(im, (0, 46))
        d = ImageDraw.Draw(cv)
        d.text((4, 3), "t=%.0f" % t, font=font(18), fill=(255, 255, 255))
        label = ("判定 %s（归属 %s）分数%.2f" % (r[1], r[2], r[3])) if r and r[1] else \
                ("判定 待复核（分数%.2f）" % (r[3] if r else -1))
        d.text((4, 24), label, font=font(18), fill=(255, 255, 255))
        panels.append(cv)
    cols = 3
    rn = (len(panels) + cols - 1) // cols
    pw, ph = panels[0].size
    sheet = Image.new("RGB", (cols * pw + (cols + 1) * 8, rn * ph + (rn + 1) * 8), (25, 25, 25))
    for i, pn in enumerate(panels):
        r_, c_ = divmod(i, cols)
        sheet.paste(pn, (8 + c_ * (pw + 8), 8 + r_ * (ph + 8)))
    sheet.save("samples/E_accept.png")
    print("已写出 samples/E_accept.png %s" % (sheet.size,))


if __name__ == "__main__":
    main()
