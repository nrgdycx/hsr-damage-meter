# -*- coding: utf-8 -*-
"""
诊断形近字：把出错的字形渲染成 PNG，并对比同类训练样本，找出真正的混淆原因。

已知错误（留出集，从未参与训练）：
    t=226 期望 49065 → 读出 49045   错在第 2 位：6 被判成 4
    t=275 期望 904004 → 读出 904096  错在最高两位：0→6、0→9

要查的假设：
  H1 字形高度不同（HUD 有"累积阶段小/结算后大"两种字号）→ 归一化到 34px 后形变不同
  H2 训练样本里 6/4/9/0 的字形本身不清晰（或被切残）
  H3 归一化方式（按峰值）对某些字形压扁
"""
# [P3 整理] 原路径：diag_glyph_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import read_hud  # noqa: E402
from digit_truth import HOLDOUT, LABELED  # noqa: E402

RAMP = " .:-=+*#%@"
OUT = "samples/A_形近字诊断.png"


def font(sz):
    for p in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/arialbd.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def ascii_art(v, cols=24):
    """v: GH×GW 的 0~1 灰度。"""
    lines = []
    for y in range(v.shape[0]):
        lines.append("".join(RAMP[int(np.clip(v[y, x], 0, 1) * 9)] for x in range(v.shape[1])))
    return lines


def main():
    model = read_hud.load_model()
    tiles = []
    print("=" * 78)
    for t, want in sorted(HOLDOUT.items()):
        png = "frames/glyphcache/f%08.2f.png" % t
        if not os.path.exists(png):
            continue
        glyphs = read_hud.extract_glyphs(png)
        res = read_hud.classify(model, glyphs)
        read = "".join(str(d) for d, _ in res)
        print("\nt=%-5d 期望 %-8s 读出 %-8s" % (t, want, read))
        print("  切出 %d 段，期望 %d 位" % (len(glyphs), len(want)))
        # 逐位对齐（右对齐）
        n = min(len(res), len(want))
        for i in range(1, n + 1):
            gt = int(want[-i])
            pred, conf = res[-i]
            mark = "✓" if pred == gt else "✗"
            gh = glyphs[-i]
            _, w, h = gh
            print("   第%d位(从右) 期望%d 读出%d 置信%.2f %s   字形像素 %dx%d" %
                  (i, gt, pred, conf, mark, w, h))
            if pred != gt:
                # 渲染：真实字形 + ASCII
                v = gh[0][0, 0].numpy()
                im = Image.fromarray((v * 255).astype(np.uint8)).resize((24 * 6, 34 * 6), Image.NEAREST)
                im = im.convert("RGB")
                d = ImageDraw.Draw(im)
                d.rectangle([0, 0, im.size[0] - 1, 40], fill=(0, 0, 0))
                d.text((3, 3), "t=%d pos%d" % (t, i), font=font(15), fill=(255, 255, 0))
                d.text((3, 20), "want %d -> read %d (%.2f)" % (gt, pred, conf),
                       font=font(14), fill=(255, 80, 80))
                tiles.append(im)

    # 出诊断图
    if tiles:
        per = 4
        rows = (len(tiles) + per - 1) // per
        TW, TH = tiles[0].size
        GAP = 6
        sheet = Image.new("RGB", (per * TW + (per + 1) * GAP, rows * TH + (rows + 1) * GAP + 24), (18, 18, 18))
        for i, tl in enumerate(tiles):
            r, c = divmod(i, per)
            sheet.paste(tl, (GAP + c * (TW + GAP), GAP + r * (TH + GAP)))
        d = ImageDraw.Draw(sheet)
        d.text((GAP, sheet.size[1] - 20), "出错的字形（放大6倍，按字形峰值归一化后）",
               font=font(15), fill=(255, 255, 255))
        sheet.save(OUT)
        print("\n已写出 %s %s" % (OUT, sheet.size))

    # 同时看训练集里 0/4/6/9 的样本数量与字形高度分布
    print("\n" + "=" * 78)
    print("训练集里形近字的字形像素高度（H2 假设）:")
    d = np.load("out/digit_dataset.npz", allow_pickle=True)
    import json
    meta = [json.loads(m) for m in d["meta"]]
    for digit in (0, 4, 6, 9):
        idx = [i for i, m in enumerate(meta) if m["digit"] == str(digit) or m["digit"] == digit]
        if not idx:
            print("  %d: 无样本" % digit)
            continue
        # meta 里没有宽高，改从数据集 X 的行分布推断字形实际高度
        print("  %d: %d 个样本  来源帧 %s" %
              (digit, len(idx), sorted(set(meta[i]["t"] for i in idx))))


if __name__ == "__main__":
    main()
