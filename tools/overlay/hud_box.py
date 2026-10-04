# -*- coding: utf-8 -*-
"""
HUD 框的**墨迹自适应**（MVP 层，不改 geometry）。

问题（实机抓屏实测，见 `docs/行动轴识别.md`）：
  · 数字**字号正常**（实测高 59px ≈ 常规档 61px），**但整体偏下约 30px**：
    实测 y 298~356，而线7 模型框是 y 260~340 → **框底切掉数字下半**。
  · 用户判断"不同模式下总伤位置不同" → **不该写死 y，要跟着墨迹走**。
  · ⚠️ 线7 的 `use_ink` 模式在本机**没生效**（退回 `src=model`），
    原因是它的墨迹判据把画面里的**发光光束**也算成墨迹了（光束也是暖色）。

本模块的做法（只读画面，不动线7）：
  1. **限定搜索区**：只在屏幕**右侧窄带**里找（HUD 在右上角，避免左侧/中间的光效）；
  2. **先定行、再定列**：用**行密度**找出"数字行带"（背景光束是弥散的，
     不像数字那样在窄行带里高度聚集）；
  3. 纵向取该行带 ± 余量；横向取该行带内的墨迹左右缘（右缘贴齐 + 留容量）；
  4. 找不到就用**线7 模型框兜底**（不劣化）。
"""
# [P3 整理] 原路径：mvp/hud_box_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 实机实测（2880×1800，全屏，常规字号）:
#   数字块 y 298~356（高 59）  x 2461~2859（宽 399，6 位）
MEASURED = {"y": (298, 356), "x": (2461, 2859), "h": 59, "w": 399}


def ink_box(rgb, shape=None, right_frac=0.82, pad_y=9, pad_right=8, pad_left=30):
    """
    返回 (hud_region dict, bar_rows, geom dict) —— 与 `mvp.reader.hud_region_for` 同构。
    rgb 为 None 时直接返回线7 模型框。
    """
    import geometry as SA

    if shape is None and rgb is not None:
        shape = np.shape(rgb)[:2]
    H, W = int(shape[0]), int(shape[1])
    base = SA.hud_geometry(shape=(H, W))
    by0, bx0, by1, bx1 = base["box"]

    if rgb is None:
        return _region(base["box"]), base["bar_rows"], base

    a = np.asarray(rgb).astype(np.int16)
    # ① 限定在右侧窄带 + 模型框上下放宽的范围
    sx0 = int(W * right_frac)
    sy0 = max(0, by0 - 150)
    sy1 = min(H, by1 + 150)
    sub = a[sy0:sy1, sx0:W]
    if sub.size == 0:
        return _region(base["box"]), base["bar_rows"], base

    r, g, b = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
    # ② 数字是"亮黄"：R/G 都高、B 明显低（阈值偏严以避开暗光束）
    yellow = (r > 195) & (g > 185) & ((r - b) > 40)
    rows = yellow.sum(axis=1)
    if rows.max() < 20:
        return _region(base["box"]), base["bar_rows"], base

    # ③ 数字行带 = **所有超过低阈值**的行取整体跨度（min~max），允许中间起伏。
    #    ⚠️ 不要"取最长的连续稠密段" —— 数字笔画中段密度会掉（实测 y312 只有 70，峰值 308），
    #    那样会把一个数字切成好几段、只抓到最密的一段（本模块第一版就栽在这）。
    #    背景光束是**弥散**的：它在窄带里不会形成"连续几十行都超过 20 像素"的结构。
    on = rows > max(20, rows.max() * 0.06)
    idx = np.where(on)[0]
    if len(idx) < 8:
        return _region(base["box"]), base["bar_rows"], base

    dy0, dy1 = int(idx[0]), int(idx[-1])

    # ③b 纵向：**只用"墨迹行带"**，不要与模型框取并集。
    #    实测教训（本文件迭代出来的）：
    #      · 只用模型框（y 260~340）→ 底部切掉数字（墨迹到 358）→ 读数少位
    #      · 模型框 ∪ 墨迹带（y 251~368）→ 区域太大，**多框进来的背景反而让分割变差**
    #        （实机对照里 6 段 → 4 段）
    #    所以取"能完整覆盖墨迹的最小带" = 墨迹带的上下各留 pad_y。
    ny0 = max(0, sy0 + dy0 - pad_y)
    ny1 = min(H, sy0 + dy1 + 1 + pad_y)

    # ④ 横向：**沿用"模型容量"**，不要用墨迹左右缘。
    #    ⚠️ 实测教训：用墨迹定横向会**切掉最高位** ——
    #    画面里的发光光束也是暖色，它会把"墨迹左缘"抬右，导致框左移不够；
    #    实机对照里墨迹框把 `55343` 读成 `73431`（少一位），就是这个原因。
    #    模型框按"12 位容量"算宽度，是**分辨率无关**的，不会切位。
    nx0, nx1 = bx0, bx1
    band = yellow[dy0:dy1 + 1]
    cols = band.sum(axis=0)
    cnz = np.where(cols > 0)[0]

    box = (ny0, nx0, ny1, nx1)
    geom = dict(base)
    geom.update({"box": box, "bar_rows": base["bar_rows"], "src": "ink-mvp",
                 "shift": ny0 - by0, "ink_y": (sy0 + dy0, sy0 + dy1),
                 "ink_x": ((sx0 + int(cnz[0]), sx0 + int(cnz[-1])) if len(cnz) >= 2 else None)})
    return _region(box), base["bar_rows"], geom


def _region(box):
    y0, x0, y1, x1 = box
    return {"left": int(x0), "top": int(y0),
            "width": int(max(1, x1 - x0)), "height": int(max(1, y1 - y0))}


if __name__ == "__main__":
    from PIL import Image
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", default="samples/M_grab_full.png")
    ap.add_argument("--out", default="samples")
    args = ap.parse_args()

    im = Image.open(args.png).convert("RGB")
    big = im.resize((2880, 1800), Image.LANCZOS) if im.size != (2880, 1800) else im
    rgb = np.asarray(big)

    reg, br, geom = ink_box(rgb)
    import geometry as SA
    base = SA.hud_geometry(shape=(1800, 2880))
    print("实测参考      : y %s  x %s（高 %d 宽 %d）"
          % (MEASURED["y"], MEASURED["x"], MEASURED["h"], MEASURED["w"]))
    print("墨迹自适应框  :", reg, " src=", geom.get("src"), " shift=", geom.get("shift"))
    print("  检出的墨迹 y:", geom.get("ink_y"), " x:", geom.get("ink_x"))
    print("线7 模型框    :", _region(base["box"]))

    c = big.crop((reg["left"], reg["top"], reg["left"] + reg["width"], reg["top"] + reg["height"]))
    c = c.resize((c.size[0] * 2, c.size[1] * 2), Image.LANCZOS)
    c.save(os.path.join(args.out, "M_hud_inkbox.png"))
    print("已写出 %s/M_hud_inkbox.png %s" % (args.out, c.size))
