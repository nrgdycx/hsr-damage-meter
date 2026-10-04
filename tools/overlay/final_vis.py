# -*- coding: utf-8 -*-
"""
最终可见性确认 —— 倒计时后显示大号亮色窗口，让用户盯着看。

用法：
    python mvp/final_vis_M.py --delay 8 --seconds 20
"""
# [P3 整理] 原路径：mvp/final_vis_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
ROOT = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
for _p in (ROOT, os.path.join(ROOT, "vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tkinter as tk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=8.0)
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--alpha", type=float, default=1.0)
    ap.add_argument("--pos", default="120,120")
    a = ap.parse_args()

    x, y = (int(v) for v in a.pos.split(","))
    for i in range(int(a.delay), 0, -1):
        print("  %d 秒后显示…（请盯着屏幕 %d,%d 附近）" % (i, x, y), flush=True)
        time.sleep(1)

    r = tk.Tk()
    r.overrideredirect(True)
    r.geometry("+%d+%d" % (x, y))
    r.configure(bg="#00e5ff")
    tk.Label(r, text="看到我了吗？", bg="#00e5ff", fg="#101010",
             font=("Microsoft YaHei UI", 34, "bold")).pack(padx=40, pady=(30, 6))
    tk.Label(r, text="这是亮青色测试窗口  #00e5ff", bg="#00e5ff", fg="#101010",
             font=("Microsoft YaHei UI", 16)).pack(padx=40, pady=(0, 30))
    r.attributes("-topmost", True)
    if a.alpha < 1.0:
        r.attributes("-alpha", a.alpha)
    r.update()

    print(">>> 现在显示中！看屏幕 %d,%d，持续 %.0f 秒。（alpha=%.2f）"
          % (x, y, a.seconds, a.alpha), flush=True)
    end = time.perf_counter() + a.seconds
    while time.perf_counter() < end:
        r.update()
        time.sleep(0.03)
    r.destroy()
    print("已关闭。")


if __name__ == "__main__":
    main()
