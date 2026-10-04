# -*- coding: utf-8 -*-
"""【线2】导出录屏2 的**逐帧行动者**（给线3/线5 与后续统计用）。

产出：
  out/axis_actors_L2.csv   t,unit,score,margin,marker,inserted,card_type,reject,how
  out/L2_coverage.txt      覆盖率小结（按 card_type 分布 + 与 HUD 读数的交集）

用法：
  python -u axis_export_L2.py                 # 全片 0~380 整数秒
  python -u axis_export_L2.py --dir frames/axis2_L2 --out out/axis_actors_L2.csv
"""
# [P3 整理] 原路径：axis_export_L2.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import csv
import glob
import os
import sys

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)

import axis_actor as T          # noqa: E402
import axis_actor_team2 as T2        # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=T2.CROP_DIR)
    ap.add_argument("--out", default="out/axis_actors_L2.csv")
    ap.add_argument("--no-hud", action="store_true")
    args = ap.parse_args()
    bank = T2.load_bank()
    rows = []
    for p in sorted(glob.glob(os.path.join(args.dir, "*_top.png"))):
        t = float(os.path.basename(p)[1:9])
        try:
            r = T2.read_actor(t, bank)
        except Exception as e:                     # noqa: BLE001
            print("  t=%s 异常：%s" % (t, e))
            continue
        rows.append({"t": t, "unit": r["unit"] or "", "raw": r["raw"],
                     "score": r["score"], "margin": r["margin"], "marker": r["marker"],
                     "inserted": "" if r["inserted"] is None else int(r["inserted"]),
                     "card_type": r["card_type"], "reject": r["reject"] or ""})
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    keys = ["t", "unit", "raw", "score", "margin", "marker", "inserted", "card_type", "reject"]
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("已写出 %s（%d 行）" % (args.out, len(rows)))

    from collections import Counter
    ct = Counter(r["card_type"] for r in rows)
    un = Counter(r["unit"] for r in rows if r["unit"])
    lines = ["录屏2 行动轴顶端卡逐帧结果（%d 帧）" % len(rows),
             "  card_type：%s" % dict(ct),
             "  识别出身份的帧：%d（%.1f%%）；分布 %s"
             % (sum(un.values()), 100.0 * sum(un.values()) / max(1, len(rows)), dict(un))]
    if not args.no_hud and os.path.exists("out/frames_L2.csv"):
        hud = {float(r["t"]): r for r in csv.DictReader(open("out/frames_L2.csv", encoding="utf-8-sig"))}
        ok = [r for r in rows if r["unit"]]
        both = [r for r in ok if r["t"] in hud and hud[r["t"]]["verdict"] == "ok"]
        lines.append("  与 HUD 读数（out/frames_L2.csv）同时可用的帧：%d" % len(both))
        lines.append("  说明：HUD「总伤害」在一次攻击内累计，**同一次攻击的最终值**才有意义；"
                     "归属取攻击期间的顶端卡（见 docs/录屏2欢愉队.md）")
    txt = "\n".join(lines)
    print(txt)
    with open("out/L2_coverage.txt", "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
