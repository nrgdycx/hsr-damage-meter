# -*- coding: utf-8 -*-
"""
把文档里指向 `samples/xxx.png` 的引用改成 `docs/images/xxx.png`。

为什么需要：`samples/` 在 .gitignore 里（51MB、120 个过程图），
但文档正文引用了其中 15 张当**证据图**。这些图已复制到 `docs/images/`（18.5MB，纳入 git），
所以引用路径必须同步改掉，否则别人 clone 后链接是死的。

安全性：只替换 `samples/<单层文件名>.png` 这种**图片路径**，
不动散文里的 "samples/" 字样，也不动带子目录的路径（那些本来就不存在）。
"""
# [P3 整理] 原路径：fix_imgrefs_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import glob
import os
import re

PAT = re.compile(r"samples/([A-Za-z0-9_\u4e00-\u9fff\.\-]+\.png)")


def main():
    files = sorted(glob.glob("docs/*.md") + glob.glob("*.md"))
    total_files = total_hits = 0
    for p in files:
        with open(p, encoding="utf-8", errors="replace") as f:
            txt = f.read()
        new, n = PAT.subn(r"docs/images/\1", txt)
        if n:
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(new)
            print("  %-40s 改了 %d 处" % (os.path.basename(p), n))
            total_files += 1
            total_hits += n
    print("\n共 %d 个文档、%d 处引用改为 docs/images/" % (total_files, total_hits))


if __name__ == "__main__":
    main()
