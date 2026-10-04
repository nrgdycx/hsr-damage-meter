# -*- coding: utf-8 -*-
"""
E 线：圆点组 vs 星形组的卡面差异到底是"不同单位"还是"同一张图被缩放/位移了"？

做法：对每对帧，扫尺度 0.80~1.30 + 位移 ±6px，报告最佳 NCC。
      若最佳 NCC ≈1.8 且尺度明显偏离 1.0 → 同一张图的不同缩放（动画中）；
      若最佳 NCC 仍很低 → 真的是两张不同的卡面。
"""
# [P3 整理] 原路径：axis_scale_check_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import itertools

import cv2
import numpy as np

FRAME = "frames/glyphcache/f%08.2f.png"
ART = (90, 81, 232, 175)


def art(t):
    img = cv2.imread(FRAME % t, cv2.IMREAD_COLOR)
    return img[ART[1]:ART[3], ART[0]:ART[2]]


def prep(bgr):
    small = cv2.resize(bgr, (72, 48), interpolation=cv2.INTER_AREA)
    g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return (g - g.mean()) / max(1e-3, g.std())


def best(a_bgr, b_bgr, scales=np.arange(0.80, 1.31, 0.02), shift=8):
    """把 a 按 s 缩放后与 b 对齐，取最佳归一化相关。"""
    b = prep(b_bgr)
    out = []
    for s in scales:
        h, w = a_bgr.shape[:2]
        a = cv2.resize(a_bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        # 居中裁到 b 的尺寸并允许位移
        for dy in range(-shift, shift + 1, 2):
            for dx in range(-shift, shift + 1, 2):
                H, W = h, w
                y0 = max(0, (a.shape[0] - H) // 2 + dy)
                x0 = max(0, (a.shape[1] - W) // 2 + dx)
                crop = a[y0:y0 + H, x0:x0 + W]
                if crop.shape[0] < H or crop.shape[1] < W:
                    continue
                p = prep(crop)
                v = float((p * b).mean())
                out.append((v, float(s), dy, dx))
    out.sort(reverse=True)
    return out[0]


def main():
    A = [116, 220, 250]
    B = [129, 180, 304]
    print("同组内：")
    for x, y in list(itertools.combinations(A, 2)) + list(itertools.combinations(B, 2)):
        v, s, dy, dx = best(art(x), art(y))
        print("  t%-5s~t%-5s 最佳NCC %.2f（缩放 %.2f 位移 %d,%d）" % (x, y, v, s, dy, dx))
    print("跨组：")
    for x in A:
        for y in B:
            v, s, dy, dx = best(art(x), art(y))
            print("  t%-5s~t%-5s 最佳NCC %.2f（缩放 %.2f 位移 %d,%d）" % (x, y, v, s, dy, dx))
    print("对照（不同角色）：")
    for x, y in ((116, 150), (220, 159), (116, 307)):
        v, s, dy, dx = best(art(x), art(y))
        print("  t%-5s~t%-5s 最佳NCC %.2f（缩放 %.2f 位移 %d,%d）" % (x, y, v, s, dy, dx))


if __name__ == "__main__":
    main()
