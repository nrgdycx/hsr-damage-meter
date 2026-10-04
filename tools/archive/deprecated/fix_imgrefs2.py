# -*- coding: utf-8 -*-
"""
补齐被文档引用的证据图，并修掉两处"简写引用"（导致链接失效）。

背景：`samples/` 在 .gitignore 里，文档却引用里面的图当证据。
已把被引用的图复制到 `docs/images/`（纳入 git）。

本脚本处理三类漏网的：
  1. 文档用简写 `samples/L6_full_a/b/c/...`（正则抓不到，但 a~g 都存在）→ 展开成真文件名
  2. 文档用简写 `samples/L6_top_occ1/2.png` → 展开成 occ1.png / occ2.png
  3. 文档引用了 `samples/E_auto_*.png` 等**实际不存在的文件** → 标注为"过程图未入库"
"""
# [P3 整理] 原路径：fix_imgrefs2_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import glob
import os
import re
import shutil

EXTRA = [  # 简写对应的真实文件
    "L6_full_a.png", "L6_full_b.png", "L6_full_c.png", "L6_full_d.png",
    "L6_full_f.png", "L6_full_g.png", "L6_top_occ1.png",
    "E_nonexistent_placeholder",  # 占位，下面会过滤
]

# 文档里需要展开的简写 → 替换文本
REWRITES = [
    (r"`samples/L6_full_a/b/c/d/e/f/g\.png`",
     "`docs/images/L6_full_a.png` ~ `L6_full_g.png`（共 7 张）"),
    (r"`samples/L6_top_occ1/2\.png`",
     "`docs/images/L6_top_occ1.png`、`docs/images/L6_top_occ2.png`"),
    (r"`samples/E\*\.png`（约 40 张）",
     "`samples/E*.png`（约 13 张，**过程图未入库**，需要时重跑 E 线脚本生成）"),
]


def main():
    os.makedirs("docs/images", exist_ok=True)

    # 1) 补图
    copied = 0
    for name in EXTRA:
        src = os.path.join("samples", name)
        if not os.path.exists(src):
            continue
        dst = os.path.join("docs/images", name)
        if not os.path.exists(dst):
            shutil.copy2(src, dst)
            copied += 1
            print("  补图 %-28s %6.0f KB" % (name, os.path.getsize(src) / 1024))
    print("\n补图 %d 张" % copied)

    # 2) 修文档简写
    n_files = n_hits = 0
    for p in sorted(glob.glob("docs/*.md") + glob.glob("*.md")):
        with open(p, encoding="utf-8", errors="replace") as f:
            txt = f.read()
        orig = txt
        for pat, rep in REWRITES:
            txt = re.sub(pat, rep, txt)
        if txt != orig:
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(txt)
            print("  修文档 %-36s" % os.path.basename(p))
            n_files += 1

    # 3) 汇总 docs/images
    files = sorted(os.listdir("docs/images"))
    tot = sum(os.path.getsize(os.path.join("docs/images", f)) for f in files)
    print("\ndocs/images 现有 %d 张，合计 %.2f MB" % (len(files), tot / 1024 / 1024))


if __name__ == "__main__":
    main()
