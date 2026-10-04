# -*- coding: utf-8 -*-
"""【线2】用"跨阿哈段自洽"反推**(1+欢愉度)之比**（不需要认脸）。

思路：
  1. 阿哈时刻里，HUD 会按**成员顺序**依次显示每个欢愉技的结算值（用户口径：放完一次结算一次）；
  2. 每个结算值 = K × 倍率 × (1+欢愉度)，其中 K 在同一次阿哈时刻内对所有人相同；
  3. 于是**同一段内**任意两个值之比 = (倍率比) × ((1+欢愉度)比)；
  4. 关键约束：**(1+欢愉度) 是角色的固定属性** → 同一对角色在不同阿哈段里的比值必须**一致**。
     把这个一致性当作判据，就能反推出"结算值序列 ↔ 成员轮转"的对应关系，**不需要认头像**。

做法：对每个阿哈段取出有序的稳定结算值，枚举轮转假设（周期 3：银狼/爻光/火花，真珠无独立结算值），
计算每段隐含的 k_i = 值 / 倍率，再看跨段的 k_i 比例是否稳定；稳定度最高的假设即答案。

用法：
  python -u analyze_L2_aha_cycle.py            # 报告 + out/L2_aha_cycle.json
  python -u analyze_L2_aha_cycle.py --min-frames 2
"""
# [P3 整理] 原路径：analyze_L2_aha_cycle.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import glob
import itertools
import json
import os
import sys

import numpy as np

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)

import axis_actor as T          # noqa: E402
import axis_actor_team2 as T2        # noqa: E402
import hud_read_team2 as H        # noqa: E402

AHA_SEGS = [(20, 33), (63, 78), (106, 119), (159, 192), (217, 230), (288, 321), (334, 341)]
# 三人有**独立结算值**的欢愉技（真珠 150320 是给全队的加成，不单独结算）
MEMBERS = ["银狼", "爻光", "火花"]
MULT = {"火花": 6.875, "爻光": 2.5, "银狼": 6.75}
MIN_DIGITS = 4
SPAN_GAP = 0.45


def dense_frames():
    out = {}
    for p in glob.glob(os.path.join(T2.CROP_DIR, "*_hud.png")):
        t = float(os.path.basename(p)[1:9])
        if abs(t - round(t)) < 1e-6:
            continue                      # 只要 0.2s 密帧
        out[t] = p
    return out


def seg_of(t):
    for i, (a, b) in enumerate(AHA_SEGS):
        if a - 0.5 <= t <= b + 0.5:
            return i
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-frames", type=int, default=2, help="稳定段最少帧数")
    ap.add_argument("--json", default="out/L2_aha_cycle.json")
    args = ap.parse_args()
    frames = dense_frames()
    print("0.2s 密帧：%d 张（阿哈时段）" % len(frames))
    model, model_pixel = H.load_model(), H.load_pixel_model()

    # 逐帧读数 → 稳定段
    per_seg = {i: [] for i in range(len(AHA_SEGS))}
    cache = {}
    for t in sorted(frames):
        si = seg_of(t)
        if si is None:
            continue
        r = H.read_crop_dual(frames[t], model=model, model_pixel=model_pixel)
        if r["verdict"] != "ok" or len(r["text"]) < MIN_DIGITS or not r["text"].isdigit():
            continue
        per_seg[si].append((t, int(r["text"])))

    spans_by_seg = {}
    for si, vals in per_seg.items():
        spans, cur = [], None
        for t, v in vals:
            if cur and v == cur["v"] and t - cur["t1"] <= SPAN_GAP:
                cur["t1"], cur["n"] = t, cur["n"] + 1
            else:
                if cur and cur["n"] >= args.min_frames:
                    spans.append(cur)
                cur = {"v": v, "t0": t, "t1": t, "n": 1}
        if cur and cur["n"] >= args.min_frames:
            spans.append(cur)
        if spans:
            spans_by_seg[si] = spans

    print("\n== 各阿哈段的稳定结算值（时间序）==")
    for si in sorted(spans_by_seg):
        a, b = AHA_SEGS[si]
        print("  段%d (t=%g~%g)：%s" % (si + 1, a, b,
                                       "  ".join("%s@t=%s(%d帧)" % (s["v"], T.fmt_t(s["t0"]), s["n"])
                                                 for s in spans_by_seg[si])))
    if not spans_by_seg:
        print("  没有可用稳定值 —— 退路：请用户给一个欢愉度数字")
        return 1

    print("\n== 反推轮转：哪个轮转假设能让 (1+欢愉度) 之比跨段一致 ==")
    best = None
    for perm in itertools.permutations(MEMBERS):
        ks = {}
        for si, spans in spans_by_seg.items():
            for j, s in enumerate(spans):
                who = perm[j % len(perm)]
                ks.setdefault((si, who), []).append(s["v"] / MULT[who])
        # 跨段一致性：对每个角色，取各段的中位 k，然后看"两两角色的 k 之比"在各段内的方差
        score, detail = 0.0, []
        for si, spans in spans_by_seg.items():
            row = []
            for j, s in enumerate(spans):
                who = perm[j % len(perm)]
                row.append((who, s["v"] / MULT[who]))
            if len(row) >= 2:
                for (w1, k1), (w2, k2) in itertools.combinations(row, 2):
                    detail.append((si, w1, w2, k1 / k2))
        # 一致性 = 相同角色对之间比值的离散度（越小越好）
        pairs = {}
        for si, w1, w2, r in detail:
            pairs.setdefault(tuple(sorted((w1, w2))), []).append(r)
        spread = {}
        for k, vs in pairs.items():
            if len(vs) >= 2:
                spread[k] = float(np.std(vs) / max(1e-9, np.mean(vs)))
        score = -float(np.mean(list(spread.values()))) if spread else -9.0
        label = "→".join(perm)
        print("  轮转 %-14s 可比对数 %-3d 跨段离散度 %s  (越小越好)"
              % (label, len(detail), {("%s/%s" % k): round(v, 3) for k, v in spread.items()}))
        if best is None or score > best[0]:
            best = (score, perm, spread, detail)
    print("\n**离散度最小（最自洽）的轮转：%s**（离散度均值 %.3f）"
          % ("→".join(best[1]), -best[0]))
    if best[2]:
        print("\n== 由该轮转推出的 (1+欢愉度) 之比（取跨段中位）==")
        ks = {}
        for si, spans in spans_by_seg.items():
            for j, s in enumerate(spans):
                who = best[1][j % len(best[1])]
                ks.setdefault(who, []).append(s["v"] / MULT[who])
        med = {w: float(np.median(v)) for w, v in ks.items()}
        base = min(med.values()) if med else 1.0
        for w in MEMBERS:
            if w in med:
                print("  %-4s 中位 k=%.0f  →  相对 (1+欢愉度) = %.3f （以最小者为 1）"
                      % (w, med[w], med[w] / base))
    json.dump({"spans": {str(k): v for k, v in spans_by_seg.items()},
               "best_rotation": list(best[1]), "spread": {("%s/%s" % k): v for k, v in best[2].items()}},
              open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已写出 %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
