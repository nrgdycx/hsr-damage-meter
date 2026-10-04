# -*- coding: utf-8 -*-
"""
[A 线] 诚实评测：单模型的运气分布 vs 集成 vs 集成+TTA，全部在**从未参与训练的留出帧**上。

为什么必须做这件事：
  留出集只有 5 帧 29 个字，单次训练的波动极大 —— 同一条管线只换 seed/batch，
  就能在 26/29 和 29/29 之间跳。只报一个数等于报运气。
  这里把 seed 分布、集成、集成+TTA 一起报出来，并给出**每帧的逐位明细**。

用法: python honest_eval_A.py [成员数]
"""
# [P3 整理] 原路径：honest_eval_A.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import json
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from read_hud import load_model, extract_glyphs, CY0, CY1, CX0, CX1  # noqa
from collect_glyphs import frame  # noqa
from train_digit_cnn import (train_one, train_ensemble, predict, tta_logits,  # noqa
                             DigitEnsemble, GW, GH)
from digit_truth import HOLDOUT  # noqa

SEEDS = [7, 8, 9, 10, 11]      # 单模型：只跑 5 个 seed 看"运气的分布"
ENS_SEED0 = 20                 # 集成成员统一从 seed 20 起，n=3/5/9 复用同一批成员


def glyphs_of(t):
    return extract_glyphs(frame(float(t)))


def score(read, want):
    """返回 (整串是否正确, 命中字数, 总字数)。按右对齐比较。"""
    n = min(len(read), len(want))
    hits = sum(1 for i in range(1, n + 1) if read[-i] == want[-i])
    return read == want, hits, len(want)


def eval_model(read_fn, hold, tag):
    st = gh = gt = 0
    per = []
    for t, (want, G) in hold.items():
        read = read_fn(G)
        ok, h, n = score(read, want)
        st += ok
        gh += h
        gt += n
        per.append("t=%d %s%s" % (t, read, "" if ok else "(want %s)" % want))
    print("   %-10s 整串 %d/5  逐字 %d/%d = %.1f%%  | %s" % (
        tag, st, gh, gt, gh / gt * 100, " ".join(per)), flush=True)
    return st, gh, gt, " ".join(per)


def main():
    d = np.load("out/digit_dataset.npz", allow_pickle=True)
    X, y = d["X"], d["y"]
    print("训练集 %d 样本；留出集 %d 帧：%s" % (len(y), len(HOLDOUT), sorted(HOLDOUT)))

    hold = {}
    for t, want in sorted(HOLDOUT.items()):
        gs = glyphs_of(t)
        hold[t] = (want, np.stack([g[0][0, 0].numpy() for g in gs])[:, None])
        print("   t=%-4s 期望 %-8s 切出 %d 段" % (t, want, len(gs)))

    rows = []
    print("\n单模型（每个 seed 单独训练）在留出集上的成绩 —— 看波动有多大：")
    for s in SEEDS:
        m = train_one(X, y, epochs=400, bs=64, seed=s)
        r = eval_model(lambda G, m=m: "".join(str(int(v)) for v in predict(m, G)),
                       hold, "seed=%d" % s)
        rows.append([s, "single", r[0], r[1], r[2], r[3]])

    print("\n集成（多 seed 平均 logits）—— n 越大越稳：")
    mem = train_ensemble(X, y, n=9, epochs=400, bs=64, seed0=ENS_SEED0).members
    for n in (3, 5, 9):
        sub = DigitEnsemble(list(mem[:n]))
        r = eval_model(lambda G, sub=sub: "".join(str(int(v)) for v in predict(sub, G)),
                       hold, "ens n=%d" % n)
        rows.append([n, "ens%d" % n, r[0], r[1], r[2], r[3]])

    ens9 = DigitEnsemble(list(mem))
    r = eval_model(lambda G: "".join(str(int(v)) for v in tta_logits(ens9, G).argmax(1).numpy()),
                   hold, "ens9+TTA")
    rows.append([0, "ens9+tta", r[0], r[1], r[2], r[3]])

    json.dump([{"seed_or_n": r[0], "kind": r[1], "strings": r[2],
                "glyph_hits": r[3], "glyph_total": r[4], "detail": r[5]} for r in rows],
              open("out/honest_eval_A.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已写出 out/honest_eval_A.json")


if __name__ == "__main__":
    main()
