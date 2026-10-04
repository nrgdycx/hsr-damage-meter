# -*- coding: utf-8 -*-
"""
[A 线] 专补稀缺数字：用已训好的像素字体模型扫全片，挑出"读数含指定数字"的帧，
出图请用户确认 —— 这是唯一能把稀缺数字（如 '5' 只有 1 个样本）补起来的路子。

⚠️ 注意口径：模型读数只用于**挑帧**（挑出"可能含 5"的帧），
   **标签仍然只认用户读数** —— 不能让模型自己给自己造标签。

用法: python hunt5_A.py [要补的数字，默认 5] [最多几帧，默认 8]
"""
# [P3 整理] 原路径：hunt5_A.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import glob
import json
import os
import sys

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)
import hud_profiles as HP  # noqa
from train_digit_cnn import load_any_pt  # noqa
from digit_truth import LABELED_PIXEL  # noqa

CROP = os.path.join(HERE, "frames", "hudcrop3_A")
MODEL = os.path.join(HERE, "out", "digit_cnn_yinlang999.pt")
WY0, WX0, WY1, WX1 = 246, 2390, 362, 2870
SCALE = 1.6
COLS = 2


def ncc(a, b):
    a = a.ravel() - a.mean()
    b = b.ravel() - b.mean()
    d = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float((a * b).sum() / d) if d > 1e-8 else 0.0


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else "5"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    model = load_any_pt(MODEL)

    fs = sorted(glob.glob(os.path.join(CROP, "h*.png")))
    cands = []
    for p in fs:
        t = float(os.path.basename(p)[1:-4])
        a = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
        sub = a[WY0 - 240:WY1 - 240, WX0 - 2300:WX1 - 2300]
        gs = HP.glyphs_cropped("yinlang999", sub, WY0, WX0)
        if len(gs) < 4:
            continue
        x = torch.tensor(np.stack([v for v, _, _ in gs])[:, None], dtype=torch.float32)
        with torch.no_grad():
            pr = model(x).argmax(1).numpy()
        read = "".join(str(int(d)) for d in pr)
        if want in read:
            st = np.stack([v for v, _, _ in gs])
            cands.append((t, p, read, st))
    print("读数含 %r 的像素字体帧: %d 个" % (want, len(cands)))
    # 已有的用户真值不算（避免重复请用户读同一帧）
    cands = [c for c in cands if c[0] not in LABELED_PIXEL]

    picked = []
    for t, p, read, st in cands:
        if len(picked) >= limit:
            break
        if any(st.shape[0] == s2.shape[0] and min(ncc(st[i], s2[i]) for i in range(st.shape[0])) > 0.90
               for _, _, _, s2 in picked):
            continue
        picked.append((t, p, read, st))
    print("挑出 %d 帧（模型读数，仅供挑帧）: %s" % (
        len(picked), ["%.0f:%s" % (t, r) for t, _, r, _ in picked]))
    if not picked:
        print("没挑到；可能该数字在这个录屏里确实很少")
        return

    cells = []
    for i, (t, p, read, _) in enumerate(picked, 1):
        a = np.asarray(Image.open(p).convert("RGB"))
        c = a[WY0 - 240:WY1 - 240, WX0 - 2300:WX1 - 2300]
        im = Image.fromarray(c).resize((int(c.shape[1] * SCALE), int(c.shape[0] * SCALE)), Image.LANCZOS)
        cells.append((i, im, t))
    lw = 84
    ncol = min(COLS, len(cells))
    nrow = (len(cells) + ncol - 1) // ncol
    colw = [0] * ncol
    for k, (_, im, _) in enumerate(cells):
        colw[k % ncol] = max(colw[k % ncol], im.width + 24)
    rowh = max(im.height for _, im, _ in cells) + 20
    xs = [lw]
    for cw in colw:
        xs.append(xs[-1] + cw)
    sheet = Image.new("RGB", (xs[-1] + 12, nrow * rowh + 14), (0, 0, 0))
    d = ImageDraw.Draw(sheet)
    f = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 40)
    for k, (idx, im, t) in enumerate(cells):
        r, c = divmod(k, ncol)
        d.text((10, 10 + r * rowh + im.height // 2 - 24), "%2d)" % idx, font=f, fill=(255, 255, 255))
        sheet.paste(im, (xs[c], 10 + r * rowh))
    out = os.path.join(HERE, "samples", "请看读数_像素字体_补%s.png" % want)
    sheet.save(out)
    json.dump([{"idx": i, "t": t} for i, _, t in cells],
              open(os.path.join(HERE, "out", "sheet_hunt_%s_A.json" % want), "w"),
              ensure_ascii=False, indent=1)
    print("已写出 %s %dx%d" % (out, sheet.size[0], sheet.size[1]))


if __name__ == "__main__":
    main()
