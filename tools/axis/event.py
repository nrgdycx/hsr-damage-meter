# -*- coding: utf-8 -*-
"""
E 线：把「HUD 事件时刻」映射到「行动者」的推荐做法（给 C 会话）。

规则（实测出来的）：
  * 一次攻击的 HUD 数字在打完之后才出现并停留 1~1.5s，
    而顶端卡在这段时间里可能已经因为"整列上移/播放动画"变成 待复核 或换人
  * 所以：以事件时刻为基准，在 [-1.5s, +0.5s] 内找**最近的一个已确认帧**，
    优先取事件之前的（先动手、后出数字）
用法：python axis_event_E.py [--events 109,134,152,167,195,226,261,275,284,311]
"""
# [P3 整理] 原路径：axis_event_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import csv

import axis_actor as T

CSV = "out/axis_actors_E.csv"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default="100,106,109,134,135,152,167,195,226,261,275,284,311")
    ap.add_argument("--back", type=float, default=1.5)
    ap.add_argument("--fwd", type=float, default=0.5)
    args = ap.parse_args()

    rows = []
    for r in csv.DictReader(open(CSV, encoding="utf-8-sig")):
        rows.append((float(r["t"]), r["unit"].strip(), r["owner"].strip(),
                     float(r["score"]), r["marker"]))
    rows.sort()
    print("事件 -> 行动者（窗口 [-%.1fs, +%.1fs]，取最近的已确认帧）" % (args.back, args.fwd))
    for e in [float(x) for x in args.events.split(",")]:
        cand = [(abs(t - e), t - e, u, o, s) for (t, u, o, s, m) in rows
                if -args.back <= t - e <= args.fwd and u]
        if not cand:
            print("  t=%-6.0f -> 待复核（窗口内没有任何已确认帧）" % e)
            continue
        # 先按"事件之前优先"排序，再按时间距离
        cand.sort(key=lambda c: (0 if c[1] <= 0 else 1, c[0]))
        d, dt, u, o, s = cand[0]
        print("  t=%-6.0f -> 顶端 %-5s 归属 %-5s （取自 t=%.1f，%+.1fs，分数%.2f）" %
              (e, u, o, e + dt, dt, s))


if __name__ == "__main__":
    main()
