# -*- coding: utf-8 -*-
"""
E 线：axis_actor.py 的正式评估报告（**直接调用模块的 match**，保证评估与线上完全一致）。

1) 留一帧：把该帧（含它的所有缩放态）从模板库移除后再判
2) 负向集（人工核对过不是我方）：对完整模板库打分 → 假阳性上限
3) 阈值扫描：负向 0 误报的前提下，能接受多少正向帧、接受里判对多少
"""
# [P3 整理] 原路径：axis_report_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import numpy as np

import axis_probe as D
import axis_actor as T

_FC = {}


def f_of(t, z):
    key = (float(t), float(z))
    if key not in _FC:
        img = T.load_frame(float(t))
        _FC[key] = T.feats_art(img, s_zoom=z)
    return _FC[key]


def bank_from(lab, skip=None):
    banks = {}
    for unit, ts in lab.items():
        rows = [f_of(t, z) for t in ts if skip is None or float(t) != float(skip)
                for z in T.ZOOMS]
        if rows:
            banks[unit] = np.stack(rows)
    return banks


def main():
    lab = D.labels()
    full = bank_from(lab)
    n_pos = sum(len(v) for v in lab.values())
    print("正向 %d 帧 / 负向 %d 帧；模板库 %s（每帧 %d 个缩放态）" %
          (n_pos, len(D.NEG), {u: len(v) for u, v in lab.items()}, len(T.ZOOMS)))

    pos_scores = []
    for unit, ts in lab.items():
        for t in ts:
            sc = T.match(bank_from(lab, skip=t), T.load_frame(float(t)))
            pred, (best, _) = max(sc.items(), key=lambda kv: kv[1][0])
            pos_scores.append((t, unit, pred, best, pred == unit))
    ok = sum(1 for r in pos_scores if r[4])
    print("\n=== 留一帧 ===")
    print("   准确率 %.1f%% (%d/%d)" % (ok * 100.0 / n_pos, ok, n_pos))
    for t, u, p, s, c in pos_scores:
        if not c:
            print("   错例 t=%-6s 真值%-5s 判成%-5s 分数%.2f" % (T.fmt_t(t), u, p, s))

    neg_scores = []
    for t in D.NEG:
        try:
            img = T.load_frame(float(t))
        except FileNotFoundError:
            continue
        sc = T.match(full, img)
        p, (v, _) = max(sc.items(), key=lambda kv: kv[1][0])
        neg_scores.append((t, p, v))
    mx = max(neg_scores, key=lambda r: r[2])
    print("\n=== 负向集（不该判成我方）===")
    print("   最高分 %.2f（t=%s -> %s），p95 %.2f，中位 %.2f" %
          (mx[2], T.fmt_t(mx[0]), mx[1],
           float(np.percentile([v for _, _, v in neg_scores], 95)),
           float(np.median([v for _, _, v in neg_scores]))))
    for t, p, v in sorted(neg_scores, key=lambda r: -r[2])[:5]:
        print("     最像的我方类：t=%-6s %.2f -> %s" % (T.fmt_t(t), v, p))

    print("\n=== 阈值扫描（要求负向 0 误报）===")
    best = None
    for thr in sorted({round(r[3], 2) for r in pos_scores}):
        if sum(1 for _, _, v in neg_scores if v >= thr):
            continue
        acc = [r for r in pos_scores if r[3] >= thr]
        prec = sum(1 for r in acc if r[4]) / max(1, len(acc))
        if best is None or (len(acc), prec) > (best[1], best[2]):
            best = (thr, len(acc), prec, len(acc) / n_pos)
    print("   最优阈值 %.2f：接受 %d/%d（覆盖 %.0f%%），接受内判对 %.0f%%" %
          (best[0], best[1], n_pos, best[3] * 100, best[2] * 100))
    acc_now = [r for r in pos_scores if r[3] >= T.THR]
    fp_now = [t for t, _, v in neg_scores if v >= T.THR]
    print("   当前模块 THR=%.2f MIN_MARGIN=%.2f：接受 %d/%d（覆盖 %.0f%%），接受内判对 %d/%d，负向误报 %d" %
          (T.THR, T.MIN_MARGIN, len(acc_now), n_pos, len(acc_now) * 100.0 / n_pos,
           sum(1 for r in acc_now if r[4]), len(acc_now), len(fp_now)))


if __name__ == "__main__":
    main()
