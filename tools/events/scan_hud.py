# -*- coding: utf-8 -*-
"""
扫描录屏2 的 HUD 读数 + 阿哈时刻状态，验证用户说的：
  「阿哈时刻有显示」（总伤害 HUD 不隐藏）
  「阿哈时刻结束时会把这个阿哈时刻打的所有伤害显示在正中心」

要回答的三个问题：
  Q3a 阿哈时刻期间 HUD 总伤害到底显示不显示？
  Q3b 显示的话，是"整段阿哈累计"还是"每次欢愉技各自"？
  Q3c 阿哈结束时中央那串数字，与 HUD 的关系？
"""
# [P3 整理] 原路径：scan_hud2_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from ffmpeg_path import require_ffmpeg as _req_ff
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from read_hud import load_model, read_frame  # noqa: E402

VIDEO2 = "records/屏幕录制 2026-09-30 192031.mp4"
FFMPEG = _req_ff()   # 见 ffmpeg_path.py（可用 HSR_FFMPEG 指定）
CACHE = "frames/hud2_M"


def grab(t):
    out = os.path.join(CACHE, "t%08.2f.png" % t)
    if not os.path.exists(out):
        os.makedirs(CACHE, exist_ok=True)
        import subprocess
        subprocess.run([FFMPEG, "-ss", "%.3f" % t, "-i", VIDEO2, "-frames:v", "1", "-y", out],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out if os.path.exists(out) else None


def aha_at(t, table):
    """从 axis_actors_E_video2.csv 查该时刻的 card_type。"""
    if not table:
        return "?"
    best, bt = None, 1e9
    for tt, ct in table:
        if abs(tt - t) < bt:
            bt, best = abs(tt - t), ct
    return best if bt <= 0.6 else "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--t0", type=float, default=15.0)
    ap.add_argument("--t1", type=float, default=45.0)
    ap.add_argument("--step", type=float, default=1.0)
    args = ap.parse_args()

    table = []
    p = "out/axis_actors_E_video2.csv"
    if os.path.exists(p):
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            try:
                table.append((round(float(r["t"]), 1), r.get("card_type", "?")))
            except Exception:
                pass
    model = load_model()
    print("%-8s %-8s %-12s %-8s %s" % ("t", "card_type", "HUD读数", "置信", "Δ"))
    prev = None
    for i in range(int((args.t1 - args.t0) / args.step) + 1):
        t = round(args.t0 + i * args.step, 2)
        png = grab(t)
        if not png:
            print("%-8.1f 抽帧失败" % t)
            continue
        s, c, _ = read_frame(model, png)
        ct = aha_at(t, table)
        d = ""
        if s and s.isdigit() and prev and prev.isdigit():
            d = "%+d" % (int(s) - int(prev))
        if s and s.isdigit():
            prev = s
        print("%-8.1f %-8s %-12s %-8.2f %s" % (t, ct, s or "(空)", c, d))


if __name__ == "__main__":
    main()
