# -*- coding: utf-8 -*-
"""
E 线：行动轴顶端卡的几何/尺度探测（纯数值，终端输出 ASCII，不依赖看图）。

回答三个问题：
  Q1 顶端卡的"头像区"是否固定在同一个矩形？（同一角色在不同帧是否逐像素一致）
  Q2 顶端卡的渲染尺度与"非顶端卡"是否相同？（同角色 顶端 vs 队列里）
  Q3 左标记（卡片左边界那个圆/星/菱）的位置、颜色、形状是否可稳定检出？
"""
# [P3 整理] 原路径：axis_probe_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import itertools
import json
import os
import sys

import cv2
import numpy as np

FRAME = "frames/glyphcache/f%08.2f.png"
# 顶端卡头像区（t=226 真值槽1 的内容裁剪：x 88..284 -> 头像 x 90..232, y 81..175）
TOP_ART = (90, 81, 232, 175)
MARKER = (66, 108, 104, 150)          # 左标记候选框（含卡片左边界缺口）
ALLY = ["遐蝶", "风堇", "昔涟", "长夜月"]


def gray(t):
    a = cv2.imread(FRAME % t, cv2.IMREAD_GRAYSCALE)
    if a is None:
        raise FileNotFoundError(FRAME % t)
    return a


def color(t):
    a = cv2.imread(FRAME % t, cv2.IMREAD_COLOR)
    if a is None:
        raise FileNotFoundError(FRAME % t)
    return a


def crop(a, r):
    x0, y0, x1, y1 = r
    return a[y0:y1, x0:x1]


def ncc(a, b):
    """两个同尺寸块的最优位移 NCC（±3 像素内），避免 1~2px 抖动毁掉分数。"""
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    best = -1.0
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            h, w = b.shape
            y0, x0 = max(0, dy), max(0, dx)
            y1, x1 = min(a.shape[0], h + dy), min(a.shape[1], w + dx)
            if y1 - y0 < 20 or x1 - x0 < 20:
                continue
            aa = a[y0:y1, x0:x1]
            bb = b[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
            if aa.std() < 1e-3 or bb.std() < 1e-3:
                continue
            v = float(np.corrcoef(aa.ravel(), bb.ravel())[0, 1])
            best = max(best, v)
    return best


def marker_stats(t):
    """返回左标记区的统计：最亮色块的 bbox / 颜色 / 是否圆形。"""
    img = color(t)
    reg = crop(img, MARKER)
    hsv = cv2.cvtColor(reg, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1].astype(np.float32)
    val = hsv[:, :, 2].astype(np.float32)
    score = sat * (val / 255.0)
    m = score > max(60.0, score.max() * 0.6)
    ys, xs = np.where(m)
    if len(xs) == 0:
        return dict(t=t, found=False)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    bgr = reg[m].mean(axis=0)
    return dict(t=t, found=True, area=int(m.sum()),
                w=int(x1 - x0 + 1), h=int(y1 - y0 + 1),
                cx=float(xs.mean()) + MARKER[0], cy=float(ys.mean()) + MARKER[1],
                B=round(float(bgr[0]), 1), G=round(float(bgr[1]), 1), R=round(float(bgr[2]), 1),
                fill=round(float(m.sum()) / max(1, (x1 - x0 + 1) * (y1 - y0 + 1)), 2),
                asp=round((x1 - x0 + 1) / max(1, (y1 - y0 + 1)), 2))


def q1_same_actor():
    print("\n=== Q1 顶端卡头像区是否固定（同角色跨帧 NCC，1.0=逐像素一致）===")
    groups = {
        "死龙(龙)": [100, 150, 260],
        "长夜(水母)": [160, 280, 310],
        "小伊卡(独角兽)": [140, 167],
        "德谬歌(粉发忆灵)": [180, 307],
        "风堇": [110, 200],
        "遐蝶": [226, 251],
    }
    for name, ts in groups.items():
        blk = {t: crop(gray(t), TOP_ART) for t in ts}
        vals = []
        for a, b in itertools.combinations(ts, 2):
            vals.append("t%d~t%d=%.3f" % (a, b, ncc(blk[a], blk[b])))
        print("  %-16s %s" % (name, "  ".join(vals)))


def q2_top_vs_queue():
    print("\n=== Q2 顶端卡 vs 队列卡 尺度/NCC（真值帧 t=226 的 4 张角色卡）===")
    # t=226 真值槽位（extract_axis_templates.py 的 SLOTS）
    slots = {1: ("遐蝶", 88, 79, 196, 98), 6: ("风堇", 85, 515, 173, 75),
             8: ("昔涟", 86, 698, 175, 81), 9: ("长夜月", 86, 789, 173, 76)}
    g = gray(226)
    blocks = {}
    for i, (n, x, y, w, h) in slots.items():
        blocks[n] = g[y + 2:y + h - 2, x + 2:x + 144]
        print("  slot%-2d %-6s 内容块 %s" % (i, n, blocks[n].shape))
    print("  --- 4 个角色队列卡两两 NCC（同帧同源，应≈1.0）")
    for a, b in itertools.combinations(ALLY, 2):
        print("      %-6s~%-6s %.3f" % (a, b, ncc(blocks[a], blocks[b])))
    print("  --- 顶端卡（t=226 slot1 遐蝶）与队列卡比：跨角色应低，同角色应高")
    # 顶端 风堇 (t=200) vs 队列 风堇 (t=226 slot6)
    top_fj = crop(gray(200), TOP_ART)
    print("      顶端风堇(t=200) 与 队列风堇(t=226 slot6) NCC=%.3f" %
          ncc(top_fj, blocks["风堇"]))
    print("      顶端风堇(t=200) 与 队列遐蝶(t=226 slot1) NCC=%.3f" %
          ncc(top_fj, blocks["遐蝶"]))
    # 顶端 遐蝶 (t=226) vs 队列 遐蝶 (t=226 slot1)
    top_xd = crop(gray(226), TOP_ART)
    print("      顶端遐蝶(t=226) 与 真值slot1遐蝶 NCC=%.3f" % ncc(top_xd, blocks["遐蝶"]))
    # 尺度扫描：把队列风堇按不同缩放去匹配顶端风堇
    print("  --- 尺度扫描（把队列风堇缩放到 s 后与顶端风堇比）")
    src = blocks["风堇"]
    for s in (0.8, 0.9, 1.0, 1.1, 1.15, 1.2, 1.25, 1.3, 1.4):
        r = cv2.resize(top_fj, (int(src.shape[1] * s), int(src.shape[0] * s)))
        hh, ww = min(src.shape[0], r.shape[0]), min(src.shape[1], r.shape[1])
        print("      s=%.2f  NCC=%.3f" % (s, ncc(src[:hh, :ww], r[:hh, :ww])))


def q3_marker():
    print("\n=== Q3 左标记（区域 %s）统计 ===" % (MARKER,))
    frames = [100, 110, 140, 150, 160, 170, 180, 190, 200, 210, 220, 226, 230,
              250, 260, 280, 307, 310, 311, 120, 130, 240, 290, 300, 320, 330]
    for t in frames:
        st = marker_stats(t)
        if not st["found"]:
            print("  t=%-4d 无标记" % t)
        else:
            print("  t=%-4d 面积%-5d bbox %2dx%-3d 中心(%.0f,%.0f) 填充%.2f 纵横%.2f "
                  "BGR=(%.0f,%.0f,%.0f)" %
                  (t, st["area"], st["w"], st["h"], st["cx"], st["cy"], st["fill"],
                   st["asp"], st["B"], st["G"], st["R"]))


if __name__ == "__main__":
    q1_same_actor()
    q2_top_vs_queue()
    q3_marker()
