# -*- coding: utf-8 -*-
"""一次性：把悬浮窗的近黑配色改成高对比配色（原色叠在暗色游戏上=一片黑）。"""
# [P3 整理] 原路径：fix_overlay_colors_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import io

p = "mvp/overlay.py"
s = io.open(p, encoding="utf-8").read()
before = s

# 原 #0e0e12 近黑 → 更亮更实的卡片色
s = s.replace("#0e0e12", "#1c1f2b")
s = s.replace("#3a3a46", "#4a4f63")      # 分隔线
s = s.replace("#9aa0b4", "#b8bfd6")      # 次要文字（占比）
s = s.replace("#6f7488", "#8f96ad")      # 脚注

io.open(p, "w", encoding="utf-8", newline="").write(s)
print("改动字节数:", len(s) - len(before))
for k in ("#1c1f2b", "#4a4f63", "#b8bfd6", "#8f96ad", "#0e0e12"):
    print("  %-10s 出现 %d 次" % (k, s.count(k)))
