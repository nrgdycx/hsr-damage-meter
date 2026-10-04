# -*- coding: utf-8 -*-
"""
E 线：给 axis_actor.py 调参用的评估台（留一帧口径）。

正向集：out/axis_top_labels_E.json（人工核对）+ 可选把过渡帧 201(小伊卡)/237(昔涟)/293(风堇) 也算进去
负向集：只放**人工核对过确认不是我方**的帧（敌人/空/过渡）——注意不要把真单位混进负向集，
        否则会虚高"负向最高分"、把阈值带偏（第一版就踩了这个坑）。
"""
# [P3 整理] 原路径：axis_tune_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import json

import cv2
import numpy as np

import axis_actor as T

FRAME = "frames/glyphcache/f%08.2f.png"
GRID = (8, 6)
KEEP = 0.6
SCALES = (1.0, 0.95, 1.05)

# 人工核对确认"不是我方单位"的帧（背景/空槽/敌人/过渡）
NEG = [103, 104, 111, 113, 118, 120, 126, 130, 133, 134, 135, 139, 142, 144, 147,
       153, 155, 158, 168, 170, 171, 172, 173, 179, 181, 183, 187, 189, 190, 191,
       196, 198, 204, 207, 208, 209, 210, 212, 216, 227, 230, 231, 235, 240, 244,
       248, 253, 254, 263, 266, 270, 276, 281, 282, 288, 290, 291, 297, 299, 300,
       305, 312, 313, 320, 325, 330, 335, 339]
# 我肉眼确认是单位的过渡帧（默认不算负向；加不加进正向集由 --add-transition 决定）
TRANSITION_UNITS = {201: "小伊卡", 237: "昔涟", 293: "风堇"}


def labels(add_transition=False):
    d = json.load(open(T.LABELS_PATH, encoding="utf-8"))
    out = {k: [float(x) for x in v] for k, v in d.items() if not k.startswith("_")}
    if add_transition:
        for t, u in TRANSITION_UNITS.items():
            if float(t) not in out.get(u, []):        # 标签文件里可能已经加过了，别重复计数
                out[u].append(float(t))
    return out


def art(t):
    img = cv2.imread(FRAME % t, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(t)
    return T.top_art(img)


def feats_scaled(bgr, s=1.0):
    h, w = bgr.shape[:2]
    a = bgr
    if s != 1.0:
        a = cv2.resize(a, (max(2, int(round(w * s))), max(2, int(round(h * s)))),
                       interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        if a.shape[0] >= h and a.shape[1] >= w:
            y0, x0 = (a.shape[0] - h) // 2, (a.shape[1] - w) // 2
            a = a[y0:y0 + h, x0:x0 + w]
        else:
            a = cv2.copyMakeBorder(a, 0, max(0, h - a.shape[0]), 0, max(0, w - a.shape[1]),
                                   cv2.BORDER_REPLICATE)
    small = cv2.resize(a, (72, 48), interpolation=cv2.INTER_AREA)
    g = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)
    return (T._norm(g), T._norm(cv2.magnitude(gx, gy)),
            T._norm(lab[:, :, 1]), T._norm(lab[:, :, 2]))


def blocks(f, grid=GRID):
    ch, cw = f.shape
    rh, rw = ch // grid[1], cw // grid[0]
    return [f[i * rh:(i + 1) * rh, j * rw:(j + 1) * rw]
            for i in range(grid[1]) for j in range(grid[0])]


def robust(b1, b2, keep=KEEP):
    v = np.array([float((a * b).mean()) for a, b in zip(b1, b2)])
    k = max(1, int(len(v) * keep))
    return float(np.sort(v)[-k:].mean())


def make_score(wg, wr, wc, scales):
    def sc(A, B):
        best = -9e9
        for s in scales:
            a, b = A.get(s), B.get(s)
            if a is None or b is None:
                continue
            v = float((a[0] * b[0]).mean()) + wg * float((a[1] * b[1]).mean())
            if wc:
                v += wc * (float((a[2] * b[2]).mean()) + float((a[3] * b[3]).mean())) / 2
            if wr:
                v += wr * (robust(blocks(a[0]), blocks(b[0]))
                           + 0.6 * robust(blocks(a[1]), blocks(b[1])))
            best = max(best, v)
        return best
    return sc


def bank_score(q, tmpl, sc, S, zw):
    """q：查询帧特征（按查询尺度）；tmpl：模板帧特征（多个缩放版本）；zw：缩放版折扣。"""
    best = -9e9
    for s in S:
        t = tmpl.get(s)
        if t is None:
            continue
        v = sc(q, {1.0: t})
        if s != 1.0:
            v -= zw
        best = max(best, v)
    return best


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--add-transition", action="store_true")
    ap.add_argument("--bank-zoom", default="", help="给模板库额外加这几个缩放版本，如 1.08（1.0 始终保留）")
    ap.add_argument("--zoom-weight", type=float, default=0.0,
                    help="模板缩放版得分的折扣（防止缩放版带来假阳性），如 0.03")
    args = ap.parse_args()
    lab = labels(args.add_transition)
    zoom = [float(x) for x in args.bank_zoom.split(",") if x.strip()]
    S = sorted(set([1.0] + zoom))
    cache = {}
    for ts in lab.values():
        for t in ts:
            if t not in cache:
                cache[t] = {s: feats_scaled(art(t), s) for s in S}
    negc = {}
    for t in NEG:
        if t in cache:
            continue
        try:
            negc[t] = {s: feats_scaled(art(t), s) for s in SCALES}
        except FileNotFoundError:
            pass
    print("正向 %d 帧（含过渡帧=%s）/ 负向 %d 帧 / 模板缩放版本=%s / 折扣=%.2f" %
          (sum(len(v) for v in lab.values()), args.add_transition, len(negc), S, args.zoom_weight))

    cfgs = [(0.6, 0.0, 0.0, (1.0,)), (0.6, 0.0, 0.3, (1.0,)),
            (0.4, 0.0, 0.3, (1.0,)), (0.6, 0.0, 0.5, (1.0,)),
            (0.6, 0.4, 0.3, (1.0,)), (0.6, 0.0, 0.3, SCALES),
            (0.8, 0.0, 0.3, (1.0,)), (0.6, 0.0, 0.4, (1.0,))]
    print("\n%-6s %-6s %-6s %-18s | %-7s %-9s %-8s %-9s %-8s %-8s" %
          ("wgrad", "wrob", "wcol", "scales", "LOO", "零误报阈值", "接受率", "接受内正确", "正向最低", "负向最高"))
    res = []
    for wg, wr, wc, sc_ in cfgs:
        sc = make_score(wg, wr, wc, sc_)
        ok = n = 0
        pos_scores = []          # (该帧的最高分, 是否判对)
        errs = []
        for unit, ts in lab.items():
            for t in ts:
                best, bt = -9e9, None
                for u2, ts2 in lab.items():
                    for t2 in ts2:
                        if t2 == t:
                            continue
                        v = bank_score(cache[t], cache[t2], sc, S, args.zoom_weight)
                        if v > best:
                            best, bt = v, u2
                n += 1
                pos_scores.append((best, bt == unit))
                if bt == unit:
                    ok += 1
                else:
                    errs.append("t%.0f %s->%s(%.2f)" % (t, unit, bt, best))
        negs = [max(bank_score(f, cache[t2], sc, S, args.zoom_weight)
                    for ts2 in lab.values() for t2 in ts2)
                for f in negc.values()]
        # 选阈值：先要求负向 0 误报，再取接受的正向最多、且接受里判对比例最高
        best_thr, best_tp, best_acc = 0.0, -1, 0.0
        for thr in sorted({round(v, 2) for v, _ in pos_scores} | {round(v, 2) for v in negs}):
            if sum(1 for v in negs if v >= thr):
                continue
            acc_set = [(v, c) for v, c in pos_scores if v >= thr]
            tp = len(acc_set)
            a = sum(1 for _, c in acc_set if c) / max(1, tp)
            if (tp, a) > (best_tp, best_acc):
                best_thr, best_tp, best_acc = thr, tp, a
        acc = ok / n
        mn = min(v for v, _ in pos_scores)
        res.append((acc, best_thr, best_tp / n, best_acc, mn, max(negs), wg, wc, sc_, errs))
        print("%-6.1f %-6.1f %-6.1f %-18s | %-7.3f %-9.2f %-7.0f%% %-8.0f%% %-8.2f %-8.2f" %
              (wg, wr, wc, str(sc_), acc, best_thr, best_tp / n * 100, best_acc * 100, mn, max(negs)))

    print("\n按 (接受率, 接受内正确率) 排序：")
    for (acc, thr, cov, a, mn, mx, wg, wc, sc_, errs) in sorted(res, key=lambda r: (-r[2], -r[3])):
        print("   阈值%.2f 覆盖%.0f%% 接受内正确率%.0f%% LOO%.3f  wgrad=%.1f wcol=%.1f scales=%s | 错例:%s" %
              (thr, cov * 100, a * 100, acc, wg, wc, sc_, ("无" if not errs else " ".join(errs))))


if __name__ == "__main__":
    main()
