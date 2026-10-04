# -*- coding: utf-8 -*-
"""
[线4] 密帧读数诊断 —— 为「事件表时间分辨率」任务的**取证阶段**服务。

回答三个问题：
  1. 当前口径重扫出来的密帧表，与 1 fps 网格帧在整数秒上是否**逐帧一致**？
     （旧的 `out/frames_dense_C.csv` 不一致 —— 它是修扫描器之前跑的，见 C 线交付 §3.4 附）
  2. 密帧里到底有几种失败模式？各占多少？
     · `empty`        HUD 真的不存在（`hud_n == 0`）→ **边界证据**
     · `flagged`      读数带 `?` 或位数不足 → 已自带告警
     · `silent`       读数看起来正常（conf 高、无 `?`）但**与两侧锚点不相容** → 最危险的一类
  3. 「读数空白」在密帧上的时长分布是什么？→ 给密帧切分的 `--empty-min` 定阈值。

用法：
  python diag_dense_4.py --frames out/frames_dense4.csv --grid out/frames_C.csv
  python diag_dense_4.py --window 146,166 --detail
"""
# [P3 整理] 原路径：diag_dense_4.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import csv
import os
import sys
from collections import Counter

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）


# ────────────────────────────── 载入 ──────────────────────────────
def load(path):
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                t = float(r["t"])
            except (TypeError, ValueError):
                continue
            rows.append({
                "t": t,
                "text": (r.get("hud_text") or "").strip(),
                "n": int(r.get("hud_n") or 0),
                "len": int(r.get("hud_len") or 0),
                "conf": float(r.get("hud_minconf") or 0.0),
                "unit": (r.get("unit") or "").strip(),
                "owner": (r.get("owner") or "").strip(),
                "card_type": (r.get("card_type") or "").strip(),
            })
    rows.sort(key=lambda r: r["t"])
    return rows


def is_grid(t, step=1.0):
    k = t / step
    return abs(k - round(k)) < 1e-6


def kind(r):
    """帧的读数类型（三分类，边界判定靠这个）。"""
    if not r["text"] and r["n"] == 0:
        return "empty"                     # HUD 真的不存在
    if not r["text"] or "?" in r["text"] or len(r["text"]) < 3:
        return "flagged"                   # 有字形但读数不可用（自带告警或在位数上明显残缺）
    return "ok"


def fmt(t):
    return ("%.2f" % t).rstrip("0").rstrip(".")


# ────────────────────────────── 1. 同源核对 ──────────────────────────────
def cross_check(dense, grid):
    print("=== 1. 密帧表 vs 1 fps 表：整数秒上是否同源 ===")
    g = {round(r["t"], 2): r for r in grid}
    common = same = diff = 0
    bad = []
    for r in dense:
        if not is_grid(r["t"]):
            continue
        key = round(r["t"], 2)
        if key not in g:
            continue
        common += 1
        if g[key]["text"] == r["text"]:
            same += 1
        else:
            diff += 1
            bad.append((key, g[key]["text"], r["text"]))
    print("  共同整数秒帧 %d 个：读数相同 %d，不同 %d" % (common, same, diff))
    for t, a, b in bad:
        print("    !! t=%-7s  1fps=%-12s  密帧表=%-12s" % (fmt(t), a or "(空)", b or "(空)"))
    return bad


# ────────────────────────────── 2. 失败模式统计 ──────────────────────────────
def plateau_of(rows, i):
    """从 i 起、值相同的连续 ok 帧（返回 (j, 值, 帧数)）。"""
    v = rows[i]["text"]
    j = i
    while j + 1 < len(rows) and rows[j + 1]["text"] == v and rows[j + 1]["t"] - rows[j]["t"] < 0.35:
        j += 1
    return j, v, j - i + 1


def classify_dense(dense, grid):
    """
    把**密帧独有**（非整数秒）的 ok 读数分成：
      anchored   —— 与该帧 ±0.4s 内的 1 fps 锚点读数相同
      plateau    —— 与同值邻帧构成 ≥2 帧的稳定平台（HUD 停住了）
      roll       —— 落在一个"正在上涨"的链里，且链的两端都有锚点/平台
      orphan     —— 以上都不是 → **可疑，必须人工看**
    另外单独统计：落到锚点值**后缀**上的读数（疑似丢前导位）。
    """
    g = [(r["t"], r["text"]) for r in grid if kind(r) == "ok"]
    dense_only = [r for r in dense if not is_grid(r["t"])]
    stats = Counter()
    orphans, suffixes = [], []
    for i, r in enumerate(dense_only):
        if kind(r) != "ok":
            stats["not_ok:" + kind(r)] += 1
            continue
        v = r["text"]
        # anchored：±0.4s 内有同值的 1 fps 锚点
        if any(abs(t - r["t"]) <= 0.4 and tv == v for t, tv in g):
            stats["anchored"] += 1
            continue
        # plateau：与前后邻帧同值
        nb = [x for x in dense_only if 0 < abs(x["t"] - r["t"]) <= 0.21 and kind(x) == "ok"]
        if any(x["text"] == v for x in nb):
            stats["plateau"] += 1
            continue
        # 疑似丢前导位：是本帧 ±1.2s 内某个更长读数的真后缀
        near = [x["text"] for x in dense if abs(x["t"] - r["t"]) <= 1.2
                and kind(x) == "ok" and len(x["text"]) > len(v) and x["text"].endswith(v)]
        if near:
            stats["suffix_of_near"] += 1
            suffixes.append((r["t"], v, near[0]))
            continue
        stats["orphan"] += 1
        orphans.append((r["t"], v, r["conf"], len(near)))
    print("\n=== 2. 密帧独有读数（非整数秒）的分类 ===")
    for k in sorted(stats):
        print("  %-16s %d" % (k, stats[k]))
    if suffixes:
        print("\n  ── 疑似丢前导位（是本帧 ±1.2s 内更长读数的真后缀）──")
        for t, v, ref in suffixes:
            print("    t=%-8s 读 %-9s ← 邻帧有 %s" % (fmt(t), v, ref))
    if orphans:
        print("\n  ── 孤儿读数（既非锚点值、也无同值邻帧、也不是后缀）★ 需人工核对 ──")
        for t, v, c, _ in orphans:
            print("    t=%-8s 读 %-10s conf=%.3f" % (fmt(t), v, c))
    return stats, orphans, suffixes


# ────────────────────────────── 3. 空白时长分布 ──────────────────────────────
def gap_distribution(dense):
    print("\n=== 3. 「HUD 不存在」连续段的时长分布（密帧 0.2s 网格）===")
    runs, cur = [], None
    for r in dense:
        if kind(r) == "empty":
            cur = [r["t"], r["t"]] if cur is None else [cur[0], r["t"]]
        else:
            if cur is not None:
                runs.append((cur[0], cur[1], cur[1] - cur[0]))
                cur = None
    if cur is not None:
        runs.append((cur[0], cur[1], cur[1] - cur[0]))
    c = Counter()
    for a, b, d in runs:
        c[round(d, 1)] += 1
    for d in sorted(c):
        print("  空 %-5s s : %d 段" % (("%.1f" % d), c[d]))
    print("  合计 %d 段空白；最短 %.1fs，最长 %.1fs" %
          (len(runs), min([d for _, _, d in runs], default=0),
           max([d for _, _, d in runs], default=0)))
    return runs


# ────────────────────────────── 4. 单窗口明细 ──────────────────────────────
def window_detail(dense, lo, hi):
    print("\n=== 4. 窗口 %.1f~%.1f 明细 ===" % (lo, hi))
    rows = [r for r in dense if lo - 0.01 <= r["t"] <= hi + 0.01]
    i = 0
    while i < len(rows):
        r = rows[i]
        k = kind(r)
        if k == "ok":
            j, v, n = plateau_of(rows, i)
            span = rows[j]["t"] - r["t"]
            tag = "1fps" if is_grid(r["t"]) else "dense"
            print("  %-9s ~ %-9s  %-11s ×%-2d (%.1fs)  [%s]" %
                  (fmt(r["t"]), fmt(rows[j]["t"]), v, n, span, tag))
            i = j + 1
        elif k == "empty":
            j = i
            while j + 1 < len(rows) and kind(rows[j + 1]) == "empty":
                j += 1
            print("  %-9s ~ %-9s  (空)          ×%-2d (%.1fs)" %
                  (fmt(r["t"]), fmt(rows[j]["t"]), j - i + 1, rows[j]["t"] - r["t"]))
            i = j + 1
        else:
            print("  %-9s   %-12s conf=%.3f n=%d   ← %s" %
                  (fmt(r["t"]), r["text"] or "(无文本)", r["conf"], r["n"],
                   "带?/位数不足" if r["text"] else "无文本"))
            i += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default="out/frames_dense4.csv")
    ap.add_argument("--grid", default="out/frames_C.csv")
    ap.add_argument("--window", default="", help="只打这个窗口的明细，如 146,166")
    ap.add_argument("--detail", action="store_true", help="打印全部密帧窗口的明细")
    args = ap.parse_args()

    dense = load(args.frames)
    grid = load(args.grid)
    print("密帧表 %s：%d 帧（整数秒 %d / 密帧 %d）" %
          (args.frames, len(dense),
           sum(1 for r in dense if is_grid(r["t"])),
           sum(1 for r in dense if not is_grid(r["t"]))))
    print("1fps 表 %s：%d 帧\n" % (args.grid, len(grid)))

    cross_check(dense, grid)
    classify_dense(dense, grid)
    gap_distribution(dense)

    if args.window:
        lo, hi = [float(x) for x in args.window.split(",")]
        window_detail(dense, lo, hi)
    elif args.detail:
        # 自动切成"有密帧的窗口"
        ts = sorted(r["t"] for r in dense if not is_grid(r["t"]))
        lo = prev = ts[0]
        for t in ts[1:]:
            if t - prev > 0.25:
                window_detail(dense, lo, prev)
                lo = t
            prev = t
        window_detail(dense, lo, prev)
    return 0


if __name__ == "__main__":
    sys.exit(main())
