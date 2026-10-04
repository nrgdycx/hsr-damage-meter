# -*- coding: utf-8 -*-
"""
[A 线] 新字体定位工具 —— 素材到位当天的第一步：**找到数字在哪**。

为什么需要：换字体（如用户提到的"银狼999 总伤"）时，数字的
**位置、字号、颜色**都可能变，`hud_profiles.py` 里那条档案就得重新标定 box。
本工具**不依赖字形**，只用"暖亮色块 + 连通域"来找候选区域，因此对新字体同样有效。

用法：
    python locate_A.py <截图或帧路径> [--roi-top 0.25]
    python locate_A.py --video <视频> --t 12.5

输出：候选色块的绝对包围盒（按面积排序）+ 一张带坐标网格与候选框的标注图。
"""

# [P3 整理] 原路径：locate_A.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from ffmpeg_path import find_ffmpeg as _find_ffmpeg   # 共享解析器（见 ffmpeg_path.py）
_FF_FALLBACK_1 = _find_ffmpeg() or ""   # 兜底：本机已知位置（没有 local 配置时为 None）
from tools_bootstrap import *  # noqa: E402,F401,F403
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def warm_clusters(rgb, min_area=120, roi_top=None):
    """找"暖亮色块"（数字/UI 的淡黄或饱和黄都算）。返回 [(面积, x0, y0, x1, y1)]。"""
    a = rgb.astype(np.int16)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    # 宽松、字体无关：偏黄且亮（既覆盖淡黄辉光，也覆盖饱和黄核心）
    m = ((R > 150) & (G > 130) & ((np.minimum(R, G) - B) > 30)).astype(np.uint8)
    if roi_top:
        m[int(m.shape[0] * roi_top):, :] = 0
    n, lab, stats, cent = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area:
            continue
        out.append((int(area), int(x), int(y), int(x + w - 1), int(y + h - 1)))
    out.sort(reverse=True)
    return out


def annotate(rgb, clusters, out_png, scale=0.5, grid=200):
    im = Image.fromarray(rgb.astype(np.uint8)).resize(
        (int(rgb.shape[1] * scale), int(rgb.shape[0] * scale)), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 18)
    for x in range(0, rgb.shape[1], grid):
        d.line([(x * scale, 0), (x * scale, im.height)], fill=(90, 90, 90), width=1)
        d.text((x * scale + 3, 4), str(x), font=f, fill=(255, 255, 255))
    for y in range(0, rgb.shape[0], grid):
        d.line([(0, y * scale), (im.width, y * scale)], fill=(90, 90, 90), width=1)
        d.text((4, y * scale + 3), str(y), font=f, fill=(255, 255, 255))
    for k, (area, x0, y0, x1, y1) in enumerate(clusters[:6], 1):
        d.rectangle([x0 * scale, y0 * scale, x1 * scale, y1 * scale], outline=(255, 255, 255), width=2)
        d.text(((x0 * scale), max(0, y0 * scale - 20)), "#%d area=%d" % (k, area), font=f, fill=(255, 255, 255))
    im.save(out_png)
    return out_png


def main():
    argv = sys.argv[1:]
    roi_top = 0.25
    if "--roi-top" in argv:
        i = argv.index("--roi-top")
        roi_top = float(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if "--video" in argv:
        i = argv.index("--video")
        video = argv[i + 1]
        t = "0"
        if "--t" in argv:
            t = argv[argv.index("--t") + 1]
        ff = os.environ.get("FFMPEG") or \
            _FF_FALLBACK_1
        tmp = "frames/locate_tmp_A.png"
        os.makedirs("frames", exist_ok=True)
        os.system('"%s" -ss %s -i "%s" -frames:v 1 -y "%s" >nul 2>nul' % (ff, t, video, tmp))
        src = tmp
    else:
        src = argv[0] if argv else "frames/glyphcache/f00134.00.png"

    rgb = np.asarray(Image.open(src).convert("RGB"))
    print("图 %s  尺寸 %dx%d" % (src, rgb.shape[1], rgb.shape[0]))
    cl = warm_clusters(rgb, roi_top=roi_top)
    print("暖亮色块候选（已按面积排序；roi_top=%.2f 只在上部找）:" % roi_top)
    for k, (area, x0, y0, x1, y1) in enumerate(cl[:10], 1):
        print("   #%d  面积 %-7d  x %4d..%4d  y %4d..%4d   宽 %3d 高 %3d" % (
            k, area, x0, x1, y0, y1, x1 - x0 + 1, y1 - y0 + 1))
    if not cl:
        print("   （没找到暖亮色块：数字可能不是暖色，或不在上部 —— 试 --roi-top 0 看全屏）")
    out = annotate(rgb, cl, "samples/新字体定位_A.png")
    print("\n已写出标注图 %s（0.5 倍 + 200px 网格 + 候选框）" % out)
    print("下一步：把数字所在那个块的 box 填进 hud_profiles.py 的对应档案。")


if __name__ == "__main__":
    main()
