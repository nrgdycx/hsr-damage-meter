# -*- coding: utf-8 -*-
"""[P3 整理] tools/ 下所有开发脚本的**仓库根引导**。

P3 之前，99 个脚本都躺在仓库根，每个脚本体里都写着
`sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` —— 那等价于
"把仓库根加进 sys.path"，所以 `import hud_glyphs`、`out/xxx.npz`、
`frames/glyphcache` 这些**相对仓库根**的写法都能用。

P3 之后脚本搬进了 `tools/<功能>/`，`__file__` 不再是仓库根，于是：
  * `import hud_glyphs`（仓库根的库模块）会 ImportError；
  * 打开 `out/...`、`frames/...` 会 FileNotFoundError；
  * `HERE = os.path.dirname(os.path.abspath(__file__))` 从"仓库根"变成了"脚本自己那层目录"。

本模块把这三件事一次性恢复：
  1. 把**仓库根**（以及 `vendor/`）加进 sys.path；
  2. 把工作目录 chdir 回仓库根；
  3. 提供 `rebase()`，让脚本把自己定义的 `HERE` / `ROOT` 改回仓库根。

用法是每个脚本头部一段（`out/p3_fix_bootstrap.py` 自动注入）：

    import os as _os, sys as _sys
    _t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
    if _os.path.isdir(_t) and _t not in _sys.path:
        _sys.path.insert(0, _t)
    from tools_bootstrap import *

顺带做的小事：把 stdout/stderr 切到 UTF-8（Windows 控制台默认 GBK，`print("✓")` 会崩）。

⚠️ 它**不删**脚本自己的 `sys.path.insert(__file__)` 那行（留着无害，脚本被拷到别处单跑时还能自救），
也**不吞**异常：引导失败就该报错。
"""
from __future__ import annotations

import os
import sys

# tools/ 的上一级 = 仓库根
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(ROOT, "vendor")

for _p in (VENDOR, ROOT):                  # vendor 在前：mss 只装在仓库里
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

try:
    if os.getcwd() != ROOT:
        os.chdir(ROOT)                     # 老行为：脚本都假设"在仓库根跑"
except OSError:
    pass

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

__all__ = ["ROOT", "VENDOR", "rebase"]

# 老脚本里常见的"其实是仓库根"的变量名
_REBASE_NAMES = ("HERE", "ROOT", "BASE", "RUNTIME_DIR")


def rebase(*names, _depth=1):
    """把**调用者模块**里的 `HERE` / `ROOT` 之类的变量改回仓库根。

    为什么需要：P3 之前 `HERE = os.path.dirname(os.path.abspath(__file__))` 就等于仓库根；
    搬进 `tools/<功能>/` 之后它变成了脚本自己的目录，于是
    `os.path.join(HERE, "out/events_dense4.csv")` 会去找 `tools/<功能>/out/...`（不存在）。

    实现：从调用栈取调用者那一帧，改写它全局命名空间里的这些变量。
    安全边界：**只改"当前值确实是本脚本目录（或仓库根的上级）"的变量**，
    当前值已经等于仓库根时跳过，不是字符串时跳过，名字不存在时什么都不做
    （不会凭空造变量，所以不改变脚本语义）。返回被改写的名字列表。

        rebase()                 # 默认处理 HERE / ROOT / BASE / RUNTIME_DIR
        rebase("BANK", "OUT")    # 也可以指定别的名字
    """
    import inspect
    frm = inspect.stack()[_depth].frame
    g = frm.f_globals
    try:
        mine = os.path.dirname(os.path.abspath(g["__file__"]))
    except Exception:
        mine = ROOT
    parent_of_root = os.path.dirname(os.path.abspath(ROOT))
    changed = []
    for name in (names or _REBASE_NAMES):
        if name not in g:
            continue
        cur = g[name]
        if not isinstance(cur, str):
            continue
        cur_abs = os.path.abspath(cur)
        if cur_abs == os.path.abspath(ROOT):
            continue
        if cur_abs == mine or cur_abs.startswith(mine + os.sep) \
                or cur_abs == parent_of_root or cur_abs.startswith(parent_of_root + os.sep):
            g[name] = ROOT
            changed.append(name)
    return changed
