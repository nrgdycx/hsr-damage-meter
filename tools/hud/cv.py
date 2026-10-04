# -*- coding: utf-8 -*-
"""
[A 线] 留一帧交叉验证（单模型）—— 比 5 帧留出集统计意义大得多的泛化估计。

19 个来源帧 × 107 个字形，每次留出一整帧（同一帧的字形不跨训练/测试集）。
历史值（44 样本、bs=16、260 epochs、单模型）是 90.9%；这里用 bs=64 重测，
并同时报告"哪一帧容易错"，作为交付的诚实下限。
"""
# [P3 整理] 原路径：cv_A.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import json
import sys

import numpy as np

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from train_digit_cnn import train_one, predict  # noqa


def main():
    d = np.load("out/digit_dataset.npz", allow_pickle=True)
    X, y = d["X"], d["y"]
    meta = [json.loads(m) for m in d["meta"]]
    frames = sorted(set(m["t"] for m in meta))
    print("留一帧交叉验证：%d 样本 / %d 帧" % (len(y), len(frames)), flush=True)
    tot = ok = 0
    per_frame = []
    for held in frames:
        te = np.array([i for i, m in enumerate(meta) if m["t"] == held])
        tr = np.array([i for i, m in enumerate(meta) if m["t"] != held])
        if len(tr) == 0:
            continue
        m = train_one(X[tr], y[tr], epochs=260, bs=64, seed=held)
        p = predict(m, X[te])
        hit = int((p == y[te]).sum())
        tot += len(te)
        ok += hit
        per_frame.append({"t": held, "hit": hit, "n": int(len(te))})
        print("   留出 t=%-4s %2d/%2d  %s" % (
            held, hit, len(te),
            "".join("[ok]" if a == b else "[%d->%d]" % (b, a) for a, b in zip(p, y[te]))), flush=True)
    print("\n逐字准确率（留一帧，单模型）: %d/%d = %.1f%%" % (ok, tot, ok / tot * 100))
    json.dump({"per_frame": per_frame, "hits": ok, "total": tot},
              open("out/cv_A.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已写出 out/cv_A.json")


if __name__ == "__main__":
    main()
