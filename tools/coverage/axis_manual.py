# -*- coding: utf-8 -*-
"""
线6：把人工抽样标注（out/L6_manual.json）与 `out/axis_actors_L6.csv` 对照，报外推准确率。

口径：
  * L1（身份级）：人工能认出"是谁"（角色名）或"是敌方" → 与外推值 `owner_out` 直接比。
  * L2（阵营级）：只认得出"我方/敌方" → 只比阵营。
  * `演出`（波次切换 / 机制演出）本来就没有行动者，不计入准确率分母，单独列出。
  * `不可辨`（画面认不出）也不计入分母。
  * 参考列 `alt_owner`（取最近锚点）单独统计。

用法：python axis_manual_L6.py [--json out/L6_manual.json]
"""
# [P3 整理] 原路径：axis_manual_L6.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import collections
import json
import os
import sys

import axis_coverage as H

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
MANUAL = os.path.join(HERE, "out/L6_manual.json")


def pred_side(r):
    if r["source"] in ("read", "hold"):
        return "ally"
    if r["source"] == "enemy":
        return "enemy"
    return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=MANUAL)
    args = ap.parse_args()
    items = json.load(open(args.json, encoding="utf-8"))["items"]
    rows = {r["t"]: r for r in H.load_rows()}
    l1_ok = l1_bad = l2_ok = l2_bad = 0
    alt_ok = alt_bad = 0
    n_show = n_blind = 0
    tier_stat = collections.defaultdict(lambda: collections.Counter())
    detail = []
    for it in items:
        t = float(it["t"])
        r = rows.get(t)
        if r is None:
            continue
        got = r["owner_out"] or ("(敌方)" if r["source"] == "enemy" else
                                 ("(阿哈)" if r["source"] == "aha" else ""))
        alt = r["alt_owner"] or "-"
        ps = pred_side(r)
        if it["how"] == "演出":
            n_show += 1
            tag = "演出不适用"
        elif it["seen"]:
            exp = it["seen"]
            ok = (got == exp) or (exp == "敌方" and r["source"] == "enemy")
            if ok:
                l1_ok += 1
                tag = "一致"
            else:
                l1_bad += 1
                tag = "**不一致**"
            tier_stat[r["tier"]]["n"] += 1
            tier_stat[r["tier"]]["ok" if ok else "bad"] += 1
            if it["seen"] == "敌方":
                a_ok = (r["alt_owner"] == "")
            else:
                a_ok = (r["alt_owner"] == it["seen"])
            alt_ok += a_ok
            alt_bad += (not a_ok)
        elif it["side"] and it["side"] != "none":
            ok = (ps == it["side"])
            if ok:
                l2_ok += 1
                tag = "阵营一致"
            else:
                l2_bad += 1
                tag = "**阵营不一致**"
            tier_stat[r["tier"]]["n"] += 1
            tier_stat[r["tier"]]["ok" if ok else "bad"] += 1
            a_ok = (it["side"] == "enemy" and r["alt_owner"] == "") or \
                   (it["side"] == "ally" and bool(r["alt_owner"]))
            alt_ok += a_ok
            alt_bad += (not a_ok)
        else:
            n_blind += 1
            tag = "不可辨"
        detail.append((t, it["how"], tag, r["source"], r["tier"], got or "-", alt, it["seen"] or
                       (it["side"] or "-"), it["note"]))

    print("== 人工抽样核对（out/L6_manual.json，共 %d 帧）==" % len(detail))
    print("%-6s %-7s %-14s %-7s %-4s %-9s %-9s %-8s %s"
          % ("t", "来源", "判定", "source", "tier", "外推值", "alt(最近)", "人工看到", "备注"))
    for d in detail:
        print("%-6g %-7s %-14s %-7s %-4s %-9s %-9s %-8s %s" % d)
    n_l1 = l1_ok + l1_bad
    n_l2 = l2_ok + l2_bad
    print("\nL1 身份级：%d/%d = %.1f%%（人工能认出是谁/是敌方的帧）"
          % (l1_ok, n_l1, 100.0 * l1_ok / max(1, n_l1)))
    print("L2 阵营级：%d/%d = %.1f%%（只认得出我方/敌方的帧）"
          % (l2_ok, n_l2, 100.0 * l2_ok / max(1, n_l2)))
    print("合计可判：%d/%d = %.1f%%；对照 alt_owner（取最近锚点）：%d/%d"
          % (l1_ok + l2_ok, n_l1 + n_l2, 100.0 * (l1_ok + l2_ok) / max(1, n_l1 + n_l2),
             alt_ok, alt_ok + alt_bad))
    print("不可辨 %d 帧；演出（本来没有行动者）%d 帧 —— 均不计入分母" % (n_blind, n_show))
    print("\n按 tier 拆：")
    for k in sorted(tier_stat):
        c = tier_stat[k]
        print("  tier %-3s 可判 %2d 帧 → 对 %2d 错 %2d" % (k, c["n"], c["ok"], c["bad"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
