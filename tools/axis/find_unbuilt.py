# -*- coding: utf-8 -*-
"""把一个采集目录里的卡**逐张**拿去库里认，把"认不出的"聚起来铺图。

用途：找出"当年采到了、但没建库"的角色 —— 用户问过"青雀不是已经记录了吗"，
而它不在任何标注文件里；用现在的库反查是最直接的办法。
（用 `T._flat_bank` 的向量化打分：一张卡一次矩阵乘。）

用法：python tools/axis/find_unbuilt.py --cards frames/battle1003 --tag battle1003
"""
import argparse
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import axis_actor as T                                          # noqa: E402
from harvest_characters import art_of_card, feat_fft, pair_score_shift   # noqa: E402
from build_from_annotation import feats_of_art                   # noqa: E402


def imread_u(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", required=True)
    ap.add_argument("--tag", default="unbuilt")
    ap.add_argument("--thr", type=float, default=1.45)
    ap.add_argument("--margin", type=float, default=0.45)
    ap.add_argument("--cluster", type=float, default=1.30)
    args = ap.parse_args(argv)

    bank = T.load_bank()
    flat, pen, starts, units = T._flat_bank(bank)
    files = sorted(f for f in os.listdir(args.cards) if f.endswith(".png"))
    print("目录 %s：%d 张卡；库 %d 条目" % (args.cards, len(files), len(units)))

    unmatched, matched = [], 0
    feats_cache = {}
    for i, fn in enumerate(files):
        art = art_of_card(imread_u(os.path.join(args.cards, fn)))
        f1 = T.feats(art)
        f2 = feats_of_art(art, T.ZOOMS[1])
        best = None
        for ff in (f1, f2):
            sc = flat @ (ff * T._SW).reshape(-1) / 3456.0 - pen
            per = np.array([sc[starts[k]:starts[k + 1]].max() for k in range(len(units))])
            order = np.argsort(-per)
            cand = (float(per[order[0]]), units[order[0]],
                    float(per[order[0]] - per[order[1]]), order[0])
            if best is None or cand[0] > best[0]:
                best = cand
        if best[0] >= args.thr and best[2] >= args.margin:
            matched += 1
        else:
            unmatched.append((i, float(fn[1:9]), fn, best[1], round(best[0], 3), round(best[2], 3)))
            feats_cache[i] = feat_fft(f1)

    print("认得 %d 张；认不出 %d 张" % (matched, len(unmatched)))

    # 把认不出的按"同一个人"聚起来
    groups = []
    for i, t, fn, top, sc, gap in sorted(unmatched, key=lambda x: x[1]):
        placed = False
        for g in groups:
            if pair_score_shift(feats_cache[g[0][0]], feats_cache[i]) >= args.cluster:
                g.append((i, t, fn, top, sc, gap))
                placed = True
                break
        if not placed:
            groups.append([(i, t, fn, top, sc, gap)])
    groups.sort(key=lambda g: g[0][1])
    print("认不出的卡聚成 %d 组：" % len(groups))
    for g in groups:
        print("  n=%3d  t=%.1f~%.1f  最像 %-10s (%.3f/间距%.3f)"
              % (len(g), g[0][1], g[-1][1], g[0][3], g[0][4], g[0][5]))

    from PIL import Image, ImageDraw, ImageFont       # noqa: E402
    try:
        FT = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 26)
        F = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 16)
    except OSError:
        FT = F = ImageFont.load_default()
    TW, TH, PER = 240, 120, 8
    rows = sum(max(1, (min(len(g), 5) + PER - 1) // PER) for g in groups)
    sheet = Image.new("RGB", (24 + PER * (TW + 6), 60 + rows * (TH + 38) + 20), (10, 10, 10))
    d = ImageDraw.Draw(sheet)
    d.text((16, 8), "%s：认不出的卡（库认不出的=当年采到但没建库的）" % args.tag, font=FT,
           fill=(255, 235, 120))
    y = 52
    for g in groups:
        d.text((16, y), "n=%d  t=%.1f~%.1f  最像「%s」%.2f" % (len(g), g[0][1], g[-1][1],
                                                              g[0][3], g[0][4]),
               font=F, fill=(150, 245, 170))
        y += 26
        for c, (i, t, fn, top, sc, gap) in enumerate(g[:5]):
            img = imread_u(os.path.join(args.cards, fn))
            x = 16 + c * (TW + 6)
            if img is not None:
                sheet.paste(Image.fromarray(cv2.cvtColor(
                    cv2.resize(img, (TW, TH)), cv2.COLOR_BGR2RGB)), (x, y))
            d.text((x + 2, y + TH + 1), "t=%.1f" % t, font=F, fill=(215, 215, 215))
        y += TH + 12
    sheet = sheet.crop((0, 0, sheet.width, y + 8))
    out = os.path.join(ROOT, "samples", "认不出_%s.png" % args.tag)
    ok, buf = cv2.imencode(".png", np.array(sheet)[:, :, ::-1])
    buf.tofile(out)
    print("已写出", out, sheet.size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
