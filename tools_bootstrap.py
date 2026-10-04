# -*- coding: utf-8 -*-
"""[P3 整理] 兼容入口：`from tools_bootstrap import *` 也能拿到 tools/ 里的引导。

脚本搬进 `tools/<功能>/` 后，Python 把**脚本自己所在目录**放进 sys.path，所以
`from tools_bootstrap import *` 命中的是 `tools/tools_bootstrap.py`（真身，与脚本同目录）；
只有在"仓库根已在 sys.path"的姿势下才会命中本文件。
两种姿势都必须能用，所以这里把真身再导出一次。

真身在哪、为什么需要它：见 `tools/tools_bootstrap.py` 与 `tools/README.md`。
"""
from __future__ import annotations

import os

_TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools")

try:                                     # 真身（Python 3.3+ 支持按路径加载）
    import importlib.util

    _spec = importlib.util.spec_from_file_location(
        "tools.tools_bootstrap", os.path.join(_TOOLS, "tools_bootstrap.py"))
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)       # type: ignore[union-attr]
except Exception:                        # 退路：直接改路径（与真身同样的效果）
    import sys
    if _TOOLS not in sys.path:
        sys.path.insert(0, _TOOLS)
    import tools_bootstrap as _mod       # type: ignore[no-redef]

ROOT = _mod.ROOT
VENDOR = _mod.VENDOR
__all__ = ["ROOT", "VENDOR"]
