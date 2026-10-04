# -*- coding: utf-8 -*-
"""
根因确认 + 修复验证：MVP 的 HUD 读数没走"字体档案"的参数。

## 结论（本脚本验证）

同一帧、同一个模型，只差**字形提取走哪条路**：

| 路径 | 提取参数 | 段数 | 读数 |
|---|---|---|---|
| `hud_profiles.glyphs()`（**权威**）| 档案登记：mode=glow, glyph_mode=hybrid_s, **expand=3** | 5 | **`73431`** ✅ |
| `hud_digits.extract_glyphs()`（MVP 走这条）| 只传 top/left，**其余用函数默认值** | 6 | `573438` ❌ |

**根因**：`hud_digits.extract_glyphs()` 调用 `HG.extract_cropped(rgb, top=top, left=left)`，
**没有把档案里的 `mode` / `glyph_mode` / `expand=3` / `bar_rows` 传下去**。

而 `hud_profiles.glyphs_cropped()` 才是"按档案分派"的正确入口：
```python
# hud_profiles.glyphs_cropped
return HG.extract_cropped(region, top=top, left=left,
                          mode=p["mode"], glyph_mode=p["glyph_mode"],
                          expand=p["expand"], bar_rows=bar_rows)
```

## 修复

MVP 的读数路径改成走 `hud_profiles.glyphs_cropped(profile, region, top, left, bar_rows)`。
本脚本先**离线验证**这个修复在已存抓屏图上确实能读到正确值。
"""
# [P3 整理] 原路径：mvp/verify_rootcause_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np


def main():
    from PIL import Image
    import hud_profiles as HP
    from hud_digits import HudOnnxReader, extract_glyphs

    png = "samples/M_full_now.png"
    if not os.path.exists(png):
        print("缺 %s（先跑一次抓屏）" % png)
        return
    rgb = np.asarray(Image.open(png).convert("RGB"))
    prof = HP.PROFILES["default"]
    y0, x0, y1, x1 = prof["box"]
    region = rgb[y0:y1, x0:x1]
    reader = HudOnnxReader(path=prof["onnx"], check_fresh=False)

    print("=== 路径 A：hud_profiles.glyphs_cropped（档案参数）===")
    bar = HP.PROFILES["default"].get("box") and None
    import geometry as SA
    bar = tuple(int(v) for v in SA.hud_geometry(shape=(rgb.shape[0], rgb.shape[1]))["bar_rows"])
    gsA = HP.glyphs_cropped("default", region, y0, x0, bar_rows=bar)
    resA = reader.classify(gsA)
    sA = "".join(str(d) if c >= reader.conf_min else "?" for d, c in resA)
    print("  expand=%s glyph_mode=%s mode=%s" % (prof["expand"], prof["glyph_mode"], prof["mode"]))
    print("  切出 %d 段 %s" % (len(gsA), [(int(g[1]), int(g[2])) for g in gsA]))
    print("  读出 %r" % sA)

    print("\n=== 路径 B：hud_digits.extract_glyphs（MVP 现走这条）===")
    gsB = extract_glyphs(region, top=y0, left=x0, bar_rows=bar)
    resB = reader.classify(gsB)
    sB = "".join(str(d) if c >= reader.conf_min else "?" for d, c in resB)
    print("  切出 %d 段 %s" % (len(gsB), [(int(g[1]), int(g[2])) for g in gsB]))
    print("  读出 %r" % sB)

    print("\n=== 对照 ===")
    print("  权威路径 A: %r   ← 应与屏幕数字一致（用户报 73431）" % sA)
    print("  MVP 路径 B: %r   ← 多切碎片导致错位" % sB)
    print("  结论: %s" % ("修 A 路径即可（属提取参数问题，非框/非字体模型）"
                         if sA != sB else "两条路一致（本帧看不出差异）"))


if __name__ == "__main__":
    main()
