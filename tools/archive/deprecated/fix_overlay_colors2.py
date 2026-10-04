# -*- coding: utf-8 -*-
"""
一次性地把悬浮窗配色加强到"在暗色游戏上看得清"。

问题（用户反馈）：悬浮窗是"纯黑"。根因是配色本身就是近黑：
  bg=#0e0e12 + alpha 0.85 → 叠在暗色游戏上就是一块黑洞，字也看不清。
  （`WS_EX_TRANSPARENT` 只是**鼠标穿透**，不是视觉透明 —— 这点容易误会。）

做法：背景提亮到深板岩、文字提亮、边框加亮，并顺手把默认 alpha 提到 0.97。
"""
# [P3 整理] 原路径：fix_overlay_colors2_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import io
import re

p = "mvp/overlay.py"
s = io.open(p, encoding="utf-8").read()

pairs = [
    ("#1c1f2b", "#252a3d"),   # 背景：深板岩（比近黑亮一档，仍不刺眼）
    ("#4a4f63", "#5d6480"),   # 分隔线
    ("#e8e8f0", "#ffffff"),   # 主文字：纯白
    ("#b8bfd6", "#c9d2ea"),   # 占比文字
    ("#8f96ad", "#9aa3bd"),   # 脚注
    ("#ffd479", "#ffd479"),   # 当前行动（保持金色，够亮）
]
n = 0
for a, b in pairs:
    if a != b:
        n += s.count(a)
        s = s.replace(a, b)

# 默认 alpha 0.94 → 0.97（更实，暗背景上也看得清）
s = s.replace("def __init__(self, x=40, y=40, alpha=0.94,",
              "def __init__(self, x=40, y=40, alpha=0.97,")

# 边框加亮（highlightbackground 用的是分隔线色，已经提亮；这里再加粗一格）
s = s.replace("highlightthickness=1,", "highlightthickness=2,")

io.open(p, "w", encoding="utf-8", newline="").write(s)
print("替换处数:", n)
for k in ("#252a3d", "#5d6480", "#ffffff", "#c9d2ea", "#9aa3bd", "alpha=0.97", "highlightthickness=2"):
    print("  %-22s 出现 %d 次" % (k, s.count(k)))
print("  残留 #0e0e12 / #1c1f2b:", s.count("#0e0e12"), s.count("#1c1f2b"))
