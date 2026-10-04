# -*- coding: utf-8 -*-
"""[线4] 账目脚本：把「C 线 54 段 → 线4 42 段」的每一笔变动算清楚，可复现。

用法：python -u account_4.py
"""
# [P3 整理] 原路径：account_4.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import csv
import os
import sys

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)


def load(p):
    return list(csv.DictReader(open(os.path.join(HERE, p), encoding="utf-8-sig")))


def main():
    ev = load("out/events_dense4.csv")
    cv = load("out/events_C.csv")
    for e in ev:
        e["a"], e["b"] = float(e["t_first"]), float(e["t_last"])
        e["pk"] = float(e["t_peak"])
        e["mx"] = int(e["damage_max"])
    cpeaks = [(r["event"], float(r["t_peak"]), int(r["damage_max"])) for r in cv]

    # ① C 的每个峰值落在哪个线4 段里（按段时间跨度）
    owner = {}
    for cid, t, mx in cpeaks:
        hit = None
        for e in ev:
            if e["a"] - 0.01 <= t <= e["b"] + 0.01:
                hit = e
                break
        owner[cid] = hit
    groups = {}
    for cid, t, mx in cpeaks:
        e = owner[cid]
        if e is not None:
            groups.setdefault(int(e["event"]), []).append((cid, t, mx))

    # ② 线4 独有的段：自己的峰值不在任何 C 段的时间范围内（与 compare_with_C 同口径）
    news = [e for e in ev
            if not any(float(r["t_first"]) - 0.51 <= e["pk"] <= float(r["t_last"]) + 0.51
                       for r in cv)]

    print("C 线事件 %d 段 → 线4 %d 段" % (len(cv), len(ev)))
    print("C 的 54 个峰值落在 %d 个线4 段里；线4 独有 %d 段" % (len(groups), len(news)))
    print("被并进别的 C 段同一段的 C 段数 = 54 − %d = %d" % (len(groups), len(cv) - len(groups)))
    print()
    print("── 共段的那些组（每组只有 1 个线4 段、多个 C 峰值）──")
    for k, v in sorted(groups.items()):
        if len(v) < 2:
            continue
        e = [x for x in ev if int(x["event"]) == k][0]
        print("  线4 #%-3d %-13s 最大 %-10s %-8s ← %d 个 C 段: %s" %
              (k, "%s~%s" % (e["t_first"], e["t_last"]), format(e["mx"], ","),
               e["owner"] or "-", len(v),
               ", ".join("#%s(t=%s,%s)" % (a, b, format(c, ",")) for a, b, c in v)))
    print()
    print("── 线4 独有（C 线 1 fps 网格看不到）──")
    for e in news:
        print("  #%-3d %-13s 峰值 %-10s@%-7s %-8s %s" %
              (int(e["event"]), "%s~%s" % (e["t_first"], e["t_last"]),
               format(e["mx"], ","), e["t_peak"], e["owner"] or "-", e["status"]))


if __name__ == "__main__":
    main()
