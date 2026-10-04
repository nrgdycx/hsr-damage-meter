# -*- coding: utf-8 -*-
"""
显示真实悬浮窗（用固定样例数据），让用户直接看屏幕确认配色。

用法：
    python mvp/show_overlay_M.py --delay 10 --seconds 30
"""
# [P3 整理] 原路径：mvp/show_overlay_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import os
import sys
import time

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
ROOT = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
for _p in (ROOT, os.path.join(ROOT, "vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=10.0)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--pos", default="40,40")
    ap.add_argument("--alpha", type=float, default=1.0)
    a = ap.parse_args()

    x, y = (int(v) for v in a.pos.split(","))
    for i in range(int(a.delay), 0, -1):
        print("  %d 秒后显示悬浮窗…（请看屏幕 %d,%d）" % (i, x, y), flush=True)
        time.sleep(1)

    from mvp.overlay import Overlay, FIXTURE, BG, FG, CHROMA

    ov = Overlay(x=x, y=y, alpha=a.alpha, debug=True, hotkey=None)
    ov.update(FIXTURE)
    ov.pump()
    print(">>> 悬浮窗已显示：bg=%s fg=%s 透明键=%s 透明生效=%s"
          % (BG, FG, CHROMA, getattr(ov, "transparent_ok", None)), flush=True)
    print(">>> 位置 %d,%d  持续 %.0f 秒" % (x, y, a.seconds), flush=True)

    end = time.perf_counter() + a.seconds
    while time.perf_counter() < end:
        ov.update(FIXTURE)
        ov.pump()
        time.sleep(0.05)
    ov.destroy()
    print("已关闭。")


if __name__ == "__main__":
    main()
