# -*- coding: utf-8 -*-
"""从新录屏批量采集"模拟宇宙行动卡"，并按相似度自动分组 → 出指认图。

价值：这段 7 分钟录屏里换了 5 支队伍、约 20 个角色 —— 一次采集能装 20 个。
做法：
  1. 每 0.5 秒抽一帧，裁出顶端行动卡；
  2. 用色调/亮度做快速聚簇（同一角色的卡应聚在一起）；
  3. 出"每组代表 + 组内成员"的指认图，供用户一次性报名字。
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from ffmpeg_path import require_ffmpeg as _req_ff
import glob
import os
import subprocess

import cv2
import numpy as np

ROOT = r"D:\project\hsr-damage-meter"
FF = _req_ff()   # 见 ffmpeg_path.py（可用 HSR_FFMPEG 指定）
VIDEO = os.path.join(ROOT, "records", "屏幕录制 2026-10-03 123200.mp4")
OUT = os.path.join(ROOT, "frames", "cards1003")
# 模拟宇宙顶端行动卡（本录屏 2880x1800，实测刻度坐标）
BOX = (58, 68, 252, 182)


def imread_u(p):
    try:
        return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    except OSError:
        return None


def imwrite_u(p, img):
    ok, buf = cv2.imencode(".png", img)
    if ok:
        buf.tofile(p)


def grab(t, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    cmd = [FF, "-ss", "%.2f" % t, "-i", VIDEO, "-frames:v", "1", "-y", path]
    return subprocess.run(cmd, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def main(step=0.5, t0=0.0, t1=0.0):
    os.makedirs(OUT, exist_ok=True)
    times = []
    t = t0
    while t <= t1:
        times.append(t)
        t += step
    x0, y0, x1, y1 = BOX
    tmp = os.path.join(OUT, "_tmp.png")
    ok = 0
    for i, tt in enumerate(times):
        img = None
        if grab(tt, tmp):
            img = imread_u(tmp)
        if img is None:
            continue
        card = img[y0:y1, x0:x1]
        imwrite_u(os.path.join(OUT, "t%08.2f.png" % tt), card)
        ok += 1
        if (i + 1) % 50 == 0:
            print("  %d/%d" % (i + 1, len(times)))
    try:
        os.remove(tmp)
    except OSError:
        pass
    print("采到 %d 张卡面 → %s" % (ok, OUT))


if __name__ == "__main__":
    import sys
    step = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5
    t1 = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    main(step, 0.0, t1)
