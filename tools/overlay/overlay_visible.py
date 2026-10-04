# -*- coding: utf-8 -*-
"""
高对比可见性测试 —— 把悬浮窗刷成醒目配色，请用户直接看屏幕确认能否看见。

用途：Win32 已确认窗口存在（可见=True、TOPTOST/LAYERED/TRANSPARENT 都在），
所以"纯黑"要么是配色太暗、要么是渲染问题。用醒目配色一次区分：
  · 能看见 → 就是配色问题 → 换配色即可
  · 看不见 → 是渲染/合成问题 → 另查
"""
# [P3 整理] 原路径：mvp/overlay_visible_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BG = "#00e5ff"      # 纯绿：绝不可能和游戏/聊天界面混淆
FG = "#101010"


def paint(ov):
    """把所有子控件的背景/前景换成醒目配色（只用于测试）。"""
    def walk(w):
        try:
            w.configure(bg=BG)
        except Exception:
            pass
        try:
            w.configure(fg=FG)
        except Exception:
            pass
        for c in w.winfo_children():
            walk(c)
    walk(ov.root)
    try:
        ov.root.configure(bg=BG)
    except Exception:
        pass


def main():
    from mvp.overlay import Overlay, FIXTURE

    alpha = float(sys.argv[1]) if len(sys.argv) > 1 else 0.94
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0

    ov = Overlay(x=40, y=40, alpha=alpha, debug=True, hotkey=None)
    paint(ov)
    ov.update(FIXTURE)
    # Tk 的 Label 背景在 update 之后可能被重设，再刷一次
    paint(ov)
    for _ in range(20):
        ov.pump()
        time.sleep(0.03)
    paint(ov)
    print("窗口 %dx%d @ (%d,%d)  alpha=%.2f"
          % (ov.root.winfo_width(), ov.root.winfo_height(),
             ov.root.winfo_rootx(), ov.root.winfo_rooty(), alpha))
    print(">>> 现在请看屏幕左上角 (40,40)：应该有一块【纯绿色】卡片，写着“当前行动: 遐蝶（死龙）”")
    print(">>> 持续 %.0f 秒。看得见 / 看不见，请告诉我。" % secs)
    t = time.perf_counter() + secs
    while time.perf_counter() < t:
        ov.pump()
        time.sleep(0.02)
    ov.destroy()
    print("已关闭。")


if __name__ == "__main__":
    main()
