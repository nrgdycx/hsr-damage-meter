# -*- coding: utf-8 -*-
"""
[线4] 录屏2 HUD 读数诊断 —— 给【线1 遗留】的"缺最高位"定位原因（**不改任何上游**）。

背景：`docs/剩余工作清单.md` 第二部分 / `docs/剩余工作清单.md` Q1 记着录屏2 读数坏：
    t=26 读出 0130（屏幕像 140130）  t=31 读出 79947（屏幕像 279947）  t=35 读出 00291（屏幕像 100291）
并列出三种可能原因（(a) 大字号不在训练范围 / (b) 裁剪框太窄切掉最高位 / (c) 掩膜阈值不适应），
要用户读 13 帧才敢判断。

本脚本用**列段几何**直接验，不需要用户配合。已知录屏2 的 HUD 字号比录屏1 大（HUD 裁图
570×116 vs 录屏1 的框 526×80），而 `hud_glyphs._extract_core` 的链式连续性阈值是**硬编码 20px**
（C 线已实测录屏1 同一串数字内部的列段间隔就有 23~26px）→ "整串最左边被丢掉"的机制**已经存在**。
本脚本把它量化到录屏2 上：**逐段打印列段间隔**，看断链发生在哪个间隔、差多少像素。

用法：
  python -u diag_hud2_4.py --dir frames/hud2_4          # 全部帧
  python -u diag_hud2_4.py --dir frames/hud2_4 --sweep  # 附带"链阈值扫描 + 框变体"读数
"""
# [P3 整理] 原路径：diag_hud2_4.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import glob
import os
import sys

import numpy as np
from PIL import Image

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)

import hud_glyphs as HG  # noqa: E402
import read_hud  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # [P3] 同目录的 scan_chain.py
import scan_chain as scan_C2  # noqa: E402  （P3 改名：scan_C2.py → scan_chain.py）


def col_runs(a, box):
    """按录屏1 的口径切列段：返回 (merged runs, 每个间隔)。box=(y0,x0,y1,x1)。"""
    y0, x0, y1, x1 = box
    c = a[y0:y1, x0:x1]
    if c.size == 0:
        return [], []
    m_seg, _, _ = HG._masks(c, "glow")
    ms = m_seg.copy()
    r0, r1 = max(0, HG.BAR_ROWS[0] - y0), min(ms.shape[0] - 1, HG.BAR_ROWS[1] - y0)
    if r0 <= r1 and r0 < ms.shape[0]:
        ms[r0:r1 + 1, :] = False
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
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] - 1 < 3:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    gaps = [merged[i + 1][0] - merged[i][1] - 1 for i in range(len(merged) - 1)]
    return merged, gaps


def read_with(a, model, box, chain):
    """用给定 box + 链阈值读数（链阈值靠 scan_C2.module_with_chain 替换，不改上游文件）。"""
    mod = scan_C2.module_with_chain(chain)
    import torch
    gs = mod.extract(a, box=box)
    if not gs:
        return "", 0.0, 0
    x = torch.tensor(np.stack([v for v, _, _ in gs])[:, None], dtype=torch.float32)
    with torch.no_grad():
        pr = torch.softmax(model(x), 1)
    cf, pd = pr.max(1)
    txt = "".join(str(int(d)) if c >= 0.55 else "?" for d, c in zip(pd.tolist(), cf.tolist()))
    return txt, float(min(cf.tolist())), len(gs)


# 框变体：① 录屏1 的 default 框原样；② 只把左界放宽 60px（测"框太窄"）；
#         ③ 按 HUD 裁图实测的 570×116 放大（测"字号变大"）；④ 三个都放宽
BOX_DEFAULT = (260, 2350, 340, 2876)
BOX_WIDE_X = (260, 2290, 340, 2876)
BOX_TALL = (240, 2350, 366, 2876)
BOX_BOTH = (240, 2290, 366, 2876)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="frames/hud2_4")
    ap.add_argument("--sweep", action="store_true")
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(args.dir, "*.png")))
    if not paths:
        print("目录里没有 png：%s" % args.dir)
        return 2
    model = read_hud.load_model()
    print("录屏2 帧 %d 张（%s）\n" % (len(paths), args.dir))

    print("=== A. 列段几何：断链发生在哪个间隔（录屏1 的 default 框 %s，链阈值 20）===" % (BOX_DEFAULT,))
    print("%-14s %-6s %-7s %s" % ("帧", "列段数", "最左段x", "各间隔 px（★ = 超 20px，会被丢掉左侧全部）"))
    for p in paths:
        a = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
        merged, gaps = col_runs(a, BOX_DEFAULT)
        if not merged:
            print("%-14s %-6d %-7s %s" % (os.path.basename(p), 0, "-", "(该框内没有列段)"))
            continue
        gs = " ".join(("★%d" % g) if g > 20 else str(g) for g in gaps)
        over = sum(1 for g in gaps if g > 20)
        # 链从最右往左走，第一个超阈值的间隔就是断点 → 它左边全部计入"丢掉的列段"
        lost = 0
        for g in reversed(gaps):
            if g > 20:
                lost = gaps.index(g) + 1
                break
        print("%-14s %-6d %-7d %-40s 超阈值 %d 个；按链式规则会丢掉左侧 %d 个列段"
              % (os.path.basename(p), len(merged), merged[0][0] + BOX_DEFAULT[1], gs, over, lost))
        print("               列段（相对框内 x）: %s" % " ".join("[%d,%d]" % (s, e) for s, e in merged))

    if not args.sweep:
        return 0

    print("\n=== B. 读数：链阈值 × 裁剪框 的扫描（当前上游口径 = 链 20 + default 框）===")
    boxes = [("default(录屏1框)", BOX_DEFAULT), ("左界放宽60", BOX_WIDE_X),
             ("上下放宽", BOX_TALL), ("都放宽", BOX_BOTH)]
    chains = [20, 25, 30, 35, 40, 50, 60]
    for label, box in boxes:
        print("\n  ── 框变体 %s %s ──" % (label, box))
        print("     %-14s %s" % ("帧", "  ".join("链%-3d" % c for c in chains)))
        for p in paths:
            a = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
            cells = []
            for c in chains:
                txt, mc, n = read_with(a, model, box, c)
                cells.append("%-5s" % (txt or "(空)"))
            print("     %-14s %s" % (os.path.basename(p), "  ".join(cells)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
