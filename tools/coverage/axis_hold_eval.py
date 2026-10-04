# -*- coding: utf-8 -*-
"""
线6 评估：外推准确率的**可复现**度量 + 可见性检测器标定。

核心口径（务必先读）：
  * 真值 = `out/axis_actors_L6.csv` 里 `source=read` 的帧（E 线已确认帧，分数过阈值的帧内正确率 100%）。
  * 模拟遮挡：把某个 **read 帧**假装成"不知道"，用它两侧最近的**已知状态帧**去预测它，
    再跟真值比。这正是隐藏帧的真实处境（两侧只有锚点、中间没有读数）。
  * 三种规则：
      hold   —— 只用前锚点（C 线现有口径："取事件之前最近的已确认帧"）
      near   —— 取前后锚点里时间更近的那个（平局取前）
      cons   —— 保守：只有前后都是 read 且**同一个 owner** 才给答案（覆盖低、精度高）
  * 按"两侧锚点间隔"分桶，报准确率（未给答案的帧计入弃权，不计入准确率分母）。

用法：
    python axis_hold_eval_L6.py            # A（回测）+ C（外推段结构）
    python axis_hold_eval_L6.py --labels   # 追加 B（可见性检测器标定，需人工标注）
    python axis_hold_eval_L6.py --sheet 60 # 出人工标注抽样图
"""
# [P3 整理] 原路径：axis_hold_eval_L6.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import collections
import csv
import json
import os
import random
import sys

import numpy as np

import axis_coverage as H

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
LABELS = os.path.join(HERE, "out/L6_manual_labels.json")
KINDS = ("read", "enemy", "aha", "elation")


def anchors(rows):
    return [(r["t"], r["source"], r["owner_out"]) for r in rows if r["source"] in KINDS]


def backtest_time(rows, buckets=((0, 1), (1, 2), (2, 3), (3, 4), (4, 6), (6, 10), (10, 99))):
    """按"两侧锚点间隔"分桶，算三种规则的准确率/覆盖率。"""
    A = anchors(rows)
    res = collections.defaultdict(lambda: collections.Counter())
    tiers = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        if r["source"] != "read":
            continue
        t, truth = r["t"], r["owner_out"]
        P = N = None
        for a in A:
            if a[0] < t:
                P = a
            elif a[0] > t and N is None:
                N = a
                break
        if P is None or N is None:
            continue
        gap = N[0] - P[0]
        b = next((x for x in buckets if x[0] <= gap < x[1]), None)
        if b is None:
            continue
        age_pre, age_post = t - P[0], N[0] - t
        # tier：与 axis_coverage.extrapolate 的定义一致
        tier = ("A" if (P[1] == "read" and N[1] == "read" and P[2] == N[2])
                else "B" if (P[1] == "read" and N[1] == "read") else "C")
        # hold：前锚点是 read 才给答案
        if P[1] == "read":
            res[b]["hold_cov"] += 1
            res[b]["hold_ok"] += (P[2] == truth)
            tiers[tier]["hold_cov"] += 1
            tiers[tier]["hold_ok"] += (P[2] == truth)
        # near
        pick = P if age_pre <= age_post else N
        if pick[1] == "read":
            res[b]["near_cov"] += 1
            res[b]["near_ok"] += (pick[2] == truth)
            tiers[tier]["near_cov"] += 1
            tiers[tier]["near_ok"] += (pick[2] == truth)
        # cons
        if P[1] == "read" and N[1] == "read" and P[2] == N[2]:
            res[b]["cons_cov"] += 1
            res[b]["cons_ok"] += (P[2] == truth)
        res[b]["n"] += 1
        tiers[tier]["n"] += 1
    return res, tiers


def print_tiers(tiers):
    print("\n== A2. 按外推层级（tier）拆开看 ==")
    print("%-6s %6s | %-18s | %-18s" % ("tier", "帧数", "hold 前锚点", "near 取最近"))
    for k in ("A", "B", "C"):
        c = tiers.get(k)
        if not c:
            continue
        print("%-6s %6d | %5.1f%% (%d/%d) | %5.1f%% (%d/%d)"
              % (k, c["n"],
                 100.0 * c["hold_ok"] / max(1, c["hold_cov"]), c["hold_ok"], c["hold_cov"],
                 100.0 * c["near_ok"] / max(1, c["near_cov"]), c["near_ok"], c["near_cov"]))
    print("说明：A=前后锚点都是我方且同一人；B=两侧都是我方可换人；C=至少一侧不是我方（敌方/阿哈/缺失）")


def print_backtest(res):
    print("\n== A. 时间口径模拟遮挡回测（真值 = 已确认帧；预测它两侧锚点间隔 %s）==" % "")
    print("%-10s %6s | %-16s | %-16s | %-16s" % ("锚点间隔", "帧数", "hold 前锚点", "near 取最近", "cons 两侧同人"))
    tot = collections.Counter()
    for b, c in sorted(res.items()):
        for k, v in c.items():
            tot[k] += v
        print("%-10s %6d | %5.1f%% (%d/%d) | %5.1f%% (%d/%d) | %5.1f%% (%d/%d)"
              % ("%g~%gs" % b, c["n"],
                 100.0 * c["hold_ok"] / max(1, c["hold_cov"]), c["hold_ok"], c["hold_cov"],
                 100.0 * c["near_ok"] / max(1, c["near_cov"]), c["near_ok"], c["near_cov"],
                 100.0 * c["cons_ok"] / max(1, c["cons_cov"]), c["cons_ok"], c["cons_cov"]))
    print("%-10s %6d | %5.1f%% (%d/%d) | %5.1f%% (%d/%d) | %5.1f%% (%d/%d)"
          % ("合计", tot["n"],
             100.0 * tot["hold_ok"] / max(1, tot["hold_cov"]), tot["hold_ok"], tot["hold_cov"],
             100.0 * tot["near_ok"] / max(1, tot["near_cov"]), tot["near_ok"], tot["near_cov"],
             100.0 * tot["cons_ok"] / max(1, tot["cons_cov"]), tot["cons_ok"], tot["cons_cov"]))


def hold_runs(rows):
    runs, cur = [], None
    for r in rows:
        if r["source"] == "hold":
            if cur is None:
                cur = {"t0": r["t"], "t1": r["t"], "n": 1, "pre": r["owner_out"], "post": "", "age": r["hold_age"]}
            else:
                cur["t1"] = r["t"]
                cur["n"] += 1
                cur["age"] = max(cur["age"], r["hold_age"])
        else:
            if cur is not None:
                cur["post"] = r["owner_out"] if r["source"] == "read" else "(%s)" % r["source"]
                runs.append(cur)
                cur = None
    if cur is not None:
        runs.append(cur)
    return runs


def print_runs(rows):
    runs = hold_runs(rows)
    same = sum(1 for r in runs if r["pre"] and r["pre"] == r["post"])
    diff = sum(1 for r in runs if r["pre"] and r["post"] and r["pre"] != r["post"]
               and not r["post"].startswith("("))
    print("\n== C. 外推段结构（共 %d 段）==" % len(runs))
    print("两侧锚点同一人：%d 段 ｜ 段内换人：%d 段 ｜ 后侧无我方锚点：%d 段"
          % (same, diff, len(runs) - same - diff))
    print("%-14s %5s %7s %-8s %-9s %s" % ("区间", "帧数", "最长追", "前锚点", "后锚点", "判读"))
    for r in runs:
        tag = ("两侧一致" if r["pre"] == r["post"] and r["pre"] else
               ("段内换人" if r["pre"] and r["post"] and not r["post"].startswith("(") else "后侧未知"))
        print("%-14s %5d %7.1f %-8s %-9s %s"
              % ("%g-%g" % (r["t0"], r["t1"]), r["n"], r["age"], r["pre"] or "-", r["post"] or "-", tag))
    return runs


def vis_eval():
    if not os.path.exists(LABELS):
        print("\n== B. 可见性检测器：缺人工标注 %s ==" % LABELS)
        return None
    lab = json.load(open(LABELS, encoding="utf-8"))
    rows = {r["t"]: r for r in H.load_rows()}
    ys = np.array([1 if v == "V" else 0 for v in lab.values()])
    vs = np.array([rows[float(t)]["edge_v"] for t in lab])
    print("\n== B. 可见性检测器（人工核对 %d 帧：轴可见 %d / 不可见 %d）=="
          % (len(ys), int(ys.sum()), int((1 - ys).sum())))
    best = None
    for thr in np.arange(4, 46.1, 0.5):
        pred = vs >= thr
        acc = float((pred == (ys == 1)).mean())
        if best is None or acc > best[1]:
            best = (thr, acc)
    print("最优阈值 %.1f：准确率 %.1f%%" % best)
    for thr in (H.VIS_THR, best[0]):
        pred = vs >= thr
        tp = int((pred & (ys == 1)).sum()); fp = int((pred & (ys == 0)).sum())
        fn = int((~pred & (ys == 1)).sum()); tn = int((~pred & (ys == 0)).sum())
        print("  阈值 %5.1f → 准确率 %5.1f%%｜可见召回 %d/%d｜不可见召回 %d/%d"
              % (thr, 100.0 * (tp + tn) / len(ys), tp, tp + fn, tn, tn + fp))
    bad = [(t, v) for t, v in lab.items() if (rows[float(t)]["edge_v"] >= H.VIS_THR) != (v == "V")]
    if bad:
        print("  阈值 %.1f 下的错判：" % H.VIS_THR +
              ", ".join("t=%s(人=%s,edge_v=%.1f)" % (t, v, rows[float(t)]["edge_v"]) for t, v in bad))
    return best


def make_sheet(n=60, seed=6):
    from PIL import Image, ImageDraw
    rows = H.load_rows()
    rnd = random.Random(seed)
    ts = sorted(float(t) for t in rnd.sample([r["t"] for r in rows], n))
    panels = []
    for t in ts:
        im = Image.open(H.FRAME % t).convert("RGB").crop((0, 40, 360, 1320))
        r = 300 / im.height
        im = im.resize((max(1, int(im.width * r)), 300), Image.LANCZOS)
        c = Image.new("RGB", (im.width, 320), (0, 0, 0))
        c.paste(im, (0, 20))
        ImageDraw.Draw(c).text((3, 3), "t=%g" % t, fill=(255, 255, 0))
        panels.append(c)
    pw, cols, gap, per = max(p.width for p in panels), 15, 4, 30
    for page in range((len(panels) + per - 1) // per):
        chunk = panels[page * per:(page + 1) * per]
        c = min(cols, len(chunk))
        rn = (len(chunk) + c - 1) // c
        sheet = Image.new("RGB", (c * pw + gap * (c + 1), rn * 320 + gap * (rn + 1)), (30, 30, 30))
        for i, p in enumerate(chunk):
            rr, cc = divmod(i, c)
            sheet.paste(p, (gap + cc * (pw + gap), gap + rr * (320 + gap)))
        out = os.path.join(HERE, "samples/L6_vis_page%d.png" % (page + 1))
        sheet.save(out)
        print("已写出 %s %s" % (out, sheet.size))
    if not os.path.exists(LABELS):
        json.dump({("%g" % t): "" for t in ts}, open(LABELS, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("已写出标注模板 %s（人工填 V=轴可见 / H=轴不可见）" % LABELS)
    return ts


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", action="store_true")
    ap.add_argument("--sheet", type=int, default=0)
    args = ap.parse_args()
    if args.sheet:
        make_sheet(args.sheet)
        return 0
    rows = H.load_rows()
    res, tiers = backtest_time(rows)
    print_backtest(res)
    print_tiers(tiers)
    print_runs(rows)
    if args.labels:
        vis_eval()
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
