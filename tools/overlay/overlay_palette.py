# -*- coding: utf-8 -*-
"""
悬浮窗配色候选测试 —— 用户反馈"深色配色看起来是纯黑，青色才看得见"。

所以要在"能看清"和"不刺眼"之间找一档。本脚本按顺序各显示 N 秒并打印色值，
用户看完告诉我哪档合适。

用法：
    python mvp/overlay_palette_M.py            # 依次试 4 档，每档 8 秒
    python mvp/overlay_palette_M.py --only 2   # 只试第 2 档
"""
# [P3 整理] 原路径：mvp/overlay_palette_M.py（已移入 tools/，功能见 tools/README.md）
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

# (名称, 背景, 主文字, 次要文字, 边框色)
PALETTES = [
    ("1_深板岩(当前)", "#252a3d", "#ffffff", "#c9d2ea", "#5d6480"),
    ("2_中灰蓝",       "#4a5470", "#ffffff", "#e2e8f7", "#8f9ec4"),
    ("3_浅板岩",       "#5d6a8a", "#ffffff", "#eef2fb", "#aab8dd"),
    ("4_米白(亮底深字)", "#e8ecf5", "#141824", "#3a4560", "#8f9ec4"),
]


def paint(ov, bg, fg, fg2, border):
    def walk(w, top=False):
        try:
            w.configure(bg=bg)
        except Exception:
            pass
        try:
            w.configure(fg=fg)
        except Exception:
            pass
        if top:
            try:
                w.configure(highlightbackground=border, highlightcolor=border)
            except Exception:
                pass
        for c in w.winfo_children():
            walk(c)
    def deep(w, top=False):
        try:
            w.configure(bg=bg)
        except Exception:
            pass
        try:
            w.configure(fg=fg)
        except Exception:
            pass
        if top:
            try:
                w.configure(highlightbackground=border, highlightcolor=border)
            except Exception:
                pass
        for c in w.winfo_children():
            deep(c)
    deep(ov.root, top=True)   # 递归整棵树（原版只改了一层，测试因此无效）


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--only", type=int, default=0, help="只试第 N 档（1 起）")
    a = ap.parse_args()

    from mvp.overlay import Overlay, FIXTURE

    picks = [PALETTES[a.only - 1]] if a.only else PALETTES
    for name, bg, fg, fg2, border in picks:
        ov = Overlay(x=40, y=40, alpha=1.0, debug=True, hotkey=None)
        # 关键：把 alpha 提到 1.0，排除"透明度把深色压黑"这个变量
        try:
            ov.root.attributes("-alpha", 1.0)
        except Exception:
            pass
        paint(ov, bg, fg, fg2, border)
        ov.update(FIXTURE)
        for _ in range(25):
            ov.pump()
            time.sleep(0.03)
        paint(ov, bg, fg, fg2, border)
        ov.update(FIXTURE)
        ov.pump()
        print("【%s】bg=%s fg=%s 边框=%s alpha=1.0  → 看屏幕左上角，持续 %.0f 秒"
              % (name, bg, fg, border, a.seconds), flush=True)
        t = time.perf_counter() + a.seconds
        while time.perf_counter() < t:
            ov.pump()
            time.sleep(0.02)
        ov.destroy()
        time.sleep(0.4)
    print("试完。请告诉我哪一档合适（或哪档仍然看不见）。")


if __name__ == "__main__":
    main()
