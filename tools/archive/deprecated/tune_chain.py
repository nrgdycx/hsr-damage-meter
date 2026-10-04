# -*- coding: utf-8 -*-
"""
[C 线 / 给 A 线的建议] 试不同的「链式连续性」阈值，量化收益与代价。

`hud_glyphs._extract_core` 从最右段往左串，相邻列段间隔 >20px 就停止 → 左边全丢。
实测（diag_chain_C.py --audit）：**同一串数字内部的列段间隔能到 23~26px**，
所以这个 20px 会把真字形挡在链外 → 读数少前导位、且不报错。

本脚本把阈值当参数扫一遍，同时报告：
  · A 线真值帧（LABELED + HOLDOUT）的整串正确数（**越高越好**）
  · 249 帧全量里"字数变了"的帧（越多说明动到的帧越多，需要逐帧复核）
  · 每帧切出的字形数与位数的分布

注意：这里只是评估，**不改 hud_glyphs.py**（那是 A 线的模块）。
"""
# [P3 整理] 原路径：tune_chain_C.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import glob
import os
import sys
import types

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hud_glyphs as HG  # noqa
import read_hud  # noqa
from digit_truth import LABELED, HOLDOUT  # noqa

FRAME = "frames/glyphcache/f%08.2f.png"


def module_with_chain(chain):
    """把 hud_glyphs.py 源码里链式阈值那一行替换掉，编译成一个新模块。"""
    path = os.path.join(ROOT, "hud_glyphs.py")
    src = open(path, encoding="utf-8").read()
    old = "elif chain[-1][0] - r[1] - 1 <= 20:"
    new = "elif chain[-1][0] - r[1] - 1 <= %d:" % chain
    assert old in src, "没找到链式阈值那一行（hud_glyphs.py 被改过？）"
    mod = types.ModuleType("hud_glyphs_chain%d" % chain)
    mod.__dict__["__file__"] = path
    exec(compile(src.replace(old, new), mod.__file__, "exec"), mod.__dict__)
    return mod


def read_text(mod, model, t):
    a = np.asarray(Image.open(FRAME % t).convert("RGB")).astype(np.int16)
    gs = mod.extract(a)
    if not gs:
        return "", 0
    import torch
    x = torch.tensor(np.stack([v for v, _, _ in gs])[:, None], dtype=torch.float32)
    with torch.no_grad():
        p = torch.softmax(model(x), 1)
    c, d = p.max(1)
    return "".join(str(int(v)) if float(cc) >= 0.55 else "?" for v, cc in zip(d.tolist(), c.tolist())), len(gs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chains", default="20,30,40,50,60")
    ap.add_argument("--all", action="store_true", help="跑全量 249 帧统计")
    ap.add_argument("--show", default="", help="额外打印这些帧在各阈值下的读数，如 102,135.6,303")
    args = ap.parse_args()

    model = read_hud.load_model()
    truth = {float(k): v for k, v in LABELED.items()}
    truth.update({float(k): v for k, v in HOLDOUT.items()})
    ttimes = sorted(t for t in truth if os.path.exists(FRAME % t))
    all_times = []
    if args.all:
        for p in sorted(glob.glob("frames/glyphcache/*.png")):
            try:
                all_times.append(float(os.path.basename(p)[1:-4]))
            except ValueError:
                pass
    show = [float(x) for x in args.show.split(",") if x.strip()]

    print("链阈值  真值帧整串正确   读出字数分布(=位数)")
    for chain in [int(x) for x in args.chains.split(",")]:
        mod = module_with_chain(chain)
        ok = tot = 0
        bad = []
        for t in ttimes:
            txt, n = read_text(mod, model, t)
            tot += 1
            if txt == truth[t]:
                ok += 1
            else:
                bad.append("t=%s 期望%s 读出%s" % (HG and ("%.2f" % t).rstrip("0").rstrip("."),
                                                  truth[t], txt or "空"))
        line = "%-7d %-15s" % (chain, "%d/%d" % (ok, tot))
        if args.all:
            from collections import Counter
            cnt = Counter()
            n0 = 0
            for t in all_times:
                txt, n = read_text(mod, model, t)
                cnt[len(txt)] += 1
                n0 += (not txt)
            line += "  %s（无读数 %d）" % (dict(sorted(cnt.items())), n0)
        print(line, flush=True)
        if bad:
            print("        错例: " + " | ".join(bad[:6]))

    if show:
        print("\n=== 指定帧在各阈值下的读数 ===")
        print("%-9s %s" % ("t", "  ".join("chain=%d" % c for c in [int(x) for x in args.chains.split(",")])))
        mods = [module_with_chain(int(c)) for c in args.chains.split(",")]
        for t in show:
            if not os.path.exists(FRAME % t):
                print("%-9s 无缓存帧" % ("%.2f" % t).rstrip("0").rstrip("."))
                continue
            cells = []
            for mod in mods:
                txt, n = read_text(mod, model, t)
                cells.append("%-9s(n=%d)" % (txt or "空", n))
            print("%-9s %s" % (("%.2f" % t).rstrip("0").rstrip("."), "  ".join(cells)))


if __name__ == "__main__":
    main()
