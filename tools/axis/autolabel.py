# -*- coding: utf-8 -*-
"""
E 线：用现有模板库给 100~340 全部帧自动打标，产出
  1) out/axis_autolabel_E.json  每帧 {unit, score, margin}
  2) samples/E_auto_<unit>.png  每个单位的候选帧拼图（供人工核对后并入模板库）

验收方式：人工看图核对 → 把确认的帧并入 out/axis_top_labels_E.json → 重建模板库。
"""
# [P3 整理] 原路径：axis_autolabel_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import glob
import json
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import axis_actor as T

FRAME = "frames/glyphcache/f%08.2f.png"
OUT_JSON = "out/axis_autolabel_E.json"


def font(sz):
    for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(f, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def frame_times(lo=100.0, hi=340.0):
    out = []
    for p in sorted(glob.glob("frames/glyphcache/*.png")):
        try:
            t = float(os.path.basename(p)[1:-4])
        except ValueError:
            continue
        if lo <= t <= hi:
            out.append(t)
    return out


def main():
    bank = T.load_bank()
    labels = json.load(open(T.LABELS_PATH, encoding="utf-8"))
    known = {float(t) for ts in labels.values() for t in ts}
    rows = []
    for t in frame_times():
        try:
            img = cv2.imread(FRAME % t, cv2.IMREAD_COLOR)
        except Exception:
            continue
        if img is None:
            continue
        sc = T.match(bank, img)
        unit, (best, second) = max(sc.items(), key=lambda kv: kv[1][0])
        mk, area, hue = T.marker_feat(img)
        rows.append(dict(t=t, unit=unit, score=round(best, 3), margin=round(best - second, 3),
                         marker=mk, known=t in known,
                         scores={k: round(v[0], 3) for k, v in sc.items()}))
    json.dump(rows, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已写出 %s（%d 帧）" % (OUT_JSON, len(rows)))

    # 时间轴（压缩打印）
    print("\n时间轴（每行 30 帧，格式 单位缩写+分数档：@=>=1.4 +=1.1~1.4 -=0.8~1.1 .=<0.8）")
    ab = {"遐蝶": "遐", "风堇": "风", "昔涟": "昔", "长夜月": "夜",
          "死龙": "龙", "长夜": "水", "小伊卡": "伊", "德谬歌": "德"}
    for i in range(0, len(rows), 30):
        chunk = rows[i:i + 30]
        line = "".join("%s%s" % (ab.get(r["unit"], "?"),
                                "@" if r["score"] >= 1.4 else "+" if r["score"] >= 1.1
                                else "-" if r["score"] >= 0.8 else ".")
                       for r in chunk)
        print("t=%-5.0f %s" % (chunk[0]["t"], line))

    # 每个单位的候选拼图（未并入模板库、分数>=1.2）
    for unit in T.UNIT_NAMES:
        cand = [r for r in rows if r["unit"] == unit and not r["known"] and r["score"] >= 1.2]
        cand.sort(key=lambda r: -r["score"])
        cand = cand[:12]
        if not cand:
            continue
        panels = []
        for r in cand:
            img = cv2.imread(FRAME % r["t"], cv2.IMREAD_COLOR)
            sub = cv2.cvtColor(img[66:196, 70:300], cv2.COLOR_BGR2RGB)
            im = Image.fromarray(cv2.resize(sub, (230 * 2, 130 * 2), interpolation=cv2.INTER_LANCZOS4))
            cv = Image.new("RGB", (im.width, im.height + 26), (0, 0, 0))
            cv.paste(im, (0, 26))
            ImageDraw.Draw(cv).text((4, 4), "t=%.0f  %.2f" % (r["t"], r["score"]),
                                    font=font(18), fill=(255, 255, 255))
            panels.append(cv)
        cols = 3
        rows_n = (len(panels) + cols - 1) // cols
        pw, ph = panels[0].size
        sheet = Image.new("RGB", (cols * pw + (cols + 1) * 8, rows_n * ph + (rows_n + 1) * 8), (25, 25, 25))
        for i, pn in enumerate(panels):
            r_, c_ = divmod(i, cols)
            sheet.paste(pn, (8 + c_ * (pw + 8), 8 + r_ * (ph + 8)))
        p = "samples/E_auto_%s.png" % unit
        sheet.save(p)
        print("候选 %-4s %d 帧 -> %s" % (unit, len(cand), p))


if __name__ == "__main__":
    main()
