# -*- coding: utf-8 -*-
"""自动检测并采集"行动卡"（不靠固定框）。

判据：行动卡的边框与左侧标记是**青色**（HSV 色相约 85~100、高饱和、高亮）。
本脚本在画面左上区域找**青色像素团**，若达到阈值就认为"此刻有行动卡"，
再按青色团的包围盒裁出卡面。

这样无论探索/战斗/编队，只要行动卡出现就能采到；没卡的时刻直接跳过。
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from ffmpeg_path import require_ffmpeg as _req_ff
import os
import subprocess
import sys

import cv2
import numpy as np

ROOT = r"D:\project\hsr-damage-meter"
FF = _req_ff()   # 见 ffmpeg_path.py（可用 HSR_FFMPEG 指定）
VIDEO = os.path.join(ROOT, "records", "屏幕录制 2026-10-03 123200.mp4")
OUT = os.path.join(ROOT, "frames", "cards1003")


def imread_u(p):
    try:
        return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    except OSError:
        return None


def imwrite_u(p, img):
    ok, buf = cv2.imencode(".png", img)
    if ok:
        buf.tofile(p)


def cyan_mask(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    return ((h > 80) & (h < 105) & (s > 110) & (v > 140)).astype(np.uint8)


# 本录屏（2880x1800）里行动卡的精确框（已用 50px 刻度图量出）
CARD_BOX = (82, 78, 281, 178)


def find_card(img):
    """按**空心矩形边框**判据找行动卡。

    为什么不能只看"青色多少"：敌方技能/机巧特效也可能是大片青色
    （实测无卡帧 t=40 有 10 万青色像素，比任何有卡帧都多）。
    行动卡的特征是**青色构成一个空心矩形**：上边框是一条窄而长的横线。

    判据：
      1. 在候选框内，青色像素占比在 3%~45% 之间（太低=没卡；太高=整片特效）；
      2. 上边框存在：框顶附近 2~10 行内，单行青色长度 ≥ 框宽的 55%；
      3. 框内**中心区**（头像）不是全青（排除整片特效）。
    """
    x0, y0, x1, y1 = CARD_BOX
    H, W = img.shape[:2]
    x1, y1 = min(x1, W), min(y1, H)
    if x1 - x0 < 40 or y1 - y0 < 30:
        return None, 0, None
    sub = img[y0:y1, x0:x1]
    m = cyan_mask(sub)
    n = int(m.sum())
    frac = n / float(m.size)
    if not (0.03 <= frac <= 0.45):
        return None, n, None
    w = x1 - x0
    rows = m.sum(axis=1)
    # 上边框：前 12 行里出现一条 ≥55% 框宽的长横线
    if max(rows[:12].max() if len(rows) >= 12 else rows.max(), 0) < w * 0.55:
        return None, n, None
    # 中心区（头像）不能整片是青
    cy0, cy1 = (y1 - y0) // 4, (y1 - y0) * 3 // 4
    cx0, cx1 = w // 4, w * 3 // 4
    centre = m[cy0:cy1, cx0:cx1]
    if centre.size and centre.mean() > 0.9:
        return None, n, None
    return sub, n, (x0, y0, x1, y1)


def main(step=1.0, t0=0.0, t1=432.0):
    os.makedirs(OUT, exist_ok=True)
    tmp = os.path.join(OUT, "_tmp.png")
    n_card = n_none = 0
    info = []
    t = t0
    while t <= t1:
        cmd = [FF, "-ss", "%.2f" % t, "-i", VIDEO, "-frames:v", "1", "-y", tmp]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        img = imread_u(tmp)
        if img is None:
            t += step
            continue
        roi, n, box = find_card(img)
        if roi is None:
            n_none += 1
        else:
            n_card += 1
            info.append((t, n, box))
            imwrite_u(os.path.join(OUT, "t%08.2f_roi.png" % t), roi)
        t += step
    try:
        os.remove(tmp)
    except OSError:
        pass
    print("有卡的帧 %d，无卡 %d" % (n_card, n_none))
    if info:
        print("前若干有卡时刻：%s" % [(int(x[0]), x[1]) for x in info[:15]])
    with open(os.path.join(OUT, "_index.txt"), "w", encoding="utf-8") as f:
        for t, n, b in info:
            f.write("%.2f\t%d\t%s\n" % (t, n, b))


if __name__ == "__main__":
    st = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    a = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    b = float(sys.argv[3]) if len(sys.argv) > 3 else 432.0
    main(st, a, b)
