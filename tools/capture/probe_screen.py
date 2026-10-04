# -*- coding: utf-8 -*-
"""B 线：屏幕/DPI 探针 —— 确认实时抓屏能拿到的真实分辨率与坐标口径。

结论决定后面所有坐标怎么用：
  * 录屏是 2876x1798（物理像素），而 DPI 未感知的进程只会看到 1440x900（逻辑像素）。
  * 所以抓屏前必须先声明 DPI 感知，否则 CX0=2350 这类物理坐标会裁错地方。
"""
# [P3 整理] 原路径：probe_screen_B.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import ctypes
import os
import sys

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, os.path.join(HERE, "vendor"))

user32 = ctypes.windll.user32


def metrics():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def dpi_info():
    try:
        return user32.GetDpiForSystem()
    except Exception as e:  # pragma: no cover
        return "? %s" % e


def main():
    print("== 默认（未声明 DPI 感知）==")
    print("   GetSystemMetrics        = %dx%d" % metrics())
    print("   GetDpiForSystem         = %s" % dpi_info())

    # 声明 PER_MONITOR_AWARE_V2；失败则退到 shcore.SetProcessDpiAwareness(2)
    ok = False
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ok = bool(user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)))
        print("   SetProcessDpiAwarenessContext(-4) ->", ok)
    except Exception as e:
        print("   SetProcessDpiAwarenessContext 失败:", e)
    if not ok:
        try:
            hr = ctypes.windll.shcore.SetProcessDpiAwareness(2)
            print("   shcore.SetProcessDpiAwareness(2) ->", hr)
        except Exception as e:
            print("   shcore 失败:", e)

    print("== 声明 DPI 感知之后 ==")
    print("   GetSystemMetrics        = %dx%d" % metrics())
    print("   GetDpiForSystem         = %s" % dpi_info())

    import mss
    with mss.mss() as sct:
        print("   mss.monitors           =", sct.monitors)
        mon = sct.monitors[1]
        print("   monitor[1]             = %s" % (mon,))

    print("   mss 版本               =", getattr(mss, "version", getattr(mss, "__version__", "?")))


if __name__ == "__main__":
    main()
