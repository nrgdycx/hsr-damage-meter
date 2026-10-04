# -*- coding: utf-8 -*-
"""
显示悬浮窗（**可关闭模式**，供用户确认配色）。

与运行期的区别：`closable=True` → 不鼠标穿透、保留标题栏 → 能点 × 关闭。
这样用户不会再遇到"关不掉"。

用法：
    python mvp/show_closable_M.py --delay 10 --seconds 25
"""
# [P3 整理] 原路径：mvp/show_closable_M.py（已移入 tools/，功能见 tools/README.md）
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
    ap.add_argument("--seconds", type=float, default=25.0)
    ap.add_argument("--pos", default="200,150")
    a = ap.parse_args()

    x, y = (int(v) for v in a.pos.split(","))
    for i in range(int(a.delay), 0, -1):
        print("  %d 秒后显示（位置 %d,%d，可点 × 关闭）…" % (i, x, y), flush=True)
        time.sleep(1)

    from mvp.overlay import Overlay, FIXTURE, BG

    ov = Overlay(x=x, y=y, alpha=1.0, debug=True, hotkey=None,
                 closable=True, title="HSR 伤害统计（可点 × 关闭）")
    ov.update(FIXTURE)
    ov.pump()
    print(">>> 已显示。背景 %s（不透明、无键色透明、无 alpha）。" % BG, flush=True)
    print(">>> 标题栏可以直接点 × 关闭；%0.f 秒后自动关闭。" % a.seconds, flush=True)

    end = time.perf_counter() + a.seconds
    while time.perf_counter() < end:
        try:
            ov.update(FIXTURE)
            ov.pump()
        except Exception:
            print("窗口已被用户关闭。")
            return
        time.sleep(0.05)
    try:
        ov.destroy()
    except Exception:
        pass
    print("已自动关闭。")


if __name__ == "__main__":
    main()
