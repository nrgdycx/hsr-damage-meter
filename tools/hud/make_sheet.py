# -*- coding: utf-8 -*-
"""
[A 线工具] 生成「待用户读数」的帧图 —— 用户读数是最可靠的标签来源。

挑选逻辑：
  * 按「数值保持窗口」分段（同一读数连续出现 = 同一个值）；
  * 排除留出帧 ±4s 邻域（否则等于把留出集答案喂给训练 = 泄漏）；
  * 优先：含稀缺/形近数字 0/6/5/2、模型置信度低、两种字号都覆盖、值互不重复；
  * 图上**只给编号**，不给模型读数（避免诱导用户）。

产物：samples/请看读数_A.png + out/sheet_A.json（编号 → 帧号 映射）
"""
# [P3 整理] 原路径：make_sheet_A.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import json
import os
import sys
from collections import Counter

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from read_hud import load_model, read_frame, extract_glyphs  # noqa
from collect_glyphs import frame  # noqa

CACHE = "frames/glyphcache"
HOLDOUT = {226: "49065", 261: "721193", 275: "904004", 284: "111860", 311: "379852"}
GUARD = 4
RAW_BOX = (248, 2330, 352, 2876)     # 上,左,下,右 —— 固定窗：12 位大字也放得下且留边
LIMIT = 12
SCALE = 1.5
COLS = 2


def digits_bbox(a, oy, ox):
    """返回数字串的像素包围盒 (x0,y0,x1,y1)，坐标是 RAW_BOX 内的相对坐标。"""
    c = a[RAW_BOX[0]:RAW_BOX[2], RAW_BOX[1]:RAW_BOX[3]]
    R, G, B = c[:, :, 0], c[:, :, 1], c[:, :, 2]
    m = (R > 225) & (G > 225) & (B >= 185) & ((R - B) > 25)
    ms = m.copy()
    ms[298 - RAW_BOX[0]:311 - RAW_BOX[0], :] = False
    col = ms.any(axis=0)
    runs, s = [], None
    for x in range(len(col)):
        if col[x] and s is None:
            s = x
        elif not col[x] and s is not None:
            runs.append([s, x - 1])
            s = None
    if s is not None:
        runs.append([s, len(col) - 1])
    if not runs:
        return None
    # 取最右一团（数字区就在右侧），并允许向左串到相邻字形
    chain = [runs[-1]]
    for r in reversed(runs[:-1]):
        if chain[0][0] - r[1] - 1 <= 20:
            chain.insert(0, r)
        else:
            break
    x0, x1 = chain[0][0], chain[-1][1]
    rows = np.where(m[:, x0:x1 + 1].any(axis=1))[0]
    if len(rows) == 0:
        return None
    y0, y1 = rows[0], rows[-1]
    return (max(0, x0 - 16), max(0, y0 - 14), min(c.shape[1], x1 + 17), min(c.shape[0], y1 + 15))


def main():
    model = load_model()
    CACHE_ROWS = "out/sheet_scan_A.json"
    if os.path.exists(CACHE_ROWS) and not os.environ.get("FRESH"):
        rows = json.load(open(CACHE_ROWS))
        print("复用扫描缓存 %s（%d 帧）" % (CACHE_ROWS, len(rows)))
    else:
        rows = []
        for t in range(100, 340):
            p = os.path.join(CACHE, "f%08.2f.png" % t)
            if not os.path.exists(p):
                continue
            s, c, res = read_frame(model, p)
            gs = extract_glyphs(p)
            rows.append({"t": t, "read": s, "conf": round(c, 4), "n": len(s),
                         "hmax": int(max([g[2] for g in gs], default=0)),
                         "hs": [int(g[2]) for g in gs]})
        json.dump(rows, open(CACHE_ROWS, "w"))

    # 分段
    wins = []
    for r in rows:
        if wins and wins[-1]["read"] == r["read"] and r["t"] == wins[-1]["t1"] + 1:
            wins[-1]["t1"] = r["t"]
            wins[-1]["rows"].append(r)
        else:
            wins.append({"read": r["read"], "t0": r["t"], "t1": r["t"], "rows": [r]})
    wins = [w for w in wins if w["read"] and w["read"].isdigit()]

    def guard_ok(w):
        return all(abs(t - h) > GUARD for h in HOLDOUT for t in range(w["t0"], w["t1"] + 1))

    RARE = {"0": 3.0, "6": 3.0, "5": 2.0, "2": 1.5, "4": 1.2, "9": 1.0,
            "8": 0.6, "1": 0.3, "3": 0.3, "7": 0.3}
    pool = []
    for w in wins:
        if not guard_ok(w):
            continue
        mid = w["rows"][len(w["rows"]) // 2]
        score = sum(RARE.get(ch, 0) for ch in set(w["read"]))
        score += (1.0 - mid["conf"]) * 6                      # 低置信 → 更可能是错读，价值高
        score += 1.0 if mid["hmax"] >= 66 else 0.0            # 大字号覆盖
        score += 0.15 * len(w["read"])
        pool.append({"t": mid["t"], "read": w["read"], "conf": mid["conf"],
                     "hmax": mid["hmax"], "n": len(w["rows"]), "score": round(score, 2)})

    # 贪心挑选：兼顾分数与数字覆盖
    pool.sort(key=lambda c: -c["score"])
    picked, covered, seen = [], Counter(), set()
    for c in pool:
        if len(picked) >= LIMIT:
            break
        if c["read"] in seen:
            continue
        new = [ch for ch in set(c["read"]) if covered[ch] == 0 and RARE.get(ch, 0) >= 1.0]
        if len(picked) >= 4 and not new and len(picked) < LIMIT - 2:
            continue
        picked.append(c)
        seen.add(c["read"])
        for ch in set(c["read"]):
            covered[ch] += 1
    # 补足：仍然不够就放宽
    for c in pool:
        if len(picked) >= LIMIT:
            break
        if c["read"] not in seen:
            picked.append(c)
            seen.add(c["read"])
    picked.sort(key=lambda c: c["t"])

    print("抽出 %d 帧给用户读数：" % len(picked))
    for i, c in enumerate(picked, 1):
        print("   %2d) t=%-4s (模型当前读作 %s, 置信 %.2f, 字高 %d)" % (
            i, c["t"], c["read"], c["conf"], c["hmax"]))

    # 渲染：**固定宽窗**，不按数字贴紧裁切。
    # 教训（用户指出）：贴紧裁切在大字号 / 12 位数字（放大状态）下会切边，
    # 用户只能靠经验猜 —— 那等于给出不完整信息，必须避免。
    # 固定窗 x 2330..2876 可容纳 12 位大字（最右缘 ≈2852，每字推进 ≈40px → 最左 ≈2372）并留边。
    cells = []
    for i, c in enumerate(picked, 1):
        a = np.asarray(Image.open(frame(float(c["t"]))).convert("RGB"))
        crop = a[RAW_BOX[0]:RAW_BOX[2], RAW_BOX[1]:RAW_BOX[3]]
        im = Image.fromarray(crop)
        im = im.resize((int(im.width * SCALE), int(im.height * SCALE)), Image.LANCZOS)
        cells.append((i, im))

    lw = 78
    ncol = min(COLS, max(1, len(cells)))
    nrow = (len(cells) + ncol - 1) // ncol
    # 按列取实际最大宽度，避免右边被画布裁掉
    colw = [0] * ncol
    for k, (idx, im) in enumerate(cells):
        colw[k % ncol] = max(colw[k % ncol], im.width + 24)
    rowh = max(im.height for _, im in cells) + 22
    xs = [lw]
    for cw in colw:
        xs.append(xs[-1] + cw)
    sheet = Image.new("RGB", (xs[-1] + 12, nrow * rowh + 14), (0, 0, 0))
    d = ImageDraw.Draw(sheet)
    f = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 40)
    for k, (idx, im) in enumerate(cells):
        r, cc = divmod(k, ncol)
        x = xs[cc]
        y = 10 + r * rowh
        d.text((8, y + im.height // 2 - 24), "%2d)" % idx, font=f, fill=(255, 255, 255))
        sheet.paste(im, (x, y + 10))
    sheet.save("samples/请看读数_A.png")
    json.dump({"cells": [{"idx": i, "t": c["t"], "model_read": c["read"]} for i, c in
                         zip([x[0] for x in cells], picked)]},
              open("out/sheet_A.json", "w"), ensure_ascii=False, indent=1)
    print("\n已写出 samples/请看读数_A.png  尺寸 %dx%d" % sheet.size)
    print("已写出 out/sheet_A.json")


if __name__ == "__main__":
    main()
