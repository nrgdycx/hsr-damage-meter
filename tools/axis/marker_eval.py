# -*- coding: utf-8 -*-
"""
E 线：用模块自身的 marker_feat 评估左标记分类（留一帧），样本 = 两个录屏共 100+ 个人工标注。
"""
# [P3 整理] 原路径：axis_marker_eval_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import cv2
import numpy as np

import axis_actor as T


def main():
    samples = list(T.marker_samples())
    cache = {}
    for cls, d, t in samples:
        p = "%s/f%08.2f.png" % (d, t)
        img = cv2.imread(p, cv2.IMREAD_COLOR)
        if img is None:
            continue
        cache[(cls, d, t)] = (T.feats(T.marker_patch(img, T.scale_of(img.shape))), cls)

    conf = {}
    bad = []
    n = ok = 0
    for cls, d, t in samples:
        key = (cls, d, t)
        if key not in cache:
            continue
        # 留一帧：同类的其他样本当模板
        bank = {}
        for (c2, d2, t2), (f2, _) in cache.items():
            if (d2, t2) == (d, t):
                continue
            bank.setdefault(c2, []).append((t2, f2))
        img = cv2.imread("%s/f%08.2f.png" % (d, t), cv2.IMREAD_COLOR)
        kind, score, hue = T.marker_feat(img, bank=bank)
        got = kind
        n += 1
        want = {"dot": "ally_dot", "star": "ally_star", "diamond": "ally_diamond",
                "enemy_dot": "enemy_dot", "enemy_diamond": "enemy_diamond",
                "empty": "empty"}.get(cls, cls)
        good = got.startswith(want) if want.endswith("_") else got == want
        if cls == "aha":
            good = got == "gold_aha"
        ok += good
        conf[(cls, kind)] = conf.get((cls, kind), 0) + 1
        if not good:
            bad.append((d, t, cls, kind, round(score, 2)))
    print("标记分类（留一帧，%d 个样本）准确率 %.1f%% (%d/%d)" % (n, ok * 100.0 / n, ok, n))
    print("\n混淆：")
    for (e, g), v in sorted(conf.items()):
        print("   %-10s -> %-14s %d" % (e, g, v))
    if bad:
        print("\n错例：")
        for d, t, e, g, s in bad:
            print("   %s t=%-6s 真值%-8s 判成%-14s 分数%.2f" % (d.split("/")[-1], T.fmt_t(t), e, g, s))


if __name__ == "__main__":
    main()
